<!-- flow-run n=1 id=57d4b0767ce7481781b462d68b2eb0f0 -->
## Run 1 - issue #150 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #150
- Read at:      2026-09-29T10:18:01Z
- updatedAt:    2026-09-28T19:06:35Z   (context only - moves on comments and labels)
- Body digest:  61bdecb1a261e711aef0eb6898d7be0d1ffb7b1ee5748f0c0cd86a5145b30312   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3922 of 3922 (cap 16384)

### Body as read
Blocks: cooneycw/claude-power-pack#1084 (half B). Related: #139 (agent-path readiness), #12 (matched pilot), #26 (selection probe).

## Outcome

One behavioural case in which **CPP's instructions decide the outcome**, run against a deliberately degraded CPP subject that the case reports as failure, with the resulting verified-result delivered to where CPP's consumer gate reads it.

## Why this is needed now (measured at skillc `2b60616`)

CPP #1084's consumer half is shipped: `scripts/check-behavioral-eval.py` reads records v2 verified-results from `docs/measurements/behavioral-eval/` and stays advisory until a real one arrives (the flip to blocking is pre-committed to that event). Its producer half lives here per ADR 0002, and four gaps stop it:

1. **No task where a CPP skill is needed to pass.** The only graded task is `evals/level1/slug-small-fix`, a generic slug fix (`goal.md`). Every live run so far passed with and without CPP (#26 selection probe, #12 pilot, #106/`evals/agent-trial-live`, #124/`evals/claude-code-agent-arm`). A case both arms pass cannot discriminate.
2. **No degraded arm is expressible.** `acquire_collection` (`skillc/collection_conformance.py:318`) clones `https://{locator}` at the pinned `revision` (`skillc/demo.py:143-168`); a local `checkout=` exists only as a Python/test parameter. Only the skills root is installed (`skillc/materialize.py:102-104`); `CLAUDE.md` is never delivered (`evals/subjects/cpp-claude-code/SUBJECT.md`, "Not included"), so a degraded `CLAUDE.md` cannot be expressed at all, and a degraded skill set only via an untested non-default-branch revision.
3. **No export into a consumer repository.** Only `pilot-run`/`pilot-report` export a bundle (`_export_pilot_evidence`, `skillc/cli.py:1035`), into `evals/matched-pilot/evidence/records/`. `collection-run` and `selection-probe` leave their stores under `$TMPDIR`. Nothing writes a verified-result (or a bundle) to a consumer path.
4. **An agent-path PASS arrives INCONCLUSIVE** (tracked by #139, referenced here, not duplicated): `installation-ready` stays a mandatory UNKNOWN when `readiness_source` is `agent-observation` (`skillc/verify.py:114-125`), so the treatment arm can never reach the consumer as PASS; only the degraded arm's FAIL survives.

## Acceptance

- [ ] One Level-1 task whose fixture and grader make a **specific CPP skill (or instruction) necessary** to pass, graded on an artifact, with its grader certified the same way `slug-small-fix`'s is (`qualify.py`).
- [ ] A **degraded CPP subject** - the same collection with that skill mutated or removed - expressible from the operator command line (a local snapshot or an explicitly supported revision), with a committed statement of what the mutation removes.
- [ ] Shown to discriminate: the normal subject grades PASS and the degraded subject grades FAIL on the same task, each with retained evidence; a run where both arms agree is reported as non-discriminating, never as a pass.
- [ ] An **export path** that writes the resulting verified-result (and whatever bundle the consumer needs to apply the bundle rules) into a named consumer directory, leak-checked and passed through `check-records` first, as `pilot-run` already does for its bundle.
- [ ] With #139: the normal arm's verified-result derives PASS (not INCONCLUSIVE) on the path used, or the consumer contract is changed deliberately and recorded.

## Constraints

- ADR 0005 applies: this issue authorizes no live or paid run; the arms, identities, schedule and caps are recorded before one.
- Environment faults must not read as discrimination: a positive control is mandatory (CPP #1084's 2026-09-21 comment records two arms agreeing on a false negative after an IPC fault).
- Do not put the runtime in CPP (ADR 0002).

Found while scoping CPP #1084 under `/flow:auto` (no CPP code written; the run stopped at its plan gate with a "Needs reframing" verdict).

