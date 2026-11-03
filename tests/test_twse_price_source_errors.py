"""Official raw price failures retain the same source/record diagnostics contract."""
import hashlib
import json

import pytest
from test_twse_odd_lot import _bundle

from quant_fund_lab.odd_lot_inputs.errors import PriceSourceError
from quant_fund_lab.odd_lot_inputs.twse import load_twse_price_observations


@pytest.mark.parametrize("case,locator", [
    ("invalid_date", "data[0]"), ("wrong_month", "data[0]"),
    ("duplicate", "data[1]"), ("fractional_volume", "data[0]"),
    ("negative_volume", "data[0]"), ("missing_cell", "data[0]"),
    ("negative_open", "data[0]"), ("hash", None),
])
def test_official_invalid_prices_identify_file_and_record_without_modification(tmp_path, case, locator):
    root, _ = _bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(row for row in manifest["sources"] if row["kind"] == "price")
    path = root / entry["path"]
    payload = json.loads(path.read_text())
    if case == "invalid_date":
        payload["data"][0][0] = "invalid"
    elif case == "wrong_month":
        payload["data"][0][0] = "114/07/01"
    elif case == "duplicate":
        payload["data"][1][0] = payload["data"][0][0]
    elif case == "fractional_volume":
        payload["data"][0][1] = "1.5"
    elif case == "negative_volume":
        payload["data"][0][1] = "-1"
    elif case == "missing_cell":
        payload["data"][0] = payload["data"][0][:1]
    elif case == "negative_open":
        payload["data"][0][2] = "-1"
    path.write_text(json.dumps(payload) + " ")
    if case != "hash":
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(PriceSourceError) as caught:
        load_twse_price_observations(root)
    assert isinstance(caught.value, ValueError)
    assert caught.value.source_path == entry["path"]
    assert caught.value.row_locator == locator
    if locator:
        assert caught.value.__cause__ is not None
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize("case", ["manifest", "raw_json", "schema"])
def test_official_file_level_errors_do_not_invent_a_record(tmp_path, case):
    root, _ = _bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(row for row in manifest["sources"] if row["kind"] == "price")
    path = root / entry["path"]
    if case == "manifest":
        manifest["schema_version"] = 99
    elif case == "raw_json":
        path.write_text("invalid json")
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        payload = json.loads(path.read_text())
        payload["fields"] = ["missing fields"]
        path.write_text(json.dumps(payload))
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(PriceSourceError) as caught:
        load_twse_price_observations(root)
    assert caught.value.source_path == ("manifest.json" if case == "manifest" else entry["path"])
    assert caught.value.row_locator is None and caught.value.__cause__ is not None
    assert all(p.read_bytes() == content for p, content in before.items())
