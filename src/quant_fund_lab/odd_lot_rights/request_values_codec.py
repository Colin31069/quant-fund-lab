"""Closed type registry for portable request values; never import arbitrary types."""
from dataclasses import fields, is_dataclass
from decimal import Decimal

import pandas as pd

from ..config import BacktestConfig, DividendWithholdingConfig, MarketCostConfig, StrategyConfig
from ..odd_lot_paper.event_codec import decode_event, encode_event
from ..odd_lot_paper.sale_limits import OpeningSaleLimits
from ..odd_lot_paper.types import PendingOrder, StopState
from ..odd_lot_research import OddLotResearchConfig
from .close_commands import RightsCloseCommand
from .conversion_risk import ReceiptRiskTransfer
from .inventory_valuation import SecurityMark
from .lot_events import LotRoundingPolicy, OpeningLotEvent
from .payment_authorization import PaymentAuthorization
from .session_policy import PaymentInterval, RightsSessionPolicy, SubscriptionElection
from .settlement import FractionalCashTerms, ReceiptConversionTerms
from .types import DeliveryTerms, EntitlementEvent, EntitlementLeg, PaymentRequest, PaymentTerms
from .valuation import RightsMark

CLASSES = {cls.__name__: cls for cls in (
    BacktestConfig, DividendWithholdingConfig, MarketCostConfig, StrategyConfig, OddLotResearchConfig,
    OpeningSaleLimits, PendingOrder, StopState, RightsCloseCommand, ReceiptRiskTransfer,
    SecurityMark, RightsMark, LotRoundingPolicy, OpeningLotEvent, PaymentAuthorization,
    PaymentInterval, RightsSessionPolicy, SubscriptionElection, FractionalCashTerms,
    ReceiptConversionTerms, DeliveryTerms, EntitlementEvent, EntitlementLeg, PaymentRequest, PaymentTerms)}


def encode_value(value):
    """Preserve exact financial strings, scalar kinds, frame values and dtypes."""
    if isinstance(value, Decimal):
        return ["decimal", str(value)]
    if isinstance(value, pd.DataFrame):
        if not isinstance(value.index, pd.DatetimeIndex) or not value.index.is_unique:
            raise ValueError("request frames require a unique DatetimeIndex")
        if not value.columns.is_unique or any(not isinstance(key, str) for key in value.columns):
            raise ValueError("request frame columns require unique string identities")
        return ["frame", {"index": encode_event(tuple(value.index)), "columns": list(value.columns),
            "index_name": encode_event(value.index.name), "column_name": encode_event(value.columns.name),
            "frequency": value.index.freqstr, "dtypes": [str(dtype) for dtype in value.dtypes],
            "rows": [encode_event(row) for row in value.itertuples(index=False, name=None)]}]
    if is_dataclass(value):
        name = type(value).__name__
        if CLASSES.get(name) is not type(value):
            raise TypeError("request archive refuses unregistered dataclass types")
        return ["typed", name, {field.name: encode_value(getattr(value, field.name)) for field in fields(value)}]
    if type(value) is tuple:
        return ["tuple", [encode_value(row) for row in value]]
    if type(value) is list:
        return ["list", [encode_value(row) for row in value]]
    if type(value) is dict:
        if any(not isinstance(key, str) for key in value):
            raise TypeError("request mappings require string keys")
        return ["dict", {key: encode_value(row) for key, row in value.items()}]
    return ["scalar", encode_event(value)]


def decode_value(value):
    if not isinstance(value, list) or not value:
        raise ValueError("request value requires an explicit tagged encoding")
    kind = value[0]
    if kind == "typed":
        if len(value) != 3 or value[1] not in CLASSES or not isinstance(value[2], dict):
            raise ValueError("unknown request type or malformed typed fields")
        cls = CLASSES[value[1]]
        if set(value[2]) != {field.name for field in fields(cls)}:
            raise ValueError("request typed fields must exactly match their schema")
        return cls(**{key: decode_value(row) for key, row in value[2].items()})
    if len(value) != 2:
        raise ValueError("request value has extra or missing fields")
    payload = value[1]
    if kind == "decimal":
        if not isinstance(payload, str):
            raise TypeError("request financial decimals require exact strings")
        return Decimal(payload)
    if kind in {"tuple", "list"}:
        rows = [decode_value(row) for row in payload]
        return tuple(rows) if kind == "tuple" else rows
    if kind == "dict":
        return {key: decode_value(row) for key, row in payload.items()}
    if kind == "scalar":
        return decode_event(payload)
    if kind == "frame":
        if set(payload) != {"index", "columns", "index_name", "column_name", "frequency", "dtypes", "rows"}:
            raise ValueError("request frame schema differs")
        index = pd.DatetimeIndex(decode_event(payload["index"]), name=decode_event(payload["index_name"]),
                                 freq=payload["frequency"])
        frame = pd.DataFrame([decode_event(row) for row in payload["rows"]],
                             index=index, columns=payload["columns"])
        if len(payload["dtypes"]) != len(frame.columns):
            raise ValueError("request frame dtype inventory differs")
        allowed = {"float64", "float32", "int64", "int32", "bool", "object", "datetime64[ns]"}
        for key, dtype in zip(frame.columns, payload["dtypes"]):
            if dtype not in allowed:
                raise ValueError("unsupported portable request frame dtype")
            frame[key] = frame[key].astype(dtype)
        frame.columns.name = decode_event(payload["column_name"])
        return frame
    raise ValueError("unknown request value encoding")
