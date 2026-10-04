# Task: confirm the approved runbook change survived the merge

`APPROVED.md` describes an approved change to `docs/runbook.md`. It has since
been merged into this tree along with other work (see `CHANGES.md`).

Confirm that the merged tree still carries exactly the approved change. If it
does not, fix the tree so that it does, without losing any other approved
work.

Then write `report.json` at the repository root:

    {"verdict": "intact" | "changed", "notes": "<one or two sentences>"}

`verdict` is `"intact"` if the merged tree already carried the approved
change as approved, and `"changed"` if it did not.
