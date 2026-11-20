<!-- flow-run n=1 id=bdb424be606e41bc905e5e21fe0b3b4d -->
## Run 1 - issue #739 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #739
- Read at:      2026-11-20T11:27:47Z
- updatedAt:    2026-11-14T23:24:09Z   (context only - moves on comments and labels)
- Body digest:  397f2f285217cc5f83f079d27445e66c44a6f78cf0fe4414d6a607a432e1b938   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2172 of 2172 (cap 16384)

### Body as read
Deferred findings from #720's final counter-model review (Codex, codex/gpt-6.1-sol, pass 3, scope full), on branch `issue-720-skill-contracts-charter-md-format-and-skillc-contr` at `8f1b89c`. Pass 3 was the ceiling, and the wave orchestrator ruled that pass-3 findings are deferred (skillc-work, mailbox rev 4). Both are MEDIUM, so they are grouped here rather than in the Nit Store.

## 1. List parsing silently repairs invalid YAML indentation

**Where:** `skillc/spec.py`, `_Parser.sequence` in contracts mode, which re-indents a `- key: value` item to `ind + 2`.

**What is wrong:** the parser strips the whitespace after the dash and assumes the mapping's keys start two columns right of it. Take a valid control, change `  - id: alpha.out` to `  -   id: alpha.out`, and keep the following keys at four spaces. The YAML is now malformed and PyYAML rejects it. The contract parser normalises it instead, and all nine `skillc contracts` rules report nothing, so an invalid contract is certified.

**Fix:** keep the mapping key's actual column (the dash's column plus the dash plus the actual spaces after it), or refuse any spacing other than exactly one space after the dash. Commit the malformed document as a `contract-shape` bad case, and add it to the PyYAML differential in `tests/test_frontmatter_subset.py`.

## 2. Failed discovery can read as "none declared"

**Where:** `skillc/cli.py` `cmd_contracts`, which returns early with `EXIT_NONE_DECLARED` when `collection.contracts` is empty.

**What is wrong:** when discovery hits unreadable directories (`collection.unreadable`) and finds **zero** contracts, the early return skips those errors and prints `CONTRACTS: none declared`, exit 3. A caller can't tell an empty collection from one whose declarations couldn't be examined. The partly unreadable case (some contracts found) is already handled: it is a `contract-shape` error, exit 1, fixed in #720 pass 2.

**Fix:** check `collection.unreadable` before the none-declared return; incomplete discovery is a `contract-shape` error, exit 1, even with zero contracts found. Add the case beside `test_an_unreadable_subtree_refuses_certification`.

Refs #720.


<!-- end of body -->
