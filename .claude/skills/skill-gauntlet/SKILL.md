---
name: skill-gauntlet
description: Run the skill-gauntlet on one skill and report each round's verdict and the single NEXT step. Use when the owner asks to put a skill through the gauntlet, to check what a skill is for, or to see which of its rules are stale.
---
# /skill-gauntlet <collection> <skill>

Runs `skillc gauntlet run`, the engine, on one skill, and reports what it says.
The engine does the work. This skill runs it, shows the result, and stops
wherever the owner has to decide. It never answers for the owner.

## Run it

```bash
skillc gauntlet run <collection> <skill> [--usage <log-or-dir>]...
```

- `<skill>` is a skill directory holding `SKILL.md`, or a command `.md` file,
  relative to the collection.
- Pass `--usage` for each repository where the skill has run. A skill's usage is
  recorded where it ran, which is usually not its own repository.
- For a collection whose skills are not `SKILL.md` files (CPP's commands), pass
  round 2's surface through: `--include`, `--map`, and `--repo`.

## Read the result

Show the owner every `ROUND` line as printed, the `RECORD:` line, the `NEXT:`
line and the final `GAUNTLET:` line. Do not summarise them away.

- One line per round reached: round 0 usage, round 1 charter, round 1 overlap,
  round 2 inspect, round 3 trials.
- `UNKNOWN`, `NOT BUILT` and `NOT EXAMINED` are not passes. Say so; never round
  them up.
- Exactly one `NEXT:` line. Relay it as the next step, word for word.
- The run always stops by round 3 today: rounds 3 to 5 are not built, so the
  engine never exits 0 and never gives a keep, trim or retire verdict. Say this
  plainly; the final line says it too.

## Stop at every owner point

Stop and hand the decision to the owner when the run stops at:

- **Round 1, draft ready:** the skill has no `CHARTER.md`. The engine wrote a
  draft and named it in `NEXT:`. The owner works through it clause by clause and
  runs `skillc charter confirm`. Do not answer the clauses, and do not write or
  confirm a charter yourself.
- **Round 1, not approved:** an intent or authority clause lacks the owner's
  approval. Only the owner approves.
- **Round 1 overlap:** overlaps are proposals for the owner, never findings
  against the skill.
- **Round 2 findings:** D items are stale rules the owner may move or delete.
  Nothing is trimmed by the run, and you do not trim them either.

## Never

- Never edit the skill, its charter or its committed bad cases.
- Never stage, commit or push `GAUNTLET.json`. The engine writes it; committing
  it is the owner's act.
- Never count `UNKNOWN` as a pass, or read a round that did not run as clean.
- Never spend on trials. Part 1 runs none.

The engine's rules, exit codes and record are in `docs/specs/gauntlet.md`.
