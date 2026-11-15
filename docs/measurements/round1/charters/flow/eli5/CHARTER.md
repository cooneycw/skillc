---
contract: "flow-eli5"
subject: ".claude/commands/flow/eli5.md"
version: 1
intent:
  id: "flow-eli5.intent"
  draft: true
  what: "The post-analysis, pre-implementation communication and approval gate."
  evidence:
    - "eli5.md:8 (opening paragraph; no frontmatter description)"
purpose: "The post-analysis, pre-implementation communication and approval gate."
owner: "owner"
invariants:
  always:
    - id: "flow-eli5.always-1"
      draft: true
      column: "unknown"
      what: "Misread intent almost always hides in the motivation, not in the file list - Section C already covers the mechanics."
      evidence:
        - "eli5.md:82"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.always-2"
      draft: true
      column: "unknown"
      what: "**Section B depth floor (applies regardless of how concise the model is tuned to be):** the evidence must enumerate what was actually inspected - the commit SHAs (or an explicit `none touching <paths>`), the merged PR numbers, and the duplicate/superseding ..."
      evidence:
        - "eli5.md:125"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.always-3"
      draft: true
      column: "unknown"
      what: "An approval must always be attributable to someone who read Section C."
      evidence:
        - "eli5.md:181"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.always-4"
      draft: true
      column: "unknown"
      what: "The staleness check is only meaningful when it inspects history *after* the issue's `createdAt`; always anchor `git log --since` and the PR/issue searches to that timestamp."
      evidence:
        - "eli5.md:305"
        - "UNKNOWN: no usage log"
  never:
    - id: "flow-eli5.never-1"
      draft: true
      column: "unknown"
      what: "**The explain-like-I'm-five bar.** Someone who has never seen this codebase should finish Section A understanding what is wrong today and what will be better afterward."
      evidence:
        - "eli5.md:89"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.never-2"
      draft: true
      column: "unknown"
      what: "**Section C depth floor:** every file to create or modify gets its own numbered line with the gist of its change - never \"various files\" or a rolled-up description - plus a scope estimate (files, approximate lines) and at least ..."
      evidence:
        - "eli5.md:136"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.never-3"
      draft: true
      column: "unknown"
      what: "Never silently ignore them and never silently honor them."
      evidence:
        - "eli5.md:170"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.never-4"
      draft: true
      column: "unknown"
      what: "Never scan an issue body or a commit message for approval."
      evidence:
        - "eli5.md:177"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.never-5"
      draft: true
      column: "unknown"
      what: "A pipeline that cannot pause is a pipeline whose plans are never reviewed; run the gate, then hand the report to a reviewer or an orchestrating agent, rather than approving on their behalf."
      evidence:
        - "eli5.md:179"
        - "UNKNOWN: no usage log"
    - id: "flow-eli5.never-6"
      draft: true
      column: "unknown"
      what: "The template above is a floor, not a ceiling: fill every `{...}` slot with the actual evidence, files, and reasoning - never elide or compress a slot away, however terse the surrounding style."
      evidence:
        - "eli5.md:211"
        - "UNKNOWN: no usage log"
---

# Draft charter: flow-eli5

**Draft ready for owner confirmation.** Nothing here is approved.

From `eli5.md`, no model call.

## Sources

- **skill text:** `eli5.md`: a description and 15 stated duty candidate(s)
- **git history:** 13 commit(s), newest 7eaf6bf3 2026-11-14, oldest 6c8f9571 2026-06-28
- **usage records:** 0 record(s) for flow-eli5, flow:eli5 in 0 log(s); absences UNKNOWN (no usage log)
- **repository evidence:** missing (#718 build step 4)

## The three columns

| Column | Clause | Duty | Evidence |
|---|---|---|---|
| unknown | `flow-eli5.always-1` | Misread intent almost always hides in the motivation, not in the file list - Section C already covers the mechanics. | eli5.md:82; UNKNOWN: no usage log |
| unknown | `flow-eli5.always-2` | **Section B depth floor (applies regardless of how concise the model is tuned to be):** the evidence must enumerate what was actually inspected - the commit SHAs (or an explicit `none touching <paths>`), the merged PR numbers, and the duplicate/superseding ... | eli5.md:125; UNKNOWN: no usage log |
| unknown | `flow-eli5.always-3` | An approval must always be attributable to someone who read Section C. | eli5.md:181; UNKNOWN: no usage log |
| unknown | `flow-eli5.always-4` | The staleness check is only meaningful when it inspects history *after* the issue's `createdAt`; always anchor `git log --since` and the PR/issue searches to that timestamp. | eli5.md:305; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-1` | **The explain-like-I'm-five bar.** Someone who has never seen this codebase should finish Section A understanding what is wrong today and what will be better afterward. | eli5.md:89; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-2` | **Section C depth floor:** every file to create or modify gets its own numbered line with the gist of its change - never "various files" or a rolled-up description - plus a scope estimate (files, approximate lines) and at least ... | eli5.md:136; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-3` | Never silently ignore them and never silently honor them. | eli5.md:170; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-4` | Never scan an issue body or a commit message for approval. | eli5.md:177; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-5` | A pipeline that cannot pause is a pipeline whose plans are never reviewed; run the gate, then hand the report to a reviewer or an orchestrating agent, rather than approving on their behalf. | eli5.md:179; UNKNOWN: no usage log |
| unknown | `flow-eli5.never-6` | The template above is a floor, not a ceiling: fill every `{...}` slot with the actual evidence, files, and reasoning - never elide or compress a slot away, however terse the surrounding style. | eli5.md:211; UNKNOWN: no usage log |

## Further candidates, not drafted (5)

- never `eli5.md:228`: Section A's depth floor - motivation before mechanics, every technical term glossed on first use, and the bar that someone who has never seen the codebase finishes understanding what is wrong today and what will be better afterward - is ...
- never `eli5.md:252`: That path adds no blanket gate for ordinary implementation choices - those never return here - but it does NOT remove the existing route for a consequential change: altering promised behaviour or crossing a deliberate boundary still needs agreement from ...
- never `eli5.md:267`: It is a notice, never a stop: continue on every exit code.
- never `eli5.md:304`: It never writes implementation code; the only mutating action it suggests is `gh issue close` on a `No longer needed` verdict, and that is a recommendation for the reviewer to run.
- always `eli5.md:307`: The vendored core between the markers must stay byte-identical to the canonical https://github.com/cooneycw/eli5-gate copy; `scripts/eli5-core-drift.sh` checks this (advisory, fail-open).

## Limits

Per the round-1 spec (#726), the stated column undercounts, and `clause-backed` fails until round 3.

## Warnings

- frontmatter not read (no YAML frontmatter block); the whole file was read as text
