# Goal custody controls

`cases.json` declares both custody verdicts. The healthy sealed journal verifies;
one-byte event alteration, removal of its seal, reordered records and an expected
context for another attempt must produce UNKNOWN with the independently held
reference. `tests/test_codex_goal_capture.py` executes each case against the real
verifier. It also compiles deliberately blind production variants: always
CAPTURED fails all four negative cases; always UNKNOWN fails healthy. The test
requires those exact disagreements, so a blind qualifier cannot pass silently.

These qualify a new instrument. Existing transport regressions are separately
run on actual pre-change source at `20bfbd4`, using only its existing API.
