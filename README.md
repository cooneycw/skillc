# skillc

**Skills are the new code. Code doesn't ship uncompiled.**

A skill is a unit of software now. It gets authored, versioned, installed,
depended on, and it rots. What it does not get is a build step: there is nothing
between writing a `SKILL.md` and shipping it that can refuse. `skillc` is that
missing stage.

```bash
skillc check ./skills     # refuse to build skills the spec rejects
skillc selftest           # prove every rule can still report the other verdict
skillc rules              # what it checks, and at what severity
```

Zero runtime dependencies. Python 3.11+.

---

## The problem, concretely

Run it against a real 18-skill collection, written by someone careful, in a
repository with a CI pipeline, a lint gate, a type checker and a test suite:

```
skillc: 18 skill(s) checked, 36 error(s), 37 warning(s)
```

Every single `name` violated the Agent Skills specification. Every `description`
stated a capability rather than a triggering condition, so the model had nothing
to decide *when* to fire on. And every skill carried its trigger vocabulary in a
`trigger:` frontmatter key that no harness loads - the words were written, and
inert.

None of this was sloppiness. It was invisible, because nothing was looking.

## The founding constraint

An instrument that cannot fail is not evidence. A green from a blind check and a
green from a working one look identical, and the difference is only ever found
later, by whoever was relying on it.

So every rule in `skillc` ships a committed **redcase**: an input that makes it
report the other verdict. `skillc selftest` runs each rule against its own
known-bad and known-good pair:

```
$ skillc selftest
ok       name-spec        red on bad (2), green on good
ok       required-fields  red on bad (1), green on good
ok       trigger-shape    red on bad (1), green on good
ok       unknown-field    red on bad (1), green on good
ok       body-budget      red on bad (1), green on good
ok       ref-depth        red on bad (1), green on good

skillc selftest: 6/6 rule(s) discriminate
```

Three verdicts fail the run:

| verdict | meaning |
|---|---|
| `BLIND` | the rule stayed silent on its own known-bad input |
| `NOISY` | the rule fired on its known-good input |
| `UNPROVEN` | no committed control exists, so nothing has shown the rule can fail |

`UNPROVEN` is the one that matters. A rule with no control is not treated as
passing, because absence of a control is not evidence of correctness.

The selftest is itself under a negative control. A test in the suite blinds a
rule on purpose and asserts the harness says so - because a selftest that cannot
fail proves nothing about the rules it blesses.

## What it checks

```
$ skillc rules
error  name-spec        name is spec-legal and matches its directory
error  required-fields  required frontmatter is present and in range
warn   trigger-shape    description says when to fire, not just what it does
warn   unknown-field    no content parked in a field nothing loads
warn   body-budget      SKILL.md body stays inside the line budget
warn   ref-depth        references stay one level deep
```

`error` means the specification rejects it. `warn` means it will load and quietly
underperform. `--strict` makes warnings fail too.

The pair worth understanding is `trigger-shape` and `unknown-field`. The
`description` is the only always-loaded pointer a skill has, and its wording is
what decides whether a model-invoked skill fires at all. A skill whose trigger
words live anywhere else is carrying them somewhere nothing reads:

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

## What's next

Static analysis answers whether a skill is *well-formed*. It cannot answer the
question that actually decides whether a skill was worth writing: **does it change
what the agent does?**

That needs a behavioural eval, and specifically an ablation - the same task run
with the skill loaded and without it. If the two score the same, the skill is
doing nothing, however clean its frontmatter. Claude Code ships the runner
(`claude plugin eval --ablation with-without`); the gap is that almost nobody
publishes cases. See [`evals/README.md`](evals/README.md) for the shape and the
`mustfail` idea, which is the redcase at the eval layer.

## Prior art

The argument that skills deserve software's disciplines - static analysis, evals,
security testing, dependency management, observability - is Guy Podjarny's, from
*Skills are the new Code* (AI Native DevCon London, June 2026). `skillc` is an
attempt at the first of those five, built so that it can be trusted.

The rules about descriptions, triggers, progressive disclosure and pruning draw
on Matt Pocock's [writing-for-agents](https://github.com/mattpocock/skills), which
is the best written account of what makes an agent-facing document work.

Field constraints come from the [Agent Skills
specification](https://agentskills.io/specification).

## License

MIT.
