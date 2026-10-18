# Campaign 434 live: flow:auto's clean-project case, with the model

The scripted campaign ([campaign-434](../campaign-434/RESULTS-rev2.md)) certified the
production path: the fixture service, the wiring, and grader revision 2. Its attempts were
scripted actors, so #434's first box ("the full `flow:auto` workflow in the attempt") stays
PARTIAL. This campaign runs the MODEL instead. codex 0.157.1 with gpt-6-astra (effort high)
gets CPP's real flow:auto (`cpp-codex-flow-auto-86641e8`) on fixture issue #1:
- in **CLEAN**, where the fix already landed: expect "No longer needed" with real evidence and
  no change;
- in **TWIN**, where it did not: expect "Still needed" with a plan, and nothing implemented
  before approval.

The owner approved the plan on 2026-10-18
([#434](https://github.com/cooneycw/skillc/issues/434#issuecomment-6250232333)). **That does
not approve any spend.** Each declaration below needs the owner's approval of its exact
`declaration_digest` before any attempt runs (ADR 0005 rule 5, the #287 pattern).

## Sequence

1. **Measurement**: [measurement-declaration.json](measurement-declaration.json), a DRAFT.
   It runs 1 CLEAN and 1 TWIN, at 1800 s per attempt and 3600 s in total. It measures:
   - tokens and wall time per attempt;
   - whether a TWIN attempt under `codex exec` ends its turn at flow:auto's Step-3 approval gate;
   - whether a TWIN attempt implements nothing before approval (the snapshot's `source-unmodified`).

   An implementation before approval is a finding, reported before the campaign.
2. **Campaign**: 5 attempts per case, with the caps sized by the measurement, in its own
   declaration with its own approval. It is **description, not inference**: 5 attempts per case
   estimate no rate.

## What binds a run

`skillc level3-live` (`skillc/fixture_live.py`) refuses the following before any run
directory or container exists:
- an unapproved declaration;
- an identity that is not the repository's: grader revision 2, goal, builder, each case's
  base tree (re-derived by building it), or the instruction;
- an image whose tag, ID or receipt is not the declared one (C3);
- a run store other than the declared one (C5);
- a subject or client other than the declared one;
- a dirty checkout.

The declaration reuses calibration's validators, not copies of them:
- C1: no placeholders;
- C2: a declared tolerance;
- C3: the image binding;
- C4: provider-only egress (#442) with the codex server-side channels off;
- C5: a durable store;
- the whole-declaration approval digest.

The case order is `calibration.derive_arm_order(seed, cases, attempts_per_case)`.

## Containment

- **Egress:** provider-only (#442): a per-attempt internal network and proxy, allowing
  `auth.openai.com` and `chatgpt.com` only.
- **Census credit gate:** a server-side tool use, or a missing census, is never credited.
- **Nested-codex guard:** live in every fixture attempt; an observed or unknown count is never
  credited.
- **Native containment stop.** After every dispatched attempt, any of the following finalizes
  every later attempt `not-run`, with the trigger as its reason:
  - a server-side tool use, or an unavailable census;
  - an unread egress log, a wrong allowlist digest, or an allowed connection outside the allowlist;
  - a nested launch, or an unknown nested count.

  It replaces, for this path, #287's external watcher. Each trigger has a committed red case
  in `tests/test_fixture_live.py`.

## Stated risk: there is no token cap

Only wall time is capped, per attempt and in total (`matched_pilot.run_schedule`). The report
records each attempt's tokens from its own rollout, and counts an unread one as UNKNOWN,
never zero.

## Running it

On kyle19 only, since it holds the credential. It runs in ONE lock-1 hold with an empty queue,
with at least 15 GB free on `/`. The image is moved from evals26 with
`docker save | docker load` under the same tag, and the receipt is copied beside the run store.

```bash
# Spend nothing, and may run before approval (the report says approved: false):
uv run --no-sync skillc level3-live evals/level3/campaign-434-live/measurement-declaration.json --rehearse dry
uv run --no-sync skillc level3-live evals/level3/campaign-434-live/measurement-declaration.json --rehearse actor \
    --runtime-supply-receipt <receipt>
# The live run, after the owner approves this exact declaration digest:
SKILLC_ALLOW_REAL_AGENT=1 uv run --no-sync skillc level3-live \
    evals/level3/campaign-434-live/measurement-declaration.json --runtime-supply-receipt <receipt>
```

`--rehearse actor` is the real live path: the profile treatment, provider-only egress, the
fixture service, the guard, the gate witness and the stop. A scripted actor plays a committed
PASS candidate per case, with a dummy credential, so no model is contacted.

## What it does not establish

- Other models, a Claude-run flow:auto, real repositories, or anything past Step 3.
- `zero` nested codex means none came through the guard, not that none happened: a codex
  called by absolute path bypasses it.
- The fixture service's answers are subject-influenced (#436). Grading reads only the
  post-stop snapshot.
