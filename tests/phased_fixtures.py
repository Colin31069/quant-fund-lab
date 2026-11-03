"""Explicit v6 child protocols keep existing v5 fixture semantics untouched."""
from decision_fixtures import decision_fixture
from test_registered_odd_lot_study import SOURCE

from quant_fund_lab.odd_lot_decisions.phased_reporting import export_phased_decision
from quant_fund_lab.odd_lot_decisions.selection_capture import export_development_selection
from quant_fund_lab.odd_lot_protocol import (
    ExperimentRegistry,
    freeze_protocol,
    protocol_from_studies,
)
from quant_fund_lab.odd_lot_protocol.decision import policy_from_plan


def phased_fixture(tmp_path, monkeypatch, *, positive=False, count=1, policy=None, prices=None, exploration=False):
    studies, old, legacy, args = decision_fixture(tmp_path, monkeypatch, positive=positive, count=count,
        prices=prices, exploration=exploration)
    policy = policy or policy_from_plan(old.analysis_plan_json)
    protocol = protocol_from_studies(studies, **args, decision_policy=policy,
                                     phased_decisions=True, parent_protocol_id=old.protocol_id)
    frozen = freeze_protocol(protocol, tmp_path / "protocols")
    with ExperimentRegistry(tmp_path / "registry.sqlite") as registry:
        registry.register_protocol(protocol)
    return studies, protocol, frozen, legacy, args


def save_selection(root, frozen):
    return export_development_selection(frozen, registry_path=root / "registry.sqlite",
        studies_directory=root / "studies", output_directory=root / "decisions", source_directory=SOURCE)


def publish(root, saved):
    return export_phased_decision(saved.directory, registry_path=root / "registry.sqlite",
        studies_directory=root / "studies", output_directory=root / "decisions", source_directory=SOURCE)
