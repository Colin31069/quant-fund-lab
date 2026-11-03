"""Exact combined engine/account serialization, separate from legacy SQL state-v1."""
import json

from ..odd_lot_paper.serialization import decode_state, encode_state
from .authorization_archive_codec import decode_authorized_account, encode_authorized_account
from .codec import canonical
from .engine_checkpoint import RightsEngineCheckpoint


def encode_engine_rights(checkpoint: RightsEngineCheckpoint) -> str:
    RightsEngineCheckpoint(checkpoint.engine, checkpoint.account)
    return canonical({"schema_version": 1, "engine": encode_state(checkpoint.engine),
                      "account": encode_authorized_account(checkpoint.account)})


def decode_engine_rights(payload: str) -> RightsEngineCheckpoint:
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate combined engine/account JSON key")
            values[key] = value
        return values

    value = json.loads(payload, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "engine", "account"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise ValueError("unsupported combined engine/account schema")
    result = RightsEngineCheckpoint(decode_state(value["engine"]), decode_authorized_account(value["account"]))
    if encode_engine_rights(result) != payload:
        raise ValueError("combined engine/account checkpoint is not canonical")
    return result
