# Flow run record - issue #723

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=aac930e20d174c3aacc43a3c519f5d71 -->
## Run 1

- Run-id:            aac930e20d174c3aacc43a3c519f5d71
- Run-start:         411a91e79c35e2f9175a4ee1c83280de6b590e1e
- Issue:             #723
- Base SHA:          411a91e79c35e2f9175a4ee1c83280de6b590e1e (origin/issue-724-skill-usage-hook-records-nothing-in-submodule-and, PR #742; stacked)
- Necessity verdict: Still needed
- Approval:          granted (with conditions)
- Approver:          wave orchestrator skillc-orch (policy rev 1, orchestrator-only), mailbox rev 10 "GATE: GO-WITH-CONDITIONS #723"
- Recorded at:       2026-11-14T23:55:59Z

### Section B evidence
- commits: none on origin/main touching skillc/cli.py; the stack does not touch cli.py
- PRs: none for #723; #733 (CollectionRule branch) and #720's worktree 2ccfc90 (ContractRule branch) edit _population
- dup/super: none
- host: #720 worktree commits touch cli.py in a separate branch

### Approval conditions (orchestrator, rev 10)
- a test pins {r for usage rules if not r.parser} == {skill-usage-fields, skill-usage-privacy, skill-usage-pairing}
- PR states bad side reads UNPARSED, not BLIND (differs from issue text)
- one clause in records.md: a semantic usage rule is exercised only by a control with an envelope-readable record
- the good-side sabotage test is shown red on 411a91e

### Section C - the approved plan
1. `skillc/cli.py` - inside the existing UsageRule branch of _population only: a semantic usage rule (not rule.parser) treats a log with zero envelope-readable records as unexercised (parse_error set)
2. `tests/test_usage.py` - good-side and bad-side version-2 sabotage tests via selftest, the selector pin, envelope rule and committed controls still certify
3. `docs/specs/evaluation-facility/records.md` - one clause: a semantic usage rule is exercised only by a control with an envelope-readable record
4. `changelog.d/723.md` - entry

Scope: 4 files, ~50-70 lines.
Risks: future semantic usage rules inherit the stricter population (accepted); bad side reads UNPARSED not BLIND (accepted); _population is selftest-only; re-sync conflict with #733/#720 is textual, resolved additively.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable: selftest over a control directory, no checkout layout involved |
| Run placement | will test: Woodpecker CI (`skillc selftest` is in the gate step) and host make selftest |
| Execution backend | not applicable |
| Agent client | not applicable: no client involved |
| Client invocation | not applicable |
| Static-check target | not applicable: usage rules have no `targets/` layer (controls/skill-usage-*/ are bad/good only) |
| Subject collection | not applicable |
| Subject installation | not applicable |
| skillc distribution | will test: source checkout. Built wheel: clean-install runs selftest against packaged rules, not covered by these cases |
| Python version | will test: 3.12. 3.11: not covered (project-wide) |
| Reader: selftest's certification verdict (read by make verify / CI gate and every check-records consumer) | tested against real output: the tests call `cli.main(["selftest", "--controls", <copy>])` on real copied controls, no stand-in |
| Reader: `_refusal` (reads `_Subject.parse_error`) | tested against real output, end to end through selftest |
