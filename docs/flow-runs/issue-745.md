# Flow run record - issue #745

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=d66562df541646c7b8df1d204e3fe218 -->
## Run 1

- Run-id:            d66562df541646c7b8df1d204e3fe218
- Run-start:         604084088cc9e11464c5cc263260f658836e400c
- Issue:             #745
- Base SHA:          6040840 (#748's head: main bca9ea2 + #741's branch; stacked, merges after #748)
- Necessity verdict: Still needed
- Approval:          granted (with conditions)
- Approver:          skillc-orch (wave skillc-work, policy rev 1, orchestrator-only), outbox rev 30, "GATE: GO-WITH-CONDITIONS #745"
- Recorded at:       2026-11-15T11:58:00Z (before the first implementation edit)

### Section B evidence
- commits since filing (2026-11-15T08:25Z): bca9ea2 (#744), already in this base
- PRs: #744
- dup/super: none
- reproduced on 6040840: both shapes, as filed

### Section C - the approved plan
1. `skillc/decay.py` - a fully quoted option with an owner is checked like the attached form; `env -S` / `--split-string` values are spliced into the token stream as a new command (a deque, with a 32-splice cap that is reported, never silent)
2. `tests/test_decay.py` - both quote styles and both operand forms, red on 6040840; guards (`--absent="x y"` fires, `"-> see scripts/gone.sh"` is path-checked, an attached value reads no path, a lone `--` or `-` is not a flag, a quoted non-FLAG word stays a string); `env -i -S` splices; the splice cap is reported; bounded recursion; the #741 env assertion is changed deliberately, keeping a genuine unowned count > 0
3. `tests/test_inspect.py` - the assembled-report counter keeps a > 0 count on a genuine unowned case
4. `docs/specs/inspect.md` - remove the #745 blind-spot lines whose regressions pass; document both rules
5. `docs/measurements/inspect/` - re-runs vs #748's numbers, reconciled span by span
6. `changelog.d/745.md` - release note

Conditions (orchestrator): the guards above; the cap reported; the #741 test change named under Plan deviations; blind-spot lines removed only for passing regressions; every delta reconciled; at most 3 counter-model passes, with pass-3 findings deferred.
Scope: ~120-200 lines. Risks: env -S moves the flag population; the splice cap.

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
