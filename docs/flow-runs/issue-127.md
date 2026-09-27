# Flow run record - issue #127

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #127
- Base SHA:          fd144d1
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved"
- Recorded at:       2026-09-27T12:20:00Z

## Section B evidence
- commits: none touching skillc/lifecycle.py or skillc/trial.py since fd144d1
- PRs: none merged; open #126 touches skillc/collection_conformance.py (same paste-back block) but not lifecycle.py/trial.py
- dup/super: none (#79 scoped persisting teardown out; this reopens only the journal half)

## Section C - the approved plan
1. `skillc/lifecycle.py` - cleanup_workspace() before finalize(); journal a backend-teardown detail event; update docstring
2. `skillc/trial.py` - add backend-teardown to _DETAIL_EVENTS (journal-only; LIFECYCLE_EVENTS and v2 schema unchanged)
3. `skillc/collection_conformance.py` - paste-back gains backend_teardown= and cleanup= lines (after #126 merges)
4. `tests/test_lifecycle.py` - persisted cleanup is removed through the backend path (red on old order); backend-teardown journal event confirmed / unknown
5. `tests/test_collection_conformance.py` - paste-back prints both new lines
6. `docs/specs/evaluation-facility/failure-matrix.md` - teardown outcome is now also journalled

Scope: 6 files, ~80 lines. Risks: a test pinning the old "partial" outcome; check_records must accept the new detail event; ordering vs #126.
