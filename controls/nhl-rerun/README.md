# Synthetic replay projects

All control sources are authored synthetic fixtures from `nhl-reference`.
They follow measured goalie and teammate-blocked shapes; no fetched NHL data
is committed. Qualification builds a disposable project with `project.py` and
an `oracle` package copied from the controller implementation. That is the
reference candidate only; no controller implementation or expected reports are
copied to delivered candidate containers.

The disposable project README documents its endpoint override `NHL_API_BASE`
and command `python3 project.py`. The reference retrieves schedule and all four
detailed endpoints through HTTP, stores them in SQLite and exports retained
payloads plus reconciliation. Modes are committed in [cases.json](cases.json):
strict refuses added fields, drop-fields loses them, never-discrepancy falsely
labels all checks PASS. Each must lose to the actual grader on the same cases
that the reference passes. Missing commands/exports and extra false positives
also fail. A reference using an alternate covered schedule date passes, so
qualification does not require one traversal order or every schedule alias. Qualification checks both the controls and deliberately blinded
versions of the grader.

No live model, external NHL requests, private data acquisition or Docker build
is part of these controls. Physical Docker isolation must additionally be
qualified before use in a declared run; fake Docker command tests cannot prove
kernel-level egress or custody isolation.
