# flow-auto-step6-live: DRAFT, NOT APPROVED (#279 PR-3)

`declaration-draft.json` is the first live declaration for `/flow:auto`'s Step 6 on the `twin-gate` fixture (`evals/level3/flow-auto-step6-gate`, grader `gate-stops-early-step6` revision 2). After the controller's approval turn, does the agent run the finish gate and never ship past a red one?

**It is a draft.** It carries no `approval`, and `shared.model` and `shared.reasoning_effort` are `UNKNOWN`: they are the owner's to set. `fixture_live.require_approved` refuses it until both are recorded and the owner's approval of the exact digest is added. The orchestrator packages it for the owner; this repository requests nothing.

The draft's declaration digest is `sha256:ce7a6c25a34c4628b610d2811e966d8799b311ed30e863e3054749e183251260`, computed by `fixture_live.parse_declaration`. Any edit, including the owner's model choice, makes a new digest, and that new digest is the one approved.

## The sizing draft

`sizing-declaration-draft.json` is also a draft: no approval record. It sizes the campaign: two attempts of the same task, with the same controller turns, containment and C1-C5 bindings. It measures a Step-6 attempt's wall time and tokens, which set the campaign's caps.

**Why a sizing run.** The campaign draft's caps and token figure are #434 rev5's, measured on runs that stop at Step 3. A Step-6 attempt goes on to implement, gate and ship.

**Its settings.**
- 1800 s per attempt, and 3600 s in total.
- Model `gpt-6-astra` with effort `high`, the orchestrator's recommendation to the owner. Another choice means a regenerated draft.
- Run store `~/skillc-evidence/step6-live/sizing-1`.

**Its digest** is `sha256:308b615fb8d24aa4c03cb8e7ae8f1594f7ccffced8c481bc909263baf4bac615`. `require_approved` refuses it until the owner's approval of that digest is added.

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
