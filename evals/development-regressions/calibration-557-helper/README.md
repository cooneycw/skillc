# Historical helper grading distinction

This development case replays an **ambiguity-bounded historical grader
distinction**, not a causal CPP defect or benefit. The original revision-1 goal
was ambiguous about renumbering the exact approved text. The observed candidate
left the runbook byte-identical to the starting fixture, while retaining a PASS
report. The unchanged historical grader reports two violations:
`report-verdict` and `one-section-per-step`. Its pre-existing qualified
`contacts-last` alternative passes. Neither candidate is a new model trial or a
subject repair; this case provides no held-out effectiveness evidence.

Run from the repository root with its Python environment:

```sh
python evals/development-regressions/calibration-557-helper/replay.py
python evals/development-regressions/calibration-557-helper/replay.py --control always-pass
python evals/development-regressions/calibration-557-helper/replay.py --control always-fail
```

The intact pair exits 0 with `PASS`; both committed broken-grader controls exit
1 with `REFUSED`. Each pair executes exactly two deterministic grades using the
existing contained verifier. Probe and judge each have a 30-second timeout per
candidate (120 seconds per pair, excluding cleanup). Containment failure refuses;
there is no alternative execution path, model call, API judge, or retry.
Missing or changed source metadata, candidate bytes, grader bytes, or controls
refuse before grading. `--case` and `--grader-root` support scratch drift checks;
they do not bypass the fixed pins.

`bad/` contains exactly seven captured non-canary files from experiment
`calibration-0d206a11`, provided slot 6, trial `t6-calibration_provided_1`, attempt
`a-cd2c7a7de61f`, result `r-5479ff20024a`. `source.json` records the manifest,
complete transcript digest, receipt byte digest, frozen approval, declared
collection revision and observed snapshot identity. The legacy schedule-only
record did not bind the entire approved declaration: the retained declaration
was joined explicitly to the ledger and observations. The source audit and
[calibration report](../../calibration-557-repeat/report.md) document that limit.
The public replay checks the pinned public material; it does not independently
retrieve or authenticate private source records.

Before copying, source artifact hashes and sizes were checked and both candidate
sets passed privacy screening with a seeded negative control. All seven bad file
contents remain exact captured bytes; no textual sanitization was needed. The two
canary files, raw transcript, and original private records are omitted. The manifest
records normalized owner-executable markers (`x` for the helper, `-` for the six
other public files), which are preserved. Full Unix permissions were not
captured: the public 0755/0644 permissions are packaging choices. `good/` copies the already qualified archived
alternative. Per-file hashes preserve this distinction in `source.json`.

[Replay evidence](replay-record.md) records the actual positive and negative
runs. The [existing configuration boundary comparison](../../../docs/specs/evaluation-facility/configuration-boundary-example.md)
was delivered in [PR #161](https://github.com/cooneycw/skillc/pull/161). This
source-linked replay supplies the remaining development-case portion of #28;
it does not duplicate that identity comparison or introduce a result schema.
