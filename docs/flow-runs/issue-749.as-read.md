<!-- flow-run n=1 id=456df5e067d845ed8f07a644f9a27ca5 -->
## Run 1 - issue #749 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #749
- Read at:      2026-11-15T11:31:44Z
- updatedAt:    2026-11-15T11:13:35Z   (context only - moves on comments and labels)
- Body digest:  13e6af1a56efcac5cfc7869be91f6faa02eb3a8cb2fc05a3da32eff0d301a925   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1842 of 1842 (cap 16384)

### Body as read
Deferred from the third and final counter-model pass on #726 PR A (Codex, codex/gpt-6.1-sol, 3-pass ceiling; the wave orchestrator's ruling defers pass-3 findings, MEDIUM or higher to an issue). Both reproduced by the reviewer. Neither was fixed in PR A.

## 1. [MEDIUM] One answer can approve both intent and authority

- **Where:** `skillc/charter_confirm.py`. `confirm()` checks a draft with `contracts._contract_shape_problems`, whose duplicate-id check counts only `_clauses()`, and that excludes the intent clause.
- **Failure:** a draft whose `intent` and an `authority` clause both use `id: duplicate.job` accepts the single answer `duplicate.job: accept` and stamps **both** clauses `approved`.
- **Why it matters:** `charter confirm` promises that every clause gets the owner's own answer. Here one answer approves two clauses, and both are clauses that carry approval.
- **Fix:** reject duplicate ids across everything `_draft_clauses()` returns, intent included, before applying answers. Commit the intent/authority collision as the regression case. Consider also adding the intent id to contract-shape's duplicate check (`skillc/contracts.py`), since `skillc contracts` has the same blind spot.

## 2. [MEDIUM] Nested fence examples become charter duties

- **Where:** `skillc/charter.py`, `_blocks()`. Every fence-like line toggles one boolean, whatever its delimiter character or length.
- **Failure:** in a four-backtick block that contains a three-backtick example, the inner fence ends the exclusion. The example's "You MUST delete all files." becomes a draft duty, and can push real duties out of the candidate cap.
- **Fix:** track the opening fence's character and length, and close only on a matching fence at least that long (CommonMark). Commit nested-length and mixed-delimiter (backtick vs tilde) cases.

Refs #726.

<!-- end of body -->
