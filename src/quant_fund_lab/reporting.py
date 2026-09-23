from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .analytics import performance_metrics
from .backtest import BacktestResult
from .config import BacktestConfig
from .provenance import RunManifest, build_run_manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=True)


def _session_validation_payload(result: BacktestResult) -> dict[str, dict[str, object]]:
    reports = result.session_validations
    if not reports and result.session_validation is not None:
        reports = {result.session_validation.market: result.session_validation}
    return {
        market: {
            "market": report.market,
            "observed_sessions": report.observed_sessions,
            "expected_sessions": report.expected_sessions,
            "missing_sessions": [str(value.date()) for value in report.missing_sessions],
            "off_calendar_sessions": [
                str(value.date()) for value in report.off_calendar_sessions
            ],
            "is_valid": report.is_valid,
        }
        for market, report in sorted(reports.items())
    }


def export_research_report(
    result: BacktestResult,
    config: BacktestConfig,
    dataset_id: str,
    directory: str | Path,
    run_context: dict[str, object] | None = None,
    data_provenance: dict[str, str] | None = None,
) -> tuple[RunManifest, dict[str, str]]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    run = build_run_manifest(
        config,
        dataset_id,
        run_context=run_context,
        data_provenance=data_provenance,
    )
    metrics = performance_metrics(result.equity_curve["equity"])
    session_validations = _session_validation_payload(result)

    files: dict[str, Path] = {
        "equity_curve.csv": root / "equity_curve.csv",
        "fills.csv": root / "fills.csv",
        "weights.csv": root / "weights.csv",
        "alphas.csv": root / "alphas.csv",
        "regimes.csv": root / "regimes.csv",
        "cost_attribution.csv": root / "cost_attribution.csv",
        "factor_weights.csv": root / "factor_weights.csv",
        "risk_controls.csv": root / "risk_controls.csv",
        "corporate_actions.csv": root / "corporate_actions.csv",
    }
    _write_frame(result.equity_curve, files["equity_curve.csv"])
    _write_frame(result.fills, files["fills.csv"])
    _write_frame(result.weights, files["weights.csv"])
    _write_frame(result.alphas, files["alphas.csv"])
    _write_frame(result.regimes, files["regimes.csv"])
    _write_frame(result.cost_attribution, files["cost_attribution.csv"])
    _write_frame(result.factor_weights, files["factor_weights.csv"])
    _write_frame(result.risk_controls, files["risk_controls.csv"])
    _write_frame(result.corporate_actions, files["corporate_actions.csv"])

    metrics_path = root / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    files[metrics_path.name] = metrics_path

    run_path = root / "run_manifest.json"
    run_path.write_text(json.dumps(asdict(run), indent=2, sort_keys=True), encoding="utf-8")
    files[run_path.name] = run_path

    sessions_path = root / "session_validations.json"
    sessions_path.write_text(
        json.dumps(session_validations, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    files[sessions_path.name] = sessions_path

    provenance_path = root / "data_provenance.json"
    provenance_path.write_text(
        json.dumps(run.data_provenance, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    files[provenance_path.name] = provenance_path

    html_path = root / "report.html"
    summary_rows = "".join(
        f"<tr><th>{html.escape(key)}</th><td>{value:.6f}</td></tr>" for key, value in metrics.items()
    )
    provenance_rows = "".join(
        f"<tr><th>{html.escape(key)}</th><td><code>{html.escape(value)}</code></td></tr>"
        for key, value in sorted(run.data_provenance.items())
    )
    session_rows = "".join(
        "<tr>"
        f"<td>{html.escape(market)}</td>"
        f"<td>{payload['observed_sessions']}</td>"
        f"<td>{payload['expected_sessions']}</td>"
        f"<td>{len(payload['missing_sessions'])}</td>"
        f"<td>{len(payload['off_calendar_sessions'])}</td>"
        "</tr>"
        for market, payload in session_validations.items()
    )
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Quant Fund Lab Report</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:40px auto;padding:0 20px;}"
        "table{border-collapse:collapse;width:100%;margin:16px 0;}th,td{border:1px solid #ccc;"
        "padding:6px 8px;text-align:right;}th:first-child,td:first-child{text-align:left;}</style>"
        "</head><body>"
        f"<h1>Quant Fund Lab Research Report</h1><p>Run ID: <code>{run.run_id}</code></p>"
        f"<p>Dataset ID: <code>{html.escape(dataset_id)}</code></p>"
        f"<h2>Performance</h2><table>{summary_rows}</table>"
        f"<h2>Data Provenance</h2><table>{provenance_rows}</table>"
        "<h2>Market Session Validation</h2><table>"
        "<tr><th>Market</th><th>Observed</th><th>Expected</th>"
        "<th>Missing</th><th>Off-calendar</th></tr>"
        f"{session_rows}</table>"
        f"<h2>Latest Regimes</h2>{result.regimes.tail(20).to_html()}"
        f"<h2>Latest Weights</h2>{result.weights.tail(20).to_html()}"
        "</body></html>",
        encoding="utf-8",
    )
    files[html_path.name] = html_path

    hashes = {name: _sha256(path) for name, path in sorted(files.items())}
    report_id = hashlib.sha256(
        json.dumps(
            {"run_id": run.run_id, "files": hashes}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": 2,
        "report_id": report_id,
        "run_id": run.run_id,
        "dataset_id": dataset_id,
        "files": hashes,
    }
    (root / "report_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return run, hashes


def verify_research_report(directory: str | Path) -> bool:
    root = Path(directory)
    manifest = json.loads((root / "report_manifest.json").read_text(encoding="utf-8"))
    hashes: dict[str, str] = manifest["files"]
    for filename, expected in hashes.items():
        path = root / filename
        if not path.exists() or _sha256(path) != expected:
            return False
    expected_report_id = hashlib.sha256(
        json.dumps(
            {"run_id": manifest["run_id"], "files": hashes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return expected_report_id == manifest["report_id"]
