# Exporting a collection-run's evidence to a behavioral-eval consumer

- Status: Implemented as `skillc collection-run --evidence DIR` (`skillc/cli.py`), #150 acceptance item 4
- Date: 2026-09-28
- Governing documents: [records](records.md), CPP's `scripts/check-behavioral-eval.py` (half A, CPP #1084)

## The gap this closes

`collection-run` (issue #11/#106) already stores a `verified-result` for
every graded attempt (#139), but nothing wrote it anywhere a consumer could
read: `collection-run`'s own store lives under a disposable run root, and
only `pilot-run`/`pilot-report` exported a bundle at all - into
`evals/matched-pilot/evidence/records/`, this repository's own committed
path, never an operator-named external directory. CPP's consumer
(`scripts/check-behavioral-eval.py`, half A of CPP #1084) reads
`docs/measurements/behavioral-eval/` in ITS OWN checkout and states plainly
that "how a bundle is laid out under `DEFAULT_DIR` is not decided yet - the
runner is skillc #8 ... left to whoever lands the first producer". This is
that producer, and the layout decision it makes.

## The layout

```
<evidence-dir>/
    result-<id>.json          # the verified-result(s) - flat, one per attempt
    bundle/
        ledger.json
        lifecycle-*.json
        manifest-*.json
        observation-*.json
        receipt-*.json
        result-*.json          # the SAME records again, alongside their ledger
```

No `report.json` anywhere: `matched_pilot.export_bundle` always writes one
alongside the bundle it copies, and for `pilot-run` that is fine - its
`report` is itself a schema-legal `pilot-report` record. A collection-run
envelope (`collection_conformance.evidence_envelope`) carries no `kind`/
`version` at all, so `check-records` would refuse it as an unversioned
record. It names nothing the bundle rules need (they read the ledger,
manifest and receipts, never a report summary), so it is leak-checked (it
was briefly staged) and then dropped, before `check-records` ever sees it.

**Why split, not one flat bundle.** CPP's consumer reads with
`directory.glob("*.json")` - flat, never recursive - and refuses the FIRST
file that does not parse as a `kind: "verified-result"` record, in sorted
order. Its own docstring says it reads results alone and explicitly defers
the ledger-binding/attempt-accounting "bundle rules" to a later version. So a
flat skillc bundle (`ledger.json`, `manifest-*.json`, ... beside the results)
would make today's consumer refuse on the FIRST non-result file it globbed,
usually `ledger.json` - reported as "unreadable: declares kind None, not
verified-result" - never reaching the real result at all. Splitting keeps
today's consumer working (it sees only `result-*.json` at the top level) and
still delivers "whatever bundle the consumer needs to apply the bundle
rules" for a future version, in `bundle/`, which a non-recursive glob will
never see.

**Why the results appear twice.** The top-level copies are what today's
consumer reads; the copies inside `bundle/` are what ties each result to the
ledger and receipt a future bundle-rule reader needs beside it. Neither
directory is a symlink into the other - `check-records`' bundle rules
(`ledger-binding`, `attempt-accounting`) are asserted against `bundle/`
alone, so it must be a real, self-contained bundle `records.discover_bundles`
recognises on its own.

## The gate

`skillc collection-run --evidence DIR`, after a captured attempt, mirrors
`pilot-run`'s own `_export_pilot_evidence` (issue #147's exclusive lock on
the destination's PARENT directory, held from the ownership check through
the atomic replace - see `docs/specs/evaluation-facility/verification.md`'s
sibling in `matched_pilot.py` for the race this closes) with the SAME two
refusals, checked in the SAME order, on a fresh staging copy:

1. **Leak-check the whole staging tree** (`leak.scan_path`) - both layers,
   the flat results and `bundle/`.
2. **`check-records`' bundle rules over `bundle/` alone**
   (`matched_pilot.bundle_findings`) - never given the flat top-level copies,
   which are not a bundle shape `records.discover_bundles` would recognise.

Either failing publishes nothing. `evidence`, if it already exists, may only
hold files this exporter itself would have written (a `result-*.json` at the
top level, or the `bundle/` directory) - anything else refuses the publish
rather than silently deleting an operator's unrelated file on replace.

## A degraded arm must never reach a consumer's real measurements

#150's own discrimination pair is a NORMAL subject grading PASS and a
DEGRADED subject grading FAIL on the same task, each retained as evidence -
but only the normal arm's result belongs in a consumer's real measurements
directory. CPP's `check-behavioral-eval.py` reports ANY declared `FAIL` as
an error (`evaluate`'s own verdict map), and the flip from advisory to
blocking is pre-committed to the first real record arriving - so a degraded
arm's export placed in `docs/measurements/behavioral-eval/` would turn that
gate red for good, on a failure it was never meant to measure.

A degraded arm's export is a very good one-shot NEGATIVE CONTROL for the
consumer gate instead (point it at a directory holding one, and it must go
red) - which is exactly why it is never published by habit. `--evidence-role`
(default `measurement`) names what an export is for: a `measurement` export
of a degraded-arm result (`result.revision` carrying the `degraded:` label -
see `docs/specs/evaluation-facility/degraded-subjects.md`) is refused before
anything is written; `--evidence-role control` is the explicit, named opt-in
that publishes one anyway. A normal arm's export needs no role at all - the
check only fires on a degraded `revision`.

## The transcript is exported only on purpose (#202)

Every attempt's store now retains the agent client's own transcript (the
`client-transcript` observation, `records.md`). The bundle's manifest names it
by digest either way, but its bytes are published only with
`--evidence-transcript`, because a transcript can carry subject content. With
the flag, each bundled attempt's transcript object is copied (re-hashed on the
way out) to `bundle/transcripts/<attempt>.jsonl`, which holds no `*.json` and so
is never read as a bundle. The flag refuses the whole export when an attempt
retained no transcript (none found, or its retention leak check refused it) -
an export without the transcript would read as one that had it - and the
whole-staging leak scan above covers the file too. The flag is independent of
`--evidence-role`: the normal arm is a `measurement` export, and its transcript
is exactly the one a diagnosis needs.

## What this does not do

It does not write to CPP's checkout, or to any path this repository does not
control - `--evidence` names a LOCAL directory the operator chooses; wiring
it to a real CPP clone's `docs/measurements/behavioral-eval/` is an operator
action, outside skillc entirely. It exports regardless of the run's own
PASS/FAIL verdict - a degraded arm's expected FAIL still needs to reach SOME
consumer-shaped destination, just never the real measurements one by
default - but an export that itself fails its leak check or check-records
takes priority over the run's own exit code, because it means the evidence
could not be trusted to publish at all.
