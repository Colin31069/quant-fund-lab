"""Original bytes remain reconstructable after live bundle edits or disappearance."""
from dataclasses import replace

import pytest
from test_odd_lot_observation_gate import _assess, _fixture

from quant_fund_lab.odd_lot_paper.source_archive import (
    publish_source_archive,
    verify_source_archive,
)


def test_publish_readback_and_changed_originals_preserve_old_archive(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    inputs = _assess(root, symbols, dates, plan).inputs
    archive = tmp_path / "archive"
    link = publish_source_archive(inputs, archive)
    source = verify_source_archive(archive, link)
    assert {name:(source/name).read_bytes() for name in inputs.source_hashes} == {
        name:path.read_bytes() for name,path in inputs.source_files.items()}
    assert publish_source_archive(inputs, archive) == link
    review = inputs.source_files["evidence/review.txt"]
    review.write_text("Second offline fixture review")
    assert (source / "evidence/review.txt").read_text() == "minimal offline review fixture"
    newer = _assess(root, symbols, dates, plan).inputs
    second = publish_source_archive(newer, archive)
    assert second.archive_id != link.archive_id
    assert verify_source_archive(archive, link) == source
    review.unlink()
    assert verify_source_archive(archive, second).is_dir()


@pytest.mark.parametrize("change", ["payload", "manifest", "extra", "symlink"])
def test_changed_archived_bytes_inventory_or_symlink_refuse(tmp_path, change):
    root, symbols, dates, plan = _fixture(tmp_path)
    inputs = _assess(root, symbols, dates, plan).inputs
    archive = tmp_path / "archive"
    link = publish_source_archive(inputs, archive)
    target = archive / link.archive_id
    if change == "payload":
        (target / "sources/evidence/review.txt").write_text("changed")
    elif change == "manifest":
        (target / "archive.json").write_text("{}")
    elif change == "extra":
        (target / "unexpected").mkdir()
    else:
        path = target / "sources/evidence/review.txt"
        path.unlink()
        path.symlink_to(inputs.source_files["evidence/review.txt"])
    with pytest.raises(ValueError, match="changed|inventory|symlink"):
        verify_source_archive(archive, link)
    with pytest.raises(ValueError):
        publish_source_archive(inputs, archive)


def test_input_tamper_and_unsafe_namespace_never_publish(tmp_path):
    root, symbols, dates, plan = _fixture(tmp_path)
    inputs = _assess(root, symbols, dates, plan).inputs
    archive = tmp_path / "archive"
    bad = replace(inputs, source_hashes={**inputs.source_hashes, "../escape":"a"*64},
                  source_files={**inputs.source_files, "../escape":root / "manifest.json"})
    with pytest.raises(ValueError, match="unsafe"):
        publish_source_archive(bad, archive)
    inputs.source_files["actions.csv"].write_text("changed")
    with pytest.raises(ValueError, match="integrity"):
        publish_source_archive(inputs, archive)
    assert not list(archive.glob("[0-9a-f]"*64))
