"""Completed benchmark history belongs to forward input provenance, even at no-op."""
import hashlib
import json
from dataclasses import replace

import pytest
from test_odd_lot_forward_binding import _run, _setup
from test_odd_lot_observation_gate import _assess

from quant_fund_lab.odd_lot_paper.observation_gate import assess_forward_session
from quant_fund_lab.odd_lot_paper.source_archive import publish_source_archive
from quant_fund_lab.odd_lot_study import _subset


@pytest.mark.parametrize("position,field",[(10,1),(121,2),(123,3)])
def test_changed_completed_benchmark_rejects_noop_without_account_writes(tmp_path,monkeypatch,position,field):
    setup = _setup(tmp_path)
    root,symbols,dates,plan,binding,*_ = setup
    account = tmp_path/"account.sqlite"
    _run(account,setup,create=True)
    before = account.read_bytes()
    manifest_path = root/"manifest.json"
    manifest = json.loads(manifest_path.read_text())
    day = str(dates[position].date())
    entry = next(row for row in manifest["sources"] if row["kind"] == "price"
                 and row["symbol"] == symbols[-1] and row["month"] == day[:7])
    path = root/entry["path"]
    payload = json.loads(path.read_text())
    row = next(row for row in payload["data"] if row[0] == day)
    row[field] = str(float(row[field])+1.)
    path.write_text(json.dumps(payload))
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    incoming = _assess(root,symbols,dates,plan)
    assert incoming.status == "ready"
    changed = replace(binding,evidence=incoming.evidence,
        source_archive=publish_source_archive(incoming.inputs,binding.source_root))
    # Trade panels are intentionally unchanged; only the separate benchmark differs.
    with pytest.raises(ValueError,match="completed.*benchmark|benchmark.*prefix"):
        _run(account,setup,binding=changed)
    assert account.read_bytes() == before


def test_benchmark_changes_after_completed_prefix_allow_new_sessions(tmp_path,monkeypatch):
    setup = _setup(tmp_path)
    root,symbols,dates,plan,binding,*_ = setup
    prefix = assess_forward_session(plan,str(dates[121].date()),official_directory=root,
        symbols=tuple(symbols[:2]),benchmark=symbols[-1])
    account = tmp_path/"account.sqlite"
    initial = _run(account,setup,create=True,binding=replace(binding,evidence=prefix.evidence),
                   data=_subset(prefix.inputs.data,symbols[:2]))
    assert initial.committed_sessions == 2
    manifest_path = root/"manifest.json"
    manifest = json.loads(manifest_path.read_text())
    day = str(dates[123].date())
    entry = next(row for row in manifest["sources"] if row["kind"] == "price"
                 and row["symbol"] == symbols[-1] and row["month"] == day[:7])
    path = root/entry["path"]
    payload = json.loads(path.read_text())
    next(row for row in payload["data"] if row[0] == day)[2] = "101"
    path.write_text(json.dumps(payload))
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    incoming = _assess(root,symbols,dates,plan)
    updated = replace(binding,evidence=incoming.evidence,
        source_archive=publish_source_archive(incoming.inputs,binding.source_root))
    continued = _run(account,setup,binding=updated)
    assert continued.committed_sessions == 3 and continued.checkpoint.session == str(dates[-1].date())
