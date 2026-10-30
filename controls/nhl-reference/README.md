# Synthetic NHL oracle controls

All inputs here are authored synthetic examples, not fetched NHL responses.
The IDs and compact roster/shift patterns are illustrative. No real player's
name or downloaded season data is included.

`good/sources.json` describes one three-period game with deliberately nonzero
event counts, both teams, skaters and goalies. `bad/cases.json` commits the
negative mutations and their explicit expected verdicts. There are 21 cases:
eight wrong delivered family values (FAIL), eight source discrepancies
(DISCREPANCY), missing family/check and wrong membership (FAIL), changed live
bytes (UNKNOWN), and an empty schedule population (REFUSED).

Run `uv run python -m skillc.nhl_reference selftest`. It executes the actual
oracle/comparators/re-check, requires the complete case population, and refuses
if a bad input gets the other verdict. `tests/test_nhl_reference.py` also makes
each comparator deliberately blind and requires qualification itself to fail.
The ordinary test suite runs these controls; no live network or model is used.
