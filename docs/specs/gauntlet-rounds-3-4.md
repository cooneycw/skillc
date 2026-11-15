# Skill-gauntlet rounds 3 and 4: baseline and challenge (#736)

Rounds 1 and 2 (#726, #725) judge what a skill **says**. Rounds 3 and 4 judge
what it **does**, by running trap tasks (`evals/level3`'s shape: a goal, a
fixture and a binary `grader.json`) against the skill, several times each.

```bash
skillc gauntlet round3 <declaration> --plan   # the attempt count; spends nothing
skillc gauntlet round4 <declaration> --plan
```

**PR 1 ships the machinery and offline controls only.** A real run (no
`--plan`) is refused with "real runs are #736 PR 3". PR 3 adds the Docker
runner over `calibration_run`'s path, under its own gate.

## The declaration (JSON)

| Field | Meaning |
|---|---|
| `skill`, `skill_digest` | the skill directory and its `source_digest.digest_tree`. A changed skill is refused |
| `client` | `name`, `version`, `model`: part of every ledger key |
| `attempt_cap`, `partial` | the declared attempt count (#718 decision 4). Without `partial`, a run needing more is refused |
| `replicates`, `seed` | attempts per task and arm, and the split's seed |
| `clauses` | `{clause id: [task dirs]}`, the trap tasks behind each charter clause |
| `min_tasks_per_clause` (at least 2), `min_heldout` | below either, the round reads `UNKNOWN` |
| `damaged` | at least one arm: `{arm, file, remove, clause}`. The **named passage** removed, and the clause it serves |
| `variants` | round 4's arms: `{arm, file, remove, clause}`, where `clause` names the source (a round-2 class or a round-1 overlap) |
| `tolerance` | round 4's no-worse tolerance, 0 unless the owner declares one |
| `discrimination_rule` | the `reliability.TwoArmRule` for round 3's separation test |

A passage must occur **exactly once** in its file, and the file must be a
regular file **inside the skill** (no absolute path, no `..`, no symlink).
Otherwise the arm would not be the one its name says, or would leave the skill
undamaged. `partial` must be a JSON boolean.

## Tasks and the split

**A task is identified by what the agent sees.**
- Its task digest covers `goal.md` and `fixture/`, which are both required: a
  task missing either is refused.
- The task digest alone decides the minimums and the split. Directories with
  the same goal and fixture are one task, whatever their graders. If such
  directories declare different graders, the declaration is refused.
- Its grader digest is `verify.GraderDef.digest()`: the definition, plus the
  probe, inputs and judge it names. It is part of the ledger key. Editing a
  README beside the grader changes nothing.

**One global split** covers every distinct task, so a task shared by two
clauses can never train one and be held out for the other.
- Clauses are walked in a fixed order.
- Each clause's not-yet-placed tasks are shuffled with the seed, and enough are
  held out to give that clause a third of its tasks (at least one) held out.
- The same seed always gives the same split.
- A clause left without a train task, or (for round 4) a held-out task, reads
  `UNKNOWN`.

## Round 3: baseline

- **Arms:** the intact skill and every damaged copy, each on the train tasks of
  every clause, `replicates` times.
- **Separation:** for each damaged arm, its clause's pass counts against the
  intact skill's, through `reliability.evaluate_discrimination`.
- **An error in either arm makes that separation `UNKNOWN`.** Dropping one
  arm's errors from its denominator could fake a difference.
- **The verdict is `COMPLETE` only if every damaged arm reads `DISCRIMINATING`.**
  Otherwise it is `UNKNOWN`: tasks that cannot tell a damaged skill from an
  intact one show nothing about the intact one. That is the charter's guard
  test.

## Round 4: challenge

- Round 3 must be `COMPLETE`, and its attempts are reused from the ledger. A
  round-3 `UNKNOWN` makes round 4 `UNKNOWN`. Round 3 not run yet is `REFUSED`.
  `--plan` never needs round 3: it counts round 4's attempts and states the
  round-3 prerequisite.
- **Arms:** the intact baseline and every variant, on the held-out tasks.
- **A variant passes iff, for every clause, its pass count >= the baseline's
  minus `tolerance`.** An errored attempt is never "no worse".
- If any variant passes, the recommendation is `trim` and the passing arms are
  named. If none passes, it is `keep`.
- **The safe direction.** With few replicates the strict rule is noisy, and that
  noise favours `keep`: a skill is never trimmed on weak evidence. A declared
  tolerance is printed in every report.

## Budget and the ledger

- The **declared** attempts are the distinct (arm, task, replicate) triples a
  round needs. The **new** attempts are those the ledger lacks.
- No `attempt_cap` means `REFUSED`. New attempts above the cap, without
  `partial`, also mean `REFUSED`. Either way, this happens **before any attempt**.
- With `partial: true`, the run goes up to the cap, then stops: **`INCOMPLETE`**,
  never a pass.
- **The ledger key** is the arm's skill digest, the task digest, the
  **grader's** digest (`GraderDef.digest()`), the client, its version, the
  model, the arm and the replicate. A re-run on the same key spends nothing. A
  changed grader or client is a new key, and reuses nothing.
- **The runner must report the declared client, version and model.** A
  mismatch refuses the round, and that grade is never recorded, so a re-run
  never reuses another client's result.
- **A cached row must be the attempt its key names** (client, version, model,
  arm, skill digest, replicate). Otherwise the ledger is refused, never reused.
- **Ledger rows are validated on load.** Each needs every field and a result of
  pass, fail or error. One bad row refuses the whole ledger (exit 2).
- **Every clause and arm must hold its whole population** (tasks x replicates)
  before a verdict. Missing evidence is `UNKNOWN`, never `0/0` read as no worse.
- The report prints declared, reused, new and run attempts, the cap, and the
  client and model of every attempt. The owner relates those counts to
  `/usage` (decision 4).

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | `COMPLETE`, or `PLANNED` under `--plan` |
| 1 | `REFUSED`: no cap, over the cap, round 3 not yet run, or no runner (PR 1) |
| 2 | the declaration cannot be read or run as written |
| 3 | `UNKNOWN` or `INCOMPLETE`: never a pass |

## Controls

`evals/gauntlet-controls/` holds one skill, six task stubs and one declaration.
`tests/test_gauntlet_trials.py` drives every control through `ScriptedRunner`.
A mutation check shows each guard can fail:
- turning off the separation check fails 2 tests;
- turning off the over-cap refusal fails 1;
- dropping the grader from the ledger key fails 1;
- loosening the no-worse rule fails 1.

## What this does not examine

- Whether real tasks separate a real damaged skill: that is what the real run
  measures (PR 3).
- The quality of the trap tasks themselves: that is PR 2 (tasks for a skill's
  must-never clauses, each with grader controls).
- Variant generation: PR 1 removes only DECLARED passages; nothing is invented.
