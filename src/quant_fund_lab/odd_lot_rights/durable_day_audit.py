"""Read-only historical replay against original external day requests."""
from dataclasses import dataclass

from .codec import canonical
from .durable_day_workflow import DurableRightsDay, day_settings_sha256, prepare_durable_day
from .engine_checkpoint_codec import encode_engine_rights
from .engine_ledger import RightsEngineLedger
from .engine_ledger_types import payload_digest


@dataclass(frozen=True)
class DurableDayAudit:
    sessions_checked: int
    final_digest: str
    scope: str = "external_request_engine_replay_and_nav_reconstruction"


def verify_durable_days(ledger: RightsEngineLedger,
                        days: tuple[DurableRightsDay, ...]) -> DurableDayAudit:
    """Reject self-consistent SQL changes by re-executing externally held inputs.

    Calls the production pure workflow to validate behavioral equivalence; the
    underlying financial/lot audits reconstruct independent equations. This is
    not an independently implemented strategy/execution engine. The caller must
    authenticate the external source/request catalog and frozen identities.
    """
    if type(days) is not tuple or any(not isinstance(row, DurableRightsDay) for row in days):
        raise TypeError("durable audit requires immutable original day requests")
    final, final_digest = ledger.verify()
    rows = ledger.connection.execute("""SELECT c.session,c.state_json,c.input_digest,c.parent_digest,
        e.events_json,d.commit_digest FROM rights_checkpoints c JOIN rights_events e USING(session)
        JOIN rights_completed d USING(session) ORDER BY c.session""").fetchall()
    if len(days) != len(rows):
        raise ValueError("durable audit requires every completed session's original request")
    previous = ledger.initial
    parent = payload_digest(canonical([ledger.config_json, ledger.initial_json]))
    import json

    config = json.loads(ledger.config_json)
    for day, row in zip(days, rows):
        if day_settings_sha256(day) != config["settings_sha256"]:
            raise ValueError("durable audit source settings differ from locked configuration")
        _, _, record = prepare_durable_day(previous, parent, day)
        payload = encode_engine_rights(record.checkpoint)
        identity = payload_digest(canonical([parent, payload, record.input_fingerprint, record.events_json]))
        expected = (record.checkpoint.engine.session, payload, record.input_fingerprint,
                    parent, record.events_json, identity)
        if tuple(row) != expected:
            raise ValueError("durable SQL checkpoint/events differ from original-request replay")
        previous, parent = record.checkpoint, identity
    if parent != final_digest or previous != final:
        raise ValueError("durable audit final checkpoint differs from replay")
    return DurableDayAudit(len(rows), parent)
