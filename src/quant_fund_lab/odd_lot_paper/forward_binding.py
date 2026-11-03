"""Internal plan/source evidence binding for atomic virtual observation replay.

Public activation must additionally authenticate the plan's original decision.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..config import BacktestConfig
from ..data import MarketData
from ..odd_lot_inputs.types import PriceSourcePolicy
from ..replay_provenance import replay_session_data_fingerprint
from .event_codec import decode_event
from .ledger import canonical, digest
from .observation import ObservationPlan
from .observation_evidence import SessionEvidence
from .observation_gate import assess_forward_session
from .source_archive import SourceArchiveLink, verify_source_archive

if TYPE_CHECKING:
    from ..odd_lot_research import OddLotResearchConfig


def _load_evidence(payload: dict) -> SessionEvidence:
    return SessionEvidence(**{**payload, "source_hashes":tuple(tuple(row) for row in payload["source_hashes"]),
                              "acquisitions":tuple(tuple(row) for row in payload["acquisitions"])})


@dataclass(frozen=True)
class ForwardReplayBinding:
    plan: ObservationPlan
    evidence: SessionEvidence
    source_archive: SourceArchiveLink
    source_root: Path
    required_symbols: tuple[str, ...]
    price_policy: PriceSourcePolicy | None = None

    def __post_init__(self) -> None:
        if (self.evidence.plan_id != self.plan.plan_id or self.evidence.first_session != self.plan.first_session
                or type(self.required_symbols) is not tuple or not self.required_symbols
                or len(set(self.required_symbols)) != len(self.required_symbols)):
            raise ValueError("forward binding differs from registered plan or symbols")

    def locked_config(self) -> dict:
        policy = asdict(self.price_policy) if self.price_policy is not None else None
        if policy is not None:
            # End/cutoff grow with incoming data; priority and initial history cannot.
            policy.pop("end")
            policy.pop("cutoff")
        return {"schema_version":1,"plan_id":self.plan.plan_id,
                "source_root":str(Path(self.source_root).resolve()),
                "required_symbols":self.required_symbols,"price_policy":policy}

    def record(self) -> dict:
        return {"plan_id":self.plan.plan_id, "evidence_id":self.evidence.evidence_id,
                "evidence":asdict(self.evidence), "source_archive":asdict(self.source_archive),
                "price_policy":asdict(self.price_policy) if self.price_policy is not None else None}

    def verify_configuration(self, research: OddLotResearchConfig, base: BacktestConfig) -> None:
        from ..odd_lot_research import OddLotResearchConfig
        from ..odd_lot_study import _backtest_config

        expected = replace(OddLotResearchConfig(**json.loads(self.plan.research_config_json)),
                           strategy=self.plan.strategy)
        if research != expected or base != _backtest_config(json.loads(self.plan.execution_config_json)):
            raise ValueError("forward execution settings differ from registered candidate")

    def verify_record(self, record: dict, session: str) -> MarketData:
        if set(record) != {"plan_id", "evidence_id", "evidence", "source_archive", "price_policy"}:
            raise ValueError("forward source record schema differs")
        evidence = _load_evidence(record["evidence"])
        policy = PriceSourcePolicy(**record["price_policy"]) if record["price_policy"] is not None else None
        candidate = ForwardReplayBinding(self.plan, evidence, SourceArchiveLink(**record["source_archive"]),
                                        self.source_root, self.required_symbols, policy)
        if (record["plan_id"] != self.plan.plan_id or evidence.evidence_id != record["evidence_id"]
                or canonical(candidate.locked_config()) != canonical(self.locked_config())
                or not evidence.first_session <= session <= evidence.through_session):
            raise ValueError("forward source record differs from locked plan/configuration")
        registered = datetime.fromisoformat(self.plan.recorded_at)
        acquisitions = {(day, symbol):stamp for day, symbol, _, stamp in evidence.acquisitions}
        for symbol in self.required_symbols:
            if (session, symbol) not in acquisitions:
                raise ValueError("forward session acquisition evidence is incomplete")
        for day, _, _, value in evidence.acquisitions:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp <= registered or stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() < day:
                raise ValueError("forward acquisition predates registration or session")
        source = verify_source_archive(self.source_root, candidate.source_archive)
        assessment = assess_forward_session(self.plan, evidence.through_session,
            official_directory=source, symbols=self.required_symbols[:-1], benchmark=self.required_symbols[-1],
            provider_directory=source / "provider" if policy is not None else None, price_policy=policy)
        actual = assessment.evidence
        if (assessment.status != "ready" or actual is None
                or actual.readiness_fingerprint != evidence.readiness_fingerprint
                or actual.calendar_revision != evidence.calendar_revision
                or actual.source_hashes != evidence.source_hashes or actual.acquisitions != evidence.acquisitions):
            raise ValueError("archived forward source does not reconstruct recorded readiness/acquisitions")
        return assessment.inputs.data

    def verify_current(self, data: MarketData, origin: str) -> None:
        from ..odd_lot_study import _subset

        archived = self.verify_record(self.record(), self.evidence.through_session)
        reference = _subset(archived, data.symbols)
        dates = data.close.index
        if (not dates.equals(reference.close.index) or self.evidence.through_session != str(dates[-1].date())
                or origin not in dates or int(dates.get_loc(origin))+1 >= len(dates)
                or str(dates[int(dates.get_loc(origin))+1].date()) != self.plan.first_session):
            raise ValueError("forward execution window differs from registered evidence")
        if any(replay_session_data_fingerprint(data, day, data.raw_close.loc[day], None)
               != replay_session_data_fingerprint(reference, day, reference.raw_close.loc[day], None) for day in dates):
            raise ValueError("forward execution panels differ from archived originals")

    def verify_ledger(self, db: sqlite3.Connection) -> None:
        """Validate provenance inside the same SQL transaction as the completion row."""
        from ..odd_lot_study import _subset

        config = json.loads(db.execute("SELECT value FROM account_metadata WHERE key='config'").fetchone()[0])
        current = self.verify_record(self.record(),self.evidence.through_session)
        current_all = self._prefixes(current)
        checked = {}
        for session, recorded_input in db.execute("SELECT session,input_digest FROM session_checkpoints ORDER BY session"):
            rows = db.execute("SELECT payload FROM session_events WHERE session=? AND category='observation' ORDER BY ordinal",
                              (session,)).fetchall()
            if len(rows) != 1:
                raise ValueError("completed forward session provenance is absent or duplicated")
            record = decode_event(json.loads(rows[0][0]))
            key = canonical(record)
            # A batch can share one complete source capture. Still check each
            # session boundary and its required acquisitions without rereading it.
            if key not in checked:
                complete = self.verify_record(record, session)
                archived = _subset(complete, config["symbols"])
                if archived.close.index[0].isoformat() != config["first_input_session"]:
                    raise ValueError("forward archived warmup differs from account origin")
                checked[key] = self._prefixes(archived), self._prefixes(complete)
            else:
                evidence = _load_evidence(record["evidence"])
                keys = {(day, symbol) for day, symbol, _, _ in evidence.acquisitions}
                if (not evidence.first_session <= session <= evidence.through_session
                        or any((session, symbol) not in keys for symbol in self.required_symbols)):
                    raise ValueError("forward session is outside its provenance capture")
            if checked[key][0].get(session) != recorded_input:
                raise ValueError("forward archived source prefix differs from committed inputs")
            if checked[key][1].get(session) != current_all.get(session):
                raise ValueError("completed trading/benchmark source prefix changed")

    @staticmethod
    def _prefixes(data: MarketData) -> dict[str,str]:
        chain, result = digest("odd_lot_prefix_v1"), {}
        for day in data.close.index:
            chain = digest(canonical([chain,replay_session_data_fingerprint(
                data,day,data.raw_close.loc[day],None)]))
            result[str(day.date())] = chain
        return result
