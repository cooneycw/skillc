# Flow run record - issue #416

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=05376e3ecac04f7e9a099aa4379199d3 -->
## Run 1

- Run-id:            05376e3ecac04f7e9a099aa4379199d3
- Run-start:         371d19cff8848e32cb8df0139f71612ae36a4732
- Issue:             #416
- Base SHA:          371d19cff8848e32cb8df0139f71612ae36a4732
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T14:04:00Z

### Section B evidence
Commits touching skillc/docker_backend.py, tests/test_docker_backend.py, tests/fixtures/docker-backend since 2026-10-17T13:59Z: none.
Merged PRs since filing: #405, #406, #407, #409, #411, #413, #415, #417 - none touch docker_backend.py. Open PRs #403/#411/#417: no overlap.
Duplicates/superseding: none.
AST scan (timeout= calls not inside a try catching TimeoutExpired) over docker_backend.py: L1014 (except) and L1024 in prepare() - the positive control; other hits (Limits ctor, Thread.join) are not the shape.

### Section C - the approved plan
1. `skillc/docker_backend.py` - `_best_effort_rm(name, env) -> str` helper catches OSError/TimeoutExpired from the bounded rm -f and returns a note; both prepare() failure paths use it and append the note to BackendUnavailable; timeout path keeps `from exc`; nonzero rm exit stays unreported.
2. `tests/test_docker_backend.py` - fake-CLI tests at daemon_timeout=2.0, delays 3.0: (a) RED .delay-run+.delay-rm, (b) RED .refuse-run+.delay-rm, (c) CONTROL .delay-run only (no cleanup note); (a)/(b) shown failing on unfixed main.
3. `CHANGELOG.md` - Unreleased entry.

Scope: small (~20 src lines, ~60 test lines). Risks: very loaded host may time out the 2.0s probe first (loud red, different message, never a false green); message grows a clause, existing match= users still match.
Conditions (approver): tell cpp-final-fix the test names for #412's measurement; keep the 1.5x bound ratio; run the AST scan over skillc/*.py, result in PR body, same-shape hits outside docker_backend.py to the nit store.
