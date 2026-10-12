# Flow run record - issue #360

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=69ab673a99494644939cdc4a03988a58 -->
## Run 1

- Run-id:            69ab673a99494644939cdc4a03988a58
- Run-start:         faf8810d1ec47eb9a9f6b3bb4c41a4d3730be026
- Issue: #360
- Base SHA: faf8810d1ec47eb9a9f6b3bb4c41a4d3730be026
- Necessity verdict: Needs reframing
- Approval: granted
- Approver: skillc wave orchestrator, gate-360-phase-one.md
- Recorded at: 2026-10-12

### Section B evidence

#343 supplied uv, #334 supplied consuming closure preflight, and #355/#358
repaired the real-daemon overlay. #346/#359 forwarding is on this base.
External #356/#362 owns trial-image build fixes; #341 owns shared live tests.
The historical import refusal used bridge networking with stderr suppressed;
its cause remains undiagnosed. User explicitly selected a pinned offline
runtime supply. The old cold-install image uses a different interpreter and
root-owned cache, so it is not runtime acceptance for the candidate user.

### Section C - the approved plan

1. `docker/profile-trial/` - add a bounded builder, closed policy/descriptor/receipt contract, same-trial-stage Docker extension and acceptance documentation for the one CPP pin.
2. `tests/test_profile_trial_image.py` - exercise the real preparation and contract validators with good/bad inputs, proving invalid preparation makes zero Docker calls.
3. `tests/fixtures/profile-trial-runtime/` - commit metadata/policy/receipt/malformed/source-leak negative controls and their good inputs.

Phase one only: approximately 700 lines plus fixtures. Final image additions
are dependency cache and root-owned descriptor only. Cache and final runtime
share the trial interpreter/platform; final USER remains candidate. External
receipt binds actual immutable image ID, descriptor bytes, recipes and pinned
metadata. Confirm exact closed schema with #348 owner before consumption.

Risks: same-image claims need actual runtime proof, cache ownership must allow
uv writes, inherited candidate USER requires explicit root setup/restoration,
and package cache must not leak CPP source, skill or prepared project venv.
Committed offline controls exercise validators; they cannot establish Docker
runtime behavior. Empty-cache/permissions, baseline purity and exact consuming
path controls remain mandatory acceptance, including original-image offline
red separately from historical bridge diagnosis.

No Docker execution, shared live/runner/CHANGELOG edits, paid model calls,
VM changes, historical pin edits or generic default-image switch are granted.
Return phase-one evidence and request explicit remaining-file handoff.
Independent review, serialized full verify and current-base CI precede root
merge review. Use Refs #360 until consuming-path acceptance is recorded.

Additional approval on 2026-10-12: orchestrator gate-360-changelog-and-verify.md
extends this same phase-one run after DD released its future edit window.

4. `CHANGELOG.md` - add an accurate phase-one build/policy/control entry, explicitly retaining pending real-runtime acceptance.

Full verification is serialized after DD finishes and after a clean measured
different-model review. Use an unavailable Docker socket with DOCKER_CONTEXT
unset and report live skips. This grants no Docker or shared live/runner edits.

### Phase-one execution evidence (pending full verification)

Focused offline suite: 138 passed. Selected ruff and mypy checks passed.
The checker selftest discriminated 31/31 rules; the leak scanner's seeded
negative control passed before the changed-path scan reported zero findings.
No Docker image was built or run, and no runtime acceptance is claimed.

The initial same-model advisory audit used measured codex/gpt-6-astra, matching
the implementer, so it does not satisfy independent review. It found two
accepted defects: alternate final COPY syntax bypass and missing direct
metadata/uv measurement controls. Both were fixed.

Three completed independent passes used measured codex/gpt-6.1-sol in a
read-only sandbox with successful repository reads. Pass one found unchecked
warm-stage instructions and missing independent digest-format controls; pass
two found comment-continuation normalization could hide warm/final additions;
pass three reported no defects and exercised indentation/trailing-whitespace
forms. All three findings were accepted and fixed. A subsequently requested
extra lexical audit was stopped when the orchestrator clarified that pass
three already satisfied that request; it produced no final review verdict and
is not counted as a completed review.

