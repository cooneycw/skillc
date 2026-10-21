# Flow run record - issue #508

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ec584779ba9a4531af24ff1404103322 -->
## Run 1

- Run-id:            ec584779ba9a4531af24ff1404103322
- Run-start:         21298e6deccb2671247c30271405ff5bb769f5d9
- Issue:             #508
- Base SHA:          21298e6deccb2671247c30271405ff5bb769f5d9
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #508, 2026-10-21
- Recorded at:       2026-10-21T08:00:00Z

### Section B evidence
Accepted design: #287 issuecomment-6251092328 (skillc-worker-C), rulings in its section 7. Re-read against 21298e6:
- `gate-report-honest` is already used by gate-stops-early-auto6 r1;
- the gate is `flow-auto-finish`;
- `gate_environment()` is the measured container env, with no harness-make pin;
- `Order` exists only in multi-turn attempts;
- AttemptGuard shares the trigger socket;
- the shim is harness apparatus, not a #505 home file;
- gates run in worktrees.
Duplicates: none (no `project-check` on main).

### Section C - the approved plan (this run is PR-A, the witness; PR-B, the grader, is cut from the merged PR-A)
1. `skillc/gate_witness.py`: an additive `declared_stages` param. Ordered stage argvs, one controller exec per stage, stop at the first nonzero exit, one tree digest at start. Stage outcomes come from controller exit codes. Without it the record is unchanged.
2. `skillc/gate_overlay.py`: `apply_make_gate_overlay`. A root-owned shim dir (file and dir verified unwritable), prepended to the agent's PATH.
3. `docker/fixture-service/make-gate-shim.py` (NEW): forwards `make check`, bare `make`, and `make <declared stage ids>` as `run_gate project-check`; renders make's bytes and exit code. Any other invocation passes through to the real make and is logged subject-reported (never-evidence).
4. `skillc/agent_trial.py`:
   - a `project-check` witness kind;
   - the project_gate argvs bound to the Makefile digest (drift makes stages `unavailable`);
   - controller execs use PATH minus exactly the shim dir;
   - the non-gate log in the attempt record, outside the grader's input;
   - an assertion that ONE GateWitness owns every gate exec.
5. `skillc/profile.py`: `GATE_WITNESSES += project-check`; the `project_gate` declaration.
6. Tests, append-only:
   - new `tests/test_make_gate_shim.py`, with goldens from real make per outcome cell and a regeneration control that skips LOUDLY without make;
   - new `tests/test_project_gate_witness.py`, covering the nested-request red, the single-witness red, the never-evidence red and drift;
   - appended `tests/test_gate_witness.py` and `tests/test_gate_overlay.py`.
7. `DESIGN` notes (in the module docstrings and `docs/`): why the in-container runner script was rejected (/proc/<ppid>/fd/1 forgery); completed_at ordering under the single _exec_lock.
8. `changelog.d/508-project-gate-witness.md`.

Scope: large. Risks:
- GateWitness and agent_trial are hot paths: additive changes only, existing tests unmodified.
- PATH stripping must be exact; the nested-request red proves it.
- The subject-reported log must never reach the grader; a red proves it.

<!-- flow-run n=2 id=09c447c52d5846e58c4a638b05610e00 -->
## Run 2

- Run-id:            09c447c52d5846e58c4a638b05610e00
- Run-start:         2902c5bce9a4e0fde934ac8c15a9d7545a8bd061
- Issue:             #508
- Base SHA:          2902c5bce9a4e0fde934ac8c15a9d7545a8bd061
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #508 PR-B (C1-C5, both-arms YES), 2026-10-21
- Recorded at:       2026-10-21T09:00:00Z

### Section B evidence
PR-A merged as #509 (2902c5b). A counter-model re-review of the pass-2 fixes found two HIGH findings:
- H1, a probe-to-make race;
- H2, per-stage make differing from one `make check` (goal-specific variables, a Makefile rewritten mid-run).
`--eval .PHONY` leaks into recipes' MAKEFLAGS (measured), so it is rejected. auto6's `gate-report-honest` is single-source.

### Section C - the approved plan (this run is PR-B)
1. `skillc/project_gate.py`:
   - (1a) a post-stage re-probe (blindable for reds);
   - C1: a stage whose controller-run make reports a skip ("is up to date" / "Nothing to be done for", strings pinned against make 4.3 goldens) is null, never passed;
   - C2: a closed, committed QUALIFIED_MAKEFILES set; from_declaration fails closed on any other digest; a digest without goldens fails a test.
2. `evals/level3/gate-stops-early-agent-chooses/` (NEW grader id): auto6's task copied, auto6 unchanged, and `gate-report-honest` scored by the cross-gate rule.
   - Every UNKNOWN carries a reason code (gates-disagree / none-fresh / partial / bypass / drift / ran-nothing), counted.
   - qualify covers every design §5 cell plus "pass claimed against one failing gate", with broken-judge controls.
   - C5: a pinned-digest control on auto6's grader files; a one-byte red is run once.
3. Calibration: `project-gate.json` in a task, loaded by `collection_conformance` and passed to BOTH arms; a test pins it to the fixture Makefile.
4. Tests append-only; docs (`gate-witness.md` §10, the task README/DESIGN); changelog; the live test extended under lock 1.

Scope: large. Risks:
- hot-path additive only;
- the skip-string match can only demote a stage to null (a recipe printing it forges toward UNKNOWN, never toward passed);
- baseline-arm symmetry (both arms are witnessed alike).
