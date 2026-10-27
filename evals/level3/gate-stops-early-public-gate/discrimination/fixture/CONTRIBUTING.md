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
