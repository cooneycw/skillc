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
decide which skill or file to degrade (#150-A) or wire a degraded subject
into a live discriminating run (acceptance item 3) - it only makes one
buildable and recorded, from the command line, with a receipt an operator or
a later step can read.
