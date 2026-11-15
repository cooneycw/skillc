# Flow run record - issue #737

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b72e9c5763fe476b9ca7cce4e8dc67dc -->
## Run 1

- Run-id:            b72e9c5763fe476b9ca7cce4e8dc67dc
- Run-start:         0d97bb8ee76398602ac5c9647fd1d707a97d3515
- Issue:             #737
- Base SHA:          0d97bb8ee76398602ac5c9647fd1d707a97d3515
- Necessity verdict: Still needed (inputs partly unbuilt: #736 PR 1 local-only with no report JSON; #726 part B unmerged)
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #737 (mailbox rev 22, 2026-11-15T15:36Z)
- Recorded at:       2026-11-15T15:36:30Z

### Section B evidence
- commits on main since 2026-11-14T23:19Z: #755 (8e0e02e), #764 (0d97bb8); none build a verdict
- PRs: #764 merged (the GAUNTLET.json record read here); #736 PR 1 local-only at b544741 (skillc-719), text output only; #726 part B unmerged
- dup/super: none (#738 parent; #736 and #726 are the issue's "Blocked by")
- host: no worktree has unpushed commits on these paths

### Section C - the approved plan
1. `skillc/gauntlet_verdict.py` - pure verdict from files (record, round 3/4 JSON in asdict(RoundReport) shape with the field names pinned in one place, #736 declaration, inspect --json, overlap report); UNKNOWN for any undecided or absent round including a missing --overlap (retire NOT EXAMINED); retire naming owners; trim whose remove text occurs exactly once, with a removing diff; keep; D as removal candidates, B as proposed checks; one verdict line, one NEXT; patch and PR text to the draft location through #764's writer; the rule command records rounds.5 with ruled_on from --date, refusing a stale verdict digest
2. `skillc/cli.py` - gauntlet verdict and gauntlet rule in the shared gauntlet group
3. `tests/test_gauntlet_verdict.py` - keep, trim (diff removes), retire (names owner), UNKNOWN (names round), no overlap -> UNKNOWN, zero and two remove matches -> UNKNOWN, one verdict and one NEXT across all, tree digest unchanged, verdict re-run leaves GAUNTLET.json byte-identical, B -> proposed check, rule records ruling with a date and refuses a stale digest, real asdict(RoundReport) test skipped loudly until #736 PR 1 is on main
4. `evals/subjects/gauntlet-verdict/README.md` - the planted inputs for the cases
5. `docs/specs/gauntlet-verdict.md` - inputs and fields read, rules, outputs, exit codes, the ruling, not examined (incl. the no-observed-use retire path)
6. `docs/specs/gauntlet.md` - the round-5 row stays accurate
7. `README.md` - one command entry
8. `AGENTS.md` - one layout line
9. `changelog.d/737.md` - fragment

Scope: 9 files plus fixtures, ~700 lines with tests.
Risks: designing against an unshipped JSON (pinned in one place; the real-class test runs once #736 PR 1 lands); the trim diff depends on the declaration's remove text (exactly once, else UNKNOWN); adding one dated field to a deterministic record (written only by rule).

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout and linked worktree: verdict and rule find the record and draft location from both |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host `make verify` (targeted set only); real-Docker runner VM (installed runner pin vs requested commit): not tested |
| Execution backend | not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test - synthetic (evals/subjects/gauntlet-verdict); CPP at pinned SHAs: not tested (the real proof stays open) |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (`uv sync`, editable); built wheel in a clean venv: not tested |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: verdict reading GAUNTLET.json (rounds 0-2) | tested against real output - records written by the real engine on the fixtures |
| Reader: verdict reading round 3/4 report JSON | not covered - #736 emits no JSON yet; planted asdict(RoundReport)-shaped files, real-class test skipped loudly until it lands |
| Reader: verdict reading inspect --json | tested against real output - the real inspect run on the fixture |
| Reader: verdict reading charter overlap | not covered - part B not merged; planted in its documented shape |
| Reader: the owner and /skill-gauntlet reading verdict and NEXT lines | tested against real output - the controls assert the lines |
| Reader: GAUNTLET.json gaining rounds.5 (the engine on resume) | tested against real output - an engine re-run after rule keeps rounds.5 and still caches rounds 0-3 |
