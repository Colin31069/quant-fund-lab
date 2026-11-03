"""Small protocol-only fixtures, independent of network and local research artifacts."""
from quant_fund_lab.odd_lot_protocol.types import (
    ExecutionIdentity,
    ProtocolCandidate,
    ProtocolPeriod,
    SelectionRule,
    StudyProtocol,
    canonical_json,
)


def execution_identity():
    return ExecutionIdentity("fixture-revision", "c" * 64, "d" * 64,
                             canonical_json({"python": "fixture-runtime"}))


def selection_rule():
    return SelectionRule("calmar", "Validation must meet the frozen drawdown constraint.",
                         "Reject incomplete periods or insufficient completed trades.")


def protocol():
    candidate = ProtocolCandidate("1" * 24, canonical_json({"risk": 2000}),
                                   canonical_json({"cost": 20}))
    return StudyProtocol("a" * 64, "b" * 64, canonical_json({"source": "fixture"}),
        ("fixture-calendar",), ("2330.TW", "2317.TW"), "0050.TW", 120,
        (ProtocolPeriod("validation", "2024-01-01", "2024-12-31", "validation_check",
                        "accessed", "Offline fixture, never an unseen holdout."),),
        (candidate,), 1, selection_rule(), canonical_json({"grid": "fixture"}),
        execution_identity(), "2026-10-29T00:00:00+08:00")
