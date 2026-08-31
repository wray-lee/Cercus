# BOUNDARY.md — Global Topology Constraints

## Git Identity & Commit Boundary (CRITICAL)
- **Author / Committer**: MUST be `wray-lee <i@wray7.top>` (verified GitHub primary email).
- **Rule**: Never override local `.git/config` with secondary or unlinked emails (e.g. `wray.lee@outlook.com`).
- **Verification**: Always ensure `git config user.email` returns `i@wray7.top` before committing.

## Process Physical Isolation

- The UI process (`src/ui/app.py`) and workers (`stimulus_worker.py`) MUST NOT share memory or global variables.
- The ONLY合法 path for cross-process data flow is `multiprocessing.Queue`.
- `cmd_queue`: main -> worker (commands, config, abort signals).
- `telemetry_queue`: worker -> main (status, metrics, terminal signals).
- Violation: any use of `mp.shared_memory`, `mp.Value`, `mp.Array`, `global` variables accessed across process boundaries, or direct function calls from UI into worker internals.

## Global Dependency Lock

- `requirements.txt` and environment configuration files are LOCKED.
- Introducing ANY new third-party Python library requires explicit human approval.
- Violation: adding entries to `requirements.txt`, `setup.py`, `pyproject.toml`, or any `pip install` without documented human authorization.
