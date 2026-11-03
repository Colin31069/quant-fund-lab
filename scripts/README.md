# Reproducible verification

## Acceptance evidence index

Rebuild the release evidence inventory after adding acceptance records:

```bash
rtk proxy artifacts/environments/p0-clean313/bin/python scripts/build_acceptance_index.py --output artifacts/acceptance/release/case_index.json
```

The script discovers case IDs in the architecture plans, preserves original evidence scope and status, records source hashes and JSON locators, and checks referenced test files/functions without executing them. Every case remains subject to individual acceptance review. Missing mappings are explicit; an existing test or a recorded `passed` claim does not certify the whole case. Invalid evidence aborts before replacing the previous index. Output is deterministic for unchanged inputs.

`verify.sh` invokes lint and tests through the same Python. Set `QFL_PYTHON` to an absolute interpreter path to verify a separate environment. An isolated packaging check runs before tests, rejecting missing imports and stale distribution metadata.

The recorded baseline in `requirements/python313-macos-arm64.txt` is for Python 3.13.13 on macOS ARM64. It pins the installed runtime and development dependencies; it does not claim other platforms or Python 3.9 have passed.

Create a fresh environment without replacing an existing one:

```bash
rtk proxy python3.13 -m venv artifacts/environments/clean313
rtk proxy artifacts/environments/clean313/bin/python -m pip install -r requirements/python313-macos-arm64.txt -e .
rtk proxy env QFL_PYTHON="$PWD/artifacts/environments/clean313/bin/python" ./scripts/verify.sh -q
```

Also run `scripts/check_environment.py` with the environment's Python and `-I` from outside the repository. This ensures pytest's configured source path does not hide packaging problems.

On macOS, Python 3.13 skips `.pth` files with the `UF_HIDDEN` flag (`site.addpackage`). The original mixed environment had this flag on its editable path file; clearing only that flag restored isolated imports. A freshly installed baseline environment did not require this repair. Do not insert source paths into the checker to bypass the failure.

P0 still requires its complete acceptance matrix, including the declared Python compatibility range and unchanged frozen inputs. See `src/ARCHITECTURE/plans/P0_CALENDAR.md`.

## Python 3.9 compatibility environment

`requirements/python39-macos-arm64.txt` records the independently installed Python 3.9.6 dependency set. Create it in a new directory, keeping the 3.13 environment intact:

```bash
rtk proxy /usr/bin/python3 -m venv artifacts/environments/clean39
rtk proxy artifacts/environments/clean39/bin/python -m pip install 'pip==25.3'
rtk proxy artifacts/environments/clean39/bin/python -m pip install -r requirements/python39-macos-arm64.txt -e .
rtk proxy env QFL_PYTHON="$PWD/artifacts/environments/clean39/bin/python" ./scripts/verify.sh -q
```

Check the interpreter version first; `/usr/bin/python3` is the Python 3.9.6 executable on the verified host, not a portable Python version selector. Its bundled pip 21.2.4 cannot install this project's editable `pyproject.toml` layout, so upgrade pip inside the new environment before installation. Build isolation still uses the project's declared setuptools build requirements.

The compatible exchange calendar resolved to 4.5.6. `calendar_corrections.py` records the reviewed NYSE 2025-01-09 closure and announcement date/source; the shared session provider applies it only if the package erroneously includes that session. A newer provider already excluding it retains its original session identity. This is an ex-post calendar correction, not evidence that a strategy knew a future closure before publication. Direct source HTML archiving returned HTTP 403; P0 evidence explicitly records the official web review and archival limitation rather than claiming a raw HTML hash.
