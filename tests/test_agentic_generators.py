"""Unit tests for FileBridgeGenerator and APIStrategyGenerator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_fund_lab.agentic.compiler import ASTSanitizer
from quant_fund_lab.agentic.generators import (
    APIStrategyGenerator,
    EvolutionaryStrategyGenerator,
    FileBridgeGenerator,
    extract_json_payload,
)
from quant_fund_lab.agentic.schemas import ExecutionOverlayConfig, PrimitiveConfig, StrategyContract
from quant_fund_lab.agentic.skeptic import compute_structural_diff


@pytest.fixture
def sample_contract() -> StrategyContract:
    return StrategyContract(
        strategy_name="test_bridge_alpha",
        agent_archetype="trend",
        economic_hypothesis=(
            "Capturing momentum through Kalman filtered signals over a 15-day window. "
            "Satisfying minimum character count requirements for schema validation."
        ),
        market_universe="US_LIQUID_500",
        primitives=[
            PrimitiveConfig(primitive_id="k1", module_type="KalmanTrend", params={"half_life": 10})
        ],
        signal_expression="cs_rank(k1)",
        execution_overlay=ExecutionOverlayConfig(
            rebalance_frequency="1W",
            trade_buffer_delta_weight=0.01,
            max_single_position_weight=0.2,
            target_gross_leverage=1.0,
            odd_lot_execution_mode="avoid_odd_lots",
        ),
    )


def test_extract_json_payload() -> None:
    # Raw JSON
    raw = '{"key": "value"}'
    assert extract_json_payload(raw) == '{"key": "value"}'

    # Fenced JSON
    fenced = '```json\n{"key": "value"}\n```'
    assert extract_json_payload(fenced) == '{"key": "value"}'

    # Fenced without language
    fenced_no_lang = '```\n{"key": "value"}\n```'
    assert extract_json_payload(fenced_no_lang) == '{"key": "value"}'

    # Explanatory text surrounding JSON
    surrounded = 'Here is the strategy contract you requested:\n{"key": "value"}\nLet me know if you need changes.'
    assert extract_json_payload(surrounded) == '{"key": "value"}'


def test_file_bridge_generator(tmp_path: Path, sample_contract: StrategyContract) -> None:
    bridge = FileBridgeGenerator(workspace_dir=tmp_path)

    # 1. Write task prompt
    prompt_path = bridge.write_task_prompt(
        archetype="trend",
        round_num=1,
        system_prompt="You are a trend researcher.",
        user_prompt="Improve Sharpe ratio.",
    )
    assert prompt_path.exists()
    assert "You are a trend researcher." in prompt_path.read_text(encoding="utf-8")

    # 2. Reading when proposal doesn't exist raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        bridge.read_proposal("trend")

    # 3. Write proposal and read back
    prop_path = tmp_path / "proposal_trend.json"
    prop_path.write_text(sample_contract.model_dump_json(), encoding="utf-8")
    loaded_contract = bridge.read_proposal("trend")
    assert loaded_contract.strategy_name == sample_contract.strategy_name

    # 4. Standard __call__ with proposal.json
    default_prop = tmp_path / "proposal.json"
    default_prop.write_text(sample_contract.model_dump_json(), encoding="utf-8")
    call_contract = bridge("sys", "user")
    assert call_contract.strategy_name == sample_contract.strategy_name


def test_api_strategy_generator_mock(sample_contract: StrategyContract) -> None:
    valid_payload = sample_contract.model_dump_json()
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": f"```json\n{valid_payload}\n```"}}]
    }).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        generator = APIStrategyGenerator(api_key="sk-test", model="gpt-4o")
        contract = generator("system prompt", "user prompt")
        assert isinstance(contract, StrategyContract)
        assert contract.strategy_name == sample_contract.strategy_name


def test_evolutionary_strategy_generator() -> None:
    gen = EvolutionaryStrategyGenerator(seed=42)
    assert len(gen._trend_seq) == 30
    assert len(gen._mr_seq) == 30

    # Test AST validity and single mutation constraint
    for i, c in enumerate(gen._trend_seq):
        assert ASTSanitizer.validate_contract(c)
        assert len(c.economic_hypothesis) >= 80
        if i > 0:
            n_diffs, _ = compute_structural_diff(c, gen._trend_seq[i - 1])
            assert n_diffs == 1

    for i, c in enumerate(gen._mr_seq):
        assert ASTSanitizer.validate_contract(c)
        assert len(c.economic_hypothesis) >= 80
        if i > 0:
            n_diffs, _ = compute_structural_diff(c, gen._mr_seq[i - 1])
            assert n_diffs == 1

    # Test prompt-driven call interface
    c1 = gen("Trend specialist", "Propose initial trend StrategyContract.")
    assert c1.strategy_name == "trend_gen01"
    c2 = gen("Trend specialist", "## ITERATIVE REFINEMENT ROUND 2 OF 30")
    assert c2.strategy_name == "trend_gen02"
    c_mr1 = gen("Mean-Reversion specialist", "Propose initial mean_reversion StrategyContract.")
    assert c_mr1.strategy_name == "mean_reversion_gen01"

