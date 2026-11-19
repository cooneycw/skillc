# Flow run record - issue #741

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=0e25040917c04ad9a2b9707289246259 -->
## Run 1

- Run-id:            0e25040917c04ad9a2b9707289246259
- Run-start:         1cf7bc11c1c1eab4fe8fc380e3671564586306e9
- Issue:             #741
- Base SHA:          1cf7bc1 (main fbe300b + #731's branch, merged; stacked, merges after #744)
- Necessity verdict: Still needed
- Approval:          granted (with conditions)
- Approver:          skillc-orch (wave skillc-work, policy rev 1, orchestrator-only), outbox rev 16, "GATE: GO-WITH-CONDITIONS #741"
- Recorded at:       2026-11-15T08:05:00Z - LATE: written after implementation edits had begun, not before them as Step 4 requires (an operator slip, disclosed here and in the PR)

### Section B evidence
- commits since filing (2026-11-14T23:53Z): fbe300b (#735, usage), touching no inspect file; 16ce4b1 (#733, the base code)
- PRs: #735, #733
- dup/super: none
- reproduced on 1cf7bc1: all five shapes, as filed

### Section C - the approved plan
1. `skillc/decay.py` - a quote-aware tokeniser with shlex posix boundaries plus unquoted-operator and unquoted `$(`/`)` marks; quoted strings read before the substitution logic; full-state `$(` stack; `env -S` value as command text; fallback copy alignments pooled before consumption, with a 512-extension cap that labels an estimate
2. `tests/test_decay.py` - the five exact inputs (4 in both orders), the orchestrator's guards (`p="a b"`, `--opt="x y"`, quoted `;`), the cap negative control and the exact 70 case, env -S count > 0, tokeniser equivalence with shlex
3. `tests/test_inspect.py` - the summary estimate test moves to a cap-hitting input (200 x `same` is now exact)
4. `docs/specs/inspect.md` - remove the fixed shapes; keep anything not fixed by name
5. `docs/measurements/inspect/` - re-runs vs the #731 numbers, every delta explained
6. `changelog.d/741.md` - release note

Conditions (orchestrator): posix=True boundaries; guard regressions red/green on 1cf7bc1 as stated; a negative control for the cap; env -S counter named as a reader with a count > 0; delete a blind-spot line only for a passing regression; every per-rule delta explained.
Scope: ~200-300 lines. Risks: tokeniser parity (proven on 17,694 corpus spans); copy numbers; env -S population.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test: woodpecker ci and host make verify (targeted set); not real-docker runner vm (no real_docker files) |
| Execution backend | not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test: cpp at pinned shas (d5ef0a66, 93ae8540), mattpocock-skills (5863806), synthetic (tests and fixtures) |
| Subject installation | not applicable |
| skillc distribution | will test: source checkout (targeted set) and built wheel in a clean venv (clean-install in PR CI) |
| Python version | will test: 3.12 tested; not >=3.11 declared (not run locally for this change) |
