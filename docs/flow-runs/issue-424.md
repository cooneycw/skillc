# Flow run record - issue #424

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=c497ef24a7ed46659cf819b3bca66e82 -->
## Run 1

- Run-id:            c497ef24a7ed46659cf819b3bca66e82
- Run-start:         1b62faa8aac5372c9e27205e624e8518646ad490
- Issue:             #424
- Base SHA:          1b62faa
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated) - "#424 plan APPROVED, Section C items 1-5 as written", Q1 option (a), 2026-10-17
- Recorded at:       2026-10-17T17:20:00Z

### Section B evidence
- Since #424 was filed: main gained only #425 (1b62faa, #354 itself); no PR references #424 or skill_digests adoption; no duplicate issue.
- Both planners build treatments through calibration_run.build_treatment (cli.py:1760/1878 calibration, cli.py:2020-21 uptake); only the #287 intact arm has a validated profile (inventory); uptake arms have none.
- Baseline rule split out to #427 (Q1 option a); #287 approval-visibility note posted (issuecomment-6237087975), referenced on #376.

### Section C - the approved plan
1. `skillc/profile.py` - extract the inventory's description/body digest rule into skill_md_digests(text); inventory output byte-identical.
2. `skillc/calibration_run.py` - Treatment.skill_digests from installed SKILL.md bytes in build_treatment; cross-checked against profile.skill_digest_pins(inventory) when a profile is opted in, refused on disagreement; plan_calibration declares skill_digests on every treated trial and refuses a treated arm with none.
3. `skillc/uptake_study.py` - plan_study declares each arm's own pins; run_study passes them.
4. `skillc/cli.py` - planner call sites pass the treatment pins where needed.
5. `tests/test_calibration_run.py` - red (treated trials carry skill_digests), end-to-end stale refusal and pinned control.
6. `tests/test_uptake_study.py` - per-arm pins; published != rewritten description digest.
7. `tests/test_calibration_outcome_endpoint.py` - updated call sites.
8. `tests/test_calibration_run_profile_closure.py` - inventory cross-check red.
9. `CHANGELOG.md` - entry.

Scope: medium. Risks: planner signature changes (every caller listed); hand-built Treatment fixtures reaching the planner need pins; inventory extraction must stay byte-identical (committed-inventory digest check).
