---
contract: "flow-auto"
subject: ".claude/commands/flow/auto.md"
version: 1
intent:
  id: "flow-auto.intent"
  draft: true
  what: "Worktree → issue analysis → approved plan → implementation → PR → merge → deploy."
  evidence:
    - "auto.md:3 (opening paragraph; no frontmatter description)"
purpose: "Worktree → issue analysis → approved plan → implementation → PR → merge → deploy."
owner: "owner"
invariants:
  always:
    - id: "flow-auto.always-1"
      draft: true
      column: "unknown"
      what: "**CRITICAL: You MUST create or enter a worktree before proceeding."
      evidence:
        - "auto.md:82"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.always-2"
      draft: true
      column: "unknown"
      what: "Cleanup is ALWAYS the git fallback (issue #627); on `LANE=current-branch` there is no worktree, so just delete the branch."
      evidence:
        - "auto.md:1177"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.always-3"
      draft: true
      column: "unknown"
      what: "Resolved like `/project:next`: an existing directory path first, else `~/Projects/<PROJECT>`; must be a git checkout."
      evidence:
        - "auto.md:12"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.always-4"
      draft: true
      column: "unknown"
      what: "Keys: `LANE` (`current-branch|fresh|resume|remote-pickup|local-pickup|cross-repo`), `CROSS_REPO`, `GIT_LANE` (always `GIT_LANE=1`: enter with `cd`, git cleanup at Step 7), `SESSION_CWD`, `SESSION_CWD_INFERRED`, `TARGET_REPO`, `COMPOSE_PROJECT_NAME` (the compose pin for the whole run, issue #626), `ISSUE_STATE`, `ISSUE_TITLE`, `BRANCH`, `WT_PATH`, `DEFAULT_BRANCH`, `REMOTE_BRANCH`, `WT_CREATED` (1 = the helper already ..."
      evidence:
        - "auto.md:120"
        - "UNKNOWN: no usage log"
  never:
    - id: "flow-auto.never-1"
      draft: true
      column: "unknown"
      what: "NEVER implement changes directly on main/master."
      evidence:
        - "auto.md:82"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.never-2"
      draft: true
      column: "unknown"
      what: "NEVER use `git stash push` or a bare `git stash pop`: the stash stack is shared by every worktree."
      evidence:
        - "auto.md:594"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.never-3"
      draft: true
      column: "unknown"
      what: "A SKIP IS A RECORDED STATE, NEVER AN OMISSION.** **IT COMES BEFORE THE QUALITY GATES, deliberately**: accepted findings are fixed in the worktree, and the gates must see those fixes."
      evidence:
        - "auto.md:682"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.never-4"
      draft: true
      column: "unknown"
      what: "Write the receipt - ALWAYS, including on a skip.** The writer DERIVES both identities and REFUSES to write when it cannot; never hand it a model name:"
      evidence:
        - "auto.md:758"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.never-5"
      draft: true
      column: "unknown"
      what: "Report the helper's handoff message and leave the worktree, branch, and PR INTACT - do NOT run cleanup, do NOT retry, and NEVER re-invoke with `--admin` yourself."
      evidence:
        - "auto.md:1111"
        - "UNKNOWN: no usage log"
    - id: "flow-auto.never-6"
      draft: true
      column: "unknown"
      what: "Never log the **permission-prompt** class by hand (issue #482)."
      evidence:
        - "auto.md:73"
        - "UNKNOWN: no usage log"
---

# Draft charter: flow-auto

**Draft ready for owner confirmation.** Nothing here is approved.

From `auto.md`, no model call.

## Sources

