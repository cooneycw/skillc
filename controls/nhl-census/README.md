# Synthetic census controls

All populations are authored synthetic status summaries, with no NHL data.
`cases.json` commits zero/nonzero discrepancy populations, wholly unavailable
populations, and mixed unavailable populations with/without discrepancies.
`grading_basis` states an obligation; `grading_status: NOT_GRADED` prevents a
census from claiming that any candidate or #634 plant has been graded.
`source_coverage: PARTIAL` preserves uncertainty when any game is unavailable.

`tests/test_nhl_census.py` drives the real census and qualifies a compiled variant
that drops `grading_basis`, requiring every committed case to detect it. It also
rejects variants that claim grading happened or erase unavailable coverage.
The same existing-API behavior tests run on `3f8355f` as genuine regression reds.
