"""Undefined episode metrics and the 30-closed-sample boundary stay explicit."""
import json

import pandas as pd
import pytest

from quant_fund_lab.trade_analytics import summarize_episodes


@pytest.mark.parametrize("closed,opened,expected", [
    ([], [], {"closed_count": 0, "open_count": 0, "wins": 0, "losses": 0, "flat": 0,
              "average_win": None, "average_loss": None, "payoff_ratio": None,
              "win_rate": None, "profit_factor": None, "expectancy": None,
              "closed_pnl": 0, "open_pnl": 0, "sample_sufficient": False}),
    ([], [-900], {"closed_count": 0, "open_count": 1, "wins": 0, "losses": 0, "flat": 0,
                  "average_win": None, "average_loss": None, "payoff_ratio": None,
                  "win_rate": None, "profit_factor": None, "expectancy": None,
                  "closed_pnl": 0, "open_pnl": -900, "sample_sufficient": False}),
    ([100, 200], [], {"closed_count": 2, "open_count": 0, "wins": 2, "losses": 0, "flat": 0,
                     "average_win": 150, "average_loss": None, "payoff_ratio": None,
                     "win_rate": 1, "profit_factor": None, "expectancy": 150,
                     "closed_pnl": 300, "open_pnl": 0, "sample_sufficient": False}),
    ([-100, -200], [], {"closed_count": 2, "open_count": 0, "wins": 0, "losses": 2, "flat": 0,
                       "average_win": None, "average_loss": 150, "payoff_ratio": None,
                       "win_rate": 0, "profit_factor": None, "expectancy": -150,
                       "closed_pnl": -300, "open_pnl": 0, "sample_sufficient": False}),
    ([0, 0], [], {"closed_count": 2, "open_count": 0, "wins": 0, "losses": 0, "flat": 2,
                 "average_win": None, "average_loss": None, "payoff_ratio": None,
                 "win_rate": 0, "profit_factor": None, "expectancy": 0,
                 "closed_pnl": 0, "open_pnl": 0, "sample_sufficient": False}),
])
def test_empty_open_only_and_one_sided_samples_never_invent_metrics(closed, opened, expected):
    frame = pd.DataFrame({"status": ["closed"] * len(closed) + ["open"] * len(opened),
                          "pnl": closed + opened})
    result = summarize_episodes(frame)
    assert result == expected
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("completed,enough", [(29, False), (30, True)])
def test_only_completed_episodes_count_toward_sample_requirement(completed, enough):
    # Losing completed samples meet the quantity boundary without changing their negative economics.
    # Open winners are marked PnL; they must not create wins or completed observations.
    frame = pd.DataFrame({"status": ["closed"] * completed + ["open"] * 10,
                          "pnl": [-100.0] * completed + [10000.0] * 10})
    result = summarize_episodes(frame)
    assert result["closed_count"] == completed and result["open_count"] == 10
    assert result["sample_sufficient"] is enough
    assert result["wins"] == 0 and result["losses"] == completed
    assert result["win_rate"] == 0 and result["expectancy"] == -100
    assert result["closed_pnl"] == -100 * completed and result["open_pnl"] == 100000
    assert result["average_win"] is result["payoff_ratio"] is result["profit_factor"] is None
    json.dumps(result, allow_nan=False)
