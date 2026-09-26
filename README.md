# skillc

**Skills are the new code. Code doesn't ship uncompiled.**

A skill is a unit of software now. It gets authored, versioned, installed,
depended on, and it rots. What it does not get is a build step: there is nothing
between writing a `SKILL.md` and shipping it that can refuse. `skillc` is that
missing stage.

skillc also ships an independent evaluation facility for collections of
scaffolding skills, being built incrementally toward **goal-based tasks at
progressively harder levels**. Accessible projects become test subjects
through supported adapters, exercised in disposable environments: Claude
Power Pack (CPP) was the first subject (#7), and
[mattpocock/skills](evals/subjects/mattpocock-skills/SUBJECT.md) is the
second, proving the adapter needed no change for an independently authored
collection with a different layout (#11).

**Runs wherever it is installed.** skillc assumes no dedicated machine and no
fleet: a trial uses whatever Docker (or other backend) is already on the
user's own machine. An external container platform may supply an optional
backend behind the same seam - the reference backend (skillc driving Docker
directly) is what closes #10 and remains fully functional on its own, never
required. See [ADR 0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md).

<a id="status"></a>

**Status:** the static checker, native materialization (`skillc materialize`),
the trial controller, the independent verifier and the execution-backend seam
all exist and are exercised by real evidence (see the machine-readable table
below, checked in CI against [`docs/milestones.json`](docs/milestones.json),
#73). The task levels beyond Level 1 and the full behavioral comparisons
described later in this README remain a documentation-only proposal. See the
[specification](docs/specs/evaluation-facility/spec.md),
[architecture decision](docs/decisions/0002-independent-goal-driven-evaluation.md) and
[PLAN.md](PLAN.md) for the design and delivery sequence.

<!-- milestones:start (checked against docs/milestones.json, #73) -->
| Milestone | State |
|---|---|
| 0.1.0 - static checker | closed |
| 0.2.0 - real Docker trial end to end (#10) | open |
| 0.3.0 - second independent collection (#11) | open |
<!-- milestones:end -->

**Version:** `0.1.0` (checked in CI against the package version, #73)

<!-- commands:start (checked against the real argparse parser, #73) -->
```bash
skillc check ./skills         # check a collection after validating the rules
skillc selftest                # prove every rule can still report the other verdict
skillc check-records <path>    # refuse evaluation records the contract rejects
skillc materialize <subject>   # install a declared skill surface and prove what a client lists
skillc rules                   # what it checks, and at what severity
skillc leak-check <path>       # refuse a tree or bundle carrying a machine identity
```
<!-- commands:end -->

`check` also takes `--manifest <plugin.json>` to scope a scan to a plugin
manifest's declared skills, reporting the undeclared remainder as a count
instead of mixing shipped and draft skills into one total (#53), and `--json`
(below) to print one stable-schema document instead of the human report.

The existing static checker has zero runtime dependencies and requires Python
3.11+. The evaluation facility's materialization, controller and verifier
pieces need `git` and, when installed, `codex` or another supported client;
the full behavioral-comparison proposal will have separate execution
requirements again.

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

Six verdicts fail the run:

| verdict | meaning |
|---|---|
| `BLIND` | the rule stayed silent on a known-bad input |
| `NOISY` | the rule fired on its known-good input |
| `EMPTY` | a control directory holds no input, so that side proves nothing |
| `UNPARSED` | a control input does not parse, so the parser - not the rule - decided it |
| `UNPROVEN` | no committed control exists, so nothing has shown the rule can fail |
| `MALFORMED` | a `targets/<target>/` case names an unknown target, or neither `bad/` nor `good/` | 

A rule whose behaviour varies by `--target` (`trigger-shape` is the first, #51)
also commits `controls/<rule-id>/targets/<target>/{bad,good}/`: the base pair
above always runs at the default target and cannot see a target-dependent
regression, so `skillc selftest` reports each such case on its own line, e.g.
`ok trigger-shape[claude-code] green on good (1)`. A target case may commit
only one side when the other is already proven elsewhere (the base pair, or a
sibling case) - but a side it DOES commit is held to the same discipline as the
base pair: empty is `EMPTY`, not skipped.

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
error  invocation-consistency  Claude Code's disable-model-invocation and Codex's agents/openai.yaml agree  [target: claude-code]
error  frontmatter        frontmatter is present and parses
```

Frontmatter is read by a **documented subset of YAML**, not a YAML
implementation: block mappings and lists, single-line and quoted values, and `|`/`>`
block text. Anything else is an error that says whether real YAML also rejects it
or `skillc` simply does not read it. `name` and `description` must be non-empty
strings. Which fields "load" depends on the client, so the field rules are scoped:
`--target portable` (the default, the Agent Skills specification) or
`--target claude-code` (plus Claude Code's documented extensions, read on a stated
date). See [docs/frontmatter.md](docs/frontmatter.md). `trigger-shape` itself runs
under every target but reads the active one: it stays silent under `claude-code`
on a `disable-model-invocation: true` skill, whose description the model never
reads to decide anything, and still fires under `portable`, where another client
may auto-select on it regardless (see [frontmatter.md](docs/frontmatter.md#trigger-shape-and-user-invoked-skills)).

`invocation-consistency` compares two per-client invocation declarations: Claude
Code's `disable-model-invocation` (`SKILL.md` frontmatter) and Codex's
`policy.allow_implicit_invocation` (`agents/openai.yaml`, read from
[mattpocock/skills](https://github.com/mattpocock/skills)'s own convention on
2026-09-26, at [`c55ee46`](https://github.com/mattpocock/skills/tree/c55ee46073ed923f86ce59a5eb3b6d895095d1b7) -
not a Codex specification, since that file is an upstream convention). It fires
only when a skill carries `agents/openai.yaml` and the two disagree on whether
the model may invoke it without being asked; silent when the file is absent.
Scoped to `--target claude-code`, like `claude-code-field`: the portable
specification has no invocation control for the comparison to be about.

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

## Contributing

`main` is branch-protected: the `ci/woodpecker/pr/ci` check is required and
must be up to date with `main` before merging (strict mode), and force-push
and branch deletion are blocked. Before opening a PR, run
`uv run skillc selftest && uv run pytest && uv run ruff check . && uv run mypy`
and `uv run skillc leak-check . --exclude controls/leak-check/bad --exclude
tests/test_leak.py --exclude ci/leak-check-control.sh` (the excludes skip this
repo's own seeded-bad fixtures, which a bare scan would otherwise report as
findings - see CI's `leak-check` step for the authoritative list); a PR that
changes `skillc/` also needs a new entry under `CHANGELOG.md`'s `[Unreleased]`
section, or a `Changelog-exempt: <reason>` trailer on its last commit. See
#73's CI steps (`changelog-check`, `readme-drift`) for what else is checked
automatically.

## Exit codes

| code | meaning |
|---|---|
| `0` | checked, and clean |
| `1` | findings at `error` severity (or any finding under `--strict`) |
| `2` | could not check - bad path, or **no `SKILL.md` found** |

The last one is deliberate. A scan that found nothing to scan must not report
the same thing as a scan that found nothing wrong.

## Machine-readable findings, and installing the packaged checker

`skillc check --json` prints one stable-schema JSON document instead of the
human report, for a script to consume without parsing terminal prose - keyed
on the rule's stable id, never on its prose `detail`. `scripts/repair_hint.py`
is the smallest useful consumer: it reads the JSON and prints one line of
repair guidance per finding. `ci/clean-install-check.sh` proves the packaged
checker, installed from a built wheel into a clean environment, still
discriminates good from bad, refuses to run `selftest` without its own
committed redcases (fixture data, not shipped) and correctly certifies when a
fresh copy of them is supplied. Retains a build/install identity record and
carries its own committed negative control. Details, schema and limits:
[docs/findings.md](docs/findings.md).

## Leak check: no machine identities

skillc is public, and it produces evidence bundles, ledgers and receipts from
real trial runs. Nothing committed, reported or graded - a file, a PR, a
produced bundle - may carry the operator's machine identities: a
home-directory path, a `uid=`/`gid=` number, a private (RFC 1918) IPv4
address, or a hostname from a locally-configured deny-list. The owner's
public email and GitHub handle are the stated exceptions. See
[ADR 0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md).

```bash
skillc leak-check .                          # scan a tree or a produced bundle
skillc leak-check . --exclude some/fixture   # a directory that seeds fake leaks on purpose
skillc leak-check . --denylist hosts.txt     # a local, untracked file of real hostnames to catch
```

Exit `1` on a finding, `2` on a nonexistent path or a configured deny-list
that does not resolve, `3` when nothing could be scanned at all (an empty
directory, or every file undecodable) - an unscannable target is UNKNOWN,
never clean. A hostname not on the deny-list, a username anywhere other than
a `/home/`/`/Users/` path, a public IPv4 or any IPv6 address, and a symlink
pointing outside the scanned tree are stated limits, not silent gaps - see
`skillc/leak.py`'s module docstring. Wired into CI over the whole repository
tree, with its own seeded negative control (`ci/leak-check-control.sh`) and a
committed check that the seeded values cannot collide with a realistic
worktree or container-name path.

## Adding a rule

A rule is three things: a function, a known-bad fixture, and a known-good one.

```
skillc/checks.py                          the function, registered in RULES
controls/<rule-id>/bad/<skill>/SKILL.md   an input it MUST fire on
controls/<rule-id>/good/<skill>/SKILL.md  an input it MUST stay silent on
```

If the rule's verdict on the SAME input varies by `--target`, also commit
`controls/<rule-id>/targets/<target>/{bad,good}/<skill>/SKILL.md` for each
target where the behaviour differs from the base pair above - one side is
enough when the other is already proven. `skillc selftest` and the test suite
both pick these up the same way it picks up the base pair.

`skillc selftest` and the test suite both pick the pairing up automatically. If
you cannot name the input that makes your new rule fire, you have just learned
the rule is not ready - which is the cheapest possible moment to learn it.

See [ADR 0001](docs/decisions/0001-every-check-ships-a-redcase.md) for the bound:
this applies to rules, whose verdicts are consumed by a decision that will not
independently re-derive the fact. It does not extend to every internal helper.

## Grading tiers (proposed, #69)

The verifier's deterministic grader (structural and outcome checks, no model
call) is the floor and always runs. Two further tiers are proposed, using
[`mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion) - its
own public repository, with no dependency back on a sibling platform - as the
model-judge mechanism:

1. **Deterministic** - today's grader, no model call, always runs.
2. **Same-model judge** - the model that produced the candidate's work.
3. **Independent judge** - a different model, cross-client by default (Codex
   judges Claude Code's work and the reverse), via `mcp-second-opinion`.

**When judges are enabled, every enabled tier grades the trial together and
produces its own verdict** - never averaged, weighted or overridden. The
result carries a per-criterion same-model-vs-independent disagreement record,
so the self-grading bias becomes a measured quantity across runs instead of
only a stated limitation. An unavailable judge makes only its own tier
`unavailable`; the others still report. The deterministic tier keeps working
with no judge installed, and the judge integration is never a core import -
it speaks MCP to the server as an external process, or ships as an optional
extra. Full rulings: [ADR 0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md).
Enabling paid judge tiers needs an authorized budget first (#12) - filing an
issue or merging a design document never authorizes a paid model call.

**Not yet delivered.** #10's grading-boundary work (`skillc/verify.py` grading
through an `ExecutionBackend`) leaves the judge seam open but does not build
tiers 2 and 3; that is #69's own acceptance.

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
collection or a minimal baseline under matched conditions. CPP was the first
subject (#7) and mattpocock/skills the second (#11), each with committed
materialization evidence; no paid trial has been run against either. Known-bad
artifacts or deliberately degraded variants must demonstrate that the grader
can detect the failure it claims to detect. Equal results mean **no benefit
demonstrated on those tasks**, not proof that the skill has no value.

Progress will be reported as a profile: qualified levels, success by scenario,
honesty of completion claims, human interventions, time and cost. A hard task
passed once does not erase failures on easier tasks or establish a reliable level.

## First milestone: mostly delivered; the Docker backend and Level 2+ remain proposed

The static-checker trust gaps are repaired (#2, #3), the CPP small-fix pilot
proved an independent grader with known-good/bad controls (#5, #9), and the
[interface contracts](docs/specs/evaluation-facility/interfaces.md) are
defined. `skillc materialize` proves native installation against a real
client for two independently structured collections (#7, #11 - the second
needing no adapter change). The `ExecutionBackend` protocol (#10's seam), a
lifecycle driver that exercises the full prepare/install/execute/confirm/
export/destroy/finalize sequence, and an optional-backend grading path in
`skillc/verify.py` all exist and are tested - **against a fake,
host-subprocess backend**. `skillc/docker_backend.py`, the real Docker-backed
implementation the seam was built for, **does not exist yet**; that is what
closes #10 (see the milestone table near the top of this README). Expanding
to Level 2 and beyond, and running a paid trial, remain proposed work: no
model call has been made against any subject yet, and none is authorized by
anything in this repository (#12).

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
