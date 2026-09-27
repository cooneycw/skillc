# Flow run record - issue #106

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #106
- Base SHA:          ab04c6c536de8c8ce8df2de261f85ebbb8f93d89
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          the owner (cooneycw), in the invoking session
- Recorded at:       2026-09-27T12:55:25Z

## Section B evidence
Delivered code bullets: PRs #107, #108, #113, #117. Live run under-evidenced:
PRs #121, #126 (ab04c6c, closed #11) - prompt/canary/outcome only; the
paste-back reads `refresh_observed_in_container` while the record key is
`credential_refresh_observed_in_container`, so it always printed None.
Also inspected, not addressing this: #125, #123, #120, #119, #116, #115, #111,
#110, #109, #105, #104, #103, #99, #97, #96. Superseding issues: none (#10
closed; #124 is the Claude Code arm; #26/#12 not satisfiable by these runs).

## Section C - the approved plan
1. `skillc/agent_trial.py` - record `credential_remaining_seconds_at_launch` and a transcript census (client version, model, line-type counts, normalized-event count).
2. `skillc/collection_conformance.py` - fix the refresh key; paste-back grouped into prompt delivery, canary, credential, outcome, cleanup evidence.
3. `skillc/cli.py` - host credential digest before/after + remaining life after, label-scoped leftover-container count, leak-checked record JSON in the kept store, `--minimum-credential-seconds`.
4. `tests/test_collection_conformance.py` - red cases: refresh key via a real `run_one_attempt` record, leftover container, host file changed, teardown UNKNOWN, below-threshold BLOCKED with no container.
5. `tests/test_agent_trial.py` - census fields from the committed codex fixture; red on drifted line types.
6. `evals/agent-trial-live/README.md` - verbatim leak-checked paste-backs: both collections, missing-credential and below-threshold controls, host `codex login status` afterwards, limits.
7. `CHANGELOG.md` - the new evidence fields.
8. `README.md` - the `collection-run` line.
9. `docs/flow-runs/issue-106.md` - this record.

Scope: ~7 files + evidence, ~250-400 lines. Risks: in-container refresh
rotating the host refresh token (the host check catches it; stop, do not
re-login); larger leak surface (same leak check incl. #105's token class);
"host login still working" shown without a host model call, labelled so.
