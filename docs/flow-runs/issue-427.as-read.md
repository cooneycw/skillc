<!-- flow-run n=1 id=7800b184a75c44c089c8dc8c3c8fd009 -->
## Run 1 - issue #427 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #427
- Read at:      2026-10-17T17:12:21Z
- updatedAt:    2026-10-17T16:55:16Z   (context only - moves on comments and labels)
- Body digest:  2e1e1a35fa0c1b179a22d5da16150bf065f6401b3c0111157548ee39edacc127   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1678 of 1678 (cap 16384)

### Body as read
## Problem

A baseline trial installs no skills. Its ledger names it by `subject.digest == matched_pilot.BASELINE_SUBJECT_DIGEST` (`skillc/matched_pilot.py:88`, the sha256 of empty bytes). #354 refuses an empty `skill_digests` list, so a baseline trial is necessarily unpinned, and `ledger-binding` checks a baseline attempt's `skill-evidence` for **shape only**.

**The hole:** a `skill-evidence` entry crediting a skill inside a BASELINE attempt validates clean. That is a contaminated baseline: evidence says a skill was used where none was installed. For #287's baseline-vs-intact comparison, that is exactly the signal that must never be accepted. A baseline that "used" the skill would shrink, or invert, the measured effect without anything refusing it.

#424 (planner adoption of #354's pins) deliberately leaves baseline trials unpinned and keeps itself a planner change (orchestrator ruling, 2026-10-17). This issue is the records-rule half.

## Outcome and acceptance

- [ ] `ledger-binding` refuses ANY `skill-evidence` entry for an attempt whose trial's `subject.digest` is `BASELINE_SUBJECT_DIGEST`, with a message naming the baseline and the credited skill path.
- [ ] Committed controls: a bad bundle (baseline attempt with a skill-evidence entry) and a good bundle (a baseline attempt with no skill-evidence).
- [ ] The check shown blind with it removed, and the bad bundle shown to pass on the pre-change code.
- [ ] An existing bundle that pairs a baseline trial with skill-evidence, if any is committed, is identified and dispositioned rather than silently re-verdicted.

Filed from the #424 drive (cpp-final-fix session) on the orchestrator's instruction.

