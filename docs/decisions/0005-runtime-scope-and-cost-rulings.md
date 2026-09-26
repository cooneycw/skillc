# ADR 0005: Runtime scope, judge mechanism and cost stop (owner rulings, 2026-09-26)

- Status: Accepted (owner, 2026-09-26)
- Date: 2026-09-26
- Decision owner: Repository owner
- Delivery issue: [#73](https://github.com/cooneycw/skillc/issues/73) (Part D)
- Related: [#63](https://github.com/cooneycw/skillc/issues/63) (leak-check),
  [#64](https://github.com/cooneycw/skillc/issues/64) (managed-container backend),
  [#69](https://github.com/cooneycw/skillc/issues/69) (grading tiers),
  [#12](https://github.com/cooneycw/skillc/issues/12) (cost stop)

## Context

Five owner rulings landed on 2026-09-26, in the same conversation that
produced #73 (self-maintaining version and README). None changes runtime
behaviour by itself; each closes a question the README and the specs had
left implicit or unstated, in a way a later contributor could get wrong
without a record to check against. This ADR is that record, not new scope -
every ruling below already governs an existing or in-flight issue.

## Decisions

### 1. skillc runs wherever it is installed; no dedicated machine is assumed

A trial runs on the user's own machine, using whatever Docker (or other
backend) is already there. There is no assumption of a fleet, a shared
host, or any infrastructure beyond what `skillc materialize`'s own
requirements already state (native `codex`/`git`, or Docker for #10's
reference backend). Nothing in skillc's core provisions or expects a
dedicated environment.

### 2. Platform independence: a managed-container backend is only a plug-in

The reference backend (#10: skillc drives Docker directly) is the primary
runtime and is what closes #10. An external container platform - the
first is Kyle, which manages agent sessions in Docker containers through a
privileged, policy-checked executor - may supply an **optional** backend
behind the same #10 seam (describe / prepare / install / execute /
confirm-stopped / export / destroy). skillc stays fully functional without
it, nothing under `skillc/` imports or assumes the platform, and an
unavailable platform backend is disposition `unavailable`, never a silent
fallback to the reference backend or the host. Full requirements: #64.

### 3. No machine identities in outputs

Nothing committed, reported or graded - a file, a PR, a produced evidence
bundle, a receipt, a ledger - may carry the operator's machine identities:
hostnames, VM/machine names, local usernames, uid/gid numbers,
home-directory paths, IP addresses, internal URLs or ports, or container
IDs/names that embed any of the above. The owner's public email and public
GitHub handle are the stated exceptions. `skillc leak-check` (#63) is the
instrument; it runs in CI over the whole repository tree and must run over
any backend's produced bundles, including #64's, with its own seeded
negative control.

### 4. `mcp-second-opinion` is the model-judge mechanism; all enabled tiers run together

Three grading tiers, named "tiers" (not "levels") to avoid colliding with
skillc's task levels (`evals/level1`, #13-#15):

1. **Deterministic** - today's grader. Always runs; the floor.
2. **Same-model judge** - the model that produced the candidate's work.
3. **Independent judge** - a different model, cross-client by default
   (Codex judges Claude Code's work and the reverse), via
   [`cooneycw/mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion) -
   named, not merely configurable, as the tier-3 (and tier-2) judge
   mechanism. It is its own public repository, extracted from
   claude-power-pack, with no references back to it and its own declared
   dependencies - depending on it is not depending on a sibling platform.

**When judges are enabled, a trial is graded by every enabled tier
together, and each produces its own verdict** - not "tier 2 or tier 3".
Verdicts are recorded side by side: none is averaged, weighted or
overridden, and a consumer wanting one answer must say which tier it
reads. The result carries a per-criterion same-model-vs-independent
disagreement record, turning the self-grading bias from a stated
limitation into a measured quantity across runs. An unavailable judge
makes only its own tier `unavailable`; the others still report, and
nothing silently substitutes. The run manifest records which tiers were
enabled, so an absent verdict is distinguishable from one never requested.

The deterministic tier stays the floor and works with no judge installed.
skillc's core stays stdlib-only: the judge integration speaks MCP to the
server as an external process, or ships as an optional extra, never a core
import. Judge inputs pass the #63 leak check before they leave the
machine, because the server calls external providers. Full requirements
and acceptance: #69 (not yet delivered - #10's grading-boundary work
leaves the seam open but does not build tiers 2 and 3).

### 5. Cost stop: an authorized budget, not an issue or a merged doc

Filing an issue, or merging planning documents (including this one), never
authorizes a paid model call. Tiers 2 and 3 make paid judge calls - two per
trial when both are enabled, and a run manifest's cost estimate must count
both. Before any paid invocation: exact model/client/subject/image
identities, the goal population, treatment vs. minimal baseline, repeat
schedule, arm order, and per-trial/total time and monetary caps must be
recorded. Without an approved budget, the run manifest is prepared and
execution is reported incomplete, never silently skipped or approximated.
Full acceptance: #12.

## Consequences

- **Gained:** these are load-bearing facts for anyone building #10's
  remaining backends, #64's managed-container plug-in, or #69's judge
  tiers - a single dated record settles "why" without re-deriving it from
  scattered issue comments.
- **Nothing here is newly implemented.** #63 and #10's grading-boundary
  work already exist; #64 and #69's tiers 2/3 do not yet. This ADR does
  not close any of those issues, and states no acceptance beyond what they
  already carry.
- **README is checked, not merely told.** #73's own README-drift checks
  (`ci/readme_drift.py`) verify the commands, version and milestone claims
  this document's companion README refresh makes; this ADR is the
  narrative record those checks do not themselves carry.
