"""Raw lineage, no-quote preservation and deterministic cross-provider selection."""
import csv
import hashlib
import json
from dataclasses import replace

import pytest

from quant_fund_lab.odd_lot_inputs.finmind import load_finmind_price_bundle
from quant_fund_lab.odd_lot_inputs.selection import select_prices
from quant_fund_lab.odd_lot_inputs.types import PriceSourcePolicy


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "finmind"
    (root / "raw").mkdir(parents=True)
    (root / "normalized").mkdir()
    raw = root / "raw" / "0050.json"
    rows = [{"date": "2024-01-02", "stock_id": "0050", "open": 100, "max": 101,
             "min": 99, "close": 100, "Trading_Volume": 1000,
             "Trading_money": 100000, "Trading_turnover": 10},
            {"date": "2024-01-03", "stock_id": "0050", "open": 0, "max": 0,
             "min": 0, "close": 0, "Trading_Volume": 0,
             "Trading_money": 0, "Trading_turnover": 0}]
    raw.write_text(json.dumps({"status": 200, "msg": "success", "data": rows}))
    url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=0050"
           "&start_date=2024-01-02&end_date=2024-01-03")
    source = {"provider": "FinMind", "dataset": "TaiwanStockPrice",
              "request": {"symbol": "0050.TW", "start": "2024-01-02", "end": "2024-01-03"},
              "raw_path": "raw/0050.json", "sha256": digest(raw), "bytes": raw.stat().st_size,
              "rows": 2, "requested_url": url, "final_url": url, "http_status": 200,
              "retrieved_at": "2026-10-28T12:00:00+08:00", "usage": "offline test fixture",
              "authorization_basis": ["https://finmind.github.io/Disclaimer/"]}
    normalized = root / "normalized" / "finmind_prices.csv"
    fields = ["date", "symbol", "raw_open", "raw_high", "raw_low", "raw_close",
              "volume_shares", "turnover_twd", "trades", "no_quote", "provider", "source_sha256"]
    with normalized.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(zip(fields, [row["date"], "0050.TW", row["open"], row["max"],
                row["min"], row["close"], row["Trading_Volume"], row["Trading_money"],
                row["Trading_turnover"], row["open"] == 0, "FinMind", source["sha256"]])))
    manifest = {"schema_version": 1, "provider": "FinMind", "dataset": "TaiwanStockPrice",
                "price_basis": "raw_unadjusted", "currency": "TWD", "volume_unit": "shares",
                "research_cutoff": "2024-01-03", "sources": [source],
                "normalized_sha256": digest(normalized), "months": [{"symbol": "0050.TW",
                    "month": "2024-01", "rows": 2, "first_date": "2024-01-02",
                    "last_date": "2024-01-03", "raw_path": "raw/0050.json", "sha256": source["sha256"]}]}
    (root / "provider_manifest.json").write_text(json.dumps(manifest))
    return root


def test_loader_retains_lineage_and_does_not_create_zero_price_fills(bundle):
    result = load_finmind_price_bundle(bundle)
    assert len(result.sources) == 1 and len(result.observations) == 2
    assert result.observations[0].symbol == "0050.TW"
    assert result.observations[0].row_locator == "data[0]"
    no_quote = result.observations[1]
    assert no_quote.no_quote and no_quote.raw_open is None and no_quote.raw_close is None
    with pytest.raises(ValueError, match="executable zeros"):
        replace(no_quote, raw_open=0)
    assert result.bundle_fingerprint == load_finmind_price_bundle(bundle).bundle_fingerprint


@pytest.mark.parametrize("field,value", [("price_basis", "adjusted"), ("volume_unit", "lots"),
                                        ("provider", "TWSE"), ("schema_version", True)])
def test_loader_rejects_wrong_contract(bundle, field, value):
    path = bundle / "provider_manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        load_finmind_price_bundle(bundle)


