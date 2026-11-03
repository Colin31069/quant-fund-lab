"""The source-backed workflow authenticates protocol, code and frozen inputs."""
from pathlib import Path

import pytest
from decision_fixtures import decision_fixture

from quant_fund_lab.odd_lot_paper.workflow import replay_registered_account

SOURCE = Path(__file__).resolve().parents[1]


def _kwargs(tmp_path):
    return {"period":"validation","strategy":"momentum", "studies_directory":tmp_path / "studies",
            "source_directory":SOURCE,"account_path":tmp_path / "account.sqlite",
            "snapshot_root":tmp_path / "snapshots"}


def test_registered_account_authenticates_and_noop_replay_preserves_checkpoint(tmp_path, monkeypatch):
    studies, protocol, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    period = next(row for row in protocol.periods if row.name == "validation")
    args = {**_kwargs(tmp_path), "through":period.start}
    first = replay_registered_account(frozen, protocol.candidates[0].candidate_id, create=True, **args)
    assert first.committed_sessions == 1
    second = replay_registered_account(frozen, protocol.candidates[0].candidate_id, **args)
    assert second.committed_sessions == 0 and second.checkpoint == first.checkpoint
    assert second.last_digest == first.last_digest
    before = args["account_path"].read_bytes()
    with pytest.raises(ValueError, match="cutoff"):
        replay_registered_account(frozen, protocol.candidates[0].candidate_id,
                                  **{**args,"through":"2030-01-01"})
    assert args["account_path"].read_bytes() == before
    # Raw source tampering is rejected even when no new account day is requested.
    source_file = next((studies[0] / "sources/prices").glob("*.json"))
    source_file.write_bytes(source_file.read_bytes()+b" ")
    with pytest.raises(ValueError):
        replay_registered_account(frozen, protocol.candidates[0].candidate_id, **args)
    assert args["account_path"].read_bytes() == before


def test_undeclared_candidate_cannot_create_any_account(tmp_path, monkeypatch):
    _, _, frozen, _ = decision_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="declared"):
        replay_registered_account(frozen, "f"*64, create=True, **_kwargs(tmp_path))
    assert not (tmp_path / "account.sqlite").exists()
