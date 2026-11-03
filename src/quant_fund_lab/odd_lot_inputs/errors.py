"""Source-local diagnostics remain compatible with callers catching ValueError."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PriceSourceError(ValueError):
    """Identify the original file/row without replacing its validation failure.

    Exceptions remain mutable so Python can attach tracebacks and causes.
    Row locators are provider array offsets or physical normalized CSV lines;
    manifest-level errors have no observation row.
    """

    source_path: str
    row_locator: str | None
    detail: str

    def __post_init__(self) -> None:
        location = self.source_path + (f" [{self.row_locator}]" if self.row_locator else "")
        ValueError.__init__(self, f"{location}: {self.detail}")
