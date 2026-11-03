"""Native registered-study fixture for source authentication without rights admission."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from test_registered_odd_lot_study import SOURCE, _study

from quant_fund_lab.execution import PortfolioState, prior_session_liquidity
from quant_fund_lab.odd_lot_paper.bridge import HistoricalSessionState, capture_session_state
from quant_fund_lab.odd_lot_paper.session import OddLotSessionInput
from quant_fund_lab.odd_lot_protocol.registry import ExperimentRegistry
from quant_fund_lab.odd_lot_research import OddLotResearchConfig, odd_lot_backtest_config
from quant_fund_lab.odd_lot_rights.authorization_archive import AuthorizedRightsAccount
from quant_fund_lab.odd_lot_rights.codec import fingerprint
from quant_fund_lab.odd_lot_rights.day_request_archive import archive_day_request
from quant_fund_lab.odd_lot_rights.day_workflow import RightsDayRequest, advance_rights_day
from quant_fund_lab.odd_lot_rights.durable_day_workflow import DurableRightsDay, day_settings_sha256
from quant_fund_lab.odd_lot_rights.engine_checkpoint import RightsEngineCheckpoint
from quant_fund_lab.odd_lot_rights.engine_checkpoint_codec import encode_engine_rights
from quant_fund_lab.odd_lot_rights.engine_ledger_types import RightsLedgerConfig, payload_digest
from quant_fund_lab.odd_lot_rights.inventory import RightsInventory
from quant_fund_lab.odd_lot_rights.inventory_valuation import SecurityMark
from quant_fund_lab.odd_lot_rights.lot_events import LotRoundingPolicy
from quant_fund_lab.odd_lot_rights.registered_source import RegisteredRightsSource
from quant_fund_lab.odd_lot_rights.request_catalog import (
    RightsRequestCatalog,
    append_request_catalog,
)
from quant_fund_lab.odd_lot_rights.session_policy import RightsSessionPolicy
from quant_fund_lab.odd_lot_rights.types import RightsBook
from quant_fund_lab.odd_lot_study import _backtest_config, _subset, load_frozen_odd_lot_study


def registered_catalog(tmp_path, monkeypatch):
    study, protocol, frozen = _study(tmp_path, monkeypatch, ready=True)
    registry_path = tmp_path/"registry.sqlite"
    with ExperimentRegistry(registry_path) as registry:
        registry.register_protocol(protocol)
    source, metadata = load_frozen_odd_lot_study(study)
    data = _subset(source, list(protocol.symbols))
    period = protocol.periods[0]
    import pandas as pd

    start = int(data.close.index.searchsorted(pd.Timestamp(period.start)))
    origin = str(data.close.index[start-1].date())
    session = str(data.close.index[start].date())
    research = replace(OddLotResearchConfig(**metadata["research_config"]), strategy="momentum")
    base = _backtest_config(metadata["backtest_config"])
    config = odd_lot_backtest_config(base, research)
    runtime = HistoricalSessionState(PortfolioState(base.initial_cash), {}, {}, set(), [], [], False)
    policy = RightsSessionPolicy(1, "Asia/Taipei", origin+"T08:00:00+08:00", (),
                                 "usable_cash_only_atomic", "do_not_subscribe")
    inventory = RightsInventory(Decimal(str(base.initial_cash)), (), RightsBook(Decimal(str(base.initial_cash))), ())
    account = AuthorizedRightsAccount(inventory, policy)
    initial = RightsEngineCheckpoint(capture_session_state(runtime, session=origin,
        origin_session=origin, session_offset=0, completed_index=start-1), account)
    inputs = OddLotSessionInput(runtime, data, research, config, start-1, start-1, prior_session_liquidity(data.volume))
    request = RightsDayRequest(account, inputs, (), LotRoundingPolicy(1, "latest_contributor_release"),
        "registered-first", session+"T09:00:00+08:00", session+"T16:00:00+08:00",
        session+"T16:00:00+08:00", ("a"*64,), (), session+"T16:05:00+08:00")
    result = advance_rights_day(request)
    marks = tuple(SecurityMark(symbol, Decimal(str(data.raw_close.iloc[start][symbol])), session,
        session+"T16:00:00+08:00", ("a"*64,)) for symbol in sorted({row.security_id for row in result.account.inventory.lots}))
    day = DurableRightsDay(request, marks, (), session+"T16:05:00+08:00")
    calendar = metadata["readiness"]["periods"][0]["warmup"]["calendar_revision"]
    ledger_config = RightsLedgerConfig(policy.policy_sha256, protocol.execution.identity, fingerprint(calendar),
        day_settings_sha256(day), protocol.protocol_id, payload_digest(encode_engine_rights(initial)))
    root = RightsRequestCatalog(ledger_config, encode_engine_rights(initial), (), None)
    archive = archive_day_request(tmp_path/"requests", day)
    catalog = append_request_catalog(root, archive, initial)
    binding = RegisteredRightsSource(Path(frozen), registry_path, study.parent, SOURCE,
                                     protocol.candidates[0].candidate_id, period.name, "momentum")
    return binding, catalog, initial, day, archive
