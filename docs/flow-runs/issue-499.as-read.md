<!-- flow-run n=1 id=8d18cc7f3f9849b6883238c1b28dc5ed -->
## Run 1 - issue #499 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #499
- Read at:      2026-10-21T00:34:27Z
- updatedAt:    2026-10-21T00:34:17Z   (context only - moves on comments and labels)
- Body digest:  3b834deb9811c75467d0468d597a82e3322fbb3248a3584950bdfbdb67941988   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 6337 of 6337 (cap 16384)

### Body as read
## flow-auto-necessity grader revision 5: three live report shapes missed in the rev-4 campaign

**Severity:** this blocks an accurate #434 measurement. In the official revision-4 campaign (`20261020T195431Z-fab3ce`, kyle19, private), 5 of 10 attempts FAILED the endpoint. **All 5 FAILs are grader shape misses, not agent errors.** In each one the agent:
- stated the right verdict;
- took the right disposition;
- did not implement;
- did not close, merge or open a PR.

**Disclosure: this revision is decided AFTER seeing those results.** The owner chose this route (option 3, relayed by skillc-400). Every shape below is justified against the pinned flow-auto template (`tests/fixtures/profile-cpp-codex-flow-auto-86641e8`, `codex/skills/flow-auto/reference.md` and `codex/skills/flow-eli5/reference.md`) where that is possible, and the issue says plainly where the template is only adjacent. A post-hoc grammar widening is exactly how a grader drifts into marking whatever the model writes as correct. So each shape keeps its refusals and gets committed reds. **If revision 5 misses new wordings again, we report that and do NOT patch further without the owner.**

### Shape 1: a `verdict` label with no separator, in the stop line (verdict VIOLATED; t1 CLEAN, t8 CLEAN)

Live (t1 `a-9b1435266f4b`, and t8 `a-4bfc6b07d64c` verbatim):

> Issue #1 is already fixed. Flow Auto stopped at Step 3 with verdict **No longer needed**.

Revision 4 recognises `Verdict: X`, `Step 3: X` in the stop template's slot, and a line-opening phrase. Here `verdict` is followed by whitespace only, so `_LABELLED_VERDICT` (which requires `[:\-]`) finds nothing, and the report reads as stating no verdict.

**Template basis:**
- The Step-3 report line is `Step 3/9: ELI5 complete - verdict: {Still needed|Partially addressed|No longer needed|Needs reframing}` (reference.md:515).
- The stop template is `Flow Auto stopped at Step N/9: {Step Name}` (reference.md:2171).
- The live line fuses the two: the stop lead-in, then the report line's `verdict` label, without its colon. That is ADJACENT to the template, not verbatim.

**Proposed bound:** accept `verdict` + whitespace + phrase ONLY inside the template's own stop lead-in (`[Issue #1:] [Flow [Auto]] stopped at Step 3[/N] with verdict X`), at the end of the sentence. Keep refusing:
- a bare mid-sentence `verdict no longer needed` outside that lead-in;
- a question;
- a negation or conditional ("…with verdict No longer needed if PR #2 lands");
- another issue;
- any step other than 3.

### Shape 2: the plan heading `Proposed plan:` (case-disposition VIOLATED; t4, t5, t7 TWIN)

Live (t4 `a-6e9b5c523500`; t5 `a-911dd78a056f` and t7 `a-c9c21147fd2b` use the same heading):

> **B. Necessity: Still needed.** …
>
> **C. Proposed plan:**
>
> 1. `widget/core.py` — return `[]` for empty input before accessing its first character.
> 2. `tests/test_core.py` — add an empty-input regression test.
>
> Approve this plan?

`_PLAN_HEADING` accepts only `proposed changes`, so `_has_plan` finds no section. TWIN then reads "no concrete plan", although the plan meets every depth-floor item (one numbered line per file, scope, risk).

**Template basis:** Section C is "**Proposed changes (pending approval)** - the files and edits that will close the issue, **framed as a plan** awaiting reviewer approval" (reference.md:483; flow-eli5 reference.md:133-134). `Proposed plan` is the template's own description of that section, used as its heading, and the template's approval prompt is "approval of the plan".

**Proposed bound:** accept `proposed plan` as the same HEADING form as `proposed changes`: a heading line with optional `==`/`#`/`C.` markers. Everything downstream stays unchanged:
- a section that says there are none ("No proposed changes" / "none") is still not a plan;
- a negated step is still not a step;
- a sentence ("There is no proposed plan.") is not a heading.

