- **#434 live-campaign wiring: `skillc level3-live` runs the model on the fixture-service task**
  (#434). Nothing in this change spends; the declaration is a draft.
  - `skillc/fixture_live.py` adds the `level3-fixture-live-declaration`, with the cases CLEAN and
    TWIN as its arms. It reuses calibration's C1-C5 validators, its derived case order and its
    whole-declaration approval digest. The prompt (`goal.md` plus a declared instruction) and the
    fixture (the builder, and each case's re-built base tree) are identities.
  - A native containment stop: a server-side tool use or unavailable census, an unread or
    out-of-allowlist egress log, or a nested or unknown codex count stops the schedule. It
    replaces, for this path, #287's external watcher, with one committed red per trigger.
  - `--rehearse dry` (no container) and `--rehearse actor` (the live path with a scripted actor
    and a dummy credential) spend nothing, and may run an unapproved declaration.
  - The report records per-attempt tokens. There is no token cap in the stack; only wall time
    is capped, and the report says so.
  - `evals/level3/campaign-434-live/measurement-declaration.json`: the DRAFT measurement
    (1 CLEAN + 1 TWIN), unapproved.
