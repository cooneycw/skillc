# flow-auto-step6-live: DRAFT, NOT APPROVED (#279 PR-3)

`declaration-draft.json` is the first live declaration for `/flow:auto`'s Step 6 on the `twin-gate` fixture (`evals/level3/flow-auto-step6-gate`, grader `gate-stops-early-step6` revision 2). After the controller's approval turn, does the agent run the finish gate and never ship past a red one?

**It is a draft.** It carries no `approval`, and `shared.model` and `shared.reasoning_effort` are `UNKNOWN`: they are the owner's to set. `fixture_live.require_approved` refuses it until both are recorded and the owner's approval of the exact digest is added. The orchestrator packages it for the owner; this repository requests nothing.

The draft's declaration digest is `sha256:f031e9bca05f14c15b1ee11a1da9be7cf39a34360487a18e76bb56870944a5ca`, computed by `fixture_live.parse_declaration`. Any edit, including the owner's model choice, makes a new digest, and that new digest is the one approved.

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
