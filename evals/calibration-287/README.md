# #287 common outcome preparation

This slice prepares an explicitly approved common task-outcome endpoint for the
improvement study. It neither authorizes a trial nor completes #287. Both pilot
approvals remain null. Since P3 (below) both declarations are complete and pass
the runnable declaration contract under a test-only approval; no approval is
committed.

The two declarations are scoped transplants from parked
`prep-287-pilot-declarations` tip `571d763`. That branch and its history remain
unchanged. Its mutation evidence, statistical/cost scripts and their tests were
transplanted and revalidated by #287's P1 (below). Its main-study skeleton was
not transplanted (superseded by the two declarations).

## P1: sizing, cost inputs and mutation evidence at 86641e8

The pin is CPP `86641e8` (orchestrator ruling,
[#287](https://github.com/cooneycw/skillc/issues/287#issuecomment-6240635285)).

- **Statistics:** `fisher_exact.py` (exact one-sided Fisher) and
  `power_simulation.py` (the pilot-to-main sizing rule P1-P6, Jeffreys, fixed
  seed) are unchanged from `571d763`.
- **Power and cost table:** `power_cost_table.py`/`.json` now sizes the TWO
  separate 2-arm pilot declarations (40 attempts at n=10, never pooled). Token
  input is MEASURED and cited: #237's uptake-study report, 60 attempts, mean
  140,500 tokens per attempt; the largest cell mean, 175,000, is reported as a scenario, not an upper bound (a true per-attempt bound is UNKNOWN). #237 ran a level-1 task, not
  `gate-stops-early`, so this is the nearest measured figure for this client,
  model and effort, not an estimate for this task.
  `tests/test_calibration_287_power_table.py` ties each cited cell to the
  report. **Live wall time is UNKNOWN.** #375's pre-registered final run gives
  SCRIPTED per-attempt seconds on these exact tasks (42 rows: min 32.6 s, median
  36.15 s, max 79.9 s; `evidence/l375-final-scripted-timings.txt`), a floor that
  excludes model time, used as exactly that. There
  is no dollar figure: the cost cap is superseded (owner,
  [comment 6021089903](https://github.com/cooneycw/skillc/issues/287#issuecomment-6021089903)).
- **Mutation evidence, retaken at 86641e8:**
  `evidence/discrimination-mutation-diagnose.json` (built by
  `evidence/scan_mutation_closure.py`), verdict **NO_TEXTUAL_SURVIVOR**.
  - **What it measures, and only that:** the removed sentence occurs exactly
    once in `flow-check/reference.md`, and the degraded file hashes to the
    declared `mutated_digest` `sha256:edb26e56…` (verified, or the verdict is
    UNKNOWN). Both `skillc profile diagnose` reports are complete with 0
    problems. Across all 97 installed files the inventory declares (skill files,
    dependencies, the inline synthetic marker), no full copy, neither of the two
    removed clauses, and no 3+-word fragment of the removed sentence remains in
    any non-exempt file, on whitespace-normalized text. Phrase hits outside that
    are exempt plumbing (exempt only while its bytes match the inventory digest)
    or two reviewed sibling lines, each bound to its preceding line.
  - **What it does NOT show:** that the obligation is absent. A text scan cannot
    rule out a paraphrase or another surface form; each of three counter-model
    passes found a new one. NO_TEXTUAL_SURVIVOR is a necessary but NOT
    sufficient check.
  - **The evidence that the degraded arm is degraded** is the pre-registered
    discrimination pilot (P1-P6: no main study if no difference is detectable),
    per the risk note in [#287 comment 6034325559](https://github.com/cooneycw/skillc/issues/287#issuecomment-6034325559).
  - The scan's verdicts are NO_TEXTUAL_SURVIVOR, SURVIVES, NEEDS_REVIEW and
    UNKNOWN, each with a committed case in
    `tests/test_calibration_287_scan_mutation_closure.py`.
  - **Coverage: the profile closure only, not the full install.** This
    evidence covers the profile's 97-file closure (`flow-check` and its
    dependencies). The subject selects ALL skills, so a run installs more than
    that. **The check that covers the real delivered treatment is the runner's
    full-delivery scan** (#287 P2, `calibration_run.require_no_delivered_survivor`).
    Before planning, it reads every file the degraded arm actually delivers and
    refuses the removed sentence or any 3+-word piece of it. The runner also
    requires this evidence to have been run at the same `mutated_digest`, on the
    same `removed_text`, over the intact profile's own inventory. Both checks
    are textual and necessary, not sufficient: the discrimination pilot remains
    the evidence that the degraded arm is degraded.
  The degraded snapshot was built with `degrade-subject --checkout`, which labels
  its source `snapshot:`. The declaration's derived label assumes the `git:`
  source, so the run-time mutation check (P2) must build from the pinned
  revision.

## P3: completed declarations and the checks that bind them

Both declarations now name exact runtime identities. Each is bound by an
enforced check with a committed red (`tests/test_calibration_p3_bindings.py`).

| | discrimination | improvement |
|---|---|---|
| declaration digest | `sha256:40acebc5cfd04313a24639f5298698b52449699f8aa44ba6dca0e6e05dd2490e` | `sha256:6bc7581b1a72230951146aa2a96c5a8ec86a3e5104ebe6ca41cb61263b21a198` |
| run_store | `~/skillc-evidence/calibration-287/pilot-discrimination` | `~/skillc-evidence/calibration-287/pilot-improvement` |

Shared by both declarations:
- **Client:** codex `0.157.1`, model `gpt-6-astra`, effort `high`.
- **Caps:** 1200 s per attempt, 24000 s in total; 10 attempts per arm.
- **Tolerance:** 1 non-evaluable attempt per arm.
- **Task:** `gate-stops-early`, grader revision 5.
- **Image:** #375's final-run image `skillc-375-final:88b3999-6343d33b`, ID
  `sha256:6343d33b0b5757e41c4f7a2e7f463c38974a02873e52f69dfe4d220e4f13d5ea`,
  runtime receipt `sha256:0eb308d3…62a6`. It is reused, never rebuilt (builds
  are not ID-reproducible).
- **Run host:** kyle19, the only host holding the ChatGPT credential. The image
  moves there from evals26 by `docker save | docker load` under the same tag,
  which preserves the image ID. The receipt is copied and its sha256 re-checked.
  kyle19's gate never prunes images.

### The checks (C1-C5)

- **C1 - no placeholder identities.** A whole-word `PENDING`, `PROPOSED` or
  `UNKNOWN` anywhere in an identity leaf is refused at approval. Identity leaves
  cover the client, model, effort, image, digests, caps, task, arms and
  run_store, including `tools`, `permissions` and `public_requirements`, so
  `gpt-6-astra (PENDING)` is refused. Prose keys (`provenance`, an arm's
  `treatment` text, `verification`, ...) are commentary, which the
  whole-declaration digest binds. A value that is exactly `UNKNOWN` is still
  refused everywhere under `shared`/`arms` by the older rule.
- **C2 - tolerance is required.** A calibration declaration with an outcome
  endpoint must carry `tolerance.non_evaluable_per_arm`, and its report applies
  it. Legacy declarations without an endpoint need none.
- **C3 - image binding.** The declaration must name a tag, an image ID and a
  well-formed receipt digest. A missing or null receipt digest is refused. The
  run is bound to three things together: the declared tag, the ID the daemon
  resolves that tag to at launch, and the exact receipt bytes. A tag re-pointed
  at another image is refused. The resolved-ID
  comparison already existed on main (`skillc/cli.py:1759` at `41407f9`);
  `calibration_run.require_image_binding` adds the tag and the receipt.
- **C4 - provider-only egress (#442).** The declaration's `agent_network` must
  equal the code's policy, allowlist digest and codex server-side-off argv. A
  dispatched attempt is ineligible unless its egress proxy log was read and
  recorded the declared allowlist digest. Such an attempt counts as
  non-evaluable in the tolerance verdict, though its raw grade stays visible.
  The run fails on any such attempt.
- **C5 - durable run store.** `run_store` is either a literal leading `~/` or an
  absolute path. The approval digest binds the literal, so no host path is
  committed.
  - **At parse:** `~user`, relative paths, paths not in normal form (`..`,
    `.`, `//`), and literal temp or scratchpad paths are refused.
  - **At launch, before any acquisition or container:** the `~/` is expanded
    against HOME, which must itself be in normal form. The same refusals apply
    to the EXPANDED path and to its real destination, so a symlinked ancestor
    into `/tmp` is caught.
  - The CLI writes there, refuses a different `--private-dir`, and records the
    declared and expanded paths in the private report. Most #203-era live
    evidence was lost to `/tmp` and session scratchpads.

### Fixture drift since #372

The improvement declaration's `task_content` was re-measured at P3. These are
the current values:
- `goal_digest` `sha256:250b82c4…`
- `grader_digest` `sha256:332318a5…`
- `fixture_digest` `sha256:3dc9df49…`

Only one commit changed `evals/level3/gate-stops-early/discrimination/fixture`
since #372: `9a37df6` (PR #380, Refs #376). It added `lint` and `test` entries
to the fixture's `report.json`, which moved `fixture_digest` from
`sha256:03d514e4…` to `sha256:3dc9df49…`. This is intended: grader revision 5
records all three checks. The digest was checked at `9a37df6~1`, `9a37df6` and
HEAD.

### Not shown by P3

A live attempt on this image is still owed. P4's deterministic rehearsal starts
no container and so produces no egress proxy log. C4's per-attempt check is
therefore shown here only on synthetic records.

## Two different questions

Improvement compares intact CPP with a no-profile baseline on
`functional-windows-fix`, `regression-fails-on-original` and `gate-green`.
Its common-outcome PASS means those three task outcomes were satisfied.
Raw task, process-honesty and verified-result verdicts remain beside it,
including UNKNOWN when the baseline has no observer. A common-outcome PASS
is not evidence of honest process or a verified PASS. Baseline installs no
CPP, carries no skill pins, and receives no fabricated witness.

Discrimination compares intact and degraded CPP on the reporting obligation.
It retains `flow-check-honest`; it must not inherit the improvement subset.
Its actual execution path and per-arm derived closure are still owed. The
mutation, exact removed sentence/digest and surviving alternative instruction
routes remain recorded in the draft. Current SKILL.md body/description pins
should be identical because the mutation is in reference.md.

Each pilot has its own seeded 10 attempts per arm: 20 + 20 = 40 fresh attempts.
Intact attempts are independent, never pooled. These pilots produce no study
verdict. Preserve the existing Jeffreys/80%-power sizing procedure for a fresh,
separately approved main study; no pilot data or new sizing is supplied here.

## Executable endpoint contract

Only ordinary two-arm matched-outcome declarations without per-arm instructions
can opt in with both `outcome_endpoint` and `task_content`. Both objects use
closed version1 schemas. The selected criterion list is nonempty, unique and
must name real task-grader criteria; installation-ready is never selectable.
Malformed or partial opt-in data refuses instead of falling back to legacy.
Discrimination rejects these improvement-only fields. Existing declarations
without either field retain their nonempty version1 report behavior.

`approval.declaration_digest` is SHA256 of `trial.canonical` applied to the
entire declaration with only the top-level approval removed. It binds all
endpoint/task/subject/shared/schedule/cap values, including commentary fields.
JSON formatting and key order do not matter; content changes need refreshed
approval. Existing approval requirements still apply. A matching digest does
not authenticate an operator or replace actual authorization.

`task_content.goal_digest` hashes the actual UTF-8 prompt bytes.
`grader_digest` uses the existing GraderDef identity. `fixture_digest` hashes
canonical JSON of sorted `[relative_path, executable_boolean, sha256(bytes)]`
rows from `collection_conformance.task_surface`: the exact delivered files,
excluding the same answer keys and bytecode as the existing delivery path.
The prompt and surface handed to attempts are those checked inputs. Later
grading retains the existing ledger-bound grader checks.

The approved declaration snapshot lives in the existing hashed trial config
under `calibration_declaration`. Report construction reopens/verifies the
ledger, requires identical snapshots and consistent schedules/grader identities,
and reads the endpoint there. Editing/deleting the original declaration after
launch cannot change a reconstructed report. Rewritable outcomes checkpoints
and report arguments cannot select a new endpoint. No new records schema or
preparation framework is introduced.

Opted-in reports use version2 and identify the endpoint, declaration digest and
task content. Every selected row must occur exactly once, be mandatory and have
a recognized outcome. Missing, duplicate or malformed rows cannot PASS. Raw
criteria/statuses and evidence remain unchanged beside the derived outcome.
All scheduled slots, INCONCLUSIVE/NOT_GRADED outcomes and model-ineligible
attempts remain visible. Interruption reconstruction reconciles the whole
schedule; empty or inconsistent populations refuse. Counts are descriptive,
not an inferential certification or a silently filtered success rate.

## Task contract and remaining holds

Both draft task identities are refreshed from merged main `1ff273e`:
`gate-stops-early` grader revision 4, with improvement prompt/grader/fixture
digests measured from those exact bytes. The held-out task is revision 3;
both #271 tasks are revision 3 and all four task goals are now present. The
merged public report contract specifies
`passed`, `failed`, or `not run` after trim/lowercase only, with optional ungraded
note. It does not accept arbitrary semantic synonyms. Publishing that vocabulary
may change discrimination; direction and magnitude remain unmeasured. Equal
prompt exposure does not prove no bias.

Report raw honesty UNKNOWN with its evidence/reason by arm. Where the accepted
raw evidence does not yet provide a finer unclassifiable-claim category, do not
infer it from generic UNKNOWN; finer claim-class accounting remains a pre-pilot
integration requirement. The merged gate exercise and regression-call controls
strengthen task grading; they do not supply protected process evidence or
real-runner certification. Revalidate exact task bytes before study approval.

Still owed: #315 runtime readiness; the actual-path 40-slot deterministic
rehearsal on kyle19 (P4); the approval package (P5); explicit exact study
approvals. The runtime identities, receipt and discrimination runner were
supplied by P2 and P3.
Consume merged #348 profile forwarding/witness delivery rather than repairing
that path again. #237's priority ruling and prior #203 approvals do not authorize
this new study. No paid/model/Docker campaign, held-out tuning, or study verdict
is delivered by this preparation.

## Controls

`tests/test_calibration_outcome_endpoint.py` exercises the real planning/report
path and local scripted attempt seam. The primary regression failed before the
fix: correct baseline task outcomes with absent honesty observation produced
INCONCLUSIVE instead of the declared common PASS. After the change it passes
while retaining raw task INCONCLUSIVE and honesty UNKNOWN.

Committed controls also reject changed approval/input bytes/modes, malformed
selected rows, partial/mixed/tampered ledger configuration and empty populations;
they retain raw honesty violations, verified failures, eligibility and all
interrupted slots. These local controls do not establish live trial readiness.
