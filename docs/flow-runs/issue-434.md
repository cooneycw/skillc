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
- Recorded at:       2026-10-18T04:20:00Z
- Recorded late:     this run's record was written after implementation began. Run-start above is that later HEAD; the run's base is 612ad8a. The plan and each D3 ruling below were given before the code that depends on them (plan: approved with the 2a/2b split; D3 rulings 1 and 2, the eligibility reading, and the receipt correction (a), all by skillc-400 during the run).

### Section B evidence
- PR 2a merged as 612ad8a (#453): the post-stop reader exists. Still missing on main: an in-attempt GitRemote; a dispatch shared by the witness and the service on the one socket (agent_trial.py refused a second trigger callback); verify accepted only the witness as trusted; no gh in the image; no flow-auto profile.
- D3 launch path measured (skillc-trial:latest, offline, uid 10001, codex-cli 0.157.1): the agent's codex IS /usr/local/bin/codex via PATH (skillc-wrap execvp), so a wrapper there would refuse the agent itself.
- Duplicate or superseding issues: none.

### Section C - the approved plan
PR 2b of #434: the wiring. The plan as approved (file list from the PR 2 plan, D3 per its rulings).

1. `skillc/exec_git_remote.py` - ExecGitRemote: the service's git inside the attempt via exec_in_attempt, as the candidate, confine_root /work, a fixed env -i environment, hooks and fsmonitor off. Refused: no witness_io, a stopped attempt, incomplete output.
2. `skillc/fixture_service.py` - `finalize(remote=...)` so the post-stop check reads a SnapshotGitRemote; a read-only FinalizeRemote protocol.
3. `skillc/fixture_attempt.py` - AttemptFixture and FixtureSession: routes on the one socket, bind (overlays, service) before the agent, finish (export, snapshot, finalize, capture) after the stop, trusted extras.
4. `skillc/agent_trial.py` - `run_one_attempt(fixture=...)`: dispatch composition, the witness's gate map and shim from the fixture, the credit gate (fixture failure, missing record, nested-codex count), trusted_extras to verify; a widened egress allowlist refused.
5. `skillc/verify.py` - `trusted_extras` beside a gate witness; a colliding key, or extras without a witness, refused.
6. `skillc/fixture_overlay.py` - the gh shim at /usr/local/bin/gh and the codex guard at /usr/local/sbin/codex (ruling A), root-owned and verified: not pre-planted, bytes read back, file and directory candidate-unwritable, first on the measured PATH.
7. `docker/fixture-service/flow-auto-gate-shim.py` - the bare `flow-finish-gate.sh` call maps to gate `flow-auto-finish`; anything else exits 125. docker/trial untouched.
8. D3 (ruling 1, option 2; ruling 2, B with the nested-suspected count): `docker/fixture-service/skillc-codex-guard.py` (exact ancestor identity, fail-closed ancestry, byte-for-byte pass-through) and `skillc/codex_guard.py` (the controller-held record and its credit block). The CPP contract is measured: ruling (a) on the receipt correction.
9. `evals/subjects/cpp-codex-flow-auto-86641e8/` (profile.json, subject.json, PROFILE.md, evidence/inventory.json) and `tests/fixtures/profile-cpp-codex-flow-auto-86641e8/` (the closure snapshot, with README provenance and the upstream MIT LICENSE); `pyproject.toml` excludes the snapshot from mypy like its siblings.
10. Egress: #442's defaults, no widening (the fixture attempt refuses a widened allowlist).
11. Tests: `tests/test_exec_git_remote.py`, `tests/test_codex_guard.py`, `tests/test_codex_guard_live.py`, `tests/test_flow_auto_gate_shim.py`, `tests/test_agent_trial_fixture.py`, `tests/test_cpp_codex_flow_auto_86641e8.py`, and new tests appended to `tests/test_verify.py` (existing tests unmodified).
12. Docs: `docs/specs/evaluation-facility/fixture-service.md` (Live attempts), `evals/level3/flow-auto-necessity/README.md`, `changelog.d/434-live-wiring.md`.

Scope: 24 files plus the 119-file snapshot. Large.

Risks:
- agent_trial and verify are shared hot paths: every existing test must stay green, unmodified.
- The guard's detection bound: a subject that calls the real binary by path and blocks the socket leaves no record; the count is then unknown, never zero.
- ExecGitRemote's answers are subject-influenced (#436's bound); grading reads only the post-stop snapshot.
