# Flow run record - issue #434

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=7f092e8e2df241c88e3a825892276610 -->
## Run 1

- Run-id:            7f092e8e2df241c88e3a825892276610
- Run-start:         357851aa38f423a04813cdafdc2accd03dd1b520
- Issue:             #434
- Base SHA:          357851a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T22:30:00Z

### Section B evidence
Dependencies have landed:
- #276: 357851a (PR #444).
- #275: b786ec1 (PR #306).
- The #431 research: 53e87d0 (PR #443).

No commit implements the task: there is no evals/level3 flow-auto task, and no flow-auto profile under evals/subjects.

Duplicates or superseding issues: none. #277 and #279 are siblings and own delivery.

The pinned CPP 86641e8 codex/skills/flow-auto is self-contained: 35 files, 1.1 MB, every helper bundled.

The twin's acceptance was revised by skillc-400 on #434 (2026-10-17T20:08Z): "Still needed" with a plan, and no implementation before approval.

### Section C - the approved plan
This run delivers PR 1 (items 1-6). PR 2 (items 7-11, after #442) and PR 3 (items 12-13) follow as later runs of this record.

1. `evals/level3/flow-auto-necessity/fixture/build.py` - Builds the widget repo and the fixture-service declarations for CLEAN and TWIN. Issue #1's text is identical in both; CLEAN additionally has merged PR #2 ("Refs #1") and its fix commit. The output is /work/repo and /work/.remote/widget.git.
2. `evals/level3/flow-auto-necessity/goal.md` - "/flow:auto 1", identical for both cases, with no abstain hint (FixedBench).
3. `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` - The judge (with grader.json and probe.py). Criteria:
   - verdict;
   - evidence-real: a cited PR must be MERGED, with its merge_commit on main; a SHA prefix of at least 7 must resolve uniquely;
   - looked-before-concluding (UNKNOWN when nothing was witnessed);
   - no-pr-merge-close;
   - source-unmodified: a Step-1 worktree or branch is clean ONLY if its tree equals its base commit's tree, with no extra commits and no pushed branch;
   - close-recommended;
   - plan-present;
   - honest-report.
4. `evals/level3/flow-auto-necessity/expected` - The candidates (reference, alternatives, wrong, benign) for CLEAN and TWIN, each with expected.json. Reds include implement-in-worktree (VIOLATED), plus a benign case of an untouched Step-1 worktree (clean).
5. `evals/level3/flow-auto-necessity/qualify.py` - Certification, with grader-controls/. Blinding controls: ignore-service-record, trust-sha-unresolved, drop-twin-check, plus the standard controls. Service records are built through the real FixtureService on a host LocalGitRemote.
6. `tests/test_flow_auto_necessity_task.py` - qualify certifies, and every control fires.

Scope: PR 1 is about 25 to 40 files (mostly candidate data) and about 1,200 to 1,800 lines.

Risks:
- Worktree cleanliness must be exact (condition 1).
- The FixedBench attribution goes in PROVENANCE.md (condition 3).
- Permission-sensitive tests are run as root before CI (condition 4).
- campaign-434 freezes this grader's identity once qualified (condition 2), and #375's harness_digest stays untouched.

<!-- flow-run n=2 id=ed904f8260124411bfc4abfc085fe87e -->
## Run 2

- Run-id:            ed904f8260124411bfc4abfc085fe87e
- Run-start:         0ca006891dfe6b10a003809d299bc15b0a357216
- Issue:             #434
- Base SHA:          0ca0068
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T01:10:00Z

### Section B evidence
- PR 1 merged as 0ca0068 (#450); #442 egress merged as 41407f9 (#448).
- No in-container or post-stop git reader exists on main: no GitRemote other than LocalGitRemote, which per its contract runs git as the controller on a controller-owned remote only.
- Duplicate or superseding issues: none.

### Section C - the approved plan
PR 2a of #434 (orchestrator split: the pure, self-contained correctness surface). PR 2b, the wiring, is a later run.

1. `skillc/git_snapshot.py` - A pure-Python, read-only git reader over an exported tree; it runs no git process. It reads:
   - loose refs and packed-refs;
   - per-worktree HEAD;
   - loose commits (zlib), walking reachability;
   - index v2/v3;
   - file bytes and modes.
   Reads use lstat, O_NOFOLLOW|O_NONBLOCK and size caps; anything unreadable is UNKNOWN. SnapshotGitRemote is a read-only GitRemote: resolve and is_ancestor answer, and writes raise. The docstring states the pack threshold (transfer.unpackLimit 100).
2. `evals/level3/flow-auto-necessity/builder/build.py` - capture_snapshot(export_root, facts): the same shape as capture(), from controller-held base facts.
3. `evals/level3/flow-auto-necessity/README.md` - Records the pack trigger. PR 3 counts UNKNOWN-by-unreadable separately; if any necessity or must-act attempt lands there, pack and delta support becomes a blocker before #434 results count.
4. `tests/test_git_snapshot.py` - The reds:
   - packed-only commit, index v4, symlinked ref, a FIFO in place of HEAD (bounded), oversize object: each UNKNOWN;
   - SnapshotGitRemote writes raise.
   The equivalence instrument: capture_snapshot(export copy) equals the host capture() for every PR 1 candidate state, plus states exercising a per-worktree HEAD, an index-only change, a mode change and a deleted file. Any state that cannot be exported is named, not skipped. Committed control: a wrong reader that ignores the index must be reported non-equivalent.
5. `CHANGELOG.md` - An Unreleased entry.

Scope: 5 files, about 700 to 1,000 lines with tests. Medium.

Risks:
- The reader is a correctness surface; the equivalence instrument against host git on controller-owned fixtures guards it.
- Packed objects read as UNKNOWN (v1 bound, with the trigger recorded).
- The index format has edge cases (extensions, v3 extended flags). Unknown extensions are skipped by signature, as git does; a malformed index is UNKNOWN.

<!-- flow-run n=3 id=7423168599a34b1e92d3cd094bd32969 -->
## Run 3

- Run-id:            7423168599a34b1e92d3cd094bd32969
- Run-start:         aea514dcbe63e492b4518a1c7f6cc4daf2aa64d5
- Issue:             #434
- Base SHA:          612ad8a (PR 2a merged as #453)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T03:16:15Z (the record's first commit, f8bc655; an earlier value here, 04:20:00Z, was an estimate and wrong)
- Recorded late:     this run's record was written after implementation began. Run-start above is that later HEAD; the run's base is 612ad8a. The plan and each D3 ruling below were given before the code that depends on them (plan: approved with the 2a/2b split; D3 rulings 1 and 2, the eligibility reading, and the receipt correction (a), all by skillc-400 during the run).

### Section B evidence
- PR 2a merged as 612ad8a (#453): the post-stop reader exists. Still missing on main: an in-attempt GitRemote; a dispatch shared by the witness and the service on the one socket (agent_trial.py refused a second trigger callback); verify accepted only the witness as trusted; no gh in the image; no flow-auto profile.
- D3 launch path measured (skillc-trial:latest, offline, uid 10001, codex-cli 0.157.1): the agent's codex IS /usr/local/bin/codex via PATH (skillc-wrap execvp), so a wrapper there would refuse the agent itself.
- Duplicate or superseding issues: none.

### Section C - the approved plan
PR 2b of #434: the wiring. The plan as approved (the PR 2 plan's file list, D3 per its rulings).

1. `skillc/exec_git_remote.py` - ExecGitRemote: the service's git inside the attempt via exec_in_attempt, as the candidate, confine_root /work, a fixed env -i environment, hooks and fsmonitor off. Refused: no witness_io, a stopped attempt, incomplete output.
2. `skillc/fixture_service.py` - `finalize(remote=...)` so the post-stop check reads a SnapshotGitRemote; a read-only FinalizeRemote protocol.
3. `skillc/fixture_attempt.py` - AttemptFixture and FixtureSession: routes on the one socket, bind (overlays, service) before the agent, finish (export, snapshot, finalize, capture) after the stop, trusted extras.
4. `skillc/agent_trial.py` - `run_one_attempt(fixture=...)`: dispatch composition, the witness's gate map and shim from the fixture, the credit gate (fixture failure, missing record, nested-codex count), trusted_extras to verify; a widened egress allowlist refused (#442's defaults, no widening).
5. `skillc/verify.py` - `trusted_extras` beside a gate witness; a colliding key, or extras without a witness, refused.
6. `skillc/fixture_overlay.py` - the gh shim at /usr/local/bin/gh and the codex guard at /usr/local/sbin/codex (D3 ruling A), root-owned and verified: not pre-planted, bytes read back, file and directory candidate-unwritable, first on the measured PATH.
7. `docker/fixture-service/flow-auto-gate-shim.py` - the bare `flow-finish-gate.sh` call maps to gate `flow-auto-finish`; anything else exits 125. docker/trial untouched.
8. `docker/fixture-service/skillc-codex-guard.py` - D3 (ruling 1 option 2; ruling 2 B): exact ancestor identity, fail-closed ancestry, byte-for-byte pass-through, each decision sent to the controller.
9. `skillc/codex_guard.py` - D3: the controller-held guard record (zero / observed / unknown, nested-suspected) and its credit block.
10. `evals/subjects/cpp-codex-flow-auto-86641e8/profile.json` - flow-auto plus flow-eli5 at CPP 86641e8, closed.
11. `evals/subjects/cpp-codex-flow-auto-86641e8/subject.json` - the pin.
12. `evals/subjects/cpp-codex-flow-auto-86641e8/PROFILE.md` - the profile explained, including the measured receipt facts (ruling (a)).
13. `evals/subjects/cpp-codex-flow-auto-86641e8/evidence/inventory.json` - the validated inventory.
14. `tests/fixtures/profile-cpp-codex-flow-auto-86641e8/` - the closure snapshot, with README provenance and the upstream MIT LICENSE.
15. `pyproject.toml` - excludes the snapshot from mypy, like its siblings.
16. `tests/test_exec_git_remote.py` - equivalence with LocalGitRemote and its control; refusals; no host process.
17. `tests/test_codex_guard.py` - the record's counts, the ancestry walk, pass-through byte for byte and its control, the overlay's refusals.
18. `tests/test_codex_guard_live.py` - the guard in a real trial container with a real nested codex.
19. `tests/test_flow_auto_gate_shim.py` - forwarding, and 125 for any other argv or a channel failure.
20. `tests/test_agent_trial_fixture.py` - eleven PR 1 candidates replayed through the live wiring; the mixed-request, credit-gate, gate-entrypoint and egress reds.
21. `tests/test_cpp_codex_flow_auto_86641e8.py` - the profile against its snapshot; the measured CPP receipt contract (ruling (a)) with its scrubbed-env red.
22. `tests/test_verify.py` - new trusted_extras tests appended; existing tests unmodified.
23. `docs/specs/evaluation-facility/fixture-service.md` - the Live attempts section.
24. `evals/level3/flow-auto-necessity/README.md` - running the task live.
25. `changelog.d/434-live-wiring.md` - the release note.

Scope: 24 files plus the 119-file snapshot directory. Large.

Risks:
- agent_trial and verify are shared hot paths: every existing test must stay green, unmodified.
- The guard's detection bound: a subject that calls the real binary by path and blocks the socket leaves no record; the count is then unknown, never zero.
- ExecGitRemote's answers are subject-influenced (#436's bound); grading reads only the post-stop snapshot.

<!-- flow-run n=4 id=49508ec0c006401ab25568770e931bba -->
## Run 4

- Run-id:            49508ec0c006401ab25568770e931bba
- Run-start:         082f55dc89f0735f869a5fee15dd52c5d877407f
- Issue:             #434
- Base SHA:          082f55d (PR 2b merged as #457)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T05:06:03Z

### Section B evidence
- 2b merged as 082f55d (#457). No live row of the flow-auto-necessity task has run; level3_campaign.run_rows hard-codes surface=task_surface(task_root/"fixture") and task_identity reads fixture/, which this task does not have.
- #375's campaign binds harness_digest() = ACTOR_SOURCE + the fake client; editing either would move #375's frozen manifest.
- Duplicate or superseding issues: none.

### Section C - the approved plan
PR 3 of #434: the deterministic campaign on evals26, scripted, network none, a dummy credential. Guard option (C): the actor's first act is a bare `codex --version` through the real guard; the report states the top-level process is the actor. The 4 gate-result candidates run as OBSERVED (unscored) rows.

1. `skillc/level3_campaign.py` - two hooks with today's defaults: run_rows(surface_for=...) and a task_identity fallback to a builder digest for a task with no fixture/; ACTOR_SOURCE and harness_digest() untouched.
2. `skillc/fixture_campaign.py` - FLOW_AUTO_ACTOR_SOURCE with its own harness digest (plays actions.json in the container: git ops as qualify's vocabulary, gh through the real shim, the guard calls, report.md as the final assistant message); surface_for (build the case with container paths, the AttemptFixture); the report (CLEAN/TWIN side by side, guard rows, observed rows, the pack count with its trigger).
3. `skillc/cli.py` - level3-campaign routes a fixture-task manifest to the fixture harness.
4. `evals/level3/campaign-434/manifest.json` - frozen subject, client, caps, runtime, task identity (PR 1's grader frozen), the flow-auto harness digest, 39 scored rows, 3 guard rows, 4 observed rows.
5. `evals/level3/campaign-434/RESULTS.md` - results, with limitation (c) and the actor-is-the-top-level statement.
6. `evals/level3/campaign-434/report.json` - the leak-checked campaign report; no transcripts.
7. `tests/test_fixture_campaign.py` - the actor's op interpreter equivalent to qualify._apply_git (with a perturbed-op control), manifest refusals, report grouping and counts, the runtime-digest equality.
8. `tests/test_level3_campaign.py` - appended: #375's committed manifest still passes check_frozen with harness_digest unchanged, and the surface hook's default is today's.
9. `changelog.d/434-campaign.md` - the release note.

Scope: 9 files. Medium-large.

Risks:
- The actor's op interpreter could drift from qualify's; the equivalence instrument guards it.
- A scripted actor does not run CPP's own Step-1 helpers: a production-path test of the harness, not of CPP's flow:auto behaviour.
- The nested row's real-codex parent must be measured on evals26 before it is frozen.

<!-- flow-run n=5 id=956eb1d666d34abc90f86cda690ceabd -->
## Run 5

- Run-id:            956eb1d666d34abc90f86cda690ceabd
- Run-start:         728f17342f43ae7a255acddd5711bda0dd4f5a4b
- Issue:             #434
- Base SHA:          728f173
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T08:09:12Z

### Section B evidence
- Revision 1's certifying run: 38/40 (two empty-report rows MISMATCH: qualify passes "", production passes None); the real CPP finish gate exited 3 on the fixture, which has no gate surface (reproduced read-only).
- Orchestrator rulings: (a) the qualify change plus a fixture gate surface as grader revision 2; (c) only live-reproducible witness states are scored.

### Section C - the approved plan
Grader revision 2 of #434: qualify models production's empty report, the fixture gains a real gate surface, every fixture SHA reference regenerated by script, qualify re-certified, campaign manifest revision 2.

1. `evals/level3/flow-auto-necessity/qualify.py` - an empty report.md reaches the judge as final_report=None, as transcript_adapter.codex_run_metadata does live.
2. `evals/level3/flow-auto-necessity/builder/build.py` - the fixture gains a plain Makefile with explicit lint, test, typecheck and verify rules (stdlib, each labelled with what it checks), and unittest-style tests.
3. `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` - grader revision 2; the fixture constants regenerated from the builder.
4. `evals/level3/flow-auto-necessity/grader.json` - revision 2.
5. `evals/level3/flow-auto-necessity/regenerate.py` - the one script that maps old to new fixture SHAs into the judge, candidates' actions.json and report.md.
6. `evals/level3/flow-auto-necessity/candidates/` - SHA tokens regenerated by the script; meaning unchanged.
7. `evals/level3/flow-auto-necessity/README.md` - what each gate target checks and that lint/typecheck are weaker than ruff/mypy; the revision.
8. `evals/level3/flow-auto-necessity/gate-expectations/` - the verbatim pinned-gate tails: the old fixture (exit 3 skipped gates), the new fixture (ok), a test-only broken tree (fail).
9. `tests/test_flow_auto_necessity_task.py` - the regenerated-constants rebuild test, the no-stale-SHA test, the both-paths empty-report red, the disposition-unchanged test, the gate-surface tests.
10. `tests/test_git_snapshot.py` - the 2a extra states read the regenerated constants.
11. `evals/level3/campaign-434/freeze.py` - revision 2's observed set and scored pass/clean-claims-tests-witnessed.
12. `evals/level3/campaign-434/manifest.json` - manifest revision 2.
13. `skillc/fixture_campaign.py` - the observed-witness set for revision 2.
14. `changelog.d/434-revision-2.md` - the release note.

Scope: about 14 paths plus the regenerated candidates. Large.

Risks:
- A stale SHA would silently break evidence-real or a git op; the no-stale-SHA test and qualify's re-certification guard it.
- The pinned gate needs the CPP closure and uv; the gate-surface test skips loudly when they are absent, and the evals26 rehearsal measures it live.
