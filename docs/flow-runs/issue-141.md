# Flow run record - issue #141

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #141
- Base SHA:          a0fb533d002d4c1046fe1af1cbf6e9d57a93c36b
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (session user), "approved" in the /flow:auto session
- Recorded at:       2026-09-27T15:10:00Z

## Section B evidence
Issue created 2026-09-27T14:31Z. No commits on origin/main since (a0fb533 / #142
predates the issue). No open PRs. No duplicate or superseding issue; #141 promotes
nit-store comment cooneycw/skillc#20 (issuecomment-5856506955). The live code still
launches `cc.DEFAULT_CLIENT_ARGV` with no `-m` (skillc/cli.py:1066) and documents the
model as "NOT enforced at launch" (skillc/matched_pilot.py:105).

## Section C - the approved plan
1. `evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json` - new dated declaration: #12's predeclared record with model gpt-6-astra + reasoning_effort high, a supersedes block naming run-manifest.json and the 3e1e3fb run, execution not run; no invented gpt-6-astra price.
2. `skillc/matched_pilot.py` - PilotDeclaration.reasoning_effort; CURRENT_MANIFEST_PATH; launch_argv() appends -m and -c model_reasoning_effort and refuses a base argv that overrides the model; build_report model_eligible; summarize excludes ineligible attempts from matched pairs and lists model_ineligible; write_outcomes records the declared model/effort.
3. `skillc/cli.py` - pilot-run defaults to the current declaration, refuses one with no effort, builds argv through launch_argv before any run dir, exits 1 after publishing when any dispatched attempt is model-ineligible; pilot-report uses the run's recorded declaration and requires an explicit --manifest for a pre-#141 run.
4. `tests/fixtures/agent-trial/fake_agent_client.py` - accept -m / -c, write a codex turn_context; --observed-model and --no-turn-context for red cases.
5. `tests/test_matched_pilot_run.py` - argv-from-declaration, override refusals, red cases (other model, no turn_context) -> ineligible + exit 1, green -> exit 0, pilot-report provenance refusal.
6. `tests/test_matched_pilot.py` - #12's manifest unedited; the new declaration supersedes it and differs only in allowed keys; READMEs name the current declaration.
7. `evals/matched-pilot/README.md` - state the current declaration.
8. `evals/matched-pilot/evidence/README.md` - state the current declaration; pilot-report command passes --manifest run-manifest.json.

Scope: medium. Choices approved: only the model gates eligibility (effort is pinned and reported); a mismatch does not stop the schedule; "dispatched" = captured or inconclusive.
Risks: the override refusal is a denylist (post-attempt check is the backstop); the fake client cannot prove real codex honours -m.
