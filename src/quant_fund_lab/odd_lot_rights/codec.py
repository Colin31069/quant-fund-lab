"""Exact Decimal checkpoint encoding; no float conversion or silent extra fields."""
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal

from .types import ActionReceipt, EntitlementEvent, EntitlementLeg, RightPosition, RightsBook


def _decimal(value):
    if not isinstance(value, Decimal):
        raise TypeError("unsupported rights JSON value")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_decimal)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def encode_book(book: RightsBook) -> str:
    return canonical({"schema_version":1, "book":asdict(book)})


def _amount(value: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError("encoded rights amounts require exact strings")
    return Decimal(value)


def decode_book(payload: str) -> RightsBook:
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate rights JSON key")
            values[key] = value
        return values

    encoded = json.loads(payload, object_pairs_hook=unique)
    if (set(encoded) != {"schema_version", "book"} or type(encoded["schema_version"]) is not int
            or encoded["schema_version"] != 1):
        raise ValueError("unsupported rights book schema")
    values = dict(encoded["book"])
    positions = []
    for record in values["positions"]:
        row = dict(record)
        event = dict(row["event"])
        event["legs"] = tuple(EntitlementLeg(**{**leg, "units_per_parent":_amount(leg["units_per_parent"])})
                              for leg in event["legs"])
        event["evidence_sha256"] = tuple(event["evidence_sha256"])
        row["event"] = EntitlementEvent(**event)
        for field in ("entitled", "unpaid", "expired", "settled_fraction", "cash_paid", "fees_paid"):
            row[field] = _amount(row[field])
        positions.append(RightPosition(**row))
    values["positions"] = tuple(positions)
    values["receipts"] = tuple(ActionReceipt(**row) for row in values["receipts"])
    values["cash"] = _amount(values["cash"])
    book = RightsBook(**values)
    if encode_book(book) != payload:
        raise ValueError("rights checkpoint encoding is not canonical")
    return book
