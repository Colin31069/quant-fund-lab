"""Invalid price inputs identify their original file and record without weakening guards."""
import hashlib
import json

import pytest
from test_odd_lot_price_inputs import bundle as bundle  # noqa: PLC0414 -- fixture re-export

from quant_fund_lab.odd_lot_inputs.errors import PriceSourceError
from quant_fund_lab.odd_lot_inputs.finmind import load_finmind_price_bundle


def _rehash_raw(bundle, payload):
    raw = bundle / "raw/0050.json"
    raw.write_text(json.dumps(payload))
    manifest = bundle / "provider_manifest.json"
    value = json.loads(manifest.read_text())
    value["sources"][0].update(sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), bytes=raw.stat().st_size)
    manifest.write_text(json.dumps(value))


@pytest.mark.parametrize("case,row", [("symbol", 0), ("range", 0), ("duplicate", 1),
    ("missing", 0), ("nonfinite", 0), ("fractional_volume", 0), ("envelope", 0), ("shape", 0)])
def test_invalid_raw_record_keeps_source_locator_and_original_cause(bundle, case, row):
    raw = bundle / "raw/0050.json"
    value = json.loads(raw.read_text())
    if case == "symbol":
        value["data"][0]["stock_id"] = "50"
    elif case == "range":
        value["data"][0]["date"] = "2024-01-04"
    elif case == "duplicate":
        value["data"][1]["date"] = "2024-01-02"
    elif case == "missing":
        value["data"][0].pop("open")
    elif case == "nonfinite":
        value["data"][0]["open"] = float("inf")
    elif case == "fractional_volume":
        value["data"][0]["Trading_Volume"] = 1.5
    elif case == "envelope":
        value["data"][0]["max"] = 99
    else:
        value["data"][0] = None
    _rehash_raw(bundle, value)
    before = {p: p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    with pytest.raises(PriceSourceError) as caught:
        load_finmind_price_bundle(bundle)
    error = caught.value
    assert isinstance(error, ValueError)
    assert error.source_path == "raw/0050.json" and error.row_locator == f"data[{row}]"
    assert error.source_path in str(error) and error.row_locator in str(error)
    assert error.__cause__ is not None
    assert before == {p: p.read_bytes() for p in before}


def test_duplicate_across_sources_identifies_the_later_raw_row(bundle):
    manifest = bundle / "provider_manifest.json"
    value = json.loads(manifest.read_text())
    second = bundle / "raw/second.json"
    second.write_bytes((bundle / "raw/0050.json").read_bytes())
    value["sources"].append({**value["sources"][0], "raw_path": "raw/second.json"})
    manifest.write_text(json.dumps(value))
    with pytest.raises(PriceSourceError, match="overlapping raw") as caught:
        load_finmind_price_bundle(bundle)
    assert caught.value.source_path == "raw/second.json"
    assert caught.value.row_locator == "data[0]"


@pytest.mark.parametrize("case", ["value", "duplicate", "header"])
def test_normalized_errors_keep_csv_file_and_physical_line(bundle, case):
    path = bundle / "normalized/finmind_prices.csv"
    lines = path.read_text().splitlines()
    if case == "value":
        lines[1] = lines[1].replace(",100,101,99,100,", ",100,101,99,100.5,")
    elif case == "duplicate":
        lines.append(lines[1])
    else:
        lines[0] = lines[0].replace("raw_open", "unrecognized_open")
    path.write_text("\n".join(lines) + "\n")
    manifest = bundle / "provider_manifest.json"
    value = json.loads(manifest.read_text())
    value["normalized_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(value))
    with pytest.raises(PriceSourceError) as caught:
        load_finmind_price_bundle(bundle)
    assert caught.value.source_path.endswith("normalized/finmind_prices.csv")
    assert caught.value.row_locator == {"value": "line[2]", "duplicate": "line[4]", "header": None}[case]
    assert caught.value.__cause__ is not None


def test_wrong_manifest_unit_and_bad_request_keep_manifest_context(bundle):
    path = bundle / "provider_manifest.json"
    original = json.loads(path.read_text())
    value = {**original, "volume_unit": "lots"}
    path.write_text(json.dumps(value))
    with pytest.raises(PriceSourceError, match="manifest") as caught:
        load_finmind_price_bundle(bundle)
    assert caught.value.source_path == "provider_manifest.json" and caught.value.row_locator is None
    value = json.loads(json.dumps(original))
    value["sources"][0]["request"]["symbol"] = 50
    path.write_text(json.dumps(value))
    with pytest.raises(PriceSourceError) as caught:
        load_finmind_price_bundle(bundle)
    assert caught.value.source_path == "provider_manifest.json"
    assert caught.value.row_locator == "sources[0]"


@pytest.mark.parametrize("case", ["raw_hash", "normalized_hash", "raw_json", "response_shape"])
def test_file_failures_identify_the_actual_file_without_fabricating_a_row(bundle, case):
    raw = bundle / "raw/0050.json"
    normalized = bundle / "normalized/finmind_prices.csv"
    if case == "raw_hash":
        raw.write_bytes(raw.read_bytes() + b" ")
    elif case == "normalized_hash":
        normalized.write_bytes(normalized.read_bytes() + b" ")
    elif case == "response_shape":
        _rehash_raw(bundle, {"status": 200, "msg": "success", "data": []})
    else:
        raw.write_text("invalid json")
        manifest = bundle / "provider_manifest.json"
        value = json.loads(manifest.read_text())
        value["sources"][0].update(
            sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), bytes=raw.stat().st_size)
        manifest.write_text(json.dumps(value))
    before = {p: p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    with pytest.raises(PriceSourceError) as caught:
        load_finmind_price_bundle(bundle)
    expected = "normalized/finmind_prices.csv" if case == "normalized_hash" else "raw/0050.json"
    assert caught.value.source_path == expected
    assert caught.value.row_locator is None
    assert expected in str(caught.value)
    assert before == {p: p.read_bytes() for p in before}
