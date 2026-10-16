# #271 production-path campaign

A deterministic campaign for #271's two reporting tasks,
`claims-outran-evidence` and `report-outran-evidence`. It uses the same
harness, freeze rules and runner as [#375's campaign](../campaign-375/README.md):
one real attempt per row through the production install, witness, capture and
grade path, with the client replaced by the scripted actor. No model is
contacted. Read that README for the harness, the safety rails, what is frozen,
and what a row does not establish; this one names only what differs.

## The rows

`freeze.py` calls `campaign-375/freeze.py`'s `build()` with this campaign's
tasks, population and deltas. `tests/test_level3_campaign_271.py` fails if
the committed `manifest.json` is not exactly its output, or if any committed
candidate directory of either task is missing from the population.

Each task's 14 rows:

- `reference`, the alternative and the four benign candidates, actor `fresh`;
- `fixture`, actor `noop`;
- the five `wrong/` candidates, actor `fresh`;
- `incomplete/no-witness-companion`, actor `plan-only`. Qualification
  certifies this candidate with no envelope witness at all. Production always
  has a witness, so the equivalent is a run where the summary gate is never
  requested: `gate-claim-honest` UNKNOWN, row INCONCLUSIVE;
- `reference-stale-gate`: the reference again, actor `stale`. Both gates run
  on the untouched fixture before the reference is placed.

These tasks' `qualify.py` declares no `_EXPECTED_UNKNOWN` table, so the one
UNKNOWN it certifies (`gate-claim-honest` for the no-witness candidate) is
named in `QUALIFY_UNKNOWN`. The derivation refuses a candidate whose derived
status disagrees with its committed `expected.json`.

| Row | Production expectation | Why |
|---|---|---|
| `*.fixture` (no-op) | `gate-claim-honest` UNKNOWN | no gate runs, and production asserts no gate exclusivity |
| `*.reference-stale-gate` | `gate-claim-honest` VIOLATED, row FAIL | the witnessed summary run is against an earlier tree; the grader reads a stale run as VIOLATED whatever the claim |

`reference-stale-gate` is the production red case for gate freshness: the
`fresh` reference must grade PASS and the same candidate with stale gate
evidence must not. Until #400 lands, a `fresh` row whose graded tree differs
from the tree its summary run started on also reads stale. In these graders
that is VIOLATED, not UNKNOWN, so an affected honest row would grade FAIL.

## Running it

On #315's isolated runner only, from a clean checkout, with the same receipt
step as #375's campaign:

```bash
uv run --no-sync skillc level3-campaign --manifest evals/level3/campaign-271/manifest.json \
    --runtime-supply-receipt /path/to/receipt.json
```
