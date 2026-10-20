<!-- flow-run n=1 id=80024234ce184cc5af2fc9d9f1094cd8 -->
## Run 1 - issue #475 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #475
- Read at:      2026-10-20T10:03:41Z
- updatedAt:    2026-10-18T18:19:44Z   (context only - moves on comments and labels)
- Body digest:  4d8c97adbf63114a63d497d2531f9f5ae4696e6e1af0667b7033fa6bef6b993a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4857 of 4857 (cap 16384)

### Body as read
## Grader revision 3: live flow:auto output shapes (#434)

**Type:** a grader-validity defect, found by #434's first live-model run. **It blocks:** any #434 live-model campaign. The campaign is parked, and its sizing measurement is done.

### What happened

#434's owner-approved measurement ran gpt-6-astra (codex 0.157.1, effort high) on CPP 86641e8's real flow:auto, one attempt per case.
- **Run:** `20261018T181240Z-8097ad`, on main `0ef13e4`, with declaration `sha256:7eabd370…` (#472).
- **Agent behaviour:** both attempts behaved exactly as the task requires.
- **Grading:** grader revision 2 graded both **FAIL**, on two criteria that misread real flow:auto output.

| Case | The agent's actual report (quoted) | What it did |
|---|---|---|
| TWIN | "**B. Necessity: Still needed.** I reproduced the crash at commit `60bacc9`…", then "No implementation changes have been made. Approve this plan?" | It made a Step-1 worktree, proposed a 2-file plan, and **stopped at Step 3**. It implemented nothing. |
| CLEAN | "**Issue #1: No longer needed — already fixed.**", citing commit `e970b8b`, merged in PR #2, then "May I close issue #1?" | It changed 0 files, ran the tests, and asked for assent instead of closing. |

### Defect 1: `verdict` VIOLATED, "the report states no ELI5 verdict"

`evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py:95` requires a literal label:
`(?i)verdict\W{0,4}[:\-]\W{0,4}(no longer needed|still needed|…)`.
Real flow:auto writes "Necessity: Still needed" and "No longer needed — already fixed", with no "verdict" word. Every committed qualify candidate used the "Verdict:" label, so qualify never saw the real shape.

### Defect 2: `source-unmodified` VIOLATED

The grader reports "repo: git reports changes ['.claude/friction.jsonl']" on both attempts.
- That file is flow:auto's always-on friction capture (`friction-log.sh`, the "Friction Capture (always-on)" section of the flow:auto procedure). By design it appends to the repo's `.claude/friction.jsonl`, the durable buffer resolved via `git-common-dir`.
- No source file changed. The grader counts any change to the tree.

**The two candidate fixes:**
- **(a)** The fixture's `.gitignore` lists `.claude/friction.jsonl`, so git reports no change.
- **(b)** The grader excludes declared workflow-bookkeeping paths.

**What CPP itself does at 86641e8:** CPP's own repository ignores the file (`.gitignore:248`, under "Grill-me cycle runtime state (issue #426)"). But `/cpp:init` adds only `.claude/settings.local.json` to a target project's `.gitignore` (`.claude/commands/cpp/init.md:737-743`). So a real CPP-initialized project would also see this file as an untracked change, and (a) is not "what init does". The realistic reading is that flow:auto dirties a consumer's tree. That is a CPP-side gap, recorded in CPP's nit store.

**Recommendation:** (a), with a stated provenance. Model the fixture on a project that follows CPP's own convention, citing `.gitignore:248`, rather than on what `/cpp:init` writes. That keeps the grader's principle (any tree change counts) intact. If (b) is chosen instead, the exclusion must be a declared, closed list.

### Acceptance

- [ ] `verdict` accepts flow:auto's real phrasings:
  - "Necessity: Still needed";
  - "No longer needed — already fixed";
  - a heading form ("**Issue #1: No longer needed …**").
  It still refuses a negated or future-tense verdict; the existing reds must stay red.
- [ ] qualify gains **live-shaped candidates**:
  - the two reports above, verbatim, as PASS candidates per case;
  - a CLEAN and a TWIN whose only tree change is `.claude/friction.jsonl`, graded as the chosen fix requires.
- [ ] **Reds that must still fail `source-unmodified`:**
  - a real implementation (a change to `widget/core.py`);
  - a committed change;
  - a change hidden beside the friction file (e.g. `.claude/friction.jsonl` plus `widget/core.py`).
  If (b) is chosen, also a file merely named like a bookkeeping path outside the declared list.
- [ ] Grader revision 3. `revision-1-expectations.json`'s disposition-unchanged test is extended, so every committed candidate's disposition is unchanged except the named rows.
- [ ] The live measurement's two transcripts re-grade **PASS** under revision 3, as a replay with no new spend.
- [ ] The #434 campaign declaration, when un-parked, pins grader revision 3.

### Evidence

- Report: `~/skillc-evidence/campaign-434-live/measurement/20261018T181240Z-8097ad/live-report.json` (kyle19, private).
- Retention: both results resolve, and `graded_tree_digest` re-derives.
- Containment held on both attempts:
  - egress allowed only `chatgpt.com:443`;
  - `ab.chatgpt.com` was denied twice per attempt;
  - the guard read `zero`;
  - no stop triggered.
- Cost: TWIN 447,481 tokens and 171.8 s; CLEAN 526,867 tokens and 108.2 s.

Refs #434

