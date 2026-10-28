<!-- flow-run n=1 id=f99a2ff50a8042c791151554b272bf34 -->
## Run 1 - issue #557 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #557
- Read at:      2026-10-24T21:42:54Z
- updatedAt:    2026-10-24T21:41:47Z   (context only - moves on comments and labels)
- Body digest:  f1f07c24b254e53d5ecc9a9b8d8a39201633bc8ba004a579eb9d03e5cd3700c0   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3427 of 3427 (cap 16384)

### Body as read
Parent: #28. Related: #203, #547, #556.

## Owner request and objective

On 2026-10-24 the owner asked “can we rerun it?” after the private source of calibration-09960aea could not be located, then selected “Repeat the full original 18-attempt baseline/natural/provided calibration.” This is new requested work, not restoration of the historical record and not proof that an eligible failure must occur.

Prepare a fresh declared repeat: six baseline, six natural and six provided attempts, preserving the original seeded schedule, model/effort, CPP pin and task revision where feasible. Report every changed identity and retain the complete new evidence in a durable private store. The original report remains historical and untouched.

## Known identities and changed input

- Historical task: helper-different-question revision 1, archived from skillc fc02838. Current task revision 2 clarified the approved step numbering; never silently substitute it in a literal repeat.
- CPP: 85e9b03ad2af1c41020ff6d92d36fa257bdacd2b, full cpp-codex skill surface.
- Client/model: codex 0.157.1, gpt-6-astra, high reasoning effort.
- Original image eb17e8c7995f69c4f849d6d8a9165eddfd0ccc8065b5425e0bdc2e3595a86d44 is unavailable in the inspected stores.
- Available replacement image: sha256:b9816879e22d1f62dc6b8614c787e7666c1d9f438437c3d03d3c622513d1a563. A network-none, credential-free version probe reports codex-cli 0.157.1. A rebuilt/replacement image is an explicit changed identity, never the old image under a new name.
- Use a reviewed current controller after the #547 failure-retention slice merges, with a bounded historical task snapshot; do not run obsolete controller code merely to obtain the old task.

## Bounds and launch gate

18 agent attempts only, six per arm, original seed 20261005 schedule, 1200 seconds per attempt and 21600 seconds schedule cap. Existing subscription login only; deterministic grader, no API-metered judge calls. Report the distinction between schedule time caps and cleanup overhead. No automatic retries, added attempts, changed arms or hidden exclusions. Prepare and validate the exact new declaration digest before launch; replacement identities need explicit review under ADR 0005. No live model call during preparation.

## Acceptance

- Committed declaration/preflight/runbook with exact current controller, historical task goal/grader/fixture identities, CPP/image/client/model identities, schedule, caps and durable retention policy.
- Certify the historical task/grader on known-bad and known-good candidates without models. State the revision-1 interpretation ambiguity in the report.
- Verify actual image/client and required credential, egress, opt-in and isolated-home boundaries without exposing credentials or relying on tag names.
- Execute only after declaration review. Preserve all 18 planned slots and all failed/unavailable attempts; retain source manifests, object bytes, transcripts and summaries with hashes.
- Publish a privacy-checked summary that distinguishes original-versus-new identities, outcome, uptake, evaluability and cost; no claim of generalized improvement from a floor/ceiling result.
- Assess whether a new failure supplies #28 lineage. If none does, say so; do not invent or keep rerunning to obtain one.

Preparation may proceed while #547 merges. This issue does not broaden #547 or commission a repair of the historical task/subject.

