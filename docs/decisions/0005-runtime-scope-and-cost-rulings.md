# ADR 0005: Runtime scope, judge mechanism and cost stop (owner rulings, 2026-09-26)

- Status: Accepted (owner, 2026-09-26)
- Date: 2026-09-26
- Decision owner: Repository owner
- Delivery issue: [#73](https://github.com/cooneycw/skillc/issues/73) (Part D)
- Related: [#63](https://github.com/cooneycw/skillc/issues/63) (leak-check),
  [#64](https://github.com/cooneycw/skillc/issues/64) (managed-container backend),
  [#69](https://github.com/cooneycw/skillc/issues/69) (grading tiers),
  [#12](https://github.com/cooneycw/skillc/issues/12) (cost stop),
  [#26](https://github.com/cooneycw/skillc/issues/26) (selection probe,
  subscription-login ruling applied), [#98](https://github.com/cooneycw/skillc/issues/98)
  (in-container credential path, the prerequisite rule 6 names)

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

### 6. Rulings, verbatim and dated, that later files cite by section

Each is quoted here so a later file can cite this section instead of a private
message number - skillc is public, and a message number is a channel no
outside reader can resolve.

- **The $5 ceiling** (owner ruling, 2026-09-26): "don't worry about the cost
  estimate... i expect it's under $5." Applies to the whole paid run's
  estimated cost, enforced in code by `skillc.cost_estimate.authorize` -
  refused regardless of any approved budget above it (rule 5 above).
- **"Normal Claude and codex"** (owner ruling, 2026-09-27): agent runs
  (#26's and #12's treatment and baseline attempts) use the operator's
  normal Claude Code and Codex subscription logins, not a pay-per-use API
  key. They sit inside the normal subscription budget, not metered spend,
  so their token/price figures are a usage quota, not a dollar charge.
  **This ruling covers agent runs only.** Judge calls (tiers 2/3, rule 4
  above) call external providers with API keys and stay dollar-metered and
  subject to the $5 ceiling exactly as before -
  `skillc.cost_estimate.authorize`'s `agent_uses_subscription_login` flag
  gates on judge spend alone in this mode, never on the agent-side figure.
- **The credential rule** (owner clarification, issue #98's comment
  thread): the credential behind a subscription-login agent run is the
  operator's normal, rotating, on-machine login (Claude Code's and Codex's
  own OAuth session) - never a long-lived key of any kind. The
  in-container credential path (issue #98) is the prerequisite for
  actually running an agent attempt under this ruling; it is not delivered
  by this record.

- **"yes, narrow B1"** (owner ruling, 2026-09-28): narrows #139's own ruling
  B1 (the agent-trial path's `installation-ready` criterion stays a
  mandatory UNKNOWN, because the transcript observation that stands in for
  an installation receipt shows the prompt arrived and the agent was live,
  not that the declared subject was installed and discovered). B1's UNKNOWN
  stand-in still applies, unchanged, to an agent-trial arm that installs
  nothing (an empty baseline). An arm that DOES install a declared
  collection now writes a real installation receipt instead, built from the
  client's own model-free listing run before and after delivery - so that
  arm can reach `installation-ready: SATISFIED` and the trial can PASS on
  it. This is a narrowing of B1's scope, not a reversal: an agent-trial arm
  that installs nothing is exactly as ungraded on readiness as before; only
  an installing arm's readiness now has real evidence behind it. Tracked as
  #150-D (Refs #139, #150).

  **The mechanism moved during implementation, and the exact claim matters.**
  `DockerBackend.execute()` is documented to run ONCE per container handle
  and stops the container before returning, so the listing cannot run
  before-delivery, after-delivery AND the real agent prompt all inside the
  agent's own container. The listing instead runs in a **fresh, dedicated,
  throwaway container of the same image digest** - never the agent's own -
  once with nothing delivered (baseline) and once with the same tree
  delivered the same way (discovery), cached per (image digest, tree
  digest) so a multi-attempt run pays for this once per distinct
  configuration, not once per attempt. The receipt's evidence states the
  claim precisely: **"this delivered tree, delivered by the same method,
  into a fresh container of the same image digest, was discovered by the
  client's model-free listing"** - never "the agent's own container had
  it". The receipt carries the image digest it was measured on, and the
  verifier refuses to apply it to an attempt whose own planned image digest
  differs.

  **A named limit, not a silent one: the `.system` exclusion is by path,
  not by provenance.** The discovery listing excludes anything the client
  lists under `materialize.CLIENT_SYSTEM_DIR` from the contamination check
  (`demo.run_subject_discovery`'s `unexpected` set), mirroring
  `materialize.derive_readiness`'s own existing "foreign" precedent for the
  same problem - without it, the client's own always-present seeded skill
  reads as an undeclared contaminant on every attempt, never SATISFIED. But
  the exclusion cannot distinguish "the client's real seed" from "anything
  else an image placed under that same directory name" - a rule-stating or
  otherwise contaminating skill shipped under `.system` would be just as
  invisible to this check as the real seed is. This is the same limit the
  native precedent already carries and accepts; #150-D only matches it,
  never widens it.

- **"a plus the follow-up issue"** (owner ruling, 2026-09-27): after the
  operator's live run of `skillc demo` at `8e06030` (evidence on #10), the
  owner chose between (a) accepting that run's real-daemon coverage (the
  success path plus the three seeded `--control` failures), together with
  the fake-daemon proof of every other failure path, as sufficient to close
  #10, and (b) extending `--control` with real-daemon seeds and rerunning.
  The ruling takes (a), amending #79's evidence rule and #81's scope
  accordingly, and files #122 for real-daemon seeds of the two paths where
  a real daemon most plausibly differs from the fake: timeout and operator
  cancellation. The remaining fake-only paths, and why each is hard to seed
  honestly on a real daemon, are listed in `support-matrix.md` and #122.

## Consequences

- **Gained:** these are load-bearing facts for anyone building #10's
  remaining backends, #64's managed-container plug-in, or #69's judge
  tiers - a single dated record settles "why" without re-deriving it from
  scattered issue comments.
- **Nothing here is newly implemented.** #63 and #10's grading-boundary
  work already exist; #64 and #69's tiers 2/3 do not yet. This ADR does
  not close any of those issues, and states no acceptance beyond what they
  already carry.
- **README is checked, not merely told - but only for structural facts, not
  for narrative claims.** `ci/readme_drift.py` verifies that the documented
  command list matches `skillc`'s real subcommands, that the printed version
  matches the installed package, and that the milestone table's rows and
  states match `docs/milestones.json`. It cannot and does not verify prose
  claims about what is implemented (for example, whether a given backend
  exists) - those are read by a human, or caught by the review this ADR's own
  delivery PR went through. `ci/changelog_check.py` similarly checks only that
  a `skillc`-touching PR added an `[Unreleased]` entry or carries an exempt
  trailer, not that the entry is accurate. This ADR is the narrative record
  those checks do not themselves carry, and it is not itself machine-checked.
