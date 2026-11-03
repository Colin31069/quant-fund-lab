"""Explicit post-event sale capacity for an opening, separate from owned NAV units."""
from dataclasses import dataclass
from datetime import date

from ..execution import PortfolioState


@dataclass(frozen=True)
class OpeningSaleLimits:
    """Complete per-held-security sell caps after the opening's corporate actions.

    The caller authenticates the underlying lots and corporate-action mapping.
    An omitted held identity is an error, not an implicit unlocked position.
    None at the calling boundary preserves the legacy unrestricted behavior.
    """

    session: str
    units: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if date.fromisoformat(self.session).isoformat() != self.session:
            raise ValueError("sale limits require a canonical opening session")
        if (type(self.units) is not tuple
                or any(type(row) is not tuple or len(row) != 2 for row in self.units)):
            raise TypeError("sale limits require immutable security/quantity pairs")
        for symbol, units in self.units:
            if (not isinstance(symbol, str) or not symbol or type(units) is not int
                    or not 0 <= units <= 10**12):
                raise ValueError("sale limits require explicit identities and integer capacities")
        if self.units != tuple(sorted(self.units)) or len(dict(self.units)) != len(self.units):
            raise ValueError("sale limits require unique canonical security ordering")

    def validate_for(self, portfolio: PortfolioState, session: str) -> dict[str, int]:
        """Validate against actual post-event owned shares before any orders run."""
        owned = {key: value for key, value in portfolio.shares.items() if value}
        caps = dict(self.units)
        if self.session != session or set(caps) != set(owned):
            raise ValueError("sale limits must match this opening and all owned identities")
        if any(caps[key] > value for key, value in owned.items()):
            raise ValueError("sale limit exceeds actual post-event owned shares")
        return caps
