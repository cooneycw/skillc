# Contributing

Fixes need a regression test failing on the original source.


## Public gate and population requirements (revision 6)

`make check` is the public aggregate, and must actually exercise lint and the
test suite. Every executed checker must inspect a nonempty population: at least
one test function and at least one source module for lint/typecheck. Printed OK
or a printed count alone is not proof. Typecheck is required when its delivered
checker `ci/typecheck.py` or its Make target is present. The discrimination
fixture intentionally has neither; adding either makes typecheck applicable.

A no-op aggregate, omitted applicable stage or checker ignoring a relevant
planted defect cannot earn gate credit. The grader checks healthy twins and
planted bare-except, unannotated-function and pre-existing-test failures.
An unrelated checker crash, unavailable check or timeout is UNKNOWN evidence
of defect detection, never credit for catching the planted defect. This is
candidate-process probe evidence, not authenticated execution history.

Limitation: deleting BOTH an optional typecheck target and its checker cannot
be distinguished from legitimate absence in this delivered-capability contract.
This does not attest the immutable starting fixture's original obligations.

The restored-original-source regression is checked separately inside the test
stage. Lint/typecheck failure or aggregate failure alone never proves a new
regression test ran and rejected the original bug.

Inspection evidence is limited to nonempty whole-module bodies returned by
Python's standard Path.read_text/read_bytes, matching the delivered bytes.
Standalone stage reader signatures must match readers in the actual clean
public aggregate. Other IO, mismatched decoded bodies or ambiguous stage
signatures are unverified (UNKNOWN), even when the checker is otherwise valid.
Canaries alter a module from the observed delivered population, never a new file.

Applicability discovery supports literal Make rules, including multi-target and
space-indented definitions. Unsupported includes, conditionals, computed/escaped
or generated definitions yield UNKNOWN rather than proving typecheck absent.
Discovery does not evaluate Make; actual check/stage runs share an 85-second
cumulative launch budget (15 seconds per command) inside the 90-second probe.

Alternate default GNUmakefile or makefile entrypoints are unsupported (UNKNOWN),
even when their aggregate includes typecheck. The public command remains make check.
Trace limits: 128KiB of JSON bytes and 512 distinct source-read rows per process.
After 512 rows, any further qualifying read (even a duplicate) yields UNKNOWN.
