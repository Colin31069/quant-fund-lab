"""Deterministic target schedules for real29/30-episode v6 boundary acceptance."""
from __future__ import annotations

import pandas as pd


def sample_boundary_targets(development_count: int, validation_count: int, *,
                            signal_starts: tuple[str, str]):
    """Trade only the first asset, closing each entry on the following session.

    Fixture periods use signal-history lengths120–199 and200–279. Counts are
    explicit; prices, costs, account events and report metrics remain real engine
    calculations. This is a retrospective offline accounting fixture, not alpha.

    Those lengths describe the full source frame. A registered study trims each
    period to its own warm-up, so history length cannot identify the period.
    Explicit signal-session anchors keep the schedule unchanged by that trim.
    """
    if any(type(value) is not int or not 0 <= value <= 40
           for value in (development_count, validation_count)):
        raise ValueError("boundary fixture requires zero to40 whole completed cycles")
    if (type(signal_starts) is not tuple or len(signal_starts) != 2
            or any(not isinstance(value, str) or pd.Timestamp(value).date().isoformat() != value
                   for value in signal_starts) or signal_starts[0] >= signal_starts[1]):
        raise ValueError("boundary fixture needs two ordered canonical signal-session anchors")
    anchors = tuple(pd.Timestamp(value) for value in signal_starts)

    def targets(history, eligible, research, strategy, previous):
        current = history.index[-1]
        origin, count = ((anchors[0], development_count) if current < anchors[1] else (anchors[1], validation_count))
        origin_index = history.index.get_indexer([origin])[0]
        if current >= origin and origin_index < 0:
            raise ValueError("boundary fixture history omits its declared signal origin")
        offset = len(history)-1-origin_index if current >= origin else -1
        active = 0 <= offset < count * 2 and offset % 2 == 0
        weights = pd.Series(0.0, index=history.columns)
        if active:
            weights.iloc[0] = research.max_weight
        return pd.Series(1.0, index=history.columns), weights

    return targets
