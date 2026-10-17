# Flow run record - issue #432

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=26576e9483274db9b9731d0eaf55d8af -->
## Run 1

- Run-id:            26576e9483274db9b9731d0eaf55d8af
- Run-start:         4bab8d3fd4da032d87f9c31c23e1dac8a1d7e651
- Issue:             #432
- Base SHA:          4bab8d3fd4da032d87f9c31c23e1dac8a1d7e651
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T19:05:00Z

### Section B evidence
Since the issue was created (2026-10-17T18:10:25Z): no commit on origin/main touches skillc/calibration_run.py, skillc/profile.py or tests/test_calibration_run_profile_closure.py; no PR references #432; no duplicate or superseding issue (search: "skill_pins build_treatment" - none).

### Section C - the approved plan
1. `skillc/calibration_run.py` - replace the #424 equality cross-check with a per-path subset check: every inventory pin needs an installed pin at the same path with equal body_digest and description_digest; a missing path or any digest mismatch is refused naming the paths; skill_digests (all installed skills, from installed bytes) is unchanged.
2. `tests/test_calibration_run_profile_closure.py` - regression with a two-skill content repo and a one-skill profile (fails on main, passes after); reds for a body-digest mismatch (#424's existing red, kept), a same-path description-digest mismatch, and a pinned-but-not-installed path; control that skill_digests holds both installed skills.
3. `tests/test_calibration_run_real_profile.py` - the real evals/subjects/cpp-codex-flow-check-86641e8 profile with the full install from a local claude-power-pack clone at 86641e8: fails on main, builds after with 77 pins and flow-check's pin equal to the inventory's; skipped with a reason naming the missing prerequisite (git, or a CPP checkout holding 86641e8).
4. `CHANGELOG.md` - entry.

Scope: small. Risk: subset is weaker than equality in one direction - an installed skill the inventory does not name is not cross-checked (by ruling); it stays pinned from its installed bytes, so ledger-binding still binds it. PR also states whether #287's calibration treatment reaches this path (trace).
