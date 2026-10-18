<!-- flow-run n=1 id=0df21c38590e4ab7931901cde0b98bfe -->
## Run 1 - issue #439 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #439
- Read at:      2026-10-17T19:46:34Z
- updatedAt:    2026-10-17T19:46:07Z   (context only - moves on comments and labels)
- Body digest:  41e03f21b771c295e844d336e15984a4d281205b94e5f31169dc900a1cf5fa96   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2889 of 2889 (cap 16384)

### Body as read
## Problem

Every PR that touches `skillc/` adds its entry at the top of `CHANGELOG.md`'s single `## [Unreleased]` section. So after each merge to `main`, every queued branch conflicts on the same lines. On 2026-10-17 this aborted several lock-1 holds and cost queue slots (#432 twice, #414 once). The details are in the Nit Store: https://github.com/cooneycw/skillc/issues/20#issuecomment-6239283992

The workaround in use is that hold scripts auto-resolve a CHANGELOG-only conflict by keeping both sides. `CHANGELOG.md merge=union` would do the same in git.

## Why union (or keep-both) is not safe here: measured

Probe on git 2.43 in temp repos: two branches each insert a multi-line bullet at the top of Unreleased, in the real format (2-space continuation lines, no blank lines between bullets).

| Case | Without the attribute | With `merge=union` |
|---|---|---|
| distinct bullets | CONFLICT | clean, both intact |
| bullets sharing a middle line | | clean, both intact |
| bullets sharing their **first** line | | clean but **corrupt**: the shared line is kept once, so one heading sits over both bodies |
| bullets sharing their **last** line | | clean but **interleaved**: the shared tail is emitted once after B, so A loses its last line |

The hand "keep both" auto-resolve operates on the same refined conflict hunks, so it has the same first/last-line exposure.

`ci/changelog_check.py` would accept both corrupt results. It only requires that the PR adds at least one non-blank line to Unreleased versus the merge-base, as a set of stripped lines. It checks nothing about bullet boundaries, duplication or interleaving.

## Audit of today's merges: clean

For each PR merged on 2026-10-17 (#403, #407, #409, #411, #413, #415, #417, #420, #421, #422, #423, #425, #428, #429, #430, #433, #435, #438), every block of `CHANGELOG.md` lines its squash commit added appears **exactly once, contiguously** in `main`'s file at `f0fe0b4`. That covers 15 PRs. #415, #421 and #423 touched no CHANGELOG, confirmed from their file lists.

The audit's own negative controls were each flagged:
- a copy with #438's heading removed;
- a copy with #438's last line moved after the next bullet;
- a copy with #438's bullet duplicated.

So no damage needs fixing.

## Outcome (orchestrator ruling, owner-delegated: fragments)

- A PR adds `changelog.d/<issue>.md` (one bullet) instead of editing `CHANGELOG.md`. No shared lines means no conflicts and no corruption.
- `ci/changelog_check.py` requires a fragment for a PR touching `skillc/` (the `Changelog-exempt:` trailer is kept). This changes an instrument, so it needs committed good and bad controls.
- An assemble step folds fragments into `CHANGELOG.md` at release.
- The existing Unreleased entries stay where they are.
- The contribution docs (AGENTS.md, plus the CHANGELOG header if it carries instructions) describe the new rule.

