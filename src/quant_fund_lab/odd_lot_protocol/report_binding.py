"""Verify protocol semantics in addition to the report's byte manifest."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..odd_lot_sensitivity.verify import verify_matched_report
from .benchmark import benchmark_from_plan
from .build import verify_candidate_binding
from .diagnostics import verify_diagnostic_report
from .storage import load_protocol
from .types import ExperimentRecord, digest


def verify_protocol_report_binding(directory: Path, metadata: dict) -> None:
    """Reject a rehashed sidecar that no longer belongs to its study or protocol."""
    protocol = load_protocol(directory)
    context = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
    # Initial local v1 reports had no explicit context schema field; keep them readable.
    if context.get("schema_version", 1) != 1:
        raise ValueError("unsupported experiment report context")
    record = ExperimentRecord(**context["experiment"])
    digest(context["numerical_result_fingerprint"])
    if type(context["attempt"]) is not int or context["attempt"] < 1:
        raise ValueError("invalid report experiment attempt")
    candidate = next((c for c in protocol.candidates if c.candidate_id == record.candidate_id), None)
    if (record.protocol_id != protocol.protocol_id or record.execution_id != protocol.execution.identity
            or record.study_id != metadata["study_id"] or candidate is None):
        raise ValueError("report experiment differs from its protocol and study")
    verify_candidate_binding(protocol, candidate, metadata)
    benchmark = benchmark_from_plan(protocol.analysis_plan_json)
    path = directory / "benchmark_specs.json"
    if benchmark is None:
        if path.exists():
            raise ValueError("benchmark artifact was not declared by this protocol")
    else:
        manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))
        if ("benchmark_specs.json" not in manifest["files"]
                or json.loads(path.read_text(encoding="utf-8")) != {benchmark.symbol: asdict(benchmark)}):
            raise ValueError("reported benchmark differs from the frozen protocol")
    verify_diagnostic_report(directory, metadata, protocol.analysis_plan_json,
                             benchmark.result_name if benchmark is not None else None)
    verify_matched_report(directory, metadata, protocol.analysis_plan_json, candidate.candidate_id, benchmark)
