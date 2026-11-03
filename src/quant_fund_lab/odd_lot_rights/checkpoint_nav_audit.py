"""Independent combined-checkpoint NAV equations; no production valuation calls."""
import json
from dataclasses import dataclass, fields
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from .engine_checkpoint import RightsEngineCheckpoint
from .session_nav import RightsSessionNAV
from .types import clock, evidence, number


@dataclass(frozen=True)
class CheckpointNAVAudit:
    issues: tuple[str, ...]
    scope: str = "independent_checkpoint_cash_claim_security_receivable_nav_equations"

    @property
    def passed(self) -> bool:
        return not self.issues


def audit_checkpoint_nav(checkpoint: RightsEngineCheckpoint, recorded: dict,
                         securities: list[dict], rights: list[dict],
                         raw_close: dict[str, Decimal], currencies: dict[str, str],
                         *, as_of: str) -> CheckpointNAVAudit:
    """Recompute explicit NAV components from a financially checked checkpoint.

    raw_close/currencies and mark evidence must come from authenticated external
    inputs. This checks quantities, clocks and valuation equations independently
    of value_session_nav/value_inventory/value_book; it does not establish that
    declared market prices or historical publications are economically true.
    """
    try:
        RightsEngineCheckpoint(checkpoint.engine, checkpoint.account)
        state, inventory = checkpoint.engine, checkpoint.account.inventory
        stamp = clock(as_of)
        if (stamp.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat() != state.session
                or (inventory.book.through is not None and stamp < clock(inventory.book.through))):
            raise ValueError("checkpoint NAV uses a future state or a different processing date")
        if set(recorded) != {field.name for field in fields(RightsSessionNAV)}:
            raise ValueError("checkpoint NAV field schema differs")
        sessions = [(row.action_id, json.loads(row.command_json)) for row in inventory.book.receipts
                    if json.loads(row.command_json)["kind"] in {"portfolio_session", "portfolio_lot_session"}]
        if not sessions:
            raise ValueError("checkpoint NAV has no original session anchor")
        action, command = sessions[-1]
        link = command["terms"]["link"]
        if (link["session"] != state.session or recorded["session"] != state.session
                or recorded["source_action_id"] != action or recorded["as_of"] != as_of):
            raise ValueError("checkpoint NAV source action or processing boundary differs")

        def amount(value):
            if not isinstance(value, (str, Decimal)):
                raise TypeError("checkpoint NAV amounts require exact decimal values")
            result = Decimal(value)
            number(result)
            return result

        def raw(symbol):
            if currencies.get(symbol) != "TWD" or symbol not in raw_close:
                raise ValueError("checkpoint NAV lacks a known TWD raw mark")
            value = raw_close[symbol]
            number(value)
            if value <= 0:
                raise ValueError("checkpoint NAV raw mark must be positive")
            return value

        def marks(rows, required, components=False):
            if not isinstance(rows, list):
                raise TypeError("checkpoint NAV marks require explicit lists")
            lookup = {}
            for row in rows:
                identity = "right_key" if components else "security_id"
                expected = {identity, "unit_value", "session", "available_at", "evidence_sha256"}
                if components:
                    expected.add("component")
                if set(row) != expected:
                    raise ValueError("checkpoint NAV mark schema differs")
                evidence(row["available_at"], tuple(row["evidence_sha256"]))
                if row["session"] != state.session or clock(row["available_at"]) > stamp:
                    raise ValueError("checkpoint NAV mark is stale or not yet available")
                key = (row[identity], row["component"]) if components else row[identity]
                if key in lookup:
                    raise ValueError("checkpoint NAV mark is duplicated")
                lookup[key] = amount(row["unit_value"])
            if set(lookup) != set(required):
                raise ValueError("checkpoint NAV marks are missing or unrelated")
            return lookup

        with localcontext() as context:
            context.prec = 80
            owned = {}
            for lot in inventory.lots:
                owned[lot.security_id] = owned.get(lot.security_id, 0)+lot.units
            stock_marks = marks(securities, owned)
            for symbol, price in stock_marks.items():
                if symbol in raw_close and price != raw(symbol):
                    raise ValueError("checkpoint security mark differs from raw source")
            required = {(row.key, part): units for row in inventory.book.positions
                        for part, units in (("unpaid", row.unpaid), ("pending", row.pending)) if units}
            claim_marks = marks(rights, required, True)
            unpaid = sum((units*claim_marks[key] for key, units in required.items() if key[1] == "unpaid"), Decimal(0))
            pending = sum((units*claim_marks[key] for key, units in required.items() if key[1] == "pending"), Decimal(0))
            held = sum((units*stock_marks[key] for key, units in owned.items()), Decimal(0))
            fractional = Decimal(0)
            for claim in state.receivables:
                if claim.local_currency != "TWD" or claim.settlement_date <= state.session:
                    raise ValueError("checkpoint fractional claim currency/timing differs")
                fractional += Decimal(str(claim.fractional_quantity))*raw(claim.symbol)
            if abs(Decimal(str(state.receivable_value))-fractional) > Decimal("0.000001"):
                raise ValueError("checkpoint fractional receivable mark differs")
            outstanding = [row for row in state.settlements if row.settled_at is None]
            sales = sum((Decimal(str(row.amount)) for row in outstanding if row.side == "SELL" and row.amount >= 0), Decimal(0))
            buys = sum((Decimal(str(row.amount)) for row in outstanding if row.side == "BUY"), Decimal(0))
            fees = sum((-Decimal(str(row.amount)) for row in outstanding if row.side == "SELL" and row.amount < 0), Decimal(0))
            if sales != amount(link["unsettled_sales"]):
                raise ValueError("checkpoint sale receivables differ from recorded session")
            baseline_held = sum((units*raw(symbol) for symbol, units in link["shares_after"]), Decimal(0))
            expected = {"cash": inventory.cash, "held_securities": held, "unpaid_rights": unpaid,
                "pending_claims": pending, "sale_receivables": sales, "fractional_receivables": fractional,
                "buy_payables": buys, "sale_fee_payables": fees, "settled_cash": inventory.cash+buys+fees,
                "engine_equity": amount(link["cash_after"])+baseline_held+fractional+sales,
                "nav": inventory.cash+held+unpaid+pending+sales+fractional}
            issues = tuple("checkpoint NAV "+name+" differs from independent equations"
                           for name, value in expected.items() if amount(recorded[name]) != value)
            return CheckpointNAVAudit(issues)
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError, AttributeError) as exc:
        return CheckpointNAVAudit(("invalid checkpoint NAV evidence: "+str(exc),))
