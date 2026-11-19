# Flow run record - issue #754

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b8674953e1664a24833579561107aeb2 -->
## Run 1

- Run-id:            b8674953e1664a24833579561107aeb2
- Run-start:         7fa0d2a5f65d31a40c5a4492a7a3309e62b9b10e
- Issue:             #754
- Base SHA:          7fa0d2a5f65d31a40c5a4492a7a3309e62b9b10e
- Necessity verdict: Still needed (acceptance item 1 revised at the gate, option a)
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #754 (mailbox rev 3, 2026-11-15T13:19Z); record location is the owner's ruling, option B, relayed in the same gate
- Recorded at:       2026-11-15T13:20:34Z

### Section B evidence
- commits since 2026-11-15T13:06Z: 7fa0d2a (#753, unrelated); none touching gauntlet paths or .claude/skills
- PRs: #755 open (#726 part A, the charter draft/confirm this engine calls); #733 merged (round 2 inspect)
- dup/super: #738 (parent), #736/#737 (rounds 3-5, out of scope); no duplicate
- host worktrees: none with unpushed commits on these paths; #726 part B is local-only at f1874a6 (skillc-719)
- acceptance conflict: inspect does not find #640 (docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md:54); ruled option a, issue comment 6894928344

### Section C - the approved plan
1. `skillc/gauntlet.py` - engine: round table (argv, documented exits, verdict reader, input digests), subprocess `sys.executable -m skillc.cli`, no round imports, absent command reads NOT BUILT, rounds 3-5 NOT BUILT, one NEXT line, final not-a-verdict line, GAUNTLET.json record (beside CHARTER.md; draft and record in .skillc/gauntlet/<skill>/ until a confirmed charter exists), deterministic and written only on change, resume by digests
2. `skillc/cli.py` - the agreed gauntlet subcommand group, adding only `run`
3. `tests/test_gauntlet.py` - controls with reds: unbuilt round, no-charter, resume (re-run executes nothing and the record is byte-identical; SKILL.md edit re-runs rounds 1-2), orchestration-only AST import check and copied-passage check, publish-safe record (no usage row value, no host path), exactly one NEXT line, absent command NOT BUILT, exit 0 unreachable, 600-word SKILL.md budget, CPP d5ef0a66 purpose control (host-only, loud skip)
4. `tests/test_readme_drift.py` - the single shared gauntlet command entry
5. `docs/specs/gauntlet.md` - rounds, verdicts, exit codes, the record (GAUNTLET.json, written only on change, never committed by the engine), usage discovery
6. `.claude/skills/skill-gauntlet/SKILL.md` - the skill: calls the engine, shows each verdict, stops at every owner point, says exit 0 is unreachable in part 1
7. `.claude/skills/skill-gauntlet/CHARTER.md` - drafted with skillc charter draft once #755 is on main, left unconfirmed
8. `evals/subjects/gauntlet/README.md` - fixtures: no-charter skill, confirmed-charter skill, two-skill collection, usage log
9. `README.md` - one command entry
10. `AGENTS.md` - one layout line
11. `changelog.d/754.md` - fragment
12. `docs/specs/charter-round1.md` - the narrowing sentence only (it writes only GAUNTLET.json beside the charter, and only on change), after #755 is on main; granted to this lane by the orchestrator (mailbox rev 4)

Scope: 12 files plus fixtures, ~700-900 lines with tests.
Risks: #755 / part B CLI drift before merge (tests run the real commands); contracts and usage report read as text lines; inspect on all of CPP is slower (skipped on unchanged inputs); GAUNTLET.json beside a charter is a file in the skill's repo, so it must be deterministic and publish-safe.

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout and linked worktree: the record and draft locations resolve to the main checkout from both |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host `make verify` (targeted set only, owner rule); real-Docker runner VM (installed runner pin vs requested commit): not tested, no real_docker files |
| Execution backend | not applicable |
| Agent client | will test - Claude Code: one real /skill-gauntlet session on a CPP skill; Codex: not tested |
| Client invocation | not applicable |
| Static-check target | will test - claude-code: skillc check on .claude/skills/skill-gauntlet; portable: not tested |
| Subject collection | will test - synthetic (evals/subjects/gauntlet) and CPP at pinned SHAs (d5ef0a66, host-only); mattpocock-skills: not tested |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (`uv sync`, editable); built wheel in a clean venv: not tested |
| Python version | will test - 3.12 tested (CI); >=3.11 declared: 3.11 not tested |
| Reader: usage report text (round 0) | tested against real output |
| Reader: contracts CONTRACT and finding lines (round 1) | tested against real output |
| Reader: charter draft / overlap exits (round 1) | tested against real output once #755 and part B are on main; NOT BUILT is the tested path until then |
| Reader: inspect --json report (round 2) | tested against real output |
| Reader: GAUNTLET.json (the engine on resume; later #736/#737) | tested against real output for resume; #736/#737 not covered |
| Reader: test_readme_drift command set | tested against real output |