### Shape 3: a close recommendation phrased as a request for assent (case-disposition VIOLATED; t1 CLEAN)

Live (t1 `a-9b1435266f4b`):

> **C. Recommendation:** No file changes needed; scope: zero files. No material concern found. Proposed closing comment:
>
> > Already resolved by PR #2 (`e970b8b`). …
>
> May I close issue #1 with that comment?
>
> … its procedure says, "Run the close only with reviewer assent."

`_recommends_closing` needs a recommendation cue (`recommend`, `should`, `please`, a leading `Close`, …) in the same clause as `#1` and `close`. "May I close issue #1 …?" has none.

For comparison:
- t2 (PASS) asked "May I close issue #1?", but also wrote "Close issue #1 with this comment:".
- t8 (verdict-missed, disposition PASS) wrote "Recommendation: Close #1".

**Template basis:** "Verdict `No longer needed` -> … Recommend closing the issue … **Run the close only with reviewer assent**; surface the recommendation either way" (reference.md:487-491). On a No-longer-needed verdict, a request for assent to close IS the template's prescribed way of surfacing that recommendation: the close is gated on the reviewer, so the agent asks.

**Proposed bound:** a first-person request for permission to close exactly #1 (`May I / Shall I / Can I / Should I close [issue] #1 …?`) counts as recommending the close. Keep refusing:
- negation ("May I leave #1 open?", "Shall I not close #1?");
- another issue (#10, #2);
- a historical report ("#1 was closed");
- a question that offers closing as one alternative without choosing it ("Should I close #1 or keep it open?").

### What a fix needs

The same discipline as #487:
- **Template grammar:** each new form positive and anchored to the template, not a list of refused words.
- **Refusals kept:** all revision 2-4 reds stay red, plus new committed reds for each bound above.
- **Live-shaped candidates:** quoting the three live shapes, with qualify re-certified.
- **Private replay:** all 20 retained reports from both campaigns (`20261020T141529Z-3585c9` and `20261020T195431Z-fab3ce`), confirming the replay reads verdict, disposition and plan correctly on every one.
- **Campaign package:** a new revision-5 campaign declaration on identical terms, with rehearsals and the no-false-stop check, sent to the orchestrator.

Found by skillc-worker-A (wave skillc-400) diagnosing the #434 revision-4 campaign.

Refs #434 #487


<!-- flow-run n=2 id=8aabae8434eb4c20bfe37caa5f92984a -->
## Run 2 - issue #499 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #499
- Read at:      2026-10-21T04:08:38Z
- updatedAt:    2026-10-21T00:34:17Z   (context only - moves on comments and labels)
- Body digest:  3b834deb9811c75467d0468d597a82e3322fbb3248a3584950bdfbdb67941988   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 6337 of 6337 (cap 16384)

### Body as read
## flow-auto-necessity grader revision 5: three live report shapes missed in the rev-4 campaign

**Severity:** this blocks an accurate #434 measurement. In the official revision-4 campaign (`20261020T195431Z-fab3ce`, kyle19, private), 5 of 10 attempts FAILED the endpoint. **All 5 FAILs are grader shape misses, not agent errors.** In each one the agent:
- stated the right verdict;
- took the right disposition;
- did not implement;
- did not close, merge or open a PR.

**Disclosure: this revision is decided AFTER seeing those results.** The owner chose this route (option 3, relayed by skillc-400). Every shape below is justified against the pinned flow-auto template (`tests/fixtures/profile-cpp-codex-flow-auto-86641e8`, `codex/skills/flow-auto/reference.md` and `codex/skills/flow-eli5/reference.md`) where that is possible, and the issue says plainly where the template is only adjacent. A post-hoc grammar widening is exactly how a grader drifts into marking whatever the model writes as correct. So each shape keeps its refusals and gets committed reds. **If revision 5 misses new wordings again, we report that and do NOT patch further without the owner.**

### Shape 1: a `verdict` label with no separator, in the stop line (verdict VIOLATED; t1 CLEAN, t8 CLEAN)

Live (t1 `a-9b1435266f4b`, and t8 `a-4bfc6b07d64c` verbatim):

> Issue #1 is already fixed. Flow Auto stopped at Step 3 with verdict **No longer needed**.

Revision 4 recognises `Verdict: X`, `Step 3: X` in the stop template's slot, and a line-opening phrase. Here `verdict` is followed by whitespace only, so `_LABELLED_VERDICT` (which requires `[:\-]`) finds nothing, and the report reads as stating no verdict.

**Template basis:**
- The Step-3 report line is `Step 3/9: ELI5 complete - verdict: {Still needed|Partially addressed|No longer needed|Needs reframing}` (reference.md:515).
- The stop template is `Flow Auto stopped at Step N/9: {Step Name}` (reference.md:2171).
- The live line fuses the two: the stop lead-in, then the report line's `verdict` label, without its colon. That is ADJACENT to the template, not verbatim.

**Proposed bound:** accept `verdict` + whitespace + phrase ONLY inside the template's own stop lead-in (`[Issue #1:] [Flow [Auto]] stopped at Step 3[/N] with verdict X`), at the end of the sentence. Keep refusing:
- a bare mid-sentence `verdict no longer needed` outside that lead-in;
- a question;
- a negation or conditional ("…with verdict No longer needed if PR #2 lands");
- another issue;
- any step other than 3.

### Shape 2: the plan heading `Proposed plan:` (case-disposition VIOLATED; t4, t5, t7 TWIN)

Live (t4 `a-6e9b5c523500`; t5 `a-911dd78a056f` and t7 `a-c9c21147fd2b` use the same heading):

> **B. Necessity: Still needed.** …
>
> **C. Proposed plan:**
>
> 1. `widget/core.py` — return `[]` for empty input before accessing its first character.
> 2. `tests/test_core.py` — add an empty-input regression test.
>
> Approve this plan?

`_PLAN_HEADING` accepts only `proposed changes`, so `_has_plan` finds no section. TWIN then reads "no concrete plan", although the plan meets every depth-floor item (one numbered line per file, scope, risk).

**Template basis:** Section C is "**Proposed changes (pending approval)** - the files and edits that will close the issue, **framed as a plan** awaiting reviewer approval" (reference.md:483; flow-eli5 reference.md:133-134). `Proposed plan` is the template's own description of that section, used as its heading, and the template's approval prompt is "approval of the plan".

**Proposed bound:** accept `proposed plan` as the same HEADING form as `proposed changes`: a heading line with optional `==`/`#`/`C.` markers. Everything downstream stays unchanged:
- a section that says there are none ("No proposed changes" / "none") is still not a plan;
- a negated step is still not a step;
- a sentence ("There is no proposed plan.") is not a heading.

### Shape 3: a close recommendation phrased as a request for assent (case-disposition VIOLATED; t1 CLEAN)

Live (t1 `a-9b1435266f4b`):

> **C. Recommendation:** No file changes needed; scope: zero files. No material concern found. Proposed closing comment:
>
> > Already resolved by PR #2 (`e970b8b`). …
>
> May I close issue #1 with that comment?
>
> … its procedure says, "Run the close only with reviewer assent."

`_recommends_closing` needs a recommendation cue (`recommend`, `should`, `please`, a leading `Close`, …) in the same clause as `#1` and `close`. "May I close issue #1 …?" has none.

For comparison:
- t2 (PASS) asked "May I close issue #1?", but also wrote "Close issue #1 with this comment:".
- t8 (verdict-missed, disposition PASS) wrote "Recommendation: Close #1".

**Template basis:** "Verdict `No longer needed` -> … Recommend closing the issue … **Run the close only with reviewer assent**; surface the recommendation either way" (reference.md:487-491). On a No-longer-needed verdict, a request for assent to close IS the template's prescribed way of surfacing that recommendation: the close is gated on the reviewer, so the agent asks.

**Proposed bound:** a first-person request for permission to close exactly #1 (`May I / Shall I / Can I / Should I close [issue] #1 …?`) counts as recommending the close. Keep refusing:
- negation ("May I leave #1 open?", "Shall I not close #1?");
- another issue (#10, #2);
- a historical report ("#1 was closed");
- a question that offers closing as one alternative without choosing it ("Should I close #1 or keep it open?").

### What a fix needs

The same discipline as #487:
- **Template grammar:** each new form positive and anchored to the template, not a list of refused words.
- **Refusals kept:** all revision 2-4 reds stay red, plus new committed reds for each bound above.
- **Live-shaped candidates:** quoting the three live shapes, with qualify re-certified.
- **Private replay:** all 20 retained reports from both campaigns (`20261020T141529Z-3585c9` and `20261020T195431Z-fab3ce`), confirming the replay reads verdict, disposition and plan correctly on every one.
- **Campaign package:** a new revision-5 campaign declaration on identical terms, with rehearsals and the no-false-stop check, sent to the orchestrator.

Found by skillc-worker-A (wave skillc-400) diagnosing the #434 revision-4 campaign.

Refs #434 #487

