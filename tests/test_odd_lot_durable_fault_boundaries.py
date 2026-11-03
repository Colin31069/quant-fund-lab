"""Interrupt actual business transitions and SQL validation, then retry exactly."""
import sqlite3
from dataclasses import dataclass

import pytest
from test_odd_lot_durable_events import _business, _run
from test_odd_lot_durable_events import _fixture as distribution_fixture
from test_odd_lot_durable_settlements import _fixture as settlement_fixture

from quant_fund_lab.odd_lot_paper import replay, session
from quant_fund_lab.odd_lot_paper.audit import audit_accounting


@dataclass(frozen=True)
class FaultBoundary:
    name: str
    completed_count: int
    settlement_fixture: bool = False


BOUNDARIES = (
    FaultBoundary("fill", 30),
    FaultBoundary("settlement", 33, True),
    FaultBoundary("nav", 32),
    FaultBoundary("checkpoint", 32),
    FaultBoundary("events", 32),
    FaultBoundary("precommit_audit", 32),
)


@pytest.mark.parametrize("boundary", BOUNDARIES, ids=lambda item: item.name)
@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_business_and_commit_interruptions_preserve_prefix_and_retry_exactly(
    tmp_path, monkeypatch, boundary, exception
):
    inputs = (settlement_fixture(monkeypatch) if boundary.settlement_fixture
              else distribution_fixture(monkeypatch))
    path, reference = tmp_path / "interrupted.sqlite", tmp_path / "reference.sqlite"
    _run(path, inputs, count=boundary.completed_count, create=True)
    before, before_bytes = _business(path), path.read_bytes()
    interrupted = []

    def stop():
        interrupted.append(boundary.name)
        raise exception("verified business boundary interruption")

    with monkeypatch.context() as patch:
        if boundary.name == "fill":
            original = session.execute_opening_orders

            def opening(arguments):
                result = original(arguments)
                assert len(result.fills) == 1
                assert result.fills[0]["quantity"] == 3
                assert result.portfolio.cash == 700.
                stop()

            patch.setattr(session, "execute_opening_orders", opening)
        elif boundary.name in {"settlement", "nav"}:
            original = session.close_odd_lot_session

            def closing(arguments):
                result = original(arguments)
                if boundary.name == "settlement":
                    assert result.portfolio.cash == 300.
                    assert result.nav["sale_receivables"] == 0.
                    assert any(row["side"] == "SELL" and row["settled_at"] is not None
                               for row in result.settlements)
                else:
                    assert result.nav["cash"] == 706.
                    assert result.nav["equity"] == 1000.
                stop()

            patch.setattr(session, "close_odd_lot_session", closing)
        elif boundary.name == "precommit_audit":
            original = replay.audit_accounting
            target = str(inputs[0].close.index[boundary.completed_count].date())

            def auditing(*args, **kwargs):
                result = original(*args, **kwargs)
                connection = kwargs["_connection"]
                latest = connection.execute(
                    "SELECT max(session) FROM session_checkpoints").fetchone()[0]
                if latest == target:
                    assert result.passed
                    assert connection.in_transaction
                    assert connection.execute(
                        "SELECT count(*) FROM session_events WHERE session=?", (target,)
                    ).fetchone()[0] > 0
                    stop()
                return result

            patch.setattr(replay, "audit_accounting", auditing)

        def sql_fault(stage):
            if stage == boundary.name:
                stop()

        with pytest.raises(exception, match="verified business boundary interruption"):
            _run(path, inputs, count=boundary.completed_count + 1, fault=sql_fault)

    assert interrupted == [boundary.name]
    assert _business(path) == before and path.read_bytes() == before_bytes
    assert audit_accounting(path).passed
    actual = _run(path, inputs)
    whole = _run(reference, inputs, create=True)
    assert actual.checkpoint == whole.checkpoint
    assert _business(path) == _business(reference)
    assert audit_accounting(path).passed
    with sqlite3.connect(path) as connection:
        sessions = connection.execute("SELECT count(*) FROM session_checkpoints").fetchone()[0]
    assert sessions == len(inputs[0].close) - 30
    completed_bytes = path.read_bytes()
    assert _run(path, inputs).committed_sessions == 0
    assert path.read_bytes() == completed_bytes
