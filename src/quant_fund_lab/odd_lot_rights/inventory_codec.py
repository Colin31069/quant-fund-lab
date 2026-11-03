"""Versioned exact joined rights/inventory checkpoint, separate from SQL state-v1."""
import json
from dataclasses import asdict
from decimal import Decimal

from .codec import canonical, decode_book, encode_book
from .inventory import RightsInventory, SecurityLot


def encode_inventory(account: RightsInventory) -> str:
    RightsInventory(account.initial_cash,account.initial_lots,account.book,account.lots,account.postings)
    return canonical({"schema_version":1,"initial_cash":account.initial_cash,
        "initial_lots":[asdict(row) for row in account.initial_lots],"book":encode_book(account.book),
        "lots":[asdict(row) for row in account.lots],"postings":account.postings})


def decode_inventory(payload: str) -> RightsInventory:
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError("duplicate rights inventory JSON key")
            result[key] = value
        return result

    values = json.loads(payload,object_pairs_hook=unique)
    if (not isinstance(values,dict) or set(values) != {
            "schema_version","initial_cash","initial_lots","book","lots","postings"}
            or type(values["schema_version"]) is not int or values["schema_version"] != 1):
        raise ValueError("unsupported rights inventory checkpoint schema")
    if not isinstance(values["initial_cash"],str):
        raise TypeError("rights inventory cash anchor must be an exact Decimal string")
    result = RightsInventory(Decimal(values["initial_cash"]),
        tuple(SecurityLot(**row) for row in values["initial_lots"]),decode_book(values["book"]),
        tuple(SecurityLot(**row) for row in values["lots"]),tuple(tuple(row) for row in values["postings"]))
    if encode_inventory(result) != payload:
        raise ValueError("rights inventory checkpoint is not canonical")
    return result