- **skill text:** `auto.md`: a description and 78 stated duty candidate(s)
- **git history:** 128 commit(s), newest c566b3a2 2026-11-13, oldest 3891c530 2026-02-16
- **usage records:** 0 record(s) for flow-auto, flow:auto in 0 log(s); absences UNKNOWN (no usage log)
- **repository evidence:** missing (#718 build step 4)

## The three columns

| Column | Clause | Duty | Evidence |
|---|---|---|---|
| unknown | `flow-auto.always-1` | **CRITICAL: You MUST create or enter a worktree before proceeding. | auto.md:82; UNKNOWN: no usage log |
| unknown | `flow-auto.always-2` | Cleanup is ALWAYS the git fallback (issue #627); on `LANE=current-branch` there is no worktree, so just delete the branch. | auto.md:1177; UNKNOWN: no usage log |
| unknown | `flow-auto.always-3` | Resolved like `/project:next`: an existing directory path first, else `~/Projects/<PROJECT>`; must be a git checkout. | auto.md:12; UNKNOWN: no usage log |
| unknown | `flow-auto.always-4` | Keys: `LANE` (`current-branch\|fresh\|resume\|remote-pickup\|local-pickup\|cross-repo`), `CROSS_REPO`, `GIT_LANE` (always `GIT_LANE=1`: enter with `cd`, git cleanup at Step 7), `SESSION_CWD`, `SESSION_CWD_INFERRED`, `TARGET_REPO`, `COMPOSE_PROJECT_NAME` (the compose pin for the whole run, issue #626), `ISSUE_STATE`, `ISSUE_TITLE`, `BRANCH`, `WT_PATH`, `DEFAULT_BRANCH`, `REMOTE_BRANCH`, `WT_CREATED` (1 = the helper already ... | auto.md:120; UNKNOWN: no usage log |
| unknown | `flow-auto.never-1` | NEVER implement changes directly on main/master. | auto.md:82; UNKNOWN: no usage log |
| unknown | `flow-auto.never-2` | NEVER use `git stash push` or a bare `git stash pop`: the stash stack is shared by every worktree. | auto.md:594; UNKNOWN: no usage log |
| unknown | `flow-auto.never-3` | A SKIP IS A RECORDED STATE, NEVER AN OMISSION.** **IT COMES BEFORE THE QUALITY GATES, deliberately**: accepted findings are fixed in the worktree, and the gates must see those fixes. | auto.md:682; UNKNOWN: no usage log |
| unknown | `flow-auto.never-4` | Write the receipt - ALWAYS, including on a skip.** The writer DERIVES both identities and REFUSES to write when it cannot; never hand it a model name: | auto.md:758; UNKNOWN: no usage log |
| unknown | `flow-auto.never-5` | Report the helper's handoff message and leave the worktree, branch, and PR INTACT - do NOT run cleanup, do NOT retry, and NEVER re-invoke with `--admin` yourself. | auto.md:1111; UNKNOWN: no usage log |
| unknown | `flow-auto.never-6` | Never log the **permission-prompt** class by hand (issue #482). | auto.md:73; UNKNOWN: no usage log |

## Further candidates, not drafted (68)

- never `auto.md:85`: Enter with `cd`; never call `EnterWorktree`.
- never `auto.md:90`: **Invocation discipline (issue #581):** call flow helpers BARE, with literal argument values - never wrapped in `if [ -x ... ]`, never chained with `&&` or `;`, never followed by `echo $?`.
- never `auto.md:108`: **Pass `--session-cwd` (issue #592).** Pass the directory this session reports as its cwd VERBATIM as a literal path - never `$(pwd)`.
- never `auto.md:175`: The last two are ADVISORY, never a precondition: `CLAIM=self` means the worktree is locked to this session (issue #597); `STASH_GUARD=disabled` means the repository recorded `cpp.stashGuard=false`; `STASH_GUARD=unknown` means the shared-stash guard (`scripts/stash-worktree-guard.sh`, issue #1056) was not found.
- never `auto.md:239`: Inside a generated Codex skill, use the skill's own bundled copy, `${CPP_SKILL_DIR:-/dev/null}/scripts/<name>` (issue #1542) - never a `scripts/` directory in the target project.
- never `auto.md:267`: An **Unresolved** or **Capped** note means the context is incomplete - never that the task has no constraints.
- never `auto.md:327`: Depth floor: one numbered line per file with its change gist - never "various files" - plus a scope estimate and at least one named risk (or an explicit "no notable risks").
- always `auto.md:337`: **Approval:** Always **pause and wait for reviewer approval** of the plan before continuing to Step 4.
- never `auto.md:345`: If a caller passes one, say the gate is not skippable and pause anyway - never honor it silently and never ignore it silently.
- never `auto.md:348`: An `eli5: auto-approve` trailer in the issue body or the HEAD commit message: **never read**.
- never `auto.md:368`: Pass the Step-1 `WT_PATH` verbatim as the literal argument - DECLARED, never inferred from the Bash cwd (issue #1271, the #614 rule); `FLOW_LIVE_DRIVER_PATH:` must name the run's worktree:
- never `auto.md:382`: **Early stale-base check (issue #473) - run BEFORE editing.** Bare, advisory (warns, never blocks).
- always `auto.md:383`: Pass the worktree path from the Step-1 contract (`WT_PATH`) verbatim as the trailing literal argument (issue #614, the #592 rule); the emitted `FLOW_STALE_PATH:` line must name the run's worktree:
- never `auto.md:396`: If git refuses to START the merge, commit first (`git add -A` + `git commit -m "wip(flow): pre-merge snapshot"`) and merge on the clean tree - never stash: the stash stack is SHARED across every worktree (#635).
- never `auto.md:406`: **Only after approval is granted, and never before**, and only after the two checks above, write THIS RUN's approved plan.
- never `auto.md:410`: Then APPEND this run's fields - never rewrite the file or edit an earlier run's section:
- never `auto.md:436`: **Adopting found or dirty work (issue #1504).** Only if you deliberately preserved pre-existing or dirty work by committing it unmodified as its own commit, run `declare-salvage` with that commit's sha right after `begin-run` (it refuses a sha that is not ...
- never `auto.md:468`: Proceed; Step 6 will report drift as unresolved, never clean.
- never `auto.md:472`: **Worktree path-resolution rule (issue #486).** Resolve every edit path from the active worktree root - `git rev-parse --show-toplevel` - never a hand-built `.claude/worktrees/<name>/...` absolute path.
- always `auto.md:482`: **Read the `FLOW_WORKTREE_GUARD:` line (issue #1014)**, which is always printed:
- never `auto.md:489`: Never revert main content you did not write; if it is someone else's, stop and report it.
- never `auto.md:494`: Never read or summarise it as "no leak".
- never `auto.md:496`: Only 3 stops: never run this under `set -e` or behind `\|\| stop`.
- never `auto.md:527`: An explicit constraint remains binding even when no rationale is recorded for it (see [the issue contract](../../../docs/agents/issue-contract.md)): a missing reason is something to surface, never grounds to drop it.
- always `auto.md:586`: Pass the worktree path as the trailing literal argument (issue #614); `FLOW_STALE_PATH:` must name this run's worktree:
- never `auto.md:595`: Then call the Codex re-sync helper UNCONDITIONALLY - keyed on the diff, not the base, never re-gated on a path pattern (#1136).
- never `auto.md:628`: **Closing must agree with that judgement.** When the accounting is not complete, use the non-closing `Refs #N` - in the commit message, the PR title and the PR body alike, never `Closes #N`.
- never `auto.md:632`: A revision record on its own is never delivery evidence.
- never `auto.md:644`: Select the reference here, defaulting to NON-closing and never inheriting a value from an earlier run.
- never `auto.md:658`: If you collapse anyway, collapse onto your ORIGINAL base, never a moved `origin/main`; prove the staged deletions are empty (unless intended) before committing; THEN bring the moved base in:
- never `auto.md:669`: **Never collapse AFTER the counter-model receipt (item 1 below) has been written for this branch's current commits (Nit Store #864).** The enrolment check accepts only the receipted commit or a descendant (`git merge-base --is-ancestor`).
- always `auto.md:672`: If you must collapse afterwards, re-run the review and write a fresh receipt; pick up a moved base with `git merge` instead.
- never `auto.md:680`: **THE RULE IS A PROPERTY, NOT A TOOL NAME: the reviewing model must not be the implementing model.** `/codex:code_review` satisfies it today.
- never `auto.md:717`: **The probe is ADDITIVE, never a replacement**: a codex that is installed but cannot review must still land in `reviewer-unavailable` via 1c.
- always `auto.md:722`: **Select evidence independently of runtime (issue #1584).** The reviewer must differ from every implementing model, including models earlier in the same retained session, and must have genuine runtime evidence (a Codex thread/rollout or a Claude session).
- never `auto.md:725`: When no eligible reviewer can run, record `reviewer-unavailable`; never fabricate a stream or copy a model from a banner.
- never `auto.md:745`: Later accepted fixes: STOP, ask the approver before each further pass; never receipt unreviewed commits or false counts.
- never `auto.md:749`: `COUNTER_MODEL_REVIEW: unparseable` (non-zero) - **This is not a clean review.** Record `skipped` with reason `reviewer-unavailable`; never a `ran` receipt with zeros.
- never `auto.md:752`: `COUNTER_MODEL_REVIEW: format-mismatch` (non-zero, issue #1259) - **the review HAPPENED, so this is never a skip.** Ask the reviewer once to restate its findings in the prescribed `### [SEVERITY] title` shape and parse again; if it still does not comply, triage ...
- never `auto.md:797`: **The PR body block below is a RENDERING of the receipt, never the source.** Append it to the PR body in item 5; a skipped stage appends the one-line skip note and its receipt path instead:
- never `auto.md:826`: **A run with no `FLOW_FINISH_GATE:` verdict line did not run the gate: **STOP** (issue #1547).** The trigger is the verdict LINE, never the exit code: 127, 126 (an unset `CPP_SKILL_DIR`), 2, only the `FLOW_FINISH_GATE_EXIT=` trailer, or nothing at all, gave ...
- never `auto.md:830`: It is NOT `skipped`, and the run never commits, pushes or merges on it.
- never `auto.md:836`: Proceed, but report the counts verbatim and say plainly that this gate proved nothing about the change; never "tests passed".
- never `auto.md:838`: `warn` also means a test failed and PASSED on re-run (issue #769): report the ids on the `RERUN_PASSED:` line and never call the run a clean pass.
- never `auto.md:843`: Proceed, but **repeat the runner's warning verbatim rather than paraphrasing it**; never "the gates passed".
- never `auto.md:879`: A `Co-Authored-By: <name> <noreply@anthropic.com>` trailer naming the current session's own assistant model - never a literal copied from this document (issue #1037)
- never `auto.md:920`: Write the reason in the PR; never edit the plan to make it agree.
- never `auto.md:922`: `PLAN_COMPLIANCE: unknown` (exit 4) - never report it as agreement.
- never `auto.md:989`: The Codex re-sync is called UNCONDITIONALLY here too (never re-gated on a path pattern,
- never `auto.md:1012`: **If the merge changed the branch**, re-run the FULL quality gate - the same Step-6 helper, invoked BARE as a separate call (#613; the #581 discipline - never fold it back into a compound block).
- always `auto.md:1051`: (`--strict-event` makes the required lane, named by `FLOW_CI_EVENT`, a FILTER: an absent required-lane pipeline stays `not-found` and the wait continues.) On `stalled` (issue #1552) the pipeline is dead, not slow: do not merge and do not keep waiting - report ...
- never `auto.md:1056`: On `success`, invoke the merge helper at once, PINNED to the sha that wait was keyed on (issue #1543): pass `--match-head-commit <pr-head-sha>` to the helper, never to a plain `gh pr merge`.
- never `auto.md:1064`: Never use plain `gh pr merge --delete-branch` from a linked worktree (issue #461):
- never `auto.md:1102`: **`MERGE_RC` 12 is the MISSING-HELPER REFUSAL (issue #1543), and the helper never emits it.** Nothing was merged.
- always `auto.md:1103`: **STOP** and report that `/flow:repair` must run.
- never `auto.md:1104`: Never finish the merge by hand with `gh pr merge`.
- never `auto.md:1106`: It is **never retried and never escalated to `--admin`**.
- never `auto.md:1117`: Flow itself never sets this variable.
- never `auto.md:1178`: **CRITICAL: `cd` to the main repo BEFORE removing the worktree - never remove a worktree while your cwd is inside it.
- never `auto.md:1194`: Report it and stop; never retry with an override reflexively, and never with `--steal` - that is the user's call.
- always `auto.md:1219`: Derive the paths in THIS call (`WORKTREE_PATH` must be set in it too) and record the refusal in a per-worktree marker FILE:
- never `auto.md:1351`: The helper never cancels.
- never `auto.md:1358`: **Read `FLOW_CI_WAIT` first (issue #1262):** with `FLOW_CI_WAIT: expired (<N>s)`, say that no matching pipeline was found AT EXPIRY of that window - not "CI may not be wired", and not that one never registered.
- never `auto.md:1362`: Report the named evidence gap; an unexamined lane is not green, and a fallback probe's result never establishes recorded-provider completeness.
- never `auto.md:1465`: A ROLLBACK verdict is surfaced, never acted on automatically.
- always `auto.md:1480`: `## TO-DO (owner)` - FIRST and always present.
- never `auto.md:1489`: Demoted, never deleted.
- never `auto.md:1564`: Never filter a rollout, choose a manual model window, invent a skip or bypass enrollment.

## Limits

Per the round-1 spec (#726), the stated column undercounts, and `clause-backed` fails until round 3.

## Warnings

- frontmatter not read (no YAML frontmatter block); the whole file was read as text
