# Flow run record - issue #12

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

This is the SECOND /flow:auto run on #12. The first run's record (base ab04c6c,
approved 2026-09-27, delivered by #140/#149) is in git history at 422f9d2.

- Issue:             #12
- Base SHA:          422f9d22a4489893feaa9106c7204f49a75b2064
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          cooneycw (owner), in the /flow:auto session ("approved")
- Recorded at:       2026-09-28T00:00:00Z

## Section B evidence
Commits since 2026-09-27 touching the affected files: f5b9099 (#146), c07960e
(#138), 30c593b (#128), 33e654f (#135), ab04c6c (#126) - none fixes the three
folded-in items. PRs #140/#149 met the original acceptance; #89/#103 are
groundwork. No duplicate or superseding issue (#10/#77/#78 closed, origin of the
digest finding).

## Section C - the approved plan
1. `skillc/docker_backend.py` - install() records the container's actual image id (`docker inspect --format {{.Image}}`) as readiness `image_digest`, null when inspect fails
2. `skillc/trial.py` - `backend-identity` detail event; experiment-level flock taken by capture() and _add()
3. `skillc/lifecycle.py` - journal `backend-identity` with image_digest and matches_ledger (true/false/null) after install()
4. `skillc/judge.py` - JudgeDescription.server; JudgeAnswer(verdicts, model); run_tier records the answering model separately from the server
5. `skillc/judge_mcp_second_opinion.py` - describe() reports the server as server, model None; evaluate() parses the real tool's dict reply (analysis, model_used, success)
6. `tests/fixtures/mcp-second-opinion/fake_server.py` - real-shape modes answering like the real FastMCP server
7. `skillc/verify.py` - grade() holds the experiment lock across snapshot, grade, re-check and add_result; snapshot excludes only unfinished planned sibling attempts' spool/journal files
8. `tests/test_docker_backend.py` - image digest recorded, null on inspect failure
9. `tests/test_lifecycle.py` - backend-identity event, matches_ledger false on mismatch
10. `tests/test_judge.py` - JudgeAnswer model recorded separately from server
11. `tests/test_judge_mcp_second_opinion.py` - real-shape reply, fallback model, two tiers one server different models, success false unavailable
12. `tests/test_verify.py` - red case: A graded while sibling B runs and captures; controls that still refuse
13. `CHANGELOG.md` - entry
14. `docs/specs/evaluation-facility/verification.md` - scoped snapshot and lock
15. `docs/specs/evaluation-facility/capture.md` - backend-identity event and the lock
16. `docs/flow-runs/issue-12.md` - this record

Scope: ~14 files, 500-700 lines. Risks: item 3 narrows the tamper tripwire for
unfinished sibling spool/journal files (documented, controls prove the rest
still refuses); judge.model changes meaning (no live judge result exists yet);
the lock serializes grading with capture within one experiment.
