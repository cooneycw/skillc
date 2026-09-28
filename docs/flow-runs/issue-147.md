# Flow run record - issue #147

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #147
- Base SHA:          2b606160eb009730798fbacaf19a4a6a082abe52
- Necessity verdict: Still needed
- Approval:          granted (including the live run: 6 codex attempts, subscription login, $0 metered)
- Approver:          cooneycw (owner), in the /flow:auto session
- Recorded at:       2026-09-28T08:28:25Z

## Section B evidence
Since #147 was filed (2026-09-27T18:01Z): f5b9099 (#146, stored results; #139 open
pending this), 924b961 (#145, unrelated), 2b60616 (#144, launch pin; #141 closed).
Earlier: #140 (first run), #142, #143. No duplicate re-run issue. projects-95,
projects-b8 and projects-ba each confirmed they will not run the pilot. Hazard
confirmed: pilot-run's default --evidence replaces evidence/records wholesale, and
the new declaration's retention.committed still names that directory.

## Section C - the approved plan
1. `evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json` - retention.committed points at the new evidence directory (committed BEFORE the run); after the run, execution and observed facts
2. `skillc/cli.py` - _export_pilot_evidence refuses to replace a bundle of a DIFFERENT experiment, or one whose ledger cannot be read; same-experiment re-export still replaces
3. `skillc/matched_pilot.py` - helper reading a bundle's experiment id from its ledger
4. `tests/test_matched_pilot_run.py` - red cases: default run over another experiment's bundle refused and left byte-identical; unreadable ledger refused; same-experiment re-export allowed
5. `tests/test_matched_pilot.py` - current declaration's execution bound to its evidence; new bundle clean (0 findings, not in KNOWN_GAP_EXPERIMENTS); gpt-6-astra/high/declared image on every attempt; old bundle unchanged
6. `evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/README.md` - new: records/, claims.json and README (table, matched comparison, model/effort checks, INCONCLUSIVE-stored-vs-PASS-graded, no broad claim)
7. `evals/matched-pilot/README.md` - which declaration and evidence are current
8. `evals/matched-pilot/evidence/README.md` - first run superseded but kept
9. `CHANGELOG.md` - entry
10. `docs/flow-runs/issue-147.md` - this record

Live run: `SKILLC_ALLOW_REAL_AGENT=1 uv run --no-sync skillc pilot-run --manifest
evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json --evidence
evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/records`; judged on the exit
code and summary.model_ineligible, not on a published bundle.

Scope: ~9 entries, ~60 lines code + ~120 tests + generated evidence. Risks: -c/-m
unproven live (fails loudly; stop and report, no retry); infrastructure failures
leave #12 for an owner decision; n=3 per arm is noise-level.
