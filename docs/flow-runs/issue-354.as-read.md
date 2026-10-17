<!-- flow-run n=1 id=51a714efad654dea87b58c8add85e818 -->
## Run 1 - issue #354 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #354
- Read at:      2026-10-17T16:02:22Z
- updatedAt:    2026-10-12T19:48:26Z   (context only - moves on comments and labels)
- Body digest:  1cd4bce2ac63b4c9f7f9142bc034190839ef67f3a46c493bf73762a847a9b797   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1933 of 1933 (cap 16384)

### Body as read
## Problem

`skill-evidence` (#268, PR #299) carries per-skill `skill.body_digest` / `skill.description_digest`, but they are checked for shape only. A record can name an old or wrong version of a skill and still validate clean, so evidence can be credited to bytes that were never tested. Recorded in the nit store: https://github.com/cooneycw/skillc/issues/20#issuecomment-6007178436

## Design

Pin the expected fingerprints in the controller's plan, so the check never has to read #265's `evidence/inventory.json` (a different artifact family) - it compares records against the ledger, as the owner ruled for #268: "stale" means disagreement with what the ledger planned.

- `trial-ledger`: optional per-trial `skill_digests: [{path, body_digest, description_digest}]`; malformed entries and duplicate paths refused.
- `ledger-binding`: for an attempt whose trial declares `skill_digests`, a `skill-evidence` entry is refused when its path is not pinned (unpinned), when it omits either digest (cannot go stale), or when a digest differs from the pin (stale).
- Opt-in: a trial without `skill_digests` keeps today's shape-only behaviour, so no existing bundle changes verdict.
- `trial.plan` accepts and type-checks `skill_digests`; `profile.skill_digest_pins(inventory)` derives them from a #265 inventory.

## Prior art

The ledger-pin approach is taken from the unmerged first #268 run (local commit 594d7dd, `case.attribution` pinning `profile_digest`/`contract_digest` with `attribution-binding` refusing stale/unpinned records), adapted here to `skill-evidence`'s per-skill digests.

## Acceptance

- Committed bad controls for stale, unpinned and digest-omitted-under-pin bundles, and a malformed `skill_digests` ledger; good controls for a pinned-and-current bundle and a declaring ledger.
- Each new check shown blind with its check removed; the bad bundles shown to pass on the pre-change code.
- `make verify` green.

