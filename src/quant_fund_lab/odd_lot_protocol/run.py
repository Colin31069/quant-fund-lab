"""Connect frozen protocols and durable attempts to existing guarded study execution."""
from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..odd_lot_sensitivity.engine import run_matched_sensitivity
from ..odd_lot_study import (
    export_odd_lot_study_report,
    load_frozen_odd_lot_study,
    run_frozen_odd_lot_study,
    verify_odd_lot_study_report,
)
from .benchmark import add_tradable_benchmarks, benchmark_from_plan
from .build import verify_candidate_binding
from .decision import policy_from_plan
from .diagnostics import add_risk_diagnostics, diagnostics_enabled
from .provenance import capture_execution_identity
from .registry import ExperimentRegistry
from .results import numerical_result_fingerprint
from .sensitivity import declared_scenarios, sensitivity_enabled
from .storage import load_protocol
from .types import ExperimentAttempt, ExperimentRecord, StudyProtocol, canonical_json


@dataclass(frozen=True)
class RegisteredStudyRun:
    experiment: ExperimentRecord
    attempt: ExperimentAttempt
    report: Path


def _attach_protocol_report(
    report: Path, protocol_root: Path, protocol: StudyProtocol,
    record: ExperimentRecord, attempt: int, result_fingerprint: str,
) -> None:
    (report / "protocol.json").write_bytes((protocol_root / "protocol.json").read_bytes())
    benchmark = benchmark_from_plan(protocol.analysis_plan_json)
    policy = policy_from_plan(protocol.analysis_plan_json)
    context = {"schema_version": 1, "experiment": asdict(record), "attempt": attempt,
               "numerical_result_fingerprint": result_fingerprint,
               "limitations": ["Protocol timestamps do not independently prove historical preregistration.",
                               ("Tradable benchmark and automatic selection are not yet implemented."
                                if benchmark is None else "Automatic selection is not yet implemented.")
                               if policy is None else "Decision requires complete registry-source evaluation across all declared candidates."]}
    (report / "experiment.json").write_text(canonical_json(context), encoding="utf-8")
    periods = "".join("<li>" + html.escape(f"{p.name}: {p.purpose}; data access={p.data_access}; {p.access_note}")
                      + "</li>" for p in protocol.periods)
    section = ("<h2>凍結實驗協議與資料用途</h2><p>protocol: " + protocol.protocol_id
               + "<br>experiment: " + record.experiment_id + "<br>數值結果指紋: " + result_fingerprint
               + "</p><ul>" + periods + "</ul><p>原研究的 holdout checkbox 不構成未見資料證明；"
               "接觸紀錄未知或已接觸的歷史區段維持探索性。"
               + ("此 v1 協議未納入可交易基準。" if benchmark is None else "已納入協議宣告的同成本 ETF 基準。")
               + ("自動候選選擇尚未實作。" if policy is None else
                  "可執行政策已凍結；本報告只是一個候選，決策另從完整登記紀錄彙整。") + "</p>")
    path = report / "report.html"
    path.write_text(path.read_text(encoding="utf-8").replace("</body>", section + "</body>"), encoding="utf-8")
    manifest_path = report / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("report_id")
    manifest["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(report.iterdir())
                         if p.is_file() and p.name != "report_manifest.json"}
    manifest["report_id"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    if not verify_odd_lot_study_report(report):
        raise ValueError("protocol report integrity verification failed")


def run_registered_study(
    protocol_directory: str | Path, candidate_id: str, *,
    studies_directory: str | Path, registry_path: str | Path, source_directory: str | Path,
) -> RegisteredStudyRun:
    """Run a declared candidate, preserving failures, retries and numerical mismatches.

    A running attempt left by process termination requires explicit failed-attempt
    recovery through the registry before retrying; it is never silently reset.
    """
    if Path(__file__).resolve().parents[1] != Path(source_directory).resolve() / "src" / "quant_fund_lab":
        raise ValueError("source directory does not match the executing package")
    protocol_root = Path(protocol_directory)
    protocol = load_protocol(protocol_root)
    execution = capture_execution_identity(source_directory)
    with ExperimentRegistry(registry_path) as registry:
        record = registry.register_experiment(protocol, candidate_id, execution)
        attempt = registry.start_attempt(record.experiment_id)
        try:
            directory = Path(studies_directory) / record.study_id
            data, metadata = load_frozen_odd_lot_study(directory)
            candidate = next(c for c in protocol.candidates if c.candidate_id == candidate_id)
            verify_candidate_binding(protocol, candidate, metadata)
            matched = sensitivity_enabled(protocol.analysis_plan_json)
            result = (run_frozen_odd_lot_study(directory, _include_sensitivity=False)
                      if matched else run_frozen_odd_lot_study(directory))
            benchmark = benchmark_from_plan(protocol.analysis_plan_json)
            if benchmark is not None:
                result = add_tradable_benchmarks(data, metadata, result, benchmark)
            if matched:
                result = run_matched_sensitivity(data, metadata, result, benchmark,
                    declared_scenarios(protocol.analysis_plan_json, candidate_id))
            if diagnostics_enabled(protocol.analysis_plan_json):
                result = add_risk_diagnostics(result)
            # Exposure is derived from the protocol; an old checkbox cannot relabel it.
            result = replace(result, holdout_untouched=all(p.data_access == "unseen" for p in protocol.periods))
            numerical = numerical_result_fingerprint(result)
            if capture_execution_identity(source_directory) != execution:
                raise ValueError("source or environment changed during experiment")
            report = export_odd_lot_study_report(directory, result)
            _attach_protocol_report(report, protocol_root, protocol, record, attempt.attempt, numerical)
            if load_protocol(protocol_root) != protocol or capture_execution_identity(source_directory) != execution:
                raise ValueError("protocol, source or environment changed before experiment completion")
            status = "blocked" if result.unavailable else "succeeded"
            reason = "required research periods unavailable; see frozen readiness and unavailable.json" if result.unavailable else ""
            if result.matched_sensitivity is not None and result.matched_sensitivity.status != "succeeded":
                status = result.matched_sensitivity.status
                reason = "required sensitivity scenarios " + status + "; see matched_sensitivity.json"
            finished = registry.finish_attempt(record.experiment_id, attempt.attempt, status=status,
                result_fingerprint=numerical, report_path=str(report.resolve()), reason=reason)
        except Exception as exc:
            registry.finish_attempt(record.experiment_id, attempt.attempt, status="failed",
                                    reason=f"{type(exc).__name__}: {exc}")
            raise
        if finished.status == "failed":
            raise ValueError(finished.reason)
        return RegisteredStudyRun(record, finished, report)
