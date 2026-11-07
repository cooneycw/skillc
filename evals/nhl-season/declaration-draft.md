# NHL comparison declaration draft (#639)

Status: reconciliation draft, UNAPPROVED, UNSIZED and UNFROZEN. No executable
run declaration, declaration digest, sizing report or rehearsal report is claimed.
This document grants no host action, acquisition, live or paid model call,
sizing/concurrency probe, declaration freeze or full-run execution.

This is a **product-level comparison: CPP's multi-agent pipeline versus Codex's
native single-agent goal mode**. A CPP win does not separate multi-agent effects
from CPP effects. Only the delivered product earns task credit; scaffolding,
issue creation and workflow compliance do not earn product credit.

## Sources and precedence

- [#639](https://github.com/cooneycw/skillc/issues/639) owns the sized, frozen
  declaration and its approval deliverables. This file supplies its early
  reconciliation step, not completion of the whole issue.
- [#631](https://github.com/cooneycw/skillc/issues/631) defines the comparison;
  [#628's fast path](https://github.com/cooneycw/skillc/issues/628) folds the
  concurrency probe into sizing, limits #625 to the combined CPP profile,
  limits #623 to final snapshots, drops #627's quote-task live study and defers
  #635 automated viewer browser grading to the second run.
- [October 30 Codex ruling](https://github.com/cooneycw/skillc/issues/628#issuecomment-6524765089):
  Codex is the client for every role; no token, spend or time caps are required
  for subscription Codex sessions. Record per-role and aggregate usage instead
  of treating #639's original token/time caps as mandatory. Sizing and frozen
  declaration approval remain required. Model switching must be disabled or
  detected. Any optional symmetric budget or operational calendar deadline
  must be explicit in the approved declaration, not inferred from this draft.
- [November 1 clutter ruling](https://github.com/cooneycw/skillc/issues/639#issuecomment-6557884448)
  supplies the delivered-tree/cache policy below.
- [November 7 sequence](https://github.com/cooneycw/skillc/issues/639#issuecomment-6706161825)
  replaces the November 4 order. Early reconciliation, sizing and final freeze
  are separate stages. The sequence grants none of their execution approvals.

## Arms, fairness and treatment identity

Both arms start from the same empty project task, [goal.md](goal.md), and use
the same declared tools and immutable runtime inputs. CPP uses `project:init`
to create specifications/issues, then `flow:wave`, with `flow:auto` closure,
across separate role containers. Control uses one native Codex `/goal` session.
The exact CPP profile closure and cold-install proof remain #625 inputs.

Pin Codex 0.165.0 in both arms, subject to the approved frozen identity, with
actual in-image CLI probes; recipe text alone is not evidence. Follow the
[native goal contract](../../docs/specs/evaluation-facility/codex-goal.md).
Keep its goal uncapped, record lifecycle/usage events and all CPP sessions
(including orchestration and wake turns), and retain complete controller-bound
rollout evidence. Usage-limit infrastructure outcomes are reported separately
from task failure. Changed, unknown or unbound model identity cannot pool with
the pinned treatment; paused, blocked or deadline-stopped stable sessions remain
in the population with their observed states, rather than being filtered away.

Tool/browser access must be equal: either both arms can test the viewer with
a browser or neither can. First-run grading still uses the public viewer data
hook and screenshots for owner review; deferred #635 browser grading must not
silently become a first-run endpoint. Declare the arm-neutral literal wake
policy and count every poke/session in usage (#622). Do not add CPP-only
continuation advice. Any optional token budget must be symmetric, comparing
the control with the sum across every CPP session; it is not a cost safeguard.

Role count, role/session identities, resource allocations, tool surface,
optional limits and operational stop/deadline rules: PLACEHOLDER pending
#624, #625, #637 and approved sizing. No numeric budget or repeat count is
invented here. Technical transport, output, containment and cleanup bounds
still need explicit declaration; uncapped model usage does not remove them.

## Endpoint and reporting plan

Use only the public goal's completed 2025-26 regular-season/playoff population
and requirements. Freeze its exact bytes/digest, retrieval cutoff and season
coverage. Grade the captured delivered project, never a grader-repaired version.
Report components separately rather than hiding an unavailable component in
an aggregate score:

| Component | Required evidence / pending selection |
|---|---|
| Retrieval/database | Completed-game coverage, retained payload provenance, working documented commands and idempotent persistence; #633/#634 integration pending. |
| Reconciliation | F1-F8 real discrepancy recall/precision and honest per-game PASS/DISCREPANCY/UNAVAILABLE reporting against the independent oracle. Freeze check populations and scoring rules before outputs are observed. |
| Drift and plants | Added JSON fields at every depth retained without losing original facts; baseline plus F1-F8 discrepancy plants in fresh delivered-code replays, with false positives checked on unchanged games (#634). |
| On-ice relation | Sparse player-second membership and invariants, including boundary, overtime, shootout and goalie conventions from the public goal; sample and comparison identities pending #633. |
| Viewer | Public `window.nhlViewer` hook, playback/seek state and supplied screenshots, with owner review; no unapproved #635 browser grading. |
| Clutter | Separate controller inventory under the delivered/cache policy below, including coverage and not-inspected disclosures (#619). |
| Resources | Per-role and total wall time, tokens, API calls, usage-limit events and database size, including wake turns and unsuccessful attempts. |

Reference responses, expected outputs, game/sample selections and plant recipes
stay in private controller custody outside candidate mounts and Git. Freeze
their checksums and oracle identity before use. Source drift or failed live
re-check yields UNKNOWN for the affected game, never a fabricated candidate
FAIL; an unchanged source alone does not imply candidate PASS. Missing or empty
coverage cannot earn a clean verdict. No fetched NHL payload is committed.

Exact component analysis, aggregation (if any), samples, seed/arm order,
repeat counts, uncertainty reporting and non-start/retry handling: PLACEHOLDER
pending #633/#634, rehearsal and sizing. Account for every planned attempt and
retain original evidence; do not silently replace failures with retries.

## Delivered-tree and cache clutter policy (#619)

Tracked files from the **captured delivered commit tree** count as delivered,
instead of pre-enumerating agent-chosen source paths. Bind the delivered commit,
tree and capture evidence to the attempt. This does not exempt untracked or
ignored additions, nor establish a whole-project grade. Independent Git refs,
worktrees, stashes, coordination and shared-state checks remain required.

Permit only bounded, digest-bound cache-directory **name patterns** below the
declared checkout, such as directories named `__pycache__` in agent-chosen
packages. Exact permitted names, checkout bounds and item/depth/byte limits
are PLACEHOLDER declaration inputs. They must be common to both arms and
bound into the approved declaration/configuration digests. Do not silently
substitute the current exact-path `allowed_subtrees` interface for the required
name-pattern policy; #619 delivery/qualification is pending.

Every report names each excluded directory and explicitly says its contents
were not inspected. No implicit cache exclusion or blanket checkout allowance
is permitted. Preserve existing protections against overlap with Git metadata,
fixture remotes, coordination, shared state, temporary scope or other surfaces;
independent collectors still inspect their own scopes. **Bytecode is not
suppressed**: do not set `PYTHONDONTWRITEBYTECODE` to avoid measuring caches.

Required committed negative controls before policy acceptance:

1. An undelivered stray file still reports clutter, including when Git ignores it.
2. A cache-named directory outside the checkout still reports clutter.
3. A cache-named directory outside the declared bounds still reports clutter.

Retain the positive twin: tracked delivered files plus permitted in-checkout
caches are classified under that policy, with explicit not-inspected reporting
and complete independent coverage. The November 1 ruling authorizes policy
delivery, not physical qualification or running this study.

## Controller lifecycle and credential boundary

The #630 controller runs on the separately approved isolated run host; public
text uses logical identities only. Each role has a separate container and PID
namespace, with only the declared shared state and fixture remote exposed.
Freeze image/VM identity and declaration-bound NHL/provider egress (#638).
Credential issuance, refresh/freshness, role binding and leak-free capture
remain #624/#630 obligations; no credential value or private hostname belongs
in the declaration or repository.

Keep the two observation points distinct: clutter observes controller-witnessed
completion/settle while roles still run; final delivered snapshots require
confirmed role/helper writer stop under #623. Retain the controller's immutable
remote-main/delivered-tree evidence, not a participant assertion. #613 qualifies
real-daemon stop/recovery; no scripted or local-only result substitutes for
physical evidence. #620 binds verdicts to actual captures and #626 rehearses the
complete path, including missing/forged/wrong-role evidence refusals.

Q13B and Q13C applicability and authoritative source: UNRESOLVED PLACEHOLDER.
Authoritative ruling text has been requested; no recalled wording is incorporated
here. Resolve applicability and record the source before final declaration freeze.

## Remaining inputs and approval stages

The November 7 order is: #621 physical qualification, this #639 reconciliation,
#636 acceptance mapping, #619, #630, #613, #623, #638, #622, #620, #624, #637,
#625, #633, #634, #626 full-path rehearsal, #639 approved sizing/concurrency,
then #639 final freeze/full-run approval. Close one issue at a time; newly found
issues go to the front. While a heavy slot is occupied, only the next one or
two items may receive light preparation. This draft closes no prerequisite.

| Dependency | Placeholder / evidence needed before final freeze |
|---|---|
| #621 | Five physical wave cases and accepted matching-runner receipts; merge of infrastructure alone is insufficient. |
| #636 | Acceptance map/proof for merged GitHub fixture operations used by the frozen CPP profile. |
| #619 | Implemented and qualified delivered-tree/cache-name policy, committed opposite cases, complete clutter coverage. |
| #630 | Approved VM identity/headroom, run-window credentials, evidence lifecycle/export/retention and physical qualification. |
| #613 | Real-daemon stop, interruption and recovery receipts. |
| #623 | Controller-held final snapshots and confirmed writer-stop custody. |
| #638 | Exact NHL/provider egress hosts/policy digest, long-attempt transport and failure/stop qualification. |
| #622 | Integrated neutral wake literal, counters and physical qualification. |
| #620 | Wave verdict bound to actual controller captures and complete attempt population. |
| #624 | Per-role credential/resource accounting and shared sizing/concurrency evidence. |
| #637 | Rebuilt pinned client image, in-image probe and physical native-goal integration/identity evidence. |
| #625 | Approved combined CPP profile digest and cold-install closure proof. |
| #633 | Private season acquisition, goal/oracle/reference digests, actual discrepancy census, on-ice expectations and live re-check sample. |
| #634 | Certified delivered-code replay, actual-sample plant validity and complete endpoint integration. |
| #626 | Approved-host complete-path rehearsal report with trusted controller evidence. |
| #639 sizing | Separately approved one or two attempts per arm, concurrency observations, wall time/tokens/API calls/database-size report; derive proposed repetitions and any limits from measurements. |

Final freeze must name exact task/oracle/reference/profile/client/model/image/VM/
skillc identities; seeded arm order and population; measured repetitions and any
chosen limits; technical bounds; retention/export/analysis; a calendar deadline;
and at most one redesign. All are PLACEHOLDER until supported by the dependencies
above. Deliver the declaration digest together with sizing and rehearsal reports
for owner review. Approval to size, approval to freeze a declaration and approval
to execute the full run remain distinct; none is conferred by this draft.
