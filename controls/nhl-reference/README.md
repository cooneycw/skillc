# Synthetic NHL oracle controls

All inputs here are authored synthetic examples, not fetched NHL responses.
The IDs and compact roster/shift patterns are illustrative. No real player's
name or downloaded season data is included.

`good/sources.json` describes one three-period game with deliberately nonzero
event counts, both teams, skaters and goalies. Its blocked-shot fixtures
include an opposing-team block that counts and a teammate block that does not
(`details.reason: teammate-blocked`); both remain in F7. Goalie rows intentionally lack
the four skater event fields and a reported shift count, matching the controller
verification of three completed 2025-26 boxscores. The fixture names its expected
family statuses explicitly; an honest unavailable check is a correct report. `bad/cases.json` commits the
negative mutations and their explicit expected verdicts. There are 25 cases:
eight wrong delivered family values (FAIL), eight source discrepancies
(DISCREPANCY), missing family/check and wrong membership (FAIL), changed live
bytes (UNKNOWN), an empty schedule population (REFUSED), two partial-reference
unsupported-output cases (FAIL), and fabricated 0/0 PASS over missing input
(FAIL), plus a goalie incorrectly added to the F4 population (FAIL).
Honest UNAVAILABLE reporting is graded directly; missing is never zero.

Run `uv run python -m skillc.nhl_reference selftest`. It executes the actual
oracle/comparators/re-check, requires the complete case population, and refuses
if a bad input gets the other verdict. `tests/test_nhl_reference.py` also makes
each comparator deliberately blind and requires qualification itself to fail.
The ordinary test suite runs these controls; no live network or model is used.
