from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .data import MarketData


@dataclass(frozen=True)
class CorporateActionValidation:
    dividend_events: int
    split_events: int
    negative_dividend_events: tuple[tuple[pd.Timestamp, str], ...]
    invalid_split_events: tuple[tuple[pd.Timestamp, str], ...]
    suspicious_split_adjustments: tuple[tuple[pd.Timestamp, str], ...]

    @property
    def is_valid(self) -> bool:
        return not (
            self.negative_dividend_events
            or self.invalid_split_events
            or self.suspicious_split_adjustments
        )


def validate_corporate_actions(data: MarketData) -> CorporateActionValidation:
    dividends = data.dividends if data.dividends is not None else data.close * 0.0
    splits = data.stock_splits if data.stock_splits is not None else data.close * 0.0
    returns = data.close.pct_change(fill_method=None)

    negative: list[tuple[pd.Timestamp, str]] = []
    invalid_splits: list[tuple[pd.Timestamp, str]] = []
    suspicious: list[tuple[pd.Timestamp, str]] = []
    for timestamp in data.close.index:
        for symbol in data.symbols:
            dividend = float(dividends.at[timestamp, symbol])
            split = float(splits.at[timestamp, symbol])
            if dividend < 0.0:
                negative.append((pd.Timestamp(timestamp), symbol))
            if split < 0.0 or (0.0 < split < 0.01):
                invalid_splits.append((pd.Timestamp(timestamp), symbol))
            if split > 0.0:
                adjusted_return = returns.at[timestamp, symbol]
                if pd.notna(adjusted_return) and abs(float(adjusted_return)) > 0.50:
                    suspicious.append((pd.Timestamp(timestamp), symbol))

    return CorporateActionValidation(
        dividend_events=int((dividends > 0.0).sum().sum()),
        split_events=int((splits > 0.0).sum().sum()),
        negative_dividend_events=tuple(negative),
        invalid_split_events=tuple(invalid_splits),
        suspicious_split_adjustments=tuple(suspicious),
    )
