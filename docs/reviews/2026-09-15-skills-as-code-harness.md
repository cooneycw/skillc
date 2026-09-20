# skillc as a foundation for a focused CPP harness

- Date: 2026-09-15
- Status: Review and recommendation; implementation work is not authorized by this document
- Scope: skillc source, tests, controls, ADR and eval proposal; selected CPP
  lifecycle documentation; the [research reports](../README.md#research-and-prior-reviews)
- Review method: source inspection, existing quality checks, disposable local
  probes, and verification against official Agent Skills and Claude Code docs

## Recommendation

Proceed with skillc as a small reusable validation component in a more focused
Claude Power Pack (CPP). Make the next substantial investment a behavioral
demonstration connecting skill instructions to development outcomes.

Suggested CPP positioning:

> A development harness that turns agreed intent into changes with verifiable
> acceptance evidence, using versioned and tested skills.

skillc is a credible starting point because it has a compact implementation,
committed known-good and known-bad fixtures, explicit failure on an empty scan,
and a bounded negative-control requirement. Its eval proposal also recognizes
that static validity cannot establish whether a skill improves agent behavior.

The strategic opportunity is the connection between instructions and demonstrated
delivery. A successful narrowing should reduce default instructions,
dependencies, and owner intervention while preserving reliable outcomes.

## What the research contributes

The [skills audit](../research/skills-are-the-new-code-cpp-audit.html) identifies
an imbalance: CPP checks substantial supporting software while its command
instructions lack comparable behavioral evidence. skillc begins to address the
instruction surface, but static checks alone leave that central gap open.

The [harness strategy](../research/harness-strategy-recommendation-2026-09-14.html)
supports keeping useful existing controls and bounding their scope. The
[delivery-quality assessment](../research/issue-quality-assessment-2026-09-14.html)
provides the practical objective: reduce locally convincing changes that fail
when used together. Increasing a rubric score is only a proxy for that outcome.

Treat these documents as dated research and analysis. Their comparative scores,
market claims, and historical measurements were not all independently reproduced
in this scan. Some findings have already prompted implementation: for example,
the current CPP tree contains a knowledge-lifecycle policy, despite an earlier
SDD report identifying its absence.

## Two specifications, different responsibilities

| Specification | Question |
|---|---|
| Agent Skills format | Is this skill structured correctly for its target? |
| Development contract | Did the agent deliver the requested outcome within its constraints? |

skillc currently addresses the first. CPP's `docs/agents/issue-contract.md`
already addresses the second by separating outcome, constraint, acceptance,
proposed approach, and assumption. Those distinctions do not require five
mandatory headings; a small issue can carry a small contract.

The connection to build is:

```text
Contract -> skill-guided execution -> observable acceptance
         -> evidence -> regression case
```

For example, validating the frontmatter of a finish skill helps packaging.
Demonstrating that it refuses to claim completion while an acceptance item is
unmet helps delivery. Both are useful, but they establish different facts.

## Proposed product boundary

| Component | Responsibility |
|---|---|
| skillc | Format validation, explicit target compatibility, rule controls, machine-readable findings |
| CPP core | Proportional contracts, execution lifecycle, acceptance verification, completion evidence |
| Behavioral evals | Measure whether skills improve outcomes and respect boundaries |
| Optional integrations | CI providers, secrets backends, browser tools, deployment and review services |

Keep existing integrations available while making the default path small. Begin
with the contract-to-completion workflow and expand its evaluated coverage when
the evidence warrants it. This recommendation does not call for an immediate
repository-wide migration or removal of existing integrations.

The [Agent Skills specification](https://agentskills.io/specification#validation)
already points to `skills-ref` validation. skillc's differentiation should be a
quality gate with demonstrated controls and a connection to behavioral evidence.
Static format validation is an existing capability in the ecosystem.

## Verification performed

The existing repository verification passed:

```text
uv run skillc selftest: 6/6 rules discriminate
uv run pytest:         12 passed
uv run ruff check .:   passed
uv run mypy skillc:    passed, 4 source files
```

After selftest, scanning CPP's `.claude/skills` reproduced the README example:

```text
18 skills checked, 36 errors, 37 warnings
```

This confirms the current checker's output on that corpus. It does not establish
that all warnings predict behavioral failure or that strict format violations
prevent loading in every harness. No paid agent eval or full CPP lifecycle run
was performed. No source files were changed during the assessment.

## Verified implementation gaps

These findings matter to the claim that skillc can be trusted as a gate. The
existing passing suite does not cover them. Probes used temporary directories
and in-process monkeypatching; committed fixtures were not edited.

### 1. Parser and required-field validation disagree with valid types and syntax

Affected: `skillc/spec.py:parse_frontmatter`, `Skill.get`, and
`skillc/checks.py:_required_fields` / `_name_spec`.

A valid folded description is rejected:

```yaml
name: valid-folded
description: >
  Use when checking skills.
```

Observed result: `frontmatter` error, `line 4: expected 'key: value'`.

Conversely, these invalid required-field values produce no findings:

```yaml
name:
  nested: value
description:
  nested: value
```

The keys exist, but `Skill.get` returns `None` for their mapping values, and the
rules skip them. Follow-up: validate required field types explicitly and make
the supported YAML syntax consistent with the promised compatibility. A custom
restricted syntax must not be presented as the full external specification.

### 2. Selftest can certify a rule without proving its discrimination

Affected: `skillc/cli.py:cmd_selftest` and `skillc/checks.py:run`.

Two independently reproduced cases returned exit 0 and reported 6/6:

- Copy the controls to a temporary directory, then remove the `SKILL.md` from
  `name-spec/good`, leaving the directory present. An empty good population
  passes because it produces no findings.
- Restore the controls, replace the `name-spec` rule with a function returning
  no findings, and make its bad fixture malformed frontmatter. The parser's
  `frontmatter` finding is counted as evidence that `name-spec` fired.

Follow-up: require nonempty, successfully parsed fixture populations for these
rules and require findings from the intended rule. Parser controls should have
their own explicit expectations. Extend the selftest's negative controls to
cover both failures.

### 3. Unknown rule selectors silently check no rules

Affected: `skillc/cli.py:main` and `skillc/checks.py:run`.

`skillc check <skill-directory> --rule typo` returns exit 0 with zero findings
for a parseable skill. Follow-up: reject unknown rule IDs before scanning.

### 4. Harness compatibility warnings overclaim

Affected: `skillc/spec.py:HARNESS_FIELDS` and
`skillc/checks.py:_unknown_field`.

A skill containing `user-invocable: false` receives the warning that the field
is not loaded by any harness. Claude Code documents that field, along with
other extensions absent from the current allowlist.

Follow-up: distinguish portable format constraints from explicit, versioned
target profiles. Diagnose unsupported fields for the selected target rather
than making a universal claim. See the
[Claude frontmatter reference](https://code.claude.com/docs/en/skills#frontmatter-reference).

## Claims to calibrate

- A description matching `Use when...` satisfies a writing heuristic. It does
  not prove correct triggering. Measure both intended invocation and unwanted
  invocation, and account for skills explicitly configured for manual use.
- Equal with/without scores mean no measured benefit on those cases. They do
  not establish universal uselessness. Coverage, run variability, ceiling
  effects, cost, and latency can change the interpretation.
- A successful skill invocation is not the same as successful delivery. Keep
  trigger graders separate from outcome graders.
- A known-bad fixture proves a particular distinction. It does not by itself
  establish complete coverage of a rule's stated domain.

## Proposed first milestone

Prove one small contract-to-completion workflow before expanding the static
rule catalog.

1. Fix the validation and selftest gaps above.
2. Select a bounded CPP workflow, such as acceptance verification at finish.
3. Build cases for a completed change with valid evidence, passing tests with
   an unmet acceptance requirement, stale evidence, and pressure to declare
   completion prematurely.
4. Compare runs with and without the skill under controlled conditions. Check
   the graders against deliberately incorrect outcomes as well as correct ones.
5. Record acceptance accuracy, false completion claims, human interventions,
   and cost. Retain failing cases as regression evidence.

Claude's installed CLI exposes plugin evals, and its
[official documentation](https://code.claude.com/docs/en/plugin-evals) supports
with/without comparisons. Prefer a thin integration with that runner. Validate
the case schema in `evals/README.md`, including proposed `mustfail` semantics,
against the actual installed runner before treating it as executable. The
example schema was not run during this review.

Success for this milestone is a demonstrated improvement on a clearly defined
delivery failure without unacceptable cost or false refusals. If the comparison
does not establish benefit, revise the skill or measurement before widening the
framework.

## Finding disposition

At review time, the relevant CPP findings about ungated skill checks, skill
names, and trigger fields were already recorded in its open
[Nit Store](https://github.com/cooneycw/claude-power-pack/issues/864), so no
duplicate comments were added. skillc had no open issues and therefore no open
Nit Store. Its newly verified findings were not recorded on GitHub; they are
preserved in this assessment for follow-up.
