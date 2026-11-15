<!-- flow-run n=1 id=f1c739b197084826a7585861f65ba39b -->
## Run 1 - issue #783 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #783
- Read at:      2026-11-15T21:14:36Z
- updatedAt:    2026-11-15T19:57:32Z   (context only - moves on comments and labels)
- Body digest:  96570e6ac0e4ce8ea360f568ae3fd009a7d100016c5c0f23ee2073e0c1171af4   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2484 of 2484 (cap 16384)

### Body as read
## Why

The owner ran `/skill-gauntlet` on itself (2026-11-15): "it's been an unsatisfying experience so far". Asked what bothered them, they said: **"Output is engine-speak."** The run prints `ROUND 1 charter: FAIL - contract BAD: clause-backed`, `RECORD: ...` and a `NEXT:` pointing at another command, with no plain-language account of what was checked, what was found, what it means, or what to do.

## What

1. **A plain-English report from the engine.** `skillc gauntlet run` prints it FIRST by default, then the existing machine lines (`ROUND`/`RECORD`/`NEXT`/`GAUNTLET`, unchanged, because tests and `gauntlet verdict` read them). For each round reached:
   - **Checked:** one sentence on what the round looks at, in owner terms (no rule ids; `clause-backed` becomes "each promise names a test that exists");
   - **Found:** the concrete result, with counts and names, e.g. "a draft charter with 6 'never' rules; none has a test yet; its purpose isn't approved";
   - **Means:** what that implies for a verdict, e.g. "no keep/trim/retire is possible until the charter is settled; normal for a new skill";
   - **Do next:** ONE concrete action the owner can take now, naming the skill or command and the file, e.g. "run `/charter-create skill-gauntlet`; it starts from charter v1 in discussion #718".
   - It ends with a one-line overall summary: "where this skill stands".
2. **Per-stop-reason advice** (folds in #760 item 3): each stop reason maps to its own "Do next". An unmapped reason shows the round's own detail, never another reason's advice.
3. **`/skill-gauntlet` shows the plain report first,** then the machine lines (it may collapse them), and still never answers for the owner. The SKILL.md stays inside its word budget.
4. A `--plain-only` / `--machine-only` switch for scripts, with the default being both.

## Acceptance

- [ ] For each committed fixture stop (no charter; draft unbacked; contract BAD; unapproved intent; inspect STOPPED or FINDINGS; round 3 NOT BUILT), the report has all four parts, uses no internal rule ids, and its Do-next names a concrete command or file. Each is a golden test.
- [ ] The machine lines are byte-identical to before (a golden test), so `gauntlet verdict` and the existing tests are unaffected.
- [ ] An unmapped stop reason shows the round's detail, not another reason's advice.
- [ ] The owner's real run on `/skill-gauntlet` is quoted in the PR, plain report first.

Refs #754, #760, #738. Owner feedback 2026-11-15.


<!-- end of body -->
