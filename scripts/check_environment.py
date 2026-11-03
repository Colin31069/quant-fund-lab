"""Check the installed project without pytest's source-path injection."""
import json
import sys
from importlib.metadata import version

import quant_fund_lab


def check_environment() -> dict:
    """Reject stale packaging metadata and report the actual verification runtime."""
    installed = version("quant-fund-lab")
    if installed != quant_fund_lab.__version__:
        raise RuntimeError(
            f"Installed version {installed} differs from source {quant_fund_lab.__version__}; "
            "reinstall the project with this Python"
        )
    return {
        "executable": sys.executable,
        "python": sys.version,
        "package_path": quant_fund_lab.__file__,
        "package_version": installed,
        "dependencies": {name: version(name) for name in (
            "exchange-calendars", "numpy", "pandas", "scipy", "streamlit", "pytest", "ruff"
        )},
    }


if __name__ == "__main__":
    print(json.dumps(check_environment(), indent=2))
