# NHL replay container-absence witness (Refs #634, #663)

These committed inspect results exercise the same predicate that the physical
replay test uses after cleanup. Docker 29's lowercase diagnostic and legacy
capitalized object/container diagnostics pass only with exit 1, an empty JSON
array, and the exact requested object name. Diagnostic wording is matched
without case sensitivity; object identity retains case sensitivity.

The existing-container and unrelated-error cases must be rejected. Wrong object
identity, contradictory or malformed output, and a different exit status must
also be rejected. An unavailable daemon is not proof that a container is gone.
The physical test additionally inspects its running witness container and
requires the predicate to reject that known-existing object.

`tests/test_nhl_rerun_absence.py` enumerates the expected case IDs explicitly, so
an empty or shortened case file fails rather than silently shrinking coverage.
These model-free controls require no Docker daemon. Run them with:

```bash
uv run pytest -n 0 tests/test_nhl_rerun_absence.py
```

The original assertion rejected `docker29-lowercase` and falsely accepted the
unrelated file-not-found error. The pre-fix control run failed seven cases and
passed five. Physical qualification remains the existing real-Docker CI lane;
these controls do not authorize a host run or runner re-pin.
