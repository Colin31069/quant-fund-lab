import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from quant_fund_lab import __version__
from quant_fund_lab.backtest import run_backtest
from quant_fund_lab.config import BacktestConfig, StrategyConfig
from quant_fund_lab.data import synthetic_market_data
from quant_fund_lab.provenance import AuditLog, build_run_manifest, deterministic_run_id
from quant_fund_lab.providers import SnapshotProvider, load_with_failover
from quant_fund_lab.reporting import export_research_report, verify_research_report
from quant_fund_lab.snapshot import save_market_data_snapshot


class FailingProvider:
    name = "broken"

    def load(self, symbols: list[str], start: str, end: str):
        raise RuntimeError("provider unavailable")


class SyntheticProvider:
    name = "synthetic"

    def __init__(self, data):
        self.data = data

    def load(self, symbols: list[str], start: str, end: str):
        return self.data


def test_provider_chain_fails_over_and_records_attempts():
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=40)
    result = load_with_failover(
        [FailingProvider(), SyntheticProvider(data)],
        ["AAA", "BBB"],
        "2024-01-01",
        "2025-01-01",
    )
    assert result.provider == "synthetic"
    assert [attempt.success for attempt in result.attempts] == [False, True]


def test_verified_snapshot_provider_checks_coverage_and_integrity(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB"), periods=80)
    root = tmp_path / "snapshots" / "full"
    save_market_data_snapshot(data, root)
    provider = SnapshotProvider((tmp_path / "snapshots",))
    loaded = provider.load(
        ["AAA"],
        str(data.close.index[5].date()),
        str((data.close.index[30] + pd.Timedelta(days=1)).date()),
    )
    assert loaded.symbols == ["AAA"]
    assert loaded.close.index.min() >= data.close.index[5]

    close_path = root / "close.parquet"
    close_path.write_bytes(close_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="fallback unavailable"):
        provider.load(
            ["AAA"],
            str(data.close.index[5].date()),
            str((data.close.index[30] + pd.Timedelta(days=1)).date()),
        )


def test_run_id_is_deterministic_and_config_sensitive():
    config = BacktestConfig(strategy=StrategyConfig(risk_aversion=4.0))
    same = deterministic_run_id(config, "dataset-123")
    assert same == deterministic_run_id(config, "dataset-123")
    changed = deterministic_run_id(
        BacktestConfig(strategy=StrategyConfig(risk_aversion=8.0)), "dataset-123"
    )
    assert same != changed
    contextual = deterministic_run_id(config, "dataset-123", run_context={"split": 0.7})
    assert contextual != deterministic_run_id(config, "dataset-123", run_context={"split": 0.8})
    manifest = build_run_manifest(config, "dataset-123")
    assert manifest.run_id == same
    assert manifest.config_schema_version == 1
    assert manifest.package_version == __version__
    lifecycle_run = deterministic_run_id(
        config,
        "dataset-123",
        data_provenance={"security_lifecycle_dataset_id": "life-001"},
    )
    assert lifecycle_run != deterministic_run_id(
        config,
        "dataset-123",
        data_provenance={"security_lifecycle_dataset_id": "life-002"},
    )
    provenance_manifest = build_run_manifest(
        config,
        "dataset-123",
        data_provenance={"security_lifecycle_dataset_id": "life-001"},
    )
    assert provenance_manifest.run_id == lifecycle_run
    assert provenance_manifest.data_provenance == {
        "security_lifecycle_dataset_id": "life-001"
    }


def test_audit_log_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)
    first = audit.append(
        "RUN_STARTED",
        {"run_id": "abc"},
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = audit.append(
        "RUN_FINISHED",
        {"status": "ok"},
        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    events = audit.read_and_verify()
    assert events[0].event_hash == first.event_hash
    assert events[1].previous_hash == first.event_hash
    assert events[1].event_hash == second.event_hash

    content = path.read_text(encoding="utf-8").replace('"status":"ok"', '"status":"bad"')
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.read_and_verify()


def test_report_export_is_hash_verifiable(tmp_path):
    data = synthetic_market_data(symbols=("AAA", "BBB", "CCC", "DDD"), periods=240, seed=17)
    config = BacktestConfig(
        initial_cash=500_000,
        strategy=StrategyConfig(warmup_days=80, rebalance_every=5, max_weight=0.4),
    )
    result = run_backtest(data, config)
    root = tmp_path / "report"
    run, hashes = export_research_report(
        result,
        config,
        "dataset-test",
        root,
        data_provenance={"security_lifecycle_dataset_id": "life-test"},
    )
    assert run.run_id
    assert run.data_provenance["security_lifecycle_dataset_id"] == "life-test"
    assert "report.html" in hashes
    assert "session_validations.json" in hashes
    assert "data_provenance.json" in hashes
    sessions = json.loads((root / "session_validations.json").read_text(encoding="utf-8"))
    assert "US" in sessions
    assert {
        "observed_sessions",
        "expected_sessions",
        "missing_sessions",
        "off_calendar_sessions",
    }.issubset(sessions["US"])
    assert json.loads((root / "data_provenance.json").read_text(encoding="utf-8")) == {
        "security_lifecycle_dataset_id": "life-test"
    }
    report_manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
    assert report_manifest["schema_version"] == 2
    manifest_payload = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["data_provenance"]["security_lifecycle_dataset_id"] == "life-test"
    assert verify_research_report(root)
    weights_path = root / "weights.csv"
    weights_path.write_text(weights_path.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
    assert not verify_research_report(root)
