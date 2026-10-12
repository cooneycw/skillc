# #287 common outcome preparation

This slice prepares an explicitly approved common task-outcome endpoint for the
improvement study. It neither authorizes a trial nor completes #287. Both pilot
approvals remain null. Draft runtime identities/caps are visibly unresolved and
do not yet pass the runnable declaration contract.

The two declarations are scoped transplants from parked
`prep-287-pilot-declarations` tip `571d763`. That branch and its history remain
unchanged. Its mutation evidence, statistical/cost scripts, main-study skeleton
and tests are pending transplant/revalidation, not delivered here. An earlier
three-arm proxy cost table is not the cost estimate for these two pilots.

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

The draft content identities are measured from the current committed primary
task, not from EE's pending revisions. Both drafts require refresh against the
final merged public-report contract before exact study approval. EE v2 specifies
`passed`, `failed`, or `not run` after trim/lowercase only, with optional ungraded
note. It does not accept arbitrary semantic synonyms. Publishing that vocabulary
may change discrimination; direction and magnitude remain unmeasured. Equal
prompt exposure does not prove no bias.

Report raw honesty UNKNOWN with its evidence/reason by arm. Where the accepted
raw evidence does not yet provide a finer unclassifiable-claim category, do not
infer it from generic UNKNOWN; finer claim-class accounting remains a pre-pilot
integration requirement. Missing held-out/#271 goal files are separately owned
task-readiness work, not authorization to substitute a different task here.

Still owed: final merged EE
contract and task identities; #354 pins; #315 runtime readiness; the derived
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
