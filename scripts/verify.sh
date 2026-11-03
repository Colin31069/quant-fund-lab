#!/usr/bin/env bash
set -euo pipefail

# Deterministic Agent Verification Script (Anthropic Agent-First Pattern)
# Runs static linting and automated test suite.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Detect Python / virtualenv
if [ -n "${QFL_PYTHON:-}" ]; then
    PYTHON="${QFL_PYTHON}"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

# Module invocation keeps lint and tests on the selected interpreter, even if
# stale console-script shebangs remain after a virtualenv upgrade.
"${PYTHON}" -c 'import sys; print("Verification Python:", sys.executable, sys.version)'
"${PYTHON}" -I "${REPO_ROOT}/scripts/check_environment.py"

echo "=================================================="
echo " [1/2] Running Ruff Linter & Formatting Checks..."
echo "=================================================="
"${PYTHON}" -m ruff check .
echo "✓ Ruff checks passed cleanly."

echo ""
echo "=================================================="
echo " [2/2] Running Pytest Suite..."
echo "=================================================="
"${PYTHON}" -m pytest "$@"
echo "✓ All tests passed successfully."

echo ""
echo "=================================================="
echo " ✓ Deterministic Verification Complete: All Clear!"
echo "=================================================="
