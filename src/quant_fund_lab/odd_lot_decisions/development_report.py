"""Authenticate opaque reports and fingerprint the actual development input window."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields, replace
from pathlib import Path

import pandas as pd

from ..data import MarketData
from ..odd_lot_protocol.build import verify_candidate_binding
from ..odd_lot_protocol.results import _frame
from ..odd_lot_protocol.storage import load_protocol
from ..odd_lot_protocol.types import ExperimentAttempt, ExperimentRecord, StudyProtocol
from ..twse_odd_lot import _total_return
from .development_accounts import development_account
from .development_types import DevelopmentEvidence
from .types import STRATEGIES, fingerprint


def report_inventory(report: Path, studies: Path, protocol: StudyProtocol,
                     record: ExperimentRecord, attempt: ExperimentAttempt, metadata: dict) -> dict:
    """Hash non-development payloads as opaque bytes; no validation business parsing."""
    if (report.is_symlink() or report.resolve().parent != (studies / record.study_id / "reports").resolve()
            or any(path.is_symlink() for path in (report.parent, report.parent.parent))):
        raise ValueError("development source report outside its frozen study")
    manifest_path = report / "report_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("development report manifest cannot be a symlink")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = manifest.pop("report_id")
    if (fingerprint(manifest) != identity or manifest["study_id"] != record.study_id
            or manifest["dataset_id"] != protocol.dataset_id):
        raise ValueError("development report manifest differs from registered study")
    for name, digest in manifest["files"].items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("unsafe development report artifact path")
        path = report / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("development report byte integrity failed")
    if not {"protocol.json", "experiment.json", "assumptions.json", "study_ledger.sqlite"}.issubset(manifest["files"]):
        raise ValueError("development report missing required binding artifacts")
    context = json.loads((report / "experiment.json").read_text(encoding="utf-8"))
    candidate = next(row for row in protocol.candidates if row.candidate_id == record.candidate_id)
    if (load_protocol(report) != protocol or context.get("schema_version", 1) != 1
            or context["experiment"] != asdict(record) or context["attempt"] != attempt.attempt
            or context["numerical_result_fingerprint"] != attempt.result_fingerprint
            or record.execution_id != protocol.execution.identity
            or record.protocol_id != protocol.protocol_id or record.study_id != candidate.study_id
            or json.loads((report / "assumptions.json").read_text(encoding="utf-8")) != metadata):
        raise ValueError("development report context differs from frozen protocol or attempt")
    verify_candidate_binding(protocol, candidate, metadata)
    return {**manifest, "report_id": identity}


def dependency_fingerprint(data: MarketData, metadata: dict, protocol: StudyProtocol) -> str:
    """Exclude full-study IDs, whole source hashes and future-only calendar revisions."""
    start, end = metadata["periods"]["development"]
    readiness = next(row for row in metadata["readiness"]["periods"] if row["period"] == "development")
    before = readiness["warmup"]["expected_sessions"]
    window_start = before[0] if before else start
    window = data.slice(start=window_start, end=end)
    if not window.close.empty:
        adjusted = _total_return(window.raw_close, window.dividends, window.stock_splits)
        window = replace(window, close=adjusted, open=window.raw_open * adjusted.div(window.raw_close),
                         reference=adjusted.shift(1))
    values = {field.name: _frame(value) if isinstance(value := getattr(window, field.name), pd.DataFrame)
              else value for field in fields(window)}
    # Readiness has been reconstructed from raw sources by the frozen loader.
    # Only applicable semantic findings enter this fingerprint, not global IDs.
    findings = [{"code": row["code"], "symbol": row["symbol"],
                 "start": max(row["start"], window_start), "end": min(row["end"], end)}
                for row in metadata["readiness"]["findings"] if row["finding_id"] in readiness["blocking_ids"]]
    provider = metadata.get("source_provenance", {}).get("source_policy_json")
    provider_rules = ({key: value for key, value in json.loads(provider).items()
                       if key not in {"start", "end", "cutoff"}} if provider else None)
    return fingerprint({"rule": "development_dependencies_v1", "data": values,
        "symbols": metadata["symbols"], "benchmark": metadata["benchmark"],
        "research": metadata["research_config"], "execution": metadata["backtest_config"],
        "engine": protocol.execution.identity, "warmup_required": readiness["warmup"]["required"],
        "warmup_expected": before, "warmup_verified": readiness["warmup"]["verified_sessions"],
        "readiness_status": readiness["status"], "findings": sorted(findings, key=lambda row: fingerprint(row)),
        "readiness_rule": metadata["readiness"]["rule_version"],
        "data_source": metadata["data_source"], "provider_rules": provider_rules,
        "liquidity": metadata["liquidity_model"], "execution_assumption": metadata["execution_assumption"],
        "settlement_assumption": metadata["settlement_assumption"]})


def report_development_evidence(report: Path, data: MarketData, metadata: dict,
                                protocol: StudyProtocol, files: set[str]) -> tuple[DevelopmentEvidence, ...]:
    proof = dependency_fingerprint(data, metadata, protocol)
    return tuple(development_account(report, metadata, data.close.index, strategy, protocol, proof, files)
                 for strategy in STRATEGIES)
