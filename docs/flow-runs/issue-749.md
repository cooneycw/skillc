# Flow run record - issue #749

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=456df5e067d845ed8f07a644f9a27ca5 -->
## Run 1

- Run-id:            456df5e067d845ed8f07a644f9a27ca5
- Run-start:         9dc1a7de3be7f8c2a42f0aa402195dd33e0dc20a
- Issue:             #749
- Base SHA:          9dc1a7d (PR A of #726, unpushed; per the gate, #749 stacks on PR A, not PR B)
- Necessity verdict: Still needed
- Approval:          granted (GO-WITH-CONDITIONS)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 21
- Recorded at:       2026-11-15T11:45:00Z

### Section B evidence
- commits since 2026-11-15T11:13Z: none on main touching skillc/contracts.py or skillc/charter.py (main is bca9ea2)
- PRs: none merged that touch them; dup/super: none (#750 is PR B's own list)
- host: PR A (9dc1a7d) and PR B are this work's own unpushed base; no other sibling touches these files

### Section C - the approved plan
1. `skillc/contracts.py` - contract-shape's duplicate-id check also counts the intent clause's id
2. `controls/contract-shape` - bad/intent-id-collision (intent and an authority clause share one id)
3. `skillc/charter.py` - CommonMark fences: the opening character and length, indented 0-3 spaces; closes only on the same character at least that long with no info string; an unclosed fence runs to the end of the file
4. `tests/test_charter.py` - nested and mixed fences, unclosed, indented up to 3 vs 4 or more, an info string on a closing line, and prose after a correctly closed fence
5. `tests/test_charter_confirm.py` - an intent/authority collision with one accept is refused, and nothing is dated
6. `tests/test_contracts.py` - the collision is a named contract-shape finding; distinct ids are clean
7. `changelog.d/749.md` - fragment

Conditions (rev 21): stacked on PR A; red-first on the pre-fix head, named; the CommonMark edge cases above; an inventory of every committed CHARTER.md showing none reuses its intent id (in the PR body); contract-shape named as stricter; targeted set only; up to 3 counter-model passes; nothing pushed in the silent period
Scope: 7 paths, ~150 lines. Risk: contract-shape becomes stricter (no CHARTER.md outside this wave exists; the inventory shows 53 committed, 0 reusing)

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable - no checkout resolution |
| Run placement | will test - Woodpecker CI (full-suite gate); host `make verify` targeted set only; real-Docker runner VM not applicable |
| Execution backend | not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable - contract-shape is a contracts rule, not a target-scoped SKILL.md rule |
| Subject collection | will test - synthetic controls and fixtures |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (uv sync, editable) via the suite; built wheel in a clean venv not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: `skillc contracts` users - contract-shape is stricter. Compatibility: the inventory (0 of 53) and the new control.
- Reader: `charter confirm` - refuses the collision through contract-shape. Compatibility: the confirm test.
