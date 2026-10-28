# CLAUDE.md

This file provides key commands, constraints, and architecture guidance for Claude Code and agentic workflows in **Quant Fund Lab**.

## 1. Commands & Deterministic Gates

- **One-Command Full Verification (Lint + Test)**:
  ```bash
  ./scripts/verify.sh
  ```
- **Lint & Style Check**:
  ```bash
  ruff check .
  ```
- **Run Tests**:
  ```bash
  pytest
  # Fast single module test:
  pytest tests/test_core.py
  pytest tests/test_odd_lot_research.py
  ```
- **Run Streamlit Dashboard**:
  ```bash
  streamlit run src/quant_fund_lab/ui.py
  ```

## 2. Hard Constraints & Negative Rules

- **Pure Virtual Sim**: No real broker integration, no real orders placed.
- **Preserve Documentation**: Do NOT remove existing docstrings, explanatory comments, or type annotations.
- **No Unplanned Sweeping Refactoring**: Refactor only incrementally with atomic, tested units. Avoid modifying 1000+ line monolithic files (`paper_live.py`, `ui.py`) without a focused, verified sub-plan.
- **Deterministic Verification**: Code changes MUST pass `ruff check .` and `pytest` before git commits.
- **Single File Length Guideline**: Target 250–300 lines max for newly authored or decomposed modules.
- **Type-First**: Always define dataclasses / Pydantic schemas and interface types before implementing business logic.

## 3. Architecture Topology & Context Colocation

For progressive disclosure, consult the local `README.md` files:
- **Subsystem Map & Responsibilities**: [`src/quant_fund_lab/README.md`](src/quant_fund_lab/README.md)
  - *Data Layer*: `data.py`, `snapshot.py`, `providers.py`, `security_master*.py`, `identity_market_data.py`, `fundamentals*.py`, `market_cap.py`, `market_calendar.py`, `fx.py`
  - *Alpha & Research*: `models.py`, `factors.py`, `fundamental_factors.py`, `walkforward.py`, `robustness.py`, `research.py`, `research_inputs.py`, `diagnostics.py`
  - *Portfolio & Risk*: `portfolio.py`, `risk_controls.py`
  - *Execution & Accounting*: `execution.py`, `corporate_actions.py`, `cash_carry.py`, `tax_analytics.py`, `cash_in_lieu*.py`, `backtest.py`
  - *TWSE Odd-Lot*: `twse_odd_lot.py`, `twse_preparation.py`, `odd_lot_execution.py`, `odd_lot_research.py`, `odd_lot_study.py`, `trade_analytics.py`
  - *Paper Trading & Audit*: `paper.py`, `paper_live.py`, `paper_workflow.py`, `ledger_audit.py`, `provenance.py`, `replay_provenance.py`
  - *UI & Reporting*: `ui.py`, `ui_inputs.py`, `reporting.py`, `analytics.py`, `config.py`
- **Milestones & Historical Roadmap**: [`src/ARCHITECTURE/README.md`](src/ARCHITECTURE/README.md)
- **Testing Specifications**: [`tests/README.md`](tests/README.md)
- **Agent Guidelines & Protocols**: [`AGENTS.md`](AGENTS.md)
