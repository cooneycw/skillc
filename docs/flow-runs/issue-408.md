# Flow run record - issue #408

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=033f1ef76b6349a9a6b2563d14468443 -->
## Run 1

- Run-id:            033f1ef76b6349a9a6b2563d14468443
- Run-start:         f511779b9a1206dad0141b593c4310636f04914a
- Issue:             #408
- Base SHA:          f511779b9a1206dad0141b593c4310636f04914a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw): chose option 1 in the skillc-400 session, 2026-10-17, recorded at https://github.com/cooneycw/skillc/issues/408#issuecomment-6233334595
- Recorded at:       2026-10-17T11:29:46Z

### Section B evidence
- Filed 2026-10-17 from the full #375 campaign at 7c9be48 (40/42; both misses are incomplete.isolated-child-gate). commits since filing: f511779 (#406, gate stderr forwarding; unrelated to capture). PRs: #406. dup/super: none.

### Section C - the approved plan
Option 1: bytecode caches are build products in capture.
1. `skillc/trial.py` - `_export` excludes a regular file `.../__pycache__/<name>.pyc` (parent dir exactly `__pycache__`), recorded in `exclusions` with its reason; a sourceless `mod.pyc` outside `__pycache__` stays captured.
2. `tests/test_capture_bytecode_cache.py` - unit cases (cache excluded and recorded; sourceless pyc and non-pyc under __pycache__ captured; capture_digest unmoved by a planted cache, moved by a source edit and by a sourceless pyc) plus the real `incomplete/isolated-child-gate` gate under the production env: bytecode IS written (-I), capture digest unchanged. Shown red on pre-fix code.
3. `CHANGELOG.md` - entry.

Scope: 3 files, ~150 lines. Risks: a capture-policy change for every trial (anything that relied on a captured cache .pyc; none found); the ported #400 control in tests/test_agent_trial_gate_env.py asserts the digest MOVES under the measured env and must be restated once both land.
