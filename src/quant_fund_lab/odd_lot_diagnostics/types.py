"""Read-only diagnostic inputs and explicit unavailable/pending risk outputs."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

DIAGNOSTICS_RULE = "odd_lot_risk_diagnostics_v1"


def clean_scalar(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def frame_records(frame: pd.DataFrame) -> list[dict]:
    return [{str(key): clean_scalar(value) for key, value in row.items()}
            for row in frame.to_dict("records")]


@dataclass(frozen=True)
class RiskDiagnosticInputs:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    orders: pd.DataFrame
    signals: pd.DataFrame
    episodes: pd.DataFrame
    corporate_actions: pd.DataFrame
    terminal_events: pd.DataFrame
    strategy: str
    configured_risk_budget: float


@dataclass(frozen=True)
class EpisodeRiskAudit:
    episode_id: str
    symbol: str
    entry: str
    episode_status: str
    pending_receivables: int | None
    entry_risk_budget: float | None
    estimated_entry_risk: float | None
    realized_net_loss: float | None
    loss_over_budget: float | None
    loss_to_budget_ratio: float | None
    risk_status: str
    risk_reason: str
    first_stop_signal: str | None
    share_exit: str | None
    stop_attempts: int | None
    stop_delay_sessions: int | None
    stop_delay_calendar_days: int | None
    observed_sessions_since_stop: int | None
    stop_status: str


@dataclass(frozen=True)
class OddLotDiagnostics:
    capital: pd.DataFrame
    episode_risk: tuple[EpisodeRiskAudit, ...]
    unfilled_orders: pd.DataFrame
    source_issues: tuple[str, ...]
    closed_count: int | None
    sample_threshold: int = 30

    @property
    def episode_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(row) for row in self.episode_risk],
                            columns=list(EpisodeRiskAudit.__dataclass_fields__))

    def to_dict(self) -> dict:
        return {"rule_version": DIAGNOSTICS_RULE, "capital": frame_records(self.capital),
                "episode_risk": [asdict(row) for row in self.episode_risk],
                "unfilled_orders": frame_records(self.unfilled_orders),
                "source_issues": list(self.source_issues), "closed_count": self.closed_count,
                "sample_threshold": self.sample_threshold,
                "sample_sufficient": (self.closed_count >= self.sample_threshold
                                      if self.closed_count is not None else None)}


@dataclass(frozen=True)
class StudyRiskDiagnostics:
    accounts: dict[tuple[str, str], OddLotDiagnostics]
    unavailable: dict[str, str]

    def to_dict(self) -> dict:
        return {"rule_version": DIAGNOSTICS_RULE,
                "accounts": [{"period": period, "strategy": strategy, **result.to_dict()}
                             for (period, strategy), result in sorted(self.accounts.items())],
                "unavailable": dict(sorted(self.unavailable.items())),
                "limitations": [
                    "Observed-session delays use the simulation session sequence, not a settlement calendar.",
                    "Only emitted signals/orders are classified; unlogged cancellations remain unavailable.",
                    "Risk budget is taken from entry-fill evidence, not reconstructed from realized losses.",
                    "Thirty completed episodes do not establish strategy effectiveness.",
                ]}
