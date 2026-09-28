# Operator-expressible degraded subjects

- Status: Implemented as `skillc degrade-subject` (`skillc/degrade.py`), #150 acceptance item 2
- Date: 2026-09-28
- Governing documents: [materialization](materialization.md), issue #150 ("Why this is needed now", gap 2)

## What it does

Before this, a degraded CPP subject - "the same collection with one skill
mutated or removed" - was expressible only two ways, neither of them
operator-usable: a local `checkout=` existed as a Python/test parameter
(`collection_conformance.acquire_collection`, `demo.run_subject_demo`), never
a CLI flag; and a degraded skill set was expressible only by hand-editing a
non-default-branch revision into a `subject.json`, a path with no committed
test at all.

```
skillc degrade-subject <subject> (--checkout PATH | --revision SHA)
    [--remove-skill NAME]...
    [--remove-file SKILL:PATH]...
    [--override-file SKILL:PATH=LOCAL_FILE]...
    --out DIR
```

builds one, from two independent knobs:

- **the source**: a local snapshot directory (`--checkout`, exactly
  `materialize.acquire_snapshot`'s own convention - the same mechanism
  `materialize`/`exposure`'s own `--snapshot` flag already exposes), or an
  explicitly supported alternative revision on the subject's own locator
  (`--revision`, acquired the same way `materialize.acquire_git` acquires the
  subject's declared pin);
- **the mutation** (optional, and, since #150's own #150-A finding that one
  rule can be restated across several skills and duplicated scripts, NOT
  capped at one location): any combination of whole skills removed
  (`--remove-skill`, repeatable), single files deleted inside a skill
  (`--remove-file SKILL:PATH`, repeatable), and single files replaced with
  operator-prepared content (`--override-file SKILL:PATH=LOCAL_FILE`,
  repeatable). Never a byte-level in-place patch - an override always
  replaces a whole file, so "what changed" is always the (skill, path) pair,
  never a diff someone has to recompute. `receipt()`'s `mutation.locations`
  lists every one of them, in declaration order, so a mutation that missed
  one of several known locations is visible in its own statement rather than
  silently read as "the degraded subject".

Generic over which subject, skill or file: #150-A chooses what the Level-1
task actually needs; this module never branches on a name.

## The output is installable, not only descriptive

`--out DIR` writes TWO things, both required, never a receipt alone: `DIR/
receipt.json` and `DIR/skills/`, the degraded surface tree itself
(`persist_skills`). An earlier version wrote only the receipt - the degraded
tree lived under the disposable `--base` staging root and was discarded with
it, so the receipt described a tree nothing kept and nothing could ever run
(orchestrator review of #155). `DIR` must be empty or absent; a non-empty
`--out` is refused before anything is acquired, the same "do not build on
top of a partial or stale prior write" rule `pilot-run`'s own evidence export
applies.

`verify_persisted_skills(out, expected_digest)` is the check a runner MUST
make before installing a persisted tree: it re-derives `DIR/skills`' own
tree digest and refuses (`DegradationRefused`) unless it matches the
receipt's own `degraded.digest`. `persist_skills` writes plain files with no
integrity mechanism of their own, so nothing else stands between a tampered
or corrupted `skills/` directory and being silently installed as though it
were exactly what the receipt described.

## The recorded identity is never the pin

The result's `Source.revision` is always a
`degraded:mutated=<N>-location:<base kind>:<base revision>` label (or
`mutated=none` for a source-only degradation) - never a bare commit SHA,
never a bare `snapshot:<digest>` that could be mistaken for an ordinary,
undegraded acquisition. The label carries only a count, deliberately: the
full per-location statement belongs in the receipt, not squeezed into an
identity string. `receipt()` writes both identities side by side (`base`:
what this source would have reported undegraded; `degraded`: what it reports
now) plus `mutation.locations`, so a ledger entry or a paste-back can show
exactly what changed without a second acquisition.

## Refusals

- **Neither or both of `--checkout`/`--revision`.** Exactly one source.
- **An empty mutation.** Declaring a mutation with no removal and no edit at
  all is a caller error, refused before anything is acquired - use no
  mutation (omit every `--remove-*`/`--override-*` flag) for a source-only
  degradation instead.
- **A removal or edit names a skill absent from the collection** (never
  present in the surface, or present but excluded by `subject.select` -
  either way it was never going to be installed, so touching it would
  degrade nothing).
- **An edit names a file absent from the staged surface**, or whose `path`
  escapes its own skill's directory (`../`-style traversal).
- **A skill is both wholly removed and separately file-edited** in the same
  mutation - redundant and refused rather than silently applying one and
  ignoring the other.
- **An override's content is byte-identical to what is already there** - a
  no-op edit an operator almost certainly did not intend, and one that would
  otherwise silently leave the "degraded" surface unchanged at that location.
- **The degraded identity would equal the normal one.** Reachable with a real
  input: `--revision` equal to the subject's own pin, with no mutation at
  all - nothing here differs from an ordinary acquisition of the declared
  subject, so it is refused rather than reported as "degraded". A local
  snapshot is never caught by this: its acquisition KIND (`"snapshot"`)
  already differs from the subject's own git pin, so it is always a
  distinguishable identity even with no mutation.

## What this module does not do

It does not run an agent, install anything into a client home, or grade
anything - `collection_conformance.py` and `verify.py` own those. It cannot
verify that a mutation covers EVERY place a rule is stated - that needs
knowing the rule, which would break genericity - only that every location the
caller DID declare is real, non-redundant, and listed in the receipt; showing
that a set of locations is complete (e.g. against #150-A's own five-location
finding) is the caller's job, checked by comparing the receipt's
`mutation.locations` against an independently compiled list. It does not
decide which skill or file to degrade (#150-A).

**It wires into `collection-run` (150-B2), but does not itself decide when a
degraded arm is discriminating.** `skillc collection-run --degraded DIR`
(`skillc/cli.py`) re-verifies `DIR/skills` against its receipt
(`degrade.load_persisted_degraded`, which calls `verify_persisted_skills`)
before anything installs, and the resulting attempt reports the degraded
identity throughout - `CollectionAgentResult.revision`, the exported
`verified-result`'s `revision` field, everywhere - never the pin. This fixed
a real, pre-existing bug found while wiring it: `run_collection_agent_attempt`
read `acquired.subject.revision` (the DECLARED pin) unconditionally, for
EVERY run, degraded or not - the acquired source's own identity
(`acquired.source.revision`) was computed and then never read for this. A
degraded acquisition's `select` is dropped for install purposes
(`acquire_degraded_collection`): the original subject's `select` was already
applied once, by `degrade-subject` itself, when it validated a removal or
edit against the undegraded surface - re-applying it here would refuse the
very shape a removal produces, since `materialize.inventory` requires every
selected name still present. What actually installs is whatever the
degradation left, in full.

**The receipt is the authority over what installs, not a description of it.**
Dropping `select` means nothing else constrains which skills a persisted tree
may hold - so `load_persisted_degraded`'s digest check IS that constraint: it
is taken over the WHOLE `skills/` tree, so a directory added straight into
`DIR/skills` (never through `degrade-subject` at all, and so never named in
`receipt.json`'s `mutation.locations`) changes the digest exactly as a
tampered file would, and is refused the same way. Confirmed directly
(`test_load_persisted_degraded_refuses_a_tree_holding_a_skill_the_receipt_never_declared`),
not merely inferred from the tamper case.

**The revision fix and #157's `--evidence-role` guard depend on each other,
and the dependency is tested, not just stated.** The guard
(`docs/specs/evaluation-facility/behavioral-eval-export.md`) recognises a
degraded arm by `result.revision` starting with `degraded:` - a fact only
true because of the fix immediately above. `test_cli_degraded_export_is_
refused_by_default_role_and_published_with_control` runs a REAL `--degraded`
attempt (fake docker, fake codex client, `run_collection_agent_attempt`
unmocked) through `cli.main`'s own gating and export code, twice: the
default role is refused with nothing written; `--evidence-role control`
publishes. Confirmed as a red case by reverting the revision fix and
re-running: the default-role call then wrongly published (exit 0, a
`result-*.json` actually written) instead of being refused, because
`result.revision` read back as the bare pin (`"v1"`), which the guard's own
`.startswith("degraded:")` check does not recognise as anything to restrict.

Showing that a degraded arm's FAIL and a normal arm's PASS actually
discriminate (acceptance item 3) is still not this module's job - it needs a
Level-1 task and grader that make a specific skill necessary (#150-A) and a
live run this module cannot own.
