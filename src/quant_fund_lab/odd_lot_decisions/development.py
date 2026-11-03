"""Select once using development semantics, with a replayable canonical artifact."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .development_types import DevelopmentEvidence, DevelopmentPolicy, DevelopmentRank
from .types import STRATEGIES, _digest, fingerprint


def _eligibility(policy: DevelopmentPolicy, evidence: DevelopmentEvidence | None) -> tuple[str, float | None, str]:
    if evidence is None:
        return "unavailable", None, "declared_candidate_evidence_missing"
    if evidence.status != "available":
        return "unavailable", None, "development_" + evidence.status + ": " + evidence.reason
    if evidence.completed_episodes is None:
        return "unavailable", None, "development_episode_count_unknown"
    if evidence.completed_episodes < policy.minimum_completed_trades:
        return "insufficient_sample", None, "development_completed_episodes_below_minimum"
    score = getattr(evidence, policy.development_objective)
    if score is None:
        return "unavailable", None, "development_objective_undefined"
    if policy.development_objective == "calmar" and (evidence.max_drawdown is None or evidence.max_drawdown == 0):
        return "unavailable", None, "calmar_undefined_without_drawdown"
    if policy.development_objective == "sharpe" and (evidence.annual_volatility is None or evidence.annual_volatility <= 0):
        return "unavailable", None, "sharpe_undefined_without_variation"
    return "eligible", score, "development_eligible"


@dataclass(frozen=True)
class DevelopmentSelection:
    """Semantic selection only; constructing it neither authenticates nor persists sources."""

    policy: DevelopmentPolicy
    candidate_ids: tuple[str, ...]
    evidence: tuple[DevelopmentEvidence, ...]
    candidates: tuple[DevelopmentRank, ...] = field(init=False)
    status: str = field(init=False)
    selected_candidate: str | None = field(init=False)
    selected_strategy: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, DevelopmentPolicy):
            raise TypeError("selection requires a development policy")
        if (not isinstance(self.candidate_ids, tuple) or not self.candidate_ids
                or not isinstance(self.evidence, tuple)):
            raise ValueError("selection requires finite immutable candidate and evidence tuples")
        for identity in self.candidate_ids:
            _digest(identity)
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("duplicate development candidate budget")
        if not all(isinstance(row, DevelopmentEvidence) for row in self.evidence):
            raise TypeError("selection requires typed development evidence")
        by_key = {(row.candidate_id, row.strategy): row for row in self.evidence}
        if len(by_key) != len(self.evidence):
            raise ValueError("duplicate development evidence")
        if any(row.candidate_id not in self.candidate_ids for row in self.evidence):
            raise ValueError("development evidence belongs to an undeclared candidate")
        object.__setattr__(self, "candidate_ids", tuple(sorted(self.candidate_ids)))
        object.__setattr__(self, "evidence", tuple(sorted(self.evidence, key=lambda row: (row.candidate_id, row.strategy))))
        outcomes = {(candidate, strategy): _eligibility(self.policy, by_key.get((candidate, strategy)))
                    for candidate in self.candidate_ids for strategy in STRATEGIES}
        eligible = sorted((key for key, (status, _, _) in outcomes.items() if status == "eligible"),
                          key=lambda key: (-outcomes[key][1], *key))
        ranks = {key: index + 1 for index, key in enumerate(eligible)}
        rows = tuple(DevelopmentRank(*key, *value, ranks.get(key)) for key, value in outcomes.items())
        incomplete = any(row.status == "unavailable" for row in rows)
        selected = eligible[0] if eligible and not incomplete else None
        object.__setattr__(self, "candidates", rows)
        object.__setattr__(self, "status", "incomplete_search" if incomplete else "selected" if selected else "insufficient_sample")
        object.__setattr__(self, "selected_candidate", selected[0] if selected else None)
        object.__setattr__(self, "selected_strategy", selected[1] if selected else None)

    def to_dict(self) -> dict:
        return {"schema_version": 1, "policy": asdict(self.policy), "candidate_ids": list(self.candidate_ids),
                "strategies": list(STRATEGIES), "evidence": [asdict(row) for row in self.evidence],
                "candidates": [asdict(row) for row in self.candidates], "status": self.status,
                "selected_candidate": self.selected_candidate, "selected_strategy": self.selected_strategy}

    @property
    def selection_id(self) -> str:
        return fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> DevelopmentSelection:
        """Recompute all ranks and reject altered results even after an outer hash is updated."""
        if not isinstance(value, dict):
            raise TypeError("development selection requires an object")
        result = cls(DevelopmentPolicy(**value["policy"]), tuple(value["candidate_ids"]),
                     tuple(DevelopmentEvidence(**row) for row in value["evidence"]))
        if fingerprint(result.to_dict()) != fingerprint(value):
            raise ValueError("development selection differs from reconstructed semantics")
        return result
