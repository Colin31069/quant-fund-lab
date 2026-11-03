"""Versioned no-quote handling requires the shared official individual-halt gate."""
import csv
import hashlib
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- fixture re-export
from test_twse_odd_lot import _bundle

from quant_fund_lab.odd_lot_inputs.prepare import prepare_reviewed_odd_lot_input
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy


def _provider(bundle, *, quoted=False, activity=None):
    raw = bundle / "raw/0050.json"
    row = {"date":"2025-06-12", "stock_id":"0050", "open":100 if quoted else 0,
        "max":101 if quoted else 0, "min":99 if quoted else 0, "close":100 if quoted else 0,
        "Trading_Volume":1000 if quoted else 0, "Trading_money":100000 if quoted else 0,
        "Trading_turnover":10 if quoted else 0}
    if activity is not None:
        row[activity] = 1
    raw.write_text(json.dumps({"status":200, "msg":"success", "data":[row]}))
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    path = bundle / "provider_manifest.json"
    manifest = json.loads(path.read_text())
    source = manifest["sources"][0]
    source.update(sha256=sha, bytes=raw.stat().st_size, rows=1)
    source["request"].update(start=row["date"], end=row["date"])
    url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=0050&start_date=2025-06-12&end_date=2025-06-12"
    source.update(requested_url=url, final_url=url)
    manifest["research_cutoff"] = "2025-06-20"
    manifest["months"] = [{"symbol":"0050.TW", "month":"2025-06", "rows":1,
        "first_date":row["date"], "last_date":row["date"], "raw_path":"raw/0050.json", "sha256":sha}]
    normalized = bundle / "normalized/finmind_prices.csv"
    with normalized.open() as stream:
        fields = csv.DictReader(stream).fieldnames
    with normalized.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(zip(fields, [row["date"],"0050.TW",row["open"],row["max"],row["min"],
            row["close"],row["Trading_Volume"],row["Trading_money"],row["Trading_turnover"],not quoted,"FinMind",sha])))
    manifest["normalized_sha256"] = hashlib.sha256(normalized.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))


def _policies():
    old = PriceSourcePolicy("2025-06-09", "2025-06-20", "2025-06-20")
    return old, replace(old, schema_version=2, policy_id="reviewed_provider_v2")


def test_v2_no_quote_with_evidenced_halt_keeps_nontradable_marks_and_lineage(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    _provider(bundle)
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for directory in (root,bundle)
              for p in directory.rglob("*") if p.is_file()}
    v1, v2 = (prepare_reviewed_odd_lot_input(root,bundle,symbols,p) for p in _policies())
    assert any("供應商記錄無報價" in issue.detail for issue in v1.evidence.issues)
    assert not any("供應商記錄無報價" in issue.detail for issue in v2.evidence.issues)
    pd.testing.assert_frame_equal(v1.evidence.data.raw_close, v2.evidence.data.raw_close)
    data = v2.evidence.data
    assert pd.isna(data.raw_open.at["2025-06-12", "0050.TW"])
    assert data.volume.at["2025-06-12", "0050.TW"] == 0
    assert data.raw_close.at["2025-06-12", "0050.TW"] == 188.65
    assert any(row.no_quote and row.source.provider == "FinMind" for row in v2.selection.selected)
    assert "suspensions.csv" in v2.evidence.source_hashes
    assert v1.selection.selection_fingerprint != v2.selection.selection_fingerprint
    assert before == {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before}


def test_v2_unreviewed_no_quote_still_blocks(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    _provider(bundle)
    path = root / "suspensions.csv"
    with path.open() as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(row for row in rows if row["date"] != "2025-06-12")
    prepared = prepare_reviewed_odd_lot_input(root,bundle,symbols,_policies()[1])
    assert any("供應商記錄無報價" in issue.detail for issue in prepared.evidence.issues)
    assert any("缺少價格" in issue.detail for issue in prepared.evidence.issues)


def test_v2_actual_quote_on_reviewed_halt_remains_a_conflict(tmp_path, bundle):
    root, symbols = _bundle(tmp_path)
    _provider(bundle, quoted=True)
    prepared = prepare_reviewed_odd_lot_input(root,bundle,symbols,_policies()[1])
    assert any("停牌紀錄與官方成交價量衝突" in issue.detail for issue in prepared.evidence.issues)


@pytest.mark.parametrize("activity", ["Trading_Volume", "Trading_money", "Trading_turnover"])
def test_v2_no_quote_with_reported_trade_activity_does_not_match_a_halt(tmp_path, bundle, activity):
    root, symbols = _bundle(tmp_path)
    _provider(bundle, activity=activity)
    prepared = prepare_reviewed_odd_lot_input(root,bundle,symbols,_policies()[1])
    assert any("供應商記錄無報價" in issue.detail for issue in prepared.evidence.issues)


def test_v1_identity_and_serialized_fields_remain_unchanged():
    policy = PriceSourcePolicy("2024-01-02", "2024-01-03", "2024-01-03")
    assert policy.policy_fingerprint == "35388a6c54f7f1f7bc16e8f96a9388ccf93e255d9b260c152c092157c72bdcfa"
    assert set(asdict(policy)) == {"start","end","cutoff","priority","policy_id","price_atol","schema_version"}
    assert not policy.accepts_reviewed_symbol_halts
    with pytest.raises(ValueError, match="policy"):
        replace(policy, policy_id="reviewed_provider_v2")


@pytest.mark.parametrize("version", [1, 2])
def test_forward_candidate_keeps_its_frozen_rule_version_when_cutoff_grows(version):
    from quant_fund_lab.odd_lot_paper.forward_workflow import _check_source_policy

    policy = _policies()[version - 1]
    metadata = {"data_source":"provider_reviewed",
                "source_provenance":{"source_policy_json":json.dumps(asdict(policy))}}
    extended = replace(policy, end="2025-06-23", cutoff="2025-06-23")
    _check_source_policy(metadata, "provider", extended)
    other_version = 3 - version
    changed = replace(extended, schema_version=other_version,
                      policy_id=f"reviewed_provider_v{other_version}")
    with pytest.raises(ValueError, match="differs from registered candidate"):
        _check_source_policy(metadata, "provider", changed)
