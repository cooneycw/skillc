# Flow run record - issue #202

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=93c6a71fad2646c4a2ebba179ce91632 -->
## Run 1

- Run-id:            93c6a71fad2646c4a2ebba179ce91632
- Run-start:         95e71151ed53dce2777904b14a8cd8f6f345aa17
- Issue:             #202
- Base SHA:          95e7115
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (session user, "approved")
- Recorded at:       2026-09-30T16:00:00Z

### Section B evidence
Commits since filing: none. Merged PRs today: #200, #201 (neither retains transcripts). Related issues: #106 (closed, built the reader). No duplicate/superseding issue.

### Section C - the approved plan
1. `skillc/trial.py` - capture() accepts transcript evidence; writes a client-transcript observation (complete + ref/digest/size, or missing + reason)
2. `skillc/records.py` - client-transcript rule in observation_coverage (complete/partial/missing; ref required for complete/partial, reason required for missing)
3. `skillc/lifecycle.py` - run_through_backend passes the observed transcript to trial.capture
4. `skillc/agent_trial.py` - always hold transcript bytes, leak-check before retention, transcript_retention summary, shared invocation extraction, recompute_skill_invocations
5. `skillc/collection_conformance.py` - envelope + paste-back [transcript] section
6. `skillc/cli.py` - collection-run --evidence-transcript opt-in; export copies transcript into bundle/transcripts/, refuses when requested but not retained
7. `controls/observation-coverage/bad/transcript-complete-without-ref.json` - red case
8. `controls/observation-coverage/bad/transcript-missing-without-reason.json` - red case
9. `controls/observation-coverage/good/transcript-missing-with-reason.json` - green case
10. `tests/test_collection_conformance.py` - regression, missing-transcript control, planted-leak refusal, recompute equality
11. `docs/specs/evaluation-facility/records.md` - document the stream
12. `docs/specs/evaluation-facility/capture.md` - document retention and export opt-in
13. `CHANGELOG.md` - Unreleased entry

Scope: ~13 files, ~400-600 lines. Risks: other callers' stores change (exact observations assertions); selection_probe duplicate retention (nit store); leak check may refuse real transcripts (stated with class+line).
