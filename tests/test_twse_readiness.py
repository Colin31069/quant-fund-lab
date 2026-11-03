"""Readiness contracts prevent false-ready states before assessment is connected."""
from dataclasses import replace

import pytest

from quant_fund_lab.twse_quality.types import (
    FindingCode,
    PeriodReadiness,
    ReadinessFinding,
    ReadinessStatus,
    StudyReadiness,
    WarmupEvidence,
    fingerprint,
)


def test_finding_identity_survives_translation_but_binds_policy_and_category():
    finding = ReadinessFinding(FindingCode.COVERAGE_REVIEW, "0050.TW",
                               "2024-01-01", "2024-12-31", "缺審核", "split")
    assert replace(finding, detail="Missing review").finding_id == finding.finding_id
    assert replace(finding, discriminator="reduction").finding_id != finding.finding_id
    assert replace(finding, policy_id="provider_reviewed").finding_id != finding.finding_id


def test_missing_expected_session_cannot_be_ready():
    warmup = WarmupEvidence("calendar-v1", 2, ("2024-01-02", "2024-01-03"),
                            ("2024-01-02",))
    with pytest.raises(ValueError, match="incomplete warmup"):
        PeriodReadiness("validation", "2024-01-04", "2024-01-05",
                        ReadinessStatus.READY, warmup, ())
    with pytest.raises(ValueError, match="belong"):
        replace(warmup, verified_sessions=("2024-01-04",))


def test_findings_and_periods_cannot_lose_traceability():
    finding = ReadinessFinding(FindingCode.UNKNOWN, "*", "2024-01-01", "2024-01-01", "legacy")
    with pytest.raises(ValueError, match="unknown finding"):
        StudyReadiness("input", (replace(finding, depends_on=("missing",)),), ())
    with pytest.raises(ValueError, match="duplicate"):
        StudyReadiness("input", (finding, finding), ())
    result = StudyReadiness("input", (finding,), ())
    assert result.readiness_fingerprint == fingerprint(result.to_dict())
    with pytest.raises(ValueError):
        fingerprint({"invalid": float("nan")})
