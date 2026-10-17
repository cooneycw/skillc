# Flow run record - issue #427

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=7800b184a75c44c089c8dc8c3c8fd009 -->
## Run 1

- Run-id:            7800b184a75c44c089c8dc8c3c8fd009
- Run-start:         388c9da262ab8c2b9b301022348fb6386f09dd47
- Issue:             #427
- Base SHA:          388c9da262ab8c2b9b301022348fb6386f09dd47
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T17:14:43Z

### Section B evidence
Commits since filing: 388c9da (#428, unrelated). Merged PRs: #428 only. Duplicate/superseding issues: none (#424 is the planner half). Committed-evidence scan: 1288 files, 720 records, 104 trial ledgers, 57 skill-evidence records, 6 baseline attempts (evals/matched-pilot/{evidence,evidence-2026-09-27-gpt-6-astra}/records), zero skill-evidence on a baseline attempt.

### Section C - the approved plan
1. `skillc/records.py` - define BASELINE_SUBJECT_DIGEST (sha256 of empty bytes); ledger_binding refuses every skill-evidence entry on an attempt whose trial subject.digest is the baseline, naming the baseline and the credited path; docstring.
2. `skillc/matched_pilot.py` - BASELINE_SUBJECT_DIGEST becomes an alias of records.BASELINE_SUBJECT_DIGEST (one line; approver's change).
3. `controls/ledger-binding/bad/skill-evidence-baseline-trial/` - baseline trial + receipt still listing the skill; only the new rule can catch it.
4. `controls/ledger-binding/good/baseline-trial-no-skill-evidence/` - baseline trial, no skill-evidence.
5. `tests/test_records.py` - identity alias + planner writes it; bad control finding names baseline and path; no-receipt variant refused; good controls clean.
6. `docs/specs/evaluation-facility/records.md` - baseline rule sentence.
7. `CHANGELOG.md` - entry.

Scope: small. Risks: a planner bundle with baseline skill-evidence now fails ledger-binding (intended; none committed). Rule keys on matched_pilot's digest only; selection_probe's placeholder goes to the nit store after checking whether its ledgers reach ledger-binding.
Red runs: (i) bad control validates clean on main; (ii) rule call removed -> selftest reports ledger-binding failing. Scan positive control: new bad control found as a hit.
