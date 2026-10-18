# Flow run record - issue #456

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=25b9452d3de6476da400a287e6513473 -->
## Run 1

- Run-id:            25b9452d3de6476da400a287e6513473
- Run-start:         746dd721f7712199abb9b984550ca53af680eac4
- Issue:             #456
- Base SHA:          746dd721f7712199abb9b984550ca53af680eac4
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T03:43:06Z

### Section B evidence
Observed 2026-10-17: main b2fa7f8 posted "20 executed" with runner 41407f9 while #280's floor file ran uncounted; #282's re-pin made it 23. Design approved on #456 (issuecomment-6245295141). Exit-code audit: run-real-docker exits 0/1/2/3 only (lines 31,50,64,88,101,170,259,270,277,294,383-385); poll-triggers exits 2 on config (20,26) and compares the runner's exit only to "3"; 4 is unused.

### Section C - the approved plan
1. `ci/check_real_docker_ran.py` - RUNNER_BEHIND status word; Verdict fields for files the runner does not count and files the commit dropped.
2. `ci/real_docker_post.py` - read the tested commit's DECLARED_REAL_DOCKER_FILES by ast (never import; one literal tuple of tests.<identifier> strings, else ERROR); add-only comparison; precedence ERROR > FAILURE > RUNNER_BEHIND > SUCCESS; exit 4; certifying runs only.
3. `ci/real_docker_summary.py` - RUNNER-BEHIND description and body ("re-pin, then re-seed state to the parent"), names filtered as today.
4. `ci/real-docker/run-real-docker` - pass the checkout for --break none; POST_VALID accepts 4:RUNNER_BEHIND; GitHub state error; exit 4.
5. `ci/real-docker/README.md` - re-pin trigger and procedure incl. the parent re-seed.
6. `tests/test_real_docker_runner_behind.py` + `tests/test_real_docker_post.py` - reds: behind, unreadable floor, precedence, shorter list vs a commit-list mutant, reader never executes subject code, runner wiring; green: identical floors unchanged.

Scope: medium (~90 src, ~150 test, ~25 doc lines). Risks: a certifying run now reads checkout data; bootstrap needs a re-pin.
Approver conditions: (1) RUNNER_BEHIND message and README say "re-pin, then re-seed state to the parent"; (2) exit 4 collision audit cited; merge needs a re-pin with N executed unchanged and one RUNNER_BEHIND observed live or skipped with a reason.