def test_raw_bytes_and_normalized_bytes_are_both_checked(bundle):
    raw = bundle / "raw" / "0050.json"
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        load_finmind_price_bundle(bundle)


def test_rehashed_normalized_csv_must_still_match_original_rows(bundle):
    normalized = bundle / "normalized" / "finmind_prices.csv"
    normalized.write_text(normalized.read_text().replace("100,101,99,100,", "100,101,99,100.5,"))
    path = bundle / "provider_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["normalized_sha256"] = digest(normalized)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs from raw"):
        load_finmind_price_bundle(bundle)


def test_source_selection_is_stable_and_blocks_conflicts(bundle):
    row = load_finmind_price_bundle(bundle).observations[0]
    official_source = replace(row.source, provider="TWSE", dataset="STOCK_DAY",
                              source_url="https://www.twse.com.tw/price")
    official = replace(row, source=official_source)
    policy = PriceSourcePolicy("2024-01-02", "2024-01-03", "2024-01-03")
    choice = select_prices((row, official), policy)
    assert choice.selected == (official,) and not choice.conflicts
    assert choice.selection_fingerprint == select_prices((official, row), policy).selection_fingerprint
    conflict = select_prices((replace(row, raw_close=100.5), official), policy)
    assert not conflict.selected and conflict.conflicts[0].fields == ("raw_close",)
    assert conflict.selection_fingerprint != choice.selection_fingerprint
    with pytest.raises(ValueError, match="duplicate"):
        select_prices((row, row), policy)


def test_policy_and_in_memory_value_changes_have_distinct_identity(bundle):
    row = load_finmind_price_bundle(bundle).observations[0]
    policy = PriceSourcePolicy("2024-01-02", "2024-01-03", "2024-01-03")
    changed = replace(row, raw_close=100.5)
    assert select_prices((row,), policy).selection_fingerprint != select_prices((changed,), policy).selection_fingerprint
    assert replace(policy, priority=("FinMind", "TWSE")).policy_fingerprint != policy.policy_fingerprint


@pytest.mark.parametrize("field,value", [("stock_id", "50"), ("date", "2024-01-04"),
    ("open", float("inf")), ("Trading_Volume", True), ("Trading_Volume", -1),
    ("Trading_Volume", 1.5)])
def test_invalid_raw_identity_dates_or_numbers_are_rejected_after_rehash(bundle, field, value):
    raw = bundle / "raw" / "0050.json"
    payload = json.loads(raw.read_text())
    payload["data"][0][field] = value
    raw.write_text(json.dumps(payload))
    path = bundle / "provider_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["sources"][0].update(sha256=digest(raw), bytes=raw.stat().st_size)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_finmind_price_bundle(bundle)


def test_quote_status_conflict_is_not_silently_replaced_by_a_quote(bundle):
    row, absent = load_finmind_price_bundle(bundle).observations
    source = replace(row.source, provider="TWSE", dataset="STOCK_DAY",
                     source_url="https://www.twse.com.tw/price")
    quote = replace(row, date=absent.date, source=source)
    result = select_prices((absent, quote), PriceSourcePolicy("2024-01-02", "2024-01-03", "2024-01-03"))
    assert not result.selected and "no_quote" in result.conflicts[0].fields


def test_official_adapter_retains_its_provider_and_source_rows(tmp_path):
    from test_twse_odd_lot import _bundle

    from quant_fund_lab.odd_lot_inputs.twse import load_twse_price_observations
    from quant_fund_lab.twse_odd_lot import prepare_twse_odd_lot

    root, symbols = _bundle(tmp_path)
    inputs = prepare_twse_odd_lot(root, symbols, "2025-06-09", "2025-06-20")
    rows = load_twse_price_observations(inputs)
    assert rows and all(r.source.provider == "TWSE" for r in rows)
    assert not any(r.symbol == "0050.TW" and r.date == "2025-06-12" for r in rows)
