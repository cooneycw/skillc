<!-- flow-run n=1 id=95a1a32b159b4342b9cd1ad101a00230 -->
## Run 1 - issue #599 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #599
- Read at:      2026-10-28T07:32:51Z
- updatedAt:    2026-10-28T07:26:49Z   (context only - moves on comments and labels)
- Body digest:  9cb563555669b1ddb8efe12397afb8a15ae67c8c46d28b942bc9972774db1514   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2542 of 2542 (cap 16384)

### Body as read
A valid zero development score is ranked below negative scores by `scripts/description_optimizer.py:151`:

```python
ranked = sorted(variants, key=lambda a: (scores[a]["score"] is not None, scores[a]["score"] or -9), reverse=True)
```

`0.0 or -9` produces `-9`. With variants at `0.0` and `-0.5`, the negative variant ranks first. With published at `-0.25` and a complete screen, the comparison around line165 can incorrectly report that published beat every variant and skip held-out confirmation. This is a live measurement/selection correctness defect, not a cosmetic nit.

Found during the independent consumer review for #546 checkpoint `084c6880a56e5e925dd1c5760bf8a1fc137714b6` (base `16c6b4b65b5e0d35d72ae811163625d7cd8347a7`). Reviewer evaluated the actual AST ranking expression with synthetic scores; it selected the negative variant and showed the erroneous published comparison. This was not an actual optimizer study or a full `optimize()` regression execution. The source expression is unchanged in delivered `12db6909350bc69afc0a40160312e220d2f0b0f7`. Searches of current/closed zero-score and description-optimizer issues, including #238 and #325, found no dedicated fix.

Required bounded correction: distinguish missing (`None`) from numeric zero without changing screen completeness, tie/confirmation policy, score definition or historical results. Existing issue #238 owns the broader optimizer programme; this ticket isolates the observed defect.

Acceptance:

- Run a genuine regression on the existing public optimizer path before the fix: zero beats negative, and published `-0.25` must not incorrectly keep against a zero-scoring variant. Preserve the actual old-code assertion failure; a source-expression probe alone is not the completed regression.
- Cover zero/negative/positive/None, deterministic ties and existing incomplete-screen behavior with healthy counterparts. Stub only expensive dependency boundaries; no live clients, study, Docker or paid/model calls are needed.
- Commit a load-bearing opposite case and show restoring only the bad truthiness ranking breaks the consumer regression; preserve existing held-out confirmation policy.
- Do not rewrite historical studies/reports, frozen tasks/graders or optimizer declarations. Report any prospective wider scope separately.

Priority: required new correctness work goes ahead of further #546 delivery under the skillc-update rolling-queue instruction. #546 reporting diff itself had no in-scope review finding; this defect stays in its own change.


<!-- end of body -->
