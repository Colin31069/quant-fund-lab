"""Independent fee arithmetic honors each separately rounded component."""
import pytest

from quant_fund_lab.odd_lot_paper.audit_fees import expected_fees, reconcile_fill_fees


@pytest.mark.parametrize("rounding,expected", [
    ("fractional", (20., 40.5)), ("floor", (20., 40.)), ("nearest", (20., 41.))])
def test_minimum_commission_and_sale_tax_are_separately_rounded(rounding, expected):
    research = {"commission_bps":14.25,"min_commission":20.,"fee_rounding":rounding,
                "instrument_rules":{"2330.TW":{"sell_tax_bps":30.}}}
    assert expected_fees("SELL", 13500., research, "2330.TW") == expected
    assert expected_fees("BUY", 13500., research, "2330.TW") == (20., 0.)


def test_etf_uses_its_frozen_rate_instead_of_stock_tax_default():
    research = {"commission_bps":0.,"min_commission":0.,"fee_rounding":"fractional",
                "instrument_rules":{"0050.TW":{"sell_tax_bps":10.}}}
    assert expected_fees("SELL", 10000., research, "0050.TW") == (0., 10.)
    with pytest.raises(ValueError):
        expected_fees("UNKNOWN", 10000., research, "0050.TW")


def test_fee_fields_cannot_be_made_valid_only_by_agreeing_with_each_other():
    research = {"commission_bps":0.,"min_commission":20.,"fee_rounding":"floor",
                "instrument_rules":{"2330.TW":{"sell_tax_bps":30.}}}
    fill = {"symbol":"2330.TW","side":"BUY","quantity":1,"gross_value":100.,
            "fill_price":100.,"reference_price":100.,"commission":21.,"sell_tax":0.,
            "fees":21.,"fees_local":21.,"gross_value_local":100.,
            "slippage_cost":0.,"slippage_cost_local":0.}
    order = {"symbol":"2330.TW","side":"BUY","filled_quantity":1,
             "requested_quantity":1,"expired_quantity":0,"open_proxy":100.}
    issues = reconcile_fill_fees({"fills":[fill],"orders":[order]}, research)
    assert any("commission" in issue for issue in issues) and any("fees" in issue for issue in issues)
    valid = {**fill,"commission":20.,"fees":20.,"fees_local":20.}
    assert not reconcile_fill_fees({"fills":[valid],"orders":[order]}, research)
