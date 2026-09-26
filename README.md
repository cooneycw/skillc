# skillc

**Skills are the new code. Code doesn't ship uncompiled.**

A skill is a unit of software now. It gets authored, versioned, installed,
depended on, and it rots. What it does not get is a build step: there is nothing
between writing a `SKILL.md` and shipping it that can refuse. `skillc` is that
missing stage.

The next proposed capability is an independent evaluation facility for collections
of scaffolding skills, with **goal-based tasks at progressively harder levels**.
Accessible projects become test subjects through supported adapters. Claude
Power Pack (CPP) will be the first subject, supplied as a pinned external input
and exercised in disposable environments. The facility belongs in skillc.

**Status:** the static checker exists. The task levels, Docker facility and
behavioral comparisons below are a documentation-only proposal, not implemented
features. See the [specification](docs/specs/evaluation-facility/spec.md),
[architecture decision](docs/decisions/0002-independent-goal-driven-evaluation.md) and
[PLAN.md](PLAN.md) for the design and delivery sequence.

```bash
skillc selftest           # prove every rule can still report the other verdict
skillc check ./skills     # check a collection after validating the rules
skillc rules              # what it checks, and at what severity
```

The existing static checker has zero runtime dependencies and requires Python
3.11+. The proposed evaluation facility will have separate execution requirements.

---

## The problem, concretely

The September 15, 2026 assessment ran it against a real 18-skill collection in a
repository with a CI pipeline, a lint gate, a type checker and a test suite:

```
skillc: 18 skill(s) checked, 36 error(s), 37 warning(s)
```

The checker rejected the collection's names and flagged its description style
and `trigger:` fields. Those findings motivated further investigation; they do
not establish what every client loads or whether the skills improve outcomes.

This is a historical motivating example, not a measurement of current CPP.
Static findings alone do not establish what a particular agent will load or how
its behavior will change; those questions motivate the evaluation plan.

## The founding constraint

An instrument that cannot fail is not evidence. A green from a blind check and a
green from a working one look identical, and the difference is only ever found
later, by whoever was relying on it.

So every rule in `skillc` ships a committed **redcase**: an input that makes it
report the other verdict. `skillc selftest` runs each rule against its own
known-bad and known-good pair:

```
$ skillc selftest
ok       name-spec             red on bad (2), green on good (1)
ok       required-fields       red on bad (5), green on good (2)
ok       trigger-shape         red on bad (1), green on good (1)
ok       unknown-field         red on bad (2), green on good (1)
ok       claude-code-field     red on bad (1), green on good (1)
ok       body-budget           red on bad (1), green on good (1)
ok       ref-depth             red on bad (1), green on good (1)
ok       frontmatter           red on bad (3), green on good (2)
ok       record-envelope       red on bad (7), green on good (2)
...

skillc selftest: 23/23 rule(s) discriminate
```

Five verdicts fail the run:

| verdict | meaning |
|---|---|
| `BLIND` | the rule stayed silent on a known-bad input |
| `NOISY` | the rule fired on its known-good input |
| `EMPTY` | a control directory holds no input, so that side proves nothing |
| `UNPARSED` | a control input does not parse, so the parser - not the rule - decided it |
| `UNPROVEN` | no committed control exists, so nothing has shown the rule can fail |

Only findings the rule under test raised count as red. Two rules are parser
controls (`frontmatter`, `record-envelope`): their known-bad input must include
one that does not parse. Every other rule must be shown red and green on input
that does.

`UNPROVEN` is the one that matters. A rule with no control is not treated as
passing, because absence of a control is not evidence of correctness.

The selftest is itself under a negative control. A test in the suite blinds a
rule on purpose and asserts the harness says so - because a selftest that cannot
fail proves nothing about the rules it blesses.

## What it checks

```
$ skillc rules
error  name-spec          name is spec-legal and matches its directory
error  required-fields    required frontmatter is present and in range
warn   trigger-shape      description says when to fire, not just what it does
warn   unknown-field      every field is defined by the portable specification  [target: portable]
warn   claude-code-field  every field is one Claude Code documents  [target: claude-code]
warn   body-budget        SKILL.md body stays inside the line budget
warn   ref-depth          references stay one level deep
error  frontmatter        frontmatter is present and parses
```

Frontmatter is read by a **documented subset of YAML**, not a YAML
implementation: block mappings and lists, single-line and quoted values, and `|`/`>`
block text. Anything else is an error that says whether real YAML also rejects it
or `skillc` simply does not read it. `name` and `description` must be non-empty
strings. Which fields "load" depends on the client, so the field rules are scoped:
`--target portable` (the default, the Agent Skills specification) or
`--target claude-code` (plus Claude Code's documented extensions, read on a stated
date). See [docs/frontmatter.md](docs/frontmatter.md).

(`skillc rules` also lists the evaluation-record rules checked by
`skillc check-records`: per-record rules for the installation receipt, trial
ledger, artifact manifest, verified result and attempt lifecycle, and bundle rules that bind a
directory's records to its one trial ledger. A record outside any bundle is
reported as checked alone, not against a ledger. See the
[records spec](docs/specs/evaluation-facility/records.md).) An unknown `--rule` is refused with exit 2 before
anything is scanned; a selector that matched nothing used to read as a clean run.

`error` means the checker rejects it under its format rules. `warn` flags a
heuristic concern; it does not prove poorer agent performance. `--strict` makes
warnings fail too. The [project assessment](docs/README.md) records known
implementation and evidence limits.

