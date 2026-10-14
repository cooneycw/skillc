# Flow run record - issue #382

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=51425e41753f40b5acf66b1b877c2dee -->
## Run 1

- Run-id:            51425e41753f40b5acf66b1b877c2dee
- Run-start:         552eaa6e3b375d0e258bfe2db6857b9dd02880cf
- Issue:             #382
- Base SHA:          552eaa6
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive session reply "approved"
- Recorded at:       2026-10-14T00:00:00Z

### Section B evidence
No commits on origin/main since the issue was filed (2026-10-14T10:16Z); #381 merged before and is the cited predecessor. #174 (closed) fixed an earlier form of item 1, which recurred on pipeline 457; #216 (closed) is a different test; no duplicate or superseding issue. Analysis: item 3's recorded failure was in setup (deliver_home_file docker cp under daemon_timeout=1.0); item 2 has two startup races (registration, handler install) inside its 0.3s timeout; items 1 and 3 are checkable structurally because the second drain join under a shared deadline always receives timeout=0.0.

### Section C - the approved plan
1. `tests/test_docker_backend.py` - slowed fake-docker wrapper and drain-join spy helpers; item 1 and item 3 assert shared-deadline join structure instead of wall-clock ceilings, setup off the 1s daemon_timeout, slow-exec/slow-cp parametrized reproductions; item 2 gates TERM on subject readiness and supervisor registration through a blocking cancel callable while keeping reason=="timeout", with slow-subject/slow-exec cases

Scope: one test file, ~150-200 lines; two drain tests ~3-4s slower each. Risks: item 2 relies on the poll loop checking the deadline before cancel() (asserted via reason=="timeout"); the spy reads CPython's private Thread._target (exactly-two-joins requirement turns a blind spy into a failure); setup calls keep the suite-default 5s daemon_timeout exposure.
