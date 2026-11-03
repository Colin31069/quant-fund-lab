"""Independent fee and order/fill reconciliation from locked research assumptions."""
from __future__ import annotations

import math
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal


def expected_fees(side: str, gross: float, research: dict, symbol: str) -> tuple[float, float]:
    """Recompute each fee component without importing matching/cost engine helpers."""
    if side not in {"BUY", "SELL"} or not math.isfinite(gross) or gross < 0:
        raise ValueError("invalid fee calculation inputs")
    commission = max(gross*research["commission_bps"]/10000., research["min_commission"])
    tax = gross*research["instrument_rules"][symbol]["sell_tax_bps"]/10000. if side == "SELL" else 0.
    mode = research["fee_rounding"]
    if mode == "fractional":
        return commission, tax
    if mode not in {"floor", "nearest"}:
        raise ValueError("unsupported fee rounding policy")
    rounding = ROUND_FLOOR if mode == "floor" else ROUND_HALF_UP
    return tuple(float(Decimal(str(value)).quantize(Decimal(1), rounding=rounding))
                 for value in (commission, tax))


def reconcile_fill_fees(groups: dict[str, list], research: dict) -> tuple[str, ...]:
    issues = []
    fills = groups.get("fills", [])
    orders = groups.get("orders", [])
    filled_orders = [row for row in orders if row["filled_quantity"] > 0]
    if len(filled_orders) != len(fills):
        issues.append("filled order/fill count differs")
    for fill in fills:
        matches = [row for row in filled_orders if row["symbol"] == fill["symbol"]
                   and row["side"] == fill["side"]]
        if len(matches) != 1 or matches[0]["filled_quantity"] != fill["quantity"]:
            issues.append("fill does not match exactly one filled order")
        else:
            order = matches[0]
            if order["open_proxy"] != fill["reference_price"]:
                issues.append("fill opening reference differs from order")
            if order["requested_quantity"] != order["filled_quantity"]+order["expired_quantity"]:
                issues.append("filled/expired quantity does not reconcile")
        commission, tax = expected_fees(fill["side"], fill["gross_value"], research, fill["symbol"])
        expected = {"commission":commission,"sell_tax":tax,"fees":commission+tax,
                    "fees_local":commission+tax,"gross_value_local":fill["gross_value"],
                    "slippage_cost":abs(fill["fill_price"]-fill["reference_price"])*fill["quantity"],
                    "slippage_cost_local":abs(fill["fill_price"]-fill["reference_price"])*fill["quantity"]}
        for key, value in expected.items():
            actual = fill[key]
            if not math.isfinite(actual) or not math.isclose(actual, value, abs_tol=1e-6, rel_tol=1e-12):
                issues.append("fill "+key+" differs from locked fee/order assumptions")
    return tuple(issues)
