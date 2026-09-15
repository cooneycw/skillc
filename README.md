# skillc

**Skills are the new code. Code doesn't ship uncompiled.**

A skill is a unit of software now. It gets written, installed, depended on, and
it rots. What it does not get is a build step: there is nothing between writing a
`SKILL.md` and shipping it that can refuse. `skillc` is that missing stage.

```bash
skillc check ./skills     # refuse to build skills the spec rejects
skillc selftest           # prove every rule can still report the other verdict
skillc rules              # what it checks, and at what severity
```

## The founding constraint

An instrument that cannot fail is not evidence. A green from a blind check and a
green from a working one look identical, and the difference is only ever found
later, by someone relying on it.

So every rule in `skillc` ships a committed **redcase**: an input that makes it
report the other verdict. `skillc selftest` runs each rule against its own
known-bad and known-good pair and reports which rules actually discriminate.

```
ok       name-spec        red on bad (2), green on good
ok       required-fields  red on bad (1), green on good
ok       trigger-shape    red on bad (1), green on good
ok       unknown-field    red on bad (1), green on good
ok       body-budget      red on bad (1), green on good
ok       ref-depth        red on bad (1), green on good

skillc selftest: 6/6 rule(s) discriminate
```

A rule with no committed control reports `UNPROVEN` and fails the run. It is not
treated as passing, because nothing has shown it can fail.

## What it checks

| severity | rule | what it holds |
|---|---|---|
| error | `name-spec` | `name` is `[a-z0-9-]`, within 64 chars, and matches its directory |
| error | `required-fields` | `name` and `description` present and in range |
| warn | `trigger-shape` | the description says *when to fire*, not only what it does |
| warn | `unknown-field` | no content parked in a field no harness loads |
| warn | `body-budget` | `SKILL.md` body stays under 500 lines |
| warn | `ref-depth` | references stay one level deep |

`trigger-shape` and `unknown-field` are the pair that matter most in practice.
The description is the only always-loaded pointer, and its wording is what
decides whether a model-invoked skill fires at all. A skill whose trigger words
live anywhere else is carrying them somewhere nothing reads.

## Why these rules

Run against a real 18-skill collection written by someone careful:

```
skillc: 18 skill(s) checked, 36 error(s), 37 warning(s)
```

Every name violated the specification. Every description stated a capability
rather than a triggering condition. Every skill carried its trigger vocabulary in
a `trigger:` frontmatter key that no harness loads. None of this was visible,
because nothing was looking.

## Status

v0.1.0. Static analysis works and proves itself. Behavioural evals are next - see
[`evals/README.md`](evals/README.md) for the shape and
[ADR 0001](docs/decisions/0001-every-check-ships-a-redcase.md) for the bound on
what needs a committed control.

## Install

```bash
uv sync --extra dev
uv run skillc selftest
```

MIT licensed.
