# Flow run record - issue #431

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=704e1ef3144243f08bf9936ede592e87 -->
## Run 1

- Run-id:            704e1ef3144243f08bf9936ede592e87
- Run-start:         4bab8d3fd4da032d87f9c31c23e1dac8a1d7e651
- Issue:             #431 (research-only run: decides the design; no implementation)
- Base SHA:          4bab8d3
- Necessity verdict: Needs reframing (design blocked under frozen graders; research ordered to decide it)
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-requested assignment), 2026-10-17: "Deliverable: a Markdown file docs/research/clean-project-case-2026-10.md ... No implementation, no paid model runs, nothing on evals26"
- Recorded at:       2026-10-17T19:30:00Z

### Section B evidence
- #431 filed today; no commits, PRs or duplicates. The prior ELI5 (sent to skillc-400) showed regression-fails-on-original cannot apply to a no-change run and level3_campaign.py:187 allows no clean start; the owner paused design pending research.

### Section C - the approved plan
1. `docs/research/clean-project-case-2026-10.md` - the research note: no-change cases in the benchmark literature with pins/licences, a ranked #431 recommendation, Kyle opportunities with integrity risks and first steps.
2. `docs/research/README.md` - index entry for the note.

Scope: docs only.
Risks: a claim from a summary taken as read - every claim is marked read / read (summary) / inferred / UNVERIFIED, and the load-bearing ones were re-checked directly.
