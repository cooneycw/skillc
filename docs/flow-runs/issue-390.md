# Flow run record - issue #390

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=9bb7201954d54453ad855fac322eaa8e -->
## Run 1

- Run-id:            9bb7201954d54453ad855fac322eaa8e
- Run-start:         6844ec5c0ffbbd7e1271f9393fd27f8b01194e59
- Issue:             #390
- Base SHA:          6844ec5
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (owner, interactive session)
- Recorded at:       2026-10-14T13:20:00Z

### Section B evidence
Since filing: 6844ec5 (#388, fake-Docker budget) and d94beb9 (#389, unit-test bounds); neither touches tests/*_live.py or tests/conftest.py. #385/#382 closed; #315 depends on this. Locked #341 worktree is a stale claim (owner exited), its work merged as #363.

### Section C - the approved plan
1. `tests/conftest.py` - add LIVE_DOCKER_DAEMON_TIMEOUT = 30.0 with the VM measurement rationale
2. `tests/test_profile_closure_preflight_live.py` - pass it at both constructions (:437, :506)
3. `tests/test_decide_reply_channel_live.py` - pass it at :257
4. `tests/test_gate_witness_live.py` - pass it at :495
5. `tests/test_gate_overlay_live.py` - pass it at :470
6. `tests/test_cwd_confinement_live.py` - pass it at :166
7. `tests/test_live_docker_budget.py` - static check over tests/*_live.py (fails today, population floor, planted red case) plus .delay-run behavioral cases
8. `CHANGELOG.md` - entry
Scope: 8 files, ~120 lines. Production DAEMON_TIMEOUT, ci/real-docker and the floor unchanged.
Risks: slower failure of genuinely broken setups in break runs; indirect constructions could escape the static check; real-Docker proof only on the VM (campaign 2).
