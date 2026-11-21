# Flow run record - issue #739

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=bdb424be606e41bc905e5e21fe0b3b4d -->
## Run 1

- Run-id:            bdb424be606e41bc905e5e21fe0b3b4d
- Run-start:         a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Issue:             #739
- Base SHA:          a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive "approved" in this session
- Recorded at:       2026-11-20T11:32:57Z

### Section B evidence
Commits since 2026-11-14T23:24:09Z touching the paths: aa5ddc6, 7c31067, 12da2e5, f29e3a3, fd8804a, f93499d, 295e743, 0d97bb8, 8e0e02e, 11acf2a, 5a79692, fbe300b, 16ce4b1 - none changes _Parser.sequence's re-indent or cmd_contracts's early return. Merged PRs: #746 (parent #720), #762, #764, #770, #771, #773, #780, #782, #785 - none fixes either item. Duplicate/superseding: #786 (closed; gauntlet round keys path, not cmd_contracts). Item 1 reproduced live on a2f9ffd (mis-aligned wide-dash charter certified GOOD, PyYAML ParserError).

### Section C - the approved plan
1. `skillc/spec.py` - _Parser.sequence contracts mode: re-indent a `- key:` line to its actual key column (ind + 1 + spaces after the dash), refuse a tab in the dash gap.
2. `skillc/cli.py` - cmd_contracts: none-declared only when no contracts AND no unreadable directories; otherwise run the checks (contract-shape error, exit 1).
3. `tests/test_frontmatter_subset.py` - PyYAML differential: mis-aligned wide-dash refused by both; aligned wide-dash read identically.
4. `tests/test_contracts.py` - zero contracts + unreadable directory exits 1 with "could not be read"; dash-spacing bad control fires contract-shape.
5. `controls/contract-shape/bad/dash-spacing/alpha/CHARTER.md` - committed negative control: good/valid with `  -   id: alpha.out` and keys at 4 spaces.
6. `controls/contract-shape/bad/dash-spacing/checks/alpha-out/bad/case.txt` - copied control check case.
7. `controls/contract-shape/bad/dash-spacing/checks/alpha-out/good/case.txt` - copied control check case.
8. `controls/contract-shape/bad/dash-spacing/checks/alpha-never/bad/case.txt` - copied control check case.
9. `controls/contract-shape/bad/dash-spacing/checks/alpha-never/good/case.txt` - copied control check case.
10. `controls/contract-shape/bad/dash-spacing/checks/alpha-auth/bad/case.txt` - copied control check case.
11. `controls/contract-shape/bad/dash-spacing/checks/alpha-auth/good/case.txt` - copied control check case.
12. `docs/specs/contracts.md` - add dash-spacing to the contract-shape bad cases; incomplete discovery is exit 1 even with zero contracts.
13. `changelog.d/739.md` - changelog fragment.

Scope: Tier 2, ~80 lines plus a copied control.
Risks: shared parser (guarded by contracts mode; SKILL.md frontmatter unchanged); a charter relying on the silent repair is now refused, as PyYAML does.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | not applicable |
| Execution backend | not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | will test - portable (contract rules are target-independent; selftest runs the new contract-shape bad control); claude-code not exercised separately |
| Subject collection | will test - synthetic |
| Subject installation | not applicable |
| skillc distribution | not applicable |
| Python version | not covered - 3.12 only |
