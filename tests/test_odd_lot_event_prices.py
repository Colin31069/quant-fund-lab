"""Independent price-level hand examples before integrating the daily event phase."""
import math

import pytest

from quant_fund_lab.odd_lot_paper.event_prices import EventPriceInput, adjust_event_prices


def test_dividend_precedes_split_for_reference_and_risk_levels():
    values = EventPriceInput(100., 2., 4., 90., 110.)
    result = adjust_event_prices(values)
    assert (result.reference, result.stop, result.high_close) == (48., 43., 53.)
    assert result.cancel_pending_buy
    assert values.stop == 90 and values.high_close == 110


@pytest.mark.parametrize("ratio,dividend,reference,stop,high,cancel", [
    (1., 0., 100., 90., 110., False),
    (.5, 0., 200., 180., 220., True),
    (1., 120., 0., 0., 0., False),
    (0., 2., 98., 88., 108., False),
])
def test_historical_special_cases_remain_explicit(ratio, dividend, reference, stop, high, cancel):
    result = adjust_event_prices(EventPriceInput(100., ratio, dividend, 90., 110.))
    assert (result.reference, result.stop, result.high_close, result.cancel_pending_buy) == (
        reference, stop, high, cancel)


def test_unknown_event_does_not_invent_reference_or_stop_adjustment():
    result = adjust_event_prices(EventPriceInput(100., float("nan"), 2., 90., 110.))
    assert math.isnan(result.reference) and result.stop == 88 and not result.cancel_pending_buy
    passive = adjust_event_prices(EventPriceInput(100., 2., 4.))
    assert passive.reference == 48 and passive.stop is None and passive.high_close is None