Concrete regression runs failed before their fixes: three warm-stage cases
(venv injection, changed base, removed locked sync), two physical-comment
hiding cases and one suppressed-Docker-diagnostic case. All pass afterward.
Isolated validator mutations produced failures for policy, metadata,
descriptor, receipt, additions, inventory, measured uv, final instructions and
provenance digest-format checks. Production bytes were not modified by those
in-memory mutation runs. The original generic-image offline red remains owed
to the separately authorized real-Docker acceptance, not these offline tests.

The installed counter-model receipt helper cannot represent Codex/Codex
pairings. Its actual write probe refused the real implementer session because
it sought a Claude transcript. The delegated direction also requires a Claude
reviewer. No receipt JSON or fabricated model identity was written. This is
already recorded in [CPP Nit Store comment 6128975985](https://github.com/cooneycw/claude-power-pack/issues/864#issuecomment-6128975985)
by another wave worker; no duplicate finding was posted. Actual private review
streams and model measurements are retained in operational evidence.

The later CHANGELOG grant is an authorized addition to the original file plan;
the filename compliance helper reports that difference. Lane verification
reports all 16 paths within the current grant. Implementation whitespace checks
pass; the generated as-read issue snapshot preserves a trailing blank line.

### Phase-one full verification completed

Root requested checkpointing and current-main integration before the queued
full run. Phase-one checkpoint `76388e6` was followed by main-sync merges,
ending at `0f8214fffaf72dd2531e4a30e494305f61104369` with main `1c9954a` included.
The #356/#360 changelog insertion conflict retained both entries.

After DD's explicit completion and slot release, unfiltered `make verify`
returned exit 0. `DOCKER_CONTEXT`, `PYTEST_ARGS`, `PYTEST_WORKERS` and
`PYTEST_REPORT_DIR` were unset; `DOCKER_HOST` named a deliberately unavailable
Unix socket. The Makefile's default eight-worker run finished with 3,329
passed and 15 skipped in 251.92 seconds. All 3,344 collected identities matched
the JUnit report. The skips were 12 Docker-dependent cases, two frontmatter
refusal fixtures and the intentionally gated timeout control.

Lint, typechecking (193 files), changelog/README checks, leak and secret scans,
and all negative/typecheck/leak/secret/git/population controls passed. The
population short-report control failed as intended and its complete twin
passed. The actual owned process exit was collected before releasing the
serialized slot to AA; no replacement full run was started.

This is phase-one evidence only. Root assigned supporting delivery and
selected-runtime preflight fixes to DD: candidate-created missing parents,
explicit offline/locked import probing and rejection of an undeclared external
venv selector. The default project-local `.venv` and image schemas stay unchanged.
Those supporting changes, shared live-test/runner integration, actual cache and
venv-permission controls, baseline purity and real consuming-path acceptance
remain owed to #360. The separate host-probe override defect remains #365.
The historical bridge refusal's actual cause is still unproven. No Docker
image build or model trial ran in this phase.

### Approved image-environment guard amendment

Root's later image-environment-guard grant adds one bounded change in the
existing builder/test/docs lane: refuse any observed image `Config.Env`
`UV_PROJECT_ENVIRONMENT` entry, including an empty value, before writing a
receipt. Descriptor and receipt schemas do not change. DD retains delivery,
selected-runtime preflight and effective-environment integration; #365 remains
the separate host-probe issue. No shared live/runner or profile.py edit is granted.

Both fake-Docker regression cases failed on the prior builder (no refusal),
then passed after the guard. They leave the descriptor and all required values
valid, proving the check reads independent image configuration. The existing
absent-selector builds remain the positive control. Updated full verification
is queued after AA's explicit release and before DD phase two; the earlier
0f8214f green remains historical evidence, not evidence for this new guard.

### Image-environment amendment verification completed

The orchestrator reviewed the small guard diff with no findings. After AA's
explicit exit-0/no-replacement slot release, unfiltered default-parallel
`make verify` returned exit 0: 3,331 passed and 15 skipped in 236.49 seconds;
all 3,346 collected identities matched the report. Remaining checks and
negative controls passed, including the short-report/complete-report pair.
The same unavailable Docker socket and unset selection/context variables were
used. The tested tree was HEAD `883643c` plus the archived guard/tests/docs
diff `43dfc7e23ef02a1eea012f72f2551261582668e310c0a59688b451c8b31133ac`.
The actual owned process exit was collected and the slot explicitly released
to DD before any subsequent main sync. Real Docker acceptance remains pending.
