"""A captured development analysis remains distinct from a published validation decision."""
from __future__ import annotations

from dataclasses import dataclass

from .development import DevelopmentSelection
from .source_types import DecisionSource

DEVELOPMENT_SOURCE_RULE = "development_accounts_from_latest_prefix_v1"


@dataclass(frozen=True)
class DevelopmentInputs:
    sources: tuple[DecisionSource, ...]
    selection: DevelopmentSelection
    source_rule: str = DEVELOPMENT_SOURCE_RULE

    def __post_init__(self) -> None:
        if (not isinstance(self.selection, DevelopmentSelection) or not isinstance(self.sources, tuple)
                or not all(isinstance(row, DecisionSource) for row in self.sources)):
            raise TypeError("development inputs require typed immutable sources and selection")
        if (self.source_rule != DEVELOPMENT_SOURCE_RULE or len(self.sources) != len(self.selection.candidate_ids)
                or {row.candidate_id for row in self.sources} != set(self.selection.candidate_ids)):
            raise ValueError("development source inventory differs from declared selection budget")

    def to_dict(self) -> dict:
        return {"source_rule": self.source_rule, "sources": [row.to_dict() for row in self.sources],
                "selection": self.selection.to_dict(), "selection_id": self.selection.selection_id}
