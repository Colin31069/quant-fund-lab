"""Source-backed prefix checks use offline data, not an actual forward experiment."""
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from test_twse_readiness_frozen import _ready_official_bundle

from quant_fund_lab.odd_lot_inputs.finmind import load_finmind_price_bundle
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy
from quant_fund_lab.odd_lot_paper.observation import ObservationPlan
from quant_fund_lab.odd_lot_paper.observation_gate import assess_forward_session


def _fixture(tmp_path):
    root, symbols, dates, _ = _ready_official_bundle(tmp_path)
    first = dates[120].date()
    plan = ObservationPlan(*(["a"*64]*2), "ensemble", *(["b"*64]*3), str(first),
        (datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)-timedelta(days=2)).isoformat(),
        "c"*64, "{}", '{"strategy":{"warmup_days":30}}', "Offline historical fixture only")
    return root, symbols, dates, plan


def _assess(root, symbols, dates, plan, **kwargs):
    return assess_forward_session(plan, str(dates[-1].date()), official_directory=root,
        symbols=tuple(symbols[:2]), benchmark=symbols[2], **kwargs)


def test_complete_source_prefix_has_bound_evidence_without_writes(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    before = {str(path.relative_to(root)):path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = _assess(root, symbols, dates, plan)
    assert result.status == "ready" and result.reasons == ()
    evidence = result.evidence
    assert evidence.plan_id == plan.plan_id
    assert evidence.readiness_fingerprint == result.readiness.readiness_fingerprint
    assert evidence.source_hashes == tuple(sorted(result.inputs.source_hashes.items()))
    assert {(day, symbol) for day, symbol, _, _ in evidence.acquisitions} == {
        (str(day.date()), symbol) for day in dates[120:] for symbol in symbols}
    assert len(evidence.evidence_id) == 64
    assert before == {str(path.relative_to(root)):path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert not list(tmp_path.rglob("*.sqlite"))


@pytest.mark.parametrize("timing", ["before_registration", "future"])
def test_inconsistent_source_acquisition_times_block_even_when_prices_are_ready(tmp_path, timing):
    root, symbols, dates, plan = _fixture(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    stamp = (datetime.fromisoformat(plan.recorded_at)-timedelta(days=1) if timing == "before_registration"
             else datetime.now(timezone.utc)+timedelta(days=1))
    for entry in manifest["sources"]:
        if entry["kind"] == "price":
            entry["retrieved_at"] = stamp.isoformat()
    manifest_path.write_text(json.dumps(manifest))
    result = _assess(root, symbols, dates, plan)
    assert result.readiness.periods[0].status.value == "ready"
    assert result.status == "blocked" and result.evidence is None
    assert any(reason.startswith("acquisition_time_invalid:") for reason in result.reasons)


def test_missing_trailing_session_does_not_shrink_requested_period(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    # A later calendar weekday is explicit; no data is added to the archive.
    cutoff = str((dates[-1]+pd.offsets.BDay(1)).date())
    result = assess_forward_session(plan, cutoff, official_directory=root,
        symbols=tuple(symbols[:2]), benchmark=symbols[2])
    assert result.status == "blocked" and result.evidence is None
    assert "readiness_blocked" in result.reasons
    assert any(f.start == cutoff for f in result.readiness.findings)


def test_missing_coverage_and_short_warmup_remain_blocked(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    (root / "coverage_reviews.csv").unlink()
    short = replace(plan, first_session=str(dates[100].date()),
                    recorded_at=str(dates[99].date())+"T00:00:00+00:00")
    result = _assess(root, symbols, dates, short)
    assert result.status == "blocked" and not result.readiness.periods[0].warmup.complete
    assert any(f.code.value == "coverage_review" for f in result.readiness.findings)
    assert not (root / "coverage_reviews.csv").exists()


def test_non_session_first_date_and_changed_raw_bytes_refuse(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    weekend = dates[115]
    while weekend.weekday() != 5:
        weekend += pd.Timedelta(days=1)
    changed = replace(plan, first_session=str(weekend.date()),
                      recorded_at=str((weekend-pd.Timedelta(days=2)).date())+"T00:00:00+00:00")
    result = _assess(root, symbols, dates, changed)
    assert "requested_boundaries_are_not_verified_sessions" in result.reasons
    manifest = json.loads((root / "manifest.json").read_text())
    path = root / next(entry["path"] for entry in manifest["sources"] if entry["kind"] == "price")
    path.write_text("tampered")
    with pytest.raises(ValueError):
        _assess(root, symbols, dates, plan)


def test_evidence_rejects_duplicate_rows_and_future_acquisition(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    evidence = _assess(root, symbols, dates, plan).evidence
    with pytest.raises(ValueError, match="duplicate"):
        replace(evidence, acquisitions=(*evidence.acquisitions, evidence.acquisitions[0]))
    rows = list(evidence.acquisitions)
    rows[0] = (*rows[0][:3], (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    with pytest.raises(ValueError, match="acquisition"):
        replace(evidence, acquisitions=tuple(rows))
    with pytest.raises(ValueError, match="immutable"):
        replace(evidence, acquisitions=list(evidence.acquisitions))


def test_reviewed_provider_preserves_selected_acquisition_and_official_context(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    provider = tmp_path / "provider"
    provider.mkdir()
    day = str(dates[-1].date())
    raw = provider / "quote.json"
    raw.write_text(json.dumps({"status":200,"msg":"success","data":[{
        "date":day,"stock_id":"0050","open":100,"max":101,"min":99,"close":100,
        "Trading_Volume":1000000,"Trading_money":100000000,"Trading_turnover":10}]}))
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=0050&start_date={day}&end_date={day}"
    (provider / "provider_manifest.json").write_text(json.dumps({
        "schema_version":1,"provider":"FinMind","dataset":"TaiwanStockPrice",
        "price_basis":"raw_unadjusted","currency":"TWD","volume_unit":"shares",
        "research_cutoff":day,"sources":[{"provider":"FinMind","dataset":"TaiwanStockPrice",
            "requested_url":url,"final_url":url,"retrieved_at":datetime.now(timezone.utc).isoformat(),
            "raw_path":"quote.json","sha256":sha,"bytes":raw.stat().st_size,"rows":1,
            "usage":"Offline fixture","authorization_basis":["Fixture only"],"http_status":200,
            "request":{"symbol":"0050.TW","start":day,"end":day}}]}))
    policy = PriceSourcePolicy(str(dates[0].date()), day, day, priority=("FinMind","TWSE"))
    result = _assess(root, symbols, dates, plan, provider_directory=provider, price_policy=policy)
    assert result.status == "ready"
    assert "provider/provider_manifest.json" in dict(result.evidence.source_hashes)
    assert result.inputs.provenance["source"] == "TWSE+FinMind"
    selected_id = load_finmind_price_bundle(provider).sources[0].source_id
    assert (day, "0050.TW", selected_id) in {row[:3] for row in result.evidence.acquisitions}
    assert "manifest.json" in dict(result.evidence.source_hashes)
    cutoff = str(dates[-2].date())
    earlier = assess_forward_session(plan, cutoff, official_directory=root,
        symbols=tuple(symbols[:2]), benchmark=symbols[2], provider_directory=provider, price_policy=policy)
    assert earlier.status == "ready" and earlier.inputs.data.close.index[-1] == dates[-2]
    assert all(row[0] <= cutoff for row in earlier.evidence.acquisitions)


def test_source_mutation_during_assessment_is_rejected(tmp_path, monkeypatch):
    import quant_fund_lab.odd_lot_paper.observation_gate as module

    root, symbols, dates, plan = _fixture(tmp_path)
    original = module.load_twse_price_observations
    def change(inputs):
        rows = original(inputs)
        inputs.source_files["actions.csv"].write_text("changed after assessment")
        return rows
    monkeypatch.setattr(module, "load_twse_price_observations", change)
    with pytest.raises(ValueError, match="integrity|changed"):
        _assess(root, symbols, dates, plan)


@pytest.mark.parametrize("minutes",[-1,0])
def test_same_day_acquisition_must_follow_verified_session_close(tmp_path,minutes):
    import exchange_calendars as xcals

    root,symbols,dates,plan = _fixture(tmp_path)
    first = str(dates[-1].date())
    registered = dates[-2].date().isoformat()+"T00:00:00+00:00"
    plan = replace(plan,first_session=first,recorded_at=registered)
    closing = xcals.get_calendar("XTAI").session_close(first).to_pydatetime()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["sources"]:
        if entry["kind"] == "price":
            entry["retrieved_at"] = (closing+timedelta(minutes=minutes)).isoformat()
    manifest_path.write_text(json.dumps(manifest))
    result = _assess(root,symbols,dates,plan)
    assert result.readiness.periods[0].status.value == "ready"
    if minutes < 0:
        assert result.status == "blocked" and result.evidence is None
        assert all(reason.startswith("acquisition_time_invalid:") for reason in result.reasons)
    else:
        assert result.status == "ready" and result.evidence is not None
