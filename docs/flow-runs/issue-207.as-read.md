<!-- flow-run n=1 id=055e5b06922a432d98b8c5159cdaf70f -->
## Run 1 - issue #207 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #207
- Read at:      2026-09-30T18:51:32Z
- updatedAt:    2026-09-30T18:47:46Z   (context only - moves on comments and labels)
- Body digest:  6aa8ce5e7a668dfc113b47cc86de009196d1a2b47275cc7b74de3ea71f968b55   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3992 of 3992 (cap 16384)

### Body as read
Blocks #204's calibration run, approved by the owner 2026-09-30 (`evals/calibration-204/run-manifest.json`, `approval` block). That approval stands, but no command can execute the schedule, so nothing has run.

## Why

No existing command can run the declared schedule:

- **`skillc collection-run`** runs ONE attempt of a subject. It has no baseline (no-skill) mode: a subject's `select` must be `"all"` or a non-empty list (`skillc/materialize.py:218-224`). It also does not pin the model or effort: `DEFAULT_CLIENT_ARGVS` carries no `-m` (`skillc/collection_conformance.py:140-143`).
- **`skillc pilot-run`** has a baseline arm and pins the model (`skillc/matched_pilot.py`, `launch_argv` / `model_overrides`). But it reads only the Level 1 matched-pilot declaration (`CURRENT_MANIFEST_PATH`) and parses `matched_pilot_(treatment|baseline)_N` trial ids.

Hand-running eight attempts would also get the arm order, the caps and the model pin from a person rather than from the declaration. That is the drift #141 fixed for the pilot.

## Scope

A `skillc calibration-run` (or a generalisation of `pilot-run`) that reads a `calibration-declaration` through `skillc.calibration.load_declaration` and refuses unless `require_approved` passes. It then:

- plans the schedule in the declared `arm_order.sequence` through the real controller (`trial.plan`), one trial per attempt;
- runs each attempt through ONE attempt path (`agent_trial.run_one_attempt`, as `matched_pilot` does). The arms differ only in `extra_home_files`: the treatment gets the subject's selected surface plus the #150-D `InstallationReceiptContext`, the baseline gets `{}`;
- pins the declared model and effort at launch and refuses a caller argv that sets either, reusing `matched_pilot.launch_argv`/`model_overrides` rather than a second copy. An attempt whose rollout reports another model, or none, is ineligible and fails the run;
- enforces `per_attempt_seconds` and `total_seconds` as `matched_pilot.run_schedule` does;
- retains transcripts (#202) and leak-checks anything exported;
- reports per attempt `calibration.primary_endpoint` and `calibration.readiness_beside`, never the verified status as the endpoint;
- reconciles every planned attempt, so none is dropped.

Out of scope: the run itself (a separate, already-approved step), the calibration report (#204 questions 1-5), and the go / redesign / stop call for #203.

## Acceptance

- [ ] **Refuses when not authorized.** A declaration with `approval: null` refuses before any container starts. Red case: the committed approved declaration with its approval removed.
- [ ] **Arm order.** The planned order equals `arm_order.sequence`.
- [ ] **Arms differ only in treatment.** A test drives both arms through a fake client and shows the baseline gets no skill files and the treatment gets exactly the subject's.
- [ ] **Model pin.** It is passed at launch. A caller argv that sets `-m` is refused. A mismatched observed model makes the attempt ineligible and fails the run.
- [ ] **Caps enforced.** An attempt that would start with no total cap left is finalized `not-run`, never dropped.
- [ ] **Symmetric endpoint.** Per-attempt output carries `primary_endpoint` and `readiness_beside`. A baseline attempt meeting every task criterion shows primary PASS beside `installation-ready` UNKNOWN.
- [ ] **No live model call** in the suite (fake client, as `tests/fixtures/codex-subject/fake_codex.py`).

## Constraints

- ADR 0005: runs only an approved declaration.
- ADR 0002: the runtime stays in skillc.
- Stdlib only in `skillc/`.
- Nothing may branch on a particular subject.

## Attribution

The calibration design this serves comes from an adversarial read-only critique of #203 by OpenAI Codex (`codex exec`, model `gpt-6-astra`), requested via `/codex:ask` on 2026-09-30, and recorded in #204's Attribution section. This runner's scope is derived from skillc's own `matched_pilot` and `collection_conformance` modules; nothing external is borrowed.

