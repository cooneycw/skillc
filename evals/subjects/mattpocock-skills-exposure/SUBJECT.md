# Exposure evidence: mattpocock/skills (select: tdd, diagnosing-bugs)

- Declaration: [subject.json](subject.json) - the same locator/revision/skills_root/
  select as [../mattpocock-skills/subject.json](../mattpocock-skills/subject.json)
  (#11), with `exposure_schema: 1` added
- Adapter: `skillc exposure` ([skillc/exposure.py](../../../skillc/exposure.py), #55)
- Evidence: [report.json](evidence/report.json), first produced 2026-09-26 and
  re-run 2026-10-03 on main `36d9369`, after PR #169's four exposure fixes, with
  the same verdicts; the only change is the new `manifest_coverage` field.
  Both runs used a fresh clone at the pinned revision, real `codex-cli 0.157.1`
  (the re-run used the binary copied from the pinned trial image), no `always_loaded`
  or `index` declared - see [exposure-synthetic](../exposure-synthetic/SUBJECT.md)
  for those two layers

This is #55's real-collection evidence bullet ("one run against
mattpocock/skills, pinned, as in #11"): the skill-listing layer only, since
this subject has no declared always-loaded instruction file or on-demand
index of its own. Both selected skills (`tdd`, `diagnosing-bugs`) are
reported `EXPOSED` - present in `codex debug prompt-input`'s rendered
`<skills_instructions>` block, matching #11's own `discovery_canary:
SATISFIED` result via `skillc materialize`.

Refs #55, not Closes - the conformance run of exposure through one runner
across independently-authored subjects is a later concern, not this PR's.
