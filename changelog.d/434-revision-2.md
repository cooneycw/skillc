- **#434 grader revision 2: the flow-auto-necessity fixture gains a gate surface, and
  qualify models production's empty report** (#434).
  - `builder/build.py` writes a Makefile with explicit `lint`, `test`, `typecheck` and
    `verify` rules (standard library only; weaker than ruff and mypy, and the README says
    so). The pinned CPP finish gate now subsumes them and exits `ok`. The marker lines
    for revision 1, revision 2 and a broken tree are committed and tested.
  - `regenerate.py` re-derives every fixture SHA from the builder, rewriting only
    prefixes of real revision-1 objects.
  - qualify passes an empty report as `None`, as `codex_run_metadata` does. The
    empty-report candidates move to `inconclusive/`; new `untouched-said-nothing-useful`
    candidates keep the FAIL coverage. `check_untouched` refuses an `untouched-*` PASS.
  - Calibration and matched-pilot summaries are tested to count INCONCLUSIVE as not
    passed, in the denominator.
  - `campaign-434/manifest.json` is re-frozen as revision 2: 48 rows (40 scored, 5
    observed, 3 guard). The witnessed gate's passed run is now scored.
  - `tests/test_codex_guard_live.py` builds its own trial image unless
    `SKILLC_TRIAL_IMAGE` is set, and is declared a real-Docker file.
  - PR CI's gate step installs `make`, so the fixture's gate-surface controls run there.
    `git-tests-control` now refuses a make-named skip, with a `bad-make-skip` fixture.
