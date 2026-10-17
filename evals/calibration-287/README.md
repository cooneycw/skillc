# #287 common outcome preparation

This slice prepares an explicitly approved common task-outcome endpoint for the
improvement study. It neither authorizes a trial nor completes #287. Both pilot
approvals remain null. Draft runtime identities/caps are visibly unresolved and
do not yet pass the runnable declaration contract.

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
  The degraded snapshot was built with `degrade-subject --checkout`, which labels
  its source `snapshot:`. The declaration's derived label assumes the `git:`
  source, so the run-time mutation check (P2) must build from the pinned
  revision.

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

Still owed: exact approved runtime/skill pins; #315 runtime readiness; the derived
full-tree closure and approval-bound manifest; the discrimination runner;
actual-path 40-slot deterministic rehearsal; exact client/model/effort/image and
runtime-supply receipt; current cost estimate; explicit exact study approvals.
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
