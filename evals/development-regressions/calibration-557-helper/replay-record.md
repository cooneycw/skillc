# Actual historical replay evidence

Run: 2026-10-24T23:33:40.676042+00:00

Reader base: `7373a5b4c6245a20a2cbff74e3dfba51e240f9f4` (issue #28 worktree).
Replay script: `sha256:780628e8b69a6b7090ff81e551c4c9a6cc025e67a3e4213f7711d0f24f7e0593`.
The base identifies the repository verifier, not a commit containing this new replay script.

Commands use the repository Python environment from the repository root:

```sh
python evals/development-regressions/calibration-557-helper/replay.py
python evals/development-regressions/calibration-557-helper/replay.py --control always-pass
python evals/development-regressions/calibration-557-helper/replay.py --control always-fail
```

## default

Exit 0; `PASS`.

```json
{
  "active_grader_digest": "sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523",
  "complete": true,
  "control": null,
  "grader": {
    "digest": "sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523",
    "id": "helper-different-question",
    "revision": "1"
  },
  "replay_digest": "sha256:780628e8b69a6b7090ff81e551c4c9a6cc025e67a3e4213f7711d0f24f7e0593",
  "results": {
    "bad": {
      "status": "FAIL",
      "violated": [
        "one-section-per-step",
        "report-verdict"
      ]
    },
    "good": {
      "status": "PASS",
      "violated": []
    }
  },
  "source_digest": "sha256:cec60076ac859c63000077b968288da6509da3df75460d27bff2a58ad2a3fed9",
  "verdict": "PASS"
}
```

## always-pass

Exit 1; `REFUSED`.

```json
{
  "active_grader_digest": "sha256:60e64e4bb2c0529da30064e75421eb5138c7e1b685602582972d46127b28981e",
  "complete": true,
  "control": "always-pass",
  "grader": {
    "digest": "sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523",
    "id": "helper-different-question",
    "revision": "1"
  },
  "replay_digest": "sha256:780628e8b69a6b7090ff81e551c4c9a6cc025e67a3e4213f7711d0f24f7e0593",
  "results": {
    "bad": {
      "status": "PASS",
      "violated": []
    },
    "good": {
      "status": "PASS",
      "violated": []
    }
  },
  "source_digest": "sha256:cec60076ac859c63000077b968288da6509da3df75460d27bff2a58ad2a3fed9",
  "verdict": "REFUSED"
}
```

## always-fail

Exit 1; `REFUSED`.

```json
{
  "active_grader_digest": "sha256:c8fa16a9dd3534dff2da42edd84eccb99233de90a6f627d16b9d99139703ad42",
  "complete": true,
  "control": "always-fail",
  "grader": {
    "digest": "sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523",
    "id": "helper-different-question",
    "revision": "1"
  },
  "replay_digest": "sha256:780628e8b69a6b7090ff81e551c4c9a6cc025e67a3e4213f7711d0f24f7e0593",
  "results": {
    "bad": {
      "status": "FAIL",
      "violated": [
        "approved-content-present",
        "one-section-per-step",
        "other-content-preserved",
        "report-verdict"
      ]
    },
    "good": {
      "status": "FAIL",
      "violated": [
        "approved-content-present",
        "one-section-per-step",
        "other-content-preserved",
        "report-verdict"
      ]
    }
  },
  "source_digest": "sha256:cec60076ac859c63000077b968288da6509da3df75460d27bff2a58ad2a3fed9",
  "verdict": "REFUSED"
}
```

## Source and red case

Before adding the replay, the exact seven captured files were read from the retained source objects into scratch and graded with the unchanged archived revision-1 grader: FAIL on exactly `one-section-per-step` and `report-verdict`. The pre-existing `contacts-last` alternative graded PASS. The replay preserves that distinction; it does not fix the captured candidate or infer a CPP defect from the ambiguous historical goal.

The always-pass control actually graded both candidates PASS; the always-fail control actually graded both FAIL on all four criteria. Both public-entrypoint runs refused. These are committed judge inputs in the existing historical archive, not stubbed outputs. The focused tests additionally refuse changed/missing/extra/symlinked candidate material, source metadata drift, and historical grader drift.

Source manifest, complete transcript, receipt, original result and approval identities are pinned in [source.json](source.json). Source object hashes/sizes and normalized owner-executable markers were joined to the original manifest before publication. A seeded privacy fixture was detected before both seven-file candidate sets scanned clean (zero skips); omitted canaries and raw transcripts stay private. No source-store writes, model trials, API judges, or retries were used. This is development material, not fresh effectiveness evidence.

## Review correction and its red run

The independent review found that the first blind-control tests accepted equal
statuses without requiring complete execution. A crashing judge could produce
two INCONCLUSIVE results and make those tests green. The tests now require
`complete: true` and the exact all-PASS or all-FAIL four-criterion vectors.

A scratch-only falsification replaced the always-pass judge with a process that
exits 7, and explicitly repinned that scratch control and metadata so the real
public replay reached the crashing judge. Both actual grades were INCONCLUSIVE,
with no violations; the replay correctly exited 1 with REFUSED. Applying the
pre-correction test from the staged snapshot to that actual CLI result PASSED
(blind); applying the corrected test FAILED (detects the broken control). The
unaltered committed always-pass and always-fail controls still pass their
strengthened tests by producing their exact intended verdict vectors.

Additional committed fault-injection tests alter real verifier output to mark
containment unconfirmed, cleanup partial, or an otherwise satisfied criterion
UNKNOWN. Each refuses even when the recorded status/violation totals would
otherwise match. Input checks also cover deleted source metadata, all grader
code/input dependencies, both control files, and missing grader inputs. These
checks use no private store or model call.
