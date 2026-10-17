# Flow run record - issue #392

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=cb05c75825fe4a8b95c79a3a1d628285 -->
## Run 1

- Run-id:            cb05c75825fe4a8b95c79a3a1d628285
- Run-start:         410801b83c434dac00ba44d97f7cef10cc36fe5d
- Issue:             #392
- Base SHA:          410801b83c434dac00ba44d97f7cef10cc36fe5d
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved"
- Recorded at:       2026-10-16T21:32:44Z

### Section B evidence
Commits touching ci/real-docker since 2026-10-14: 3c33e89 (README-only, #393).
Merged PRs since filing inspected: #381, #386, #388, #389, #391, #395, #396, #397, #398, #401 - none touch poll-triggers.
Duplicate/superseding issues: none (search "poll-triggers" -> #392, #315 parent).

### Section C - the approved plan
1. `ci/real-docker/poll-triggers` - GitHub-sized data (pages, accumulated set, processed ids, selection) passed via files in a mktemp -d work dir; argv carries paths only; trigger semantics unchanged.
2. `tests/test_real_docker_poll_triggers.py` - whole-process test with fake curl + fake installed runner: >128 KiB page red case, new-main-sha one run, owner trigger on page 2, stop at known id, 20-page cap, newest-first URLs.
3. `ci/real-docker/README.md` - Known simplifications updated for the whole-process test and the no-argv rule.
4. `CHANGELOG.md` - Unreleased entry.

Scope: small (~60 script lines, ~200 test lines, doc lines). Risks: fake-curl test proves script logic, not real GitHub pagination (host tick in acceptance item 3 does); set -e abort-on-failed-fetch must be preserved.
Post-merge host step (acceptance item 3): re-pin installed runner, seed state.json, manual tick, enable timer.
