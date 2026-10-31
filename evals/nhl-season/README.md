# NHL season public task

[goal.md](goal.md) is the complete participant-facing contract for the NHL
2025-26 season project (#632, mapped by #631). It names the owner-approved
reconciliation families F1-F8, time/on-ice conventions, machine-readable reports
and the viewer's observable data hook. It contains no prescribed agent workflow.

This is a task contract, not a certified grader or an approved live declaration.
The reference copy/oracle (#633), served-data perturbations (#634), browser
grading (#635, deferred to the second run) and live declaration (#639) are
separate work. A grader may not add requirements absent from the public goal.
The declaration must freeze the exact goal bytes and SHA-256 before attempts;
changing this contract requires a new identity and cannot retroactively change
an attempt's requirements. No model calls or paid runs are authorized here.

## Source verification boundary

Issue #632 records verification of the five public endpoint families on
2026-10-29, with F1-F5 checked on game 2025020001. During this document's
preparation on 2026-10-30, one request to each endpoint family from the worker
container returned HTTP 403, including that game and schedule date 2025-10-07.
Those worker requests established no new source shapes. The controller later
verified boxscore field names for the population clarification below; a complete
private season copy, live oracle validation and measured census remain
outstanding. No NHL response data is committed.

F6 explicitly reports unavailable when recognizable independent shift-chart
goal entries are absent. F7 states an exact second/boundary convention; it does
not silently repair event-versus-shift disagreement. F8 distinguishes roster
membership from actual participation, so an unused backup need not have shifts.

Controller infrastructure preparation is described in [reference.md](reference.md).
Its synthetic controls are separate from actual private season acquisition.

## Population clarification (2026-10-30)

The [owner ruling on #632](https://github.com/cooneycw/skillc/issues/632#issuecomment-6527303250)
clarifies F4 as skaters only (forwards and defense); goalie rows are outside
that population. Goalies remain included in TOI and participation, while
reported shift-count comparisons remain skaters only in F5. The public goal
now says so explicitly. This changes the goal bytes and therefore requires a
new declaration digest; it does not retroactively change any attempt.

The controller verified three completed 2025-26 boxscores for this clarification:
goalie rows lack hits, blockedShots, giveaways, takeaways and shifts; skater
rows carry these fields. No downloaded response data is committed.

## Blocked-shot population clarification

The [controller measurement on #633](https://github.com/cooneycw/skillc/issues/633#issuecomment-6530830277)
compared three completed 2025-26 games. Excluding `details.reason` equal to
`teammate-blocked` matches boxscore blockedShots for all 108 skaters; counting
those events matches only 97. The goal and F4 oracle therefore exclude that
exact reason, while ordinary opposing-team blocks still count. Teammate-blocked
plays remain retained and remain in F7 strength-state checks. The synthetic
good source contains an authored case of each kind; no fetched NHL data is
committed. This clarification changes the goal bytes and eventual declaration
digest, without changing an already-run attempt.

Controller delivered-code replay preparation and its model-free controls are
in [rerun.md](rerun.md) (#634). Physical Docker qualification and validation on
an authorized private actual sample remain prerequisites for declared use.
