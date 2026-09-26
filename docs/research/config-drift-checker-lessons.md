# config-drift-checker lessons and concept map

- Date: 2026-09-26
- Issue: [#38](https://github.com/cooneycw/skillc/issues/38)
- Decision: [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md) - no
  runtime dependency; config-drift-checker is a design reference only
- Source: [jameskomo/config-drift-checker at 0aca62b](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1),
  by [@jameskomo](https://github.com/jameskomo), plugin version 1.1.3, committed
  2026-09-26
- Licence: [FSL-1.1-Apache-2.0](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/LICENSE).
  Free to use and modify; not to be offered as a competing commercial service;
  each release becomes Apache-2.0 two years after publication
- Upstream format: its eval cases use the format of Anthropic's `claude plugin eval`
  runner, which config-drift-checker builds on. Credit for that format belongs to
  Anthropic, not to config-drift-checker or skillc

## What this document is

config-drift-checker is a Claude Code plugin and GitHub Action that turns an
agent setup (`CLAUDE.md`, skills, hooks) into eval cases, runs them against a
pinned baseline on every pull request and every Claude Code release, and reports
behaviour that moved. It answers a different question from skillc - "did anything
stop working since the baseline?" rather than "does this collection pass the
build, and does it improve outcomes under matched conditions?" - but several of
its ideas answer questions skillc's evaluation facility already has.

skillc does not run, import, wrap or vendor it. This document records which of its
ideas skillc takes, where each came from, how each is translated to skillc's
contracts, and which ideas skillc declines and why.

**Everything below is static reading** of the pinned source and of the artifacts
it publishes. No config-drift-checker code was executed by skillc. "Does X" means
"the pinned source is written to do X", not "X was observed". Paths are
repository-root relative at `0aca62b`.

Borrowing an idea listed here is allowed and expected. **Name this document, the
upstream project and the pinned commit** in the design note, spec section or ADR
that introduces it. Do not copy source, fixtures or prose beyond short attributed
quotations. The licence's non-compete clause is one more reason not to copy code;
attribution is required whether or not code is copied.

## Adopted concepts

| Concept | Upstream location (pinned) | skillc owner | Translation |
|---|---|---|---|
| Discovered versus invoked, with "invocation unknown" when a run has no transcript evidence | [`config-drift-checker/tools/eval-shim.mjs` L115-128](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-shim.mjs#L115-L128), [`config-drift-checker/tools/eval-report.mjs` L36-42, L252](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-report.mjs#L36-L42) | [#39](https://github.com/cooneycw/skillc/issues/39) | A declared observation per installed skill, with origin and coverage; incomplete coverage is UNKNOWN, never zero. Invocation is never outcome |
| A near-miss "must not trigger" case beside the positive trigger case | [`examples/komo-stack/evals/vue-request-does-not-trigger-skill`](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/examples/komo-stack/evals/vue-request-does-not-trigger-skill), [`spring-work-triggers-skill`](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/examples/komo-stack/evals/spring-work-triggers-skill) | [#26](https://github.com/cooneycw/skillc/issues/26) | Already in #26's scope. Upstream fails the case when the skill fires; skillc reports selection separately from outcome unless the case declares invocation a requirement ([spec section 5](../specs/evaluation-facility/spec.md#subject-acquisition)) |
| A deliberately degraded skill description as a detection control | [`docs/example-break/`](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/docs/example-break) | [#26](https://github.com/cooneycw/skillc/issues/26), [protocol section 2](../specs/evaluation-facility/protocol.md#2-comparison-arms) | The protocol's "Detection control" arm. State which property a variant proves: an explicit contradiction shows the instrument can go red, not that it is sensitive to subtle changes |
| Client and model release drift with the subject held fixed | [`README.md`](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/README.md), [`config-drift-checker/tools/release-watch.mjs` L2-12](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/release-watch.mjs#L2-L12) | [#40](https://github.com/cooneycw/skillc/issues/40) | A "Client/model drift" row in [protocol section 2](../specs/evaluation-facility/protocol.md#2-comparison-arms). No release watcher or scheduler is adopted |
| Per-case noise bands with escalations that stop a band hiding a real break | [`config-drift-checker/tools/eval-diff.mjs` L10-20](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-diff.mjs#L10-L20), [`config-drift-checker/tools/eval-classify.mjs` L109-120](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-classify.mjs#L109-L120) | Deferred to [#15](https://github.com/cooneycw/skillc/issues/15), recorded in [review.md](../specs/evaluation-facility/review.md#september-26-config-drift-checker-review) | Only as a predeclared policy over per-criterion outcomes across repeats, with a committed case where a real break inside the band still goes red |

## Considered and not adopted

| Upstream idea | Governing clause in skillc |
|---|---|
| Autonomous repair that edits the setup under test | [spec section 4](../specs/evaluation-facility/spec.md#4-scope-and-boundaries) excludes changes to a subject's checkout; #26 and #28 exclude subject edits and automatic reruns |
| Fractional case scores that average every grader | [records.md derivation](../specs/evaluation-facility/records.md#derivation): optional criteria never enter the status, and mandatory failures cannot be averaged away |
| Noise thresholds learned from observed history | [protocol section 7](../specs/evaluation-facility/protocol.md#7-aggregation-and-progression) needs a justified sampling plan after calibration; [PLAN section D](../../PLAN.md#d-extend-difficulty-from-observed-results) forbids silently changing standards after observing a score |
| A model judge in the default grading path | [interfaces.md](../specs/evaluation-facility/interfaces.md#what-validates-truthfulness): start with deterministic outcome checks; calibrated judges are later #9 scope |
| Status badges and a public drift index | [protocol section 7](../specs/evaluation-facility/protocol.md#7-aggregation-and-progression): no global rating or public badge by default |
| Grading from the transcript of the same run that produced the work | [interfaces.md](../specs/evaluation-facility/interfaces.md#what-validates-truthfulness) and #9: an independent verifier on a disposable copy. Acceptable for a maintainer watching their own setup; not for skillc's verified results |

## Traps the reading showed

- **Invocation by substring.** A skill counts as invoked in a case when any `Skill`
  tool input contains the skill's directory or name, lowercased
  ([`eval-report.mjs` L40](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-report.mjs#L40)).
  A short name such as `run` matches unrelated input. skillc's invocation
  observation (#39) keys on the receipt's installed identity, not on text.
- **A lenient parser defines "malformed".** A skill is malformed upstream only when
  a name or description cannot be extracted
  ([`eval-shim.mjs` L128](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-shim.mjs#L128)).
  At the pinned commit, `config-drift-checker/skills/repair/SKILL.md` is not valid
  YAML, yet it passes that check and Claude Code loads it. skillc's `frontmatter`
  rule refuses it, and PyYAML agrees. Reported upstream as
  [jameskomo/config-drift-checker#14](https://github.com/jameskomo/config-drift-checker/issues/14).
  "The client accepted it" and "it is valid" are different claims.
- **A pin that did not hold.** The published break's result records
  `"harness": "2.1.258", "harnessIsPinned": true` in its config and
  `"version": "2.1.273"` for the harness that ran
  ([`docs/example-break/aggregate-result.json` L6-17](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/docs/example-break/aggregate-result.json#L6-L17)),
  so two variables moved in one comparison. skillc's `ledger-binding` refuses a
  receipt whose client version differs from the ledger's plan.
- **Heuristic causes.** A low-scoring run with at most one turn and no tool use is
  labelled a likely refusal ([`eval-diff.mjs` L18-19](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-diff.mjs#L18-L19)),
  and the published repair summary cites the agent's own replies as the cause of
  a break. Both are useful leads. In skillc terms they are model-asserted or
  heuristic, and are labelled so rather than recorded as observed causes.

## The published receipts, read against skillc's standards

The upstream README links two artifacts as proof: a sabotage report
([`docs/example-break/report.html`](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/docs/example-break/report.html))
and a repair summary
([`docs/example-break/repair-summary.md`](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/docs/example-break/repair-summary.md)).
They are real and useful. Within skillc's evidence rules they establish less than
their headline:

- The sabotaged description ends "Do NOT use for Java, Spring Boot, or backend
  work", and the agent obeyed it. That is a valid detection control: it shows the
  trigger case can go red. It does not show sensitivity to subtle drift.
- The repair restored the file to be byte-identical to `HEAD`, so a known-good
  version was available to it. It demonstrates the red, repair, re-run loop, not
  repair of a drift with no known-good version.
- Two of the four regressed cases were re-verified, at two runs each; the summary
  says the full suite should be re-run before merge.

## Evidence and limits

Every statement here comes from reading the pinned source and its published
artifacts on 2026-09-26. The only execution was skillc's own: `skillc check` on
the upstream skills directory, and PyYAML over the 35 upstream Markdown files that
carry frontmatter. Nothing here claims how config-drift-checker behaves at run
time, and nothing here is a review of its security or of its other features.
