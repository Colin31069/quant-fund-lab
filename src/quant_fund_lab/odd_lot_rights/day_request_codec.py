"""Portable complete daily request, retaining the canonical prior checkpoint."""
import json
from dataclasses import fields

from ..data import MarketData
from ..odd_lot_paper.bridge import capture_session_state, restore_session_state
from ..odd_lot_paper.serialization import decode_state, encode_state
from ..odd_lot_paper.session import OddLotSessionInput
from .authorization_archive_codec import decode_authorized_account, encode_authorized_account
from .codec import canonical
from .day_workflow import RightsDayRequest
from .durable_day_workflow import DurableRightsDay
from .request_values_codec import decode_value, encode_value


def encode_day_request(day: DurableRightsDay) -> str:
    request, inputs = day.request, day.request.inputs
    if request.recorded_before is not None:
        raise ValueError("daily archive stores a predecessor request, not a labelled replay prefix")
    i, dates = inputs.signal_index, inputs.data.close.index
    if type(i) is not int or not 0 <= inputs.origin_index <= i < len(dates)-1:
        raise ValueError("daily archive requires valid source indexes")
    prior = capture_session_state(inputs.runtime, session=str(dates[i].date()),
        origin_session=str(dates[inputs.origin_index].date()), session_offset=i-inputs.origin_index,
        completed_index=i)
    data = {field.name: encode_value(getattr(inputs.data, field.name)) for field in fields(MarketData)}
    values = {field.name: encode_value(getattr(inputs, field.name)) for field in fields(OddLotSessionInput)
              if field.name not in {"runtime", "data"}}
    commands = {field.name: encode_value(getattr(request, field.name)) for field in fields(RightsDayRequest)
                if field.name not in {"inputs", "account", "recorded_before"}}
    return canonical({"schema_version": 1, "kind": "rights_day_request",
        "prior_engine": encode_state(prior), "account": encode_authorized_account(request.account),
        "data": data, "inputs": values, "request": commands,
        "securities": encode_value(day.securities), "rights": encode_value(day.rights),
        "valuation_at": day.valuation_at})


def decode_day_request(payload: str) -> DurableRightsDay:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate daily request JSON key")
            result[key] = value
        return result

    value = json.loads(payload, object_pairs_hook=unique)
    expected = {"schema_version", "kind", "prior_engine", "account", "data", "inputs", "request",
                "securities", "rights", "valuation_at"}
    if (not isinstance(value, dict) or set(value) != expected
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["kind"] != "rights_day_request"):
        raise ValueError("unsupported daily request archive schema")
    if set(value["data"]) != {field.name for field in fields(MarketData)}:
        raise ValueError("daily request source fields differ")
    source = MarketData(**{key: decode_value(row) for key, row in value["data"].items()})
    input_fields = {field.name for field in fields(OddLotSessionInput)}-{"data", "runtime"}
    request_fields = {field.name for field in fields(RightsDayRequest)}-{"inputs", "account", "recorded_before"}
    if set(value["inputs"]) != input_fields or set(value["request"]) != request_fields:
        raise ValueError("daily request input/command fields differ")
    values = {key: decode_value(row) for key, row in value["inputs"].items()}
    prior = decode_state(value["prior_engine"])
    runtime = restore_session_state(prior, completed_index=values["signal_index"])
    inputs = OddLotSessionInput(runtime=runtime, data=source, **values)
    request = RightsDayRequest(account=decode_authorized_account(value["account"]), inputs=inputs,
        **{key: decode_value(row) for key, row in value["request"].items()})
    result = DurableRightsDay(request, decode_value(value["securities"]), decode_value(value["rights"]),
                               value["valuation_at"])
    if encode_day_request(result) != payload:
        raise ValueError("daily request archive is not canonical or contains changed values")
    return result
