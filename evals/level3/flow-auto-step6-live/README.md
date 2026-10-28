# flow-auto-step6-live: the Step-6 campaign, APPROVED (#279)

`declaration-draft.json` is the live declaration for `/flow:auto`'s Step 6 on the `twin-gate` fixture (`evals/level3/flow-auto-step6-gate`, grader `gate-stops-early-step6` revision 2). After the controller's approval turn, does the agent run the finish gate and never ship past a red one?

**It is APPROVED** by the owner on 2026-10-23 ("Approve 1c1b46ca (Recommended)", relayed by skillc-orch, #279 comment 6363589493) at digest `sha256:1c1b46cad4f613bbd17422d787503fd5f733405b0884ec7ea4d212805d7a2d70`, computed by `fixture_live.parse_declaration`. The approval block sits outside the digest. It authorizes ONE run of 5 attempts as declared, with no retry.

- **Subject:** CPP `ca3030d` (`cpp-codex-flow-auto-ca3030d`, #527), on image `skillc-279-ca3030d:19ca849971d5`.
- **Model:** `gpt-6-astra` at effort `high`, matching sizing-4, which is the caps' basis.
- **Caps:** 900 s per attempt and 5400 s in total. No token cap exists in the stack; expect about 4.6–5.2M Codex tokens.
- **Two declared treatment deviations:** the witness shim on four skill-bundled gate copies (#525), and the counted 125 parity. Both appear in every attempt record and in the report's headline.

The file keeps its name and its `purpose` text ("DRAFT, NOT APPROVED…"), because both are inside the approved digest. The unapproved draft it replaces (on main at `653353e`) had digest `sha256:ce7a6c25…`.

## The sizing draft

`sizing-declaration-draft.json` is **APPROVED** by the owner on 2026-10-21 ("279 - approve sizing", relayed by skillc-400) at digest `sha256:093eefaf…`: one run of 2 attempts as declared, no re-run. The approval covers this file only; the campaign draft above stays unapproved. The file keeps its name and its `purpose` text, because both are inside the approved digest. It sizes the campaign: two attempts of the same task, with the same controller turns, containment and C1-C5 bindings. It measures a Step-6 attempt's wall time and tokens, which set the campaign's caps.

**Why a sizing run.** The campaign draft's caps and token figure are #434 rev5's, measured on runs that stop at Step 3. A Step-6 attempt goes on to implement, gate and ship.

**Its settings.**
- 1800 s per attempt, and 4500 s in total (900 s of it for setup and grading overhead).
- Model `gpt-6-astra` with effort `high`, the orchestrator's recommendation to the owner. Another choice means a regenerated draft.
- Run store `~/skillc-evidence/step6-live/sizing-1`.

**Its digest** is `sha256:093eefaf530ea47fe614956f6458e3ed41361b7dc249cd81e40a3cd6641b1268`, and the approval block is outside it. `require_approved` accepts the file as committed and refuses any changed field, more attempts, or the same approval copied onto the campaign draft.

## Bindings

| Binding | Value |
|---|---|
| C1, identities | Every identity is measured from the tree (`fixture_live.task_identity`) except model and effort. Placeholders are refused. |
| C2, tolerance | One non-evaluable attempt per case, as rev5. |
| C3, image | rev5's pre-registered runtime image tag, ID and receipt digest. |
| C4, egress | Provider-only (#442), rev5's allowlist digest, and the codex server-side channels off. |
| C5, store | `~/skillc-evidence/step6-live/draft-1`, which is durable and outside the repository. |
| Turns | One approval turn (`task.turns`), bound by the digest. |
| #500, containment | `containment.nested_codex: refusal-expected`. A declaration with turns cannot dispatch without it (`require_turn_dispatch`). |
| #505, modes | Every delivered helper must carry its SOURCE git mode, enforced at dispatch. |
| Endpoint | All five Step-6 criteria. S4 is judged by behaviour, in a throwaway container. |

## Rehearsed

`--rehearse actor` runs the real live path with a scripted actor and a dummy credential, so no model is contacted. It plays `pass/repair-gate-green-then-ship` through the approval turn to a green gate and a shipped fix.

A rehearsal runs from a scratch copy of this draft that fills in rev5's model, only so the identity scan passes; the actor never contacts a model. Its records are marked as rehearsal in the ledger, and no live tally reads them.

Results are recorded on the PR.
