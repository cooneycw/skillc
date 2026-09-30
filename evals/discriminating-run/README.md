# #150 discriminating run: NON-DISCRIMINATING

The first live run of `docs/runbooks/150-discriminating-run.md`, for skillc #150 acceptance item 3.

**Verdict: non-discriminating.** The NORMAL arm and the DEGRADED arm both graded PASS on `finish-close-ref`. Under the runbook's verdict table this is reported as non-discriminating, never as a pass. Nothing was exported to claude-power-pack's `docs/measurements/behavioral-eval/`.

The identities, caps and per-attempt results are in `run-manifest.json`.

## Declaration

| Field | Value |
|---|---|
| Subject | `cpp-codex` at `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` |
| Client | codex-cli 0.157.1, model `gpt-6-astra` |
| Image | `skillc-trial:latest`, `sha256:d1b2ced9dc6d25e9e1bc673c1973f032ced50a11da234fcd617ee376ff36eefc` |
| Task | `evals/level1/finish-close-ref`, revision 1 |
| Arms | positive control (`slug-small-fix`), then one NORMAL and one DEGRADED attempt |
| Time cap | `--agent-timeout 1200` per attempt |
| Authorization | owner approval in-session, 2026-09-29; codex subscription login (ADR 0005 section 6); no judge calls |

## Results

| Attempt | skillc revision | Graded | Notes |
|---|---|---|---|
| positive control | `6a278ce` | PASS | `installation-ready` SATISFIED (discovery canary, baseline absence); the recorded image digest matches the declaration |
| NORMAL | `6a278ce` | PASS | all four criteria and `installation-ready` SATISFIED; heuristic skill invocations: `flow-finish` |
| DEGRADED | `df12fc1` | PASS | all four criteria SATISFIED, `no-closing-match` included; heuristic skill invocations: none |

**The arms ran at different skillc revisions.** The first DEGRADED attempt was refused before launch, because `degrade-subject` left the overridden scripts' `SHA256SUMS` lines pinned to the original hashes (#198). `df12fc1` is `6a278ce` plus that fix (PR #200), which changes only `skillc/degrade.py`, CLI printing and docs. None of those is on the NORMAL arm's path.

The degraded subject's receipt (`degraded-subject-receipt.json`) lists exactly the five declared locations. It records the two re-pinned manifest lines separately under `manifest_rewrites`.

## Why DEGRADED passed: unresolved

What was observed: both arms wrote the same non-closing reference (`Refs #42`), each followed by a sentence saying the issue stays open. The degraded subject carried no prose statement of the closing-keyword rule, and the heuristic skill-invocation detector recorded no invocation in the DEGRADED arm (it recorded `flow-finish` in NORMAL).

What this pair shows is only that it **did not demonstrate discrimination**. It does not establish why DEGRADED passed. There are two open explanations:

- **The model's default behaviour.** `gpt-6-astra` may avoid closing keywords in this situation without any CPP instruction.
- **Influence from retained CPP content.** The degraded subject still installs CPP, including the incidental guard's code in `gh-pr-merge.sh`, which handles negation internally (the residual `DEGRADATION.md` documents). The rule could be inferred from that code. A final artifact with no closing keyword does not exclude the guard having shaped an earlier decision.

Transcripts were not retained in the run stores (the spools are empty), and the invocation detector is heuristic. So neither explanation can be ruled out from this evidence, and whether `finish-close-ref` can isolate the CPP rule for this model remains open.

## Consumer check

claude-power-pack `scripts/check-behavioral-eval.py`, at CPP main `72cb00c5`:

- `normal-evidence/` exits 0: PASS, re-derived.
- `degraded-evidence/` exits 0: PASS, re-derived.

The checker read both artifacts correctly. But because DEGRADED passed, this run does **not** provide the negative control for CPP's gate that the runbook expected from it.

## Files

- `normal-evidence/`: the NORMAL export. It is leak-checked and clean under check-records, but it is not a measurement for CPP, because the case did not discriminate.
- `degraded-evidence/`: the DEGRADED control export (`--evidence-role control`). Never copy it into CPP.
- `degraded-subject-receipt.json`: the `degrade-subject` receipt for the DEGRADED arm.
- `run-manifest.json`: identities, caps and per-attempt results.