The pair worth understanding is `trigger-shape` and `unknown-field`. Descriptions
commonly guide skill selection, but loading and invocation depend on the client.
The example below illustrates the checker's writing heuristic; it is not proof
that a client ignores every other instruction source.

```yaml
# what the model sees:        a capability statement it cannot act on
description: Secure credential access with tiered providers and output masking
# what it never sees:         the words that would actually have fired it
trigger: secrets, credentials, database password, api key, aws secrets
```

Both of those are one edit apart from correct. Neither is visible without a
checker.

## Install

```bash
git clone https://github.com/cooneycw/skillc.git
cd skillc
uv sync --extra dev
uv run skillc selftest
```

## Exit codes

| code | meaning |
|---|---|
| `0` | checked, and clean |
| `1` | findings at `error` severity (or any finding under `--strict`) |
| `2` | could not check - bad path, or **no `SKILL.md` found** |

The last one is deliberate. A scan that found nothing to scan must not report
the same thing as a scan that found nothing wrong.

## Adding a rule

A rule is three things: a function, a known-bad fixture, and a known-good one.

```
skillc/checks.py                          the function, registered in RULES
controls/<rule-id>/bad/<skill>/SKILL.md   an input it MUST fire on
controls/<rule-id>/good/<skill>/SKILL.md  an input it MUST stay silent on
```

`skillc selftest` and the test suite both pick the pairing up automatically. If
you cannot name the input that makes your new rule fire, you have just learned
the rule is not ready - which is the cheapest possible moment to learn it.

See [ADR 0001](docs/decisions/0001-every-check-ships-a-redcase.md) for the bound:
this applies to rules, whose verdicts are consumed by a decision that will not
independently re-derive the fact. It does not extend to every internal helper.

## Proposed evaluation levels

The organizing idea is a difficulty ladder. Higher levels require more capable
work, not merely more files or a longer prompt. Every level checks the delivered
result and preserves relevant protections from earlier levels.

| Level | Capability | Example challenge |
|---|---|---|
| 1 - Basic execution | Complete one clear, bounded task | Fix a small defect and pass independent acceptance tests |
| 2 - Constraint handling | Satisfy several requirements without breaking a stated boundary | Fix the defect without changing the public interface or adding a dependency |
| 3 - Integration | Make connected parts work together | Change a helper and its caller, then prove the installed path works |
| 4 - Workflow judgment | Carry a task from intent to an honest completion decision | Preserve the approved plan, review new files, and report unmet acceptance accurately |
| 5 - Resilient coordination | Preserve correctness when work is interrupted or shared | Resume after interruption, handle unavailable tools, or reconcile two workers' changes |
| 6 - Adaptive delivery | Solve unfamiliar work with incomplete information | Diagnose a new repository, challenge a flawed proposed approach, and deliver within constraints |

These are proposed difficulty bands. Pilot results must establish whether tasks
actually become harder; the labels alone cannot establish that.

Before any agent trial, readiness checks establish that the environment,
installation and grader work. Those checks are prerequisites, not an agent skill
level. An unavailable environment is not a failed reasoning test, and an empty
run is not a pass.

Experiments will compare a selected collection with a prior revision, another
collection or a minimal baseline under matched conditions. CPP is the first
intended subject. Known-bad artifacts or deliberately degraded variants must demonstrate that the grader can detect the
failure it claims to detect. Equal results mean **no benefit demonstrated on
those tasks**, not proof that the skill has no value.

Progress will be reported as a profile: qualified levels, success by scenario,
honesty of completion claims, human interventions, time and cost. A hard task
passed once does not erase failures on easier tasks or establish a reliable level.

## Proposed first milestone

Repair the documented static-checker trust gaps, then use the existing CPP
small-fix pilot to prove an independent grader and known-good/bad controls.
Define [interface contracts](docs/specs/evaluation-facility/interfaces.md) before
qualifying a replaceable execution backend. Then implement one disposable Docker trial
against a pinned CPP snapshot and retain all evidence. Prove the same interfaces
with a second small collection before claiming generic support. Expand to Level 2
after the first experiment is reproducible and its grader discriminates.

The [implementation plan](PLAN.md) sequences delivery against the specification;
the [review agenda](docs/specs/evaluation-facility/review.md) identifies open choices. No
runtime, paid model trial, CPP change or upstream CI integration is introduced
by this planning update.

See the [project assessment and research](docs/README.md) for the proposed role
of skillc in a focused CPP harness, verified implementation gaps, and a suggested
first behavioral milestone.

The [eval entrypoint](evals/README.md) links to the current contracts. Earlier
runner commands and example schemas were unverified research and have been
retired from the active instructions.

## Prior art

The argument that skills deserve software's disciplines - static analysis, evals,
security testing, dependency management, observability - is Guy Podjarny's, from
*Skills are the new Code* (AI Native DevCon London, June 2026). `skillc` is an
attempt at the first of those five, built so that it can be trusted.

The rules about descriptions, triggers, progressive disclosure and pruning draw
on Matt Pocock's [writing-for-agents](https://github.com/mattpocock/skills), which
is the best written account of what makes an agent-facing document work. Pinned
provenance: [`docs/research/mattpocock-skills-lessons.md`](docs/research/mattpocock-skills-lessons.md).

Field constraints come from the [Agent Skills
specification](https://agentskills.io/specification).

## License

MIT.
