from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import MarketData


@dataclass(frozen=True)
class CorporateActionValidation:
    dividend_events: int
    split_events: int
    negative_dividend_events: tuple[tuple[pd.Timestamp, str], ...]
    invalid_split_events: tuple[tuple[pd.Timestamp, str], ...]
    suspicious_split_adjustments: tuple[tuple[pd.Timestamp, str], ...]
    orphan_cash_in_lieu_prices: tuple[tuple[pd.Timestamp, str], ...]
    orphan_cash_in_lieu_settlement_dates: tuple[tuple[pd.Timestamp, str], ...]
    premature_cash_in_lieu_prices: tuple[tuple[pd.Timestamp, str], ...]
    missing_cash_in_lieu_settlement_prices: tuple[tuple[pd.Timestamp, str], ...]

    @property
    def is_valid(self) -> bool:
        return not (
            self.negative_dividend_events
            or self.invalid_split_events
            or self.suspicious_split_adjustments
            or self.orphan_cash_in_lieu_prices
            or self.orphan_cash_in_lieu_settlement_dates
            or self.premature_cash_in_lieu_prices
            or self.missing_cash_in_lieu_settlement_prices
        )


def validate_corporate_actions(data: MarketData) -> CorporateActionValidation:
    dividends = data.dividends if data.dividends is not None else data.close * 0.0
    splits = data.stock_splits if data.stock_splits is not None else data.close * 0.0
    returns = data.close.pct_change(fill_method=None)

    negative: list[tuple[pd.Timestamp, str]] = []
    invalid_splits: list[tuple[pd.Timestamp, str]] = []
    suspicious: list[tuple[pd.Timestamp, str]] = []
    orphan_prices: list[tuple[pd.Timestamp, str]] = []
    orphan_settlement_dates: list[tuple[pd.Timestamp, str]] = []
    premature_prices: list[tuple[pd.Timestamp, str]] = []
    missing_settlement_prices: list[tuple[pd.Timestamp, str]] = []
    referenced_settlement_prices: set[tuple[pd.Timestamp, str]] = set()
    prices = data.cash_in_lieu_prices
    settlement_dates = data.cash_in_lieu_settlement_dates
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
            event_key = (pd.Timestamp(timestamp), symbol)
            settlement_value = (
                pd.NaT
                if settlement_dates is None
                else settlement_dates.at[timestamp, symbol]
            )
            has_split_event = split > 0.0 and not np.isclose(split, 1.0)
            if pd.notna(settlement_value):
                settlement_date = pd.Timestamp(settlement_value)
                if not has_split_event:
                    orphan_settlement_dates.append(event_key)
                elif settlement_date > pd.Timestamp(timestamp):
                    settlement_key = (settlement_date, symbol)
                    referenced_settlement_prices.add(settlement_key)
                    split_date_price = (
                        float("nan") if prices is None else prices.at[timestamp, symbol]
                    )
                    if pd.notna(split_date_price):
                        premature_prices.append(event_key)
                    if settlement_date in data.close.index:
                        due_price = (
                            float("nan")
                            if prices is None
                            else prices.at[settlement_date, symbol]
                        )
                        if pd.isna(due_price):
                            missing_settlement_prices.append(settlement_key)

    if prices is not None:
        for timestamp in data.close.index:
            for symbol in data.symbols:
                if pd.isna(prices.at[timestamp, symbol]):
                    continue
                split = float(splits.at[timestamp, symbol])
                same_day_split = split > 0.0 and not np.isclose(split, 1.0)
                key = (pd.Timestamp(timestamp), symbol)
                if not same_day_split and key not in referenced_settlement_prices:
                    orphan_prices.append(key)

    return CorporateActionValidation(
        dividend_events=int((dividends > 0.0).sum().sum()),
        split_events=int((splits > 0.0).sum().sum()),
        negative_dividend_events=tuple(negative),
        invalid_split_events=tuple(invalid_splits),
        suspicious_split_adjustments=tuple(suspicious),
        orphan_cash_in_lieu_prices=tuple(orphan_prices),
        orphan_cash_in_lieu_settlement_dates=tuple(orphan_settlement_dates),
        premature_cash_in_lieu_prices=tuple(premature_prices),
        missing_cash_in_lieu_settlement_prices=tuple(missing_settlement_prices),
    )
