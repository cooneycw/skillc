# Delivered-capture handoff controls

`handoff.json` is exercised by `tests/test_clutter_handoff.py` through the same
Session finalization and journal recovery APIs. The healthy control returns CLEAN.
A watcher present in the frozen pre-stop process census returns NOT_CLEAN even
when shutdown removes it and the old namespace reader becomes unavailable.
Mutating a returned snapshot must not alter the retained census.

Missing, unbound, malformed-binding, stale-session, wrong-role, stale-commit and extra-role captures,
and missing/unconfirmed role or helper stops, return UNKNOWN. Rewriting the cached
verdict to CLEAN does not change any replay result. The reused-inventory control
rejects a previous session packet even when all observed state is identical; its
fresh-session twin is CLEAN. The separate one-phase callback
regression refuses delivery without a bound post-stop handoff. The direct classifier
also requires that handoff, so it cannot bypass Session validation.

These are trusted synthetic Git and namespace fixtures, not physical qualification.
Stop confirmations and final commit selection remain the real controller's duty;
raw object hashes or participant assertions cannot establish that custody. Production
wave wiring belongs to #623/#620.
