# Flow run record - issue #365

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=0b16ae68339a4a78b7be5b85c3b55738 -->
## Run 1

- Run-id:            0b16ae68339a4a78b7be5b85c3b55738
- Run-start:         8466aa5cf019b2748983960790b95dc919de37f7
- Issue:             #365
- Base SHA:          8466aa5cf019b2748983960790b95dc919de37f7
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T14:58:23Z

### Section B evidence
Commits touching skillc/profile.py or tests/test_profile_probes.py since 2026-10-12T18:05Z: none.
Merged PRs since filing: #357-#363, #366, #368-#374, #377-#381, #386, #388, #389, #391, #395-#398, #401, #405-#407, #409, #413, #415, #417, #420 - none touch the host probe (#369's validate_environment covers the container runtime only).
Open PRs #403, #411: no overlap. Related: #364 (closed, origin), #360 (closed, different defect). Duplicates: none.

### Section C - the approved plan
1. `skillc/profile.py` - `_isolated_probe_env(project_dir)`: drop UV_* outside runtime_supply.ENV_KEYS, drop VIRTUAL_ENV and PYTHONHOME, PYTHONPATH = project dir only; used by `_gather_python_import_probe_host`; docstring corrected.
2. `tests/test_profile_probes.py` - (a) RED UV_PROJECT_ENVIRONMENT -> throwaway uv venv holding a unique module; (b) RED module dir on ambient PYTHONPATH; (c) CONTROL module in the declared project dir; never point at the running test venv; (a)/(b) shown failing on unfixed main.
3. `CHANGELOG.md` - Unreleased entry.

Scope: small (~25 src, ~70 test lines). Risks: ambient PYTHONPATH no longer reaches the probe (intended); undeclared UV_* (e.g. UV_INDEX_URL) no longer reach the probe's sync, so a probe can fail where it passed (fails closed); tests need uv on PATH.
Approver conditions: (1) show a module only in a PYTHONUSERBASE site-packages does NOT satisfy the probe after the fix (if it does: drop PYTHONUSERBASE, set PYTHONNOUSERSITE=1, add a red case); (2) state the undeclared-UV_* behaviour change plainly in the CHANGELOG.
