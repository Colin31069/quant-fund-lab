#!/usr/bin/env bash
set -euo pipefail

# Deterministic Agent Verification Script (Anthropic Agent-First Pattern)
# Runs static linting and automated test suite.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Detect Python / virtualenv
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
    RUFF=".venv/bin/ruff"
    PYTEST=".venv/bin/pytest"
else
    PYTHON="python3"
    RUFF="ruff"
    PYTEST="pytest"
fi

echo "=================================================="
echo " [1/2] Running Ruff Linter & Formatting Checks..."
echo "=================================================="
${RUFF} check .
echo "✓ Ruff checks passed cleanly."

echo ""
echo "=================================================="
echo " [2/2] Running Pytest Suite..."
echo "=================================================="
${PYTEST} "$@"
echo "✓ All tests passed successfully."

echo ""
echo "=================================================="
echo " ✓ Deterministic Verification Complete: All Clear!"
echo "=================================================="
