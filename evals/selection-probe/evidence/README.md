# Selection probe: live evidence (#26)

Two live runs on 2026-09-27: the three predeclared selection cases, then the
predeclared detection control. Both used the same host, image, client and
collection.

- **Host:** the operator's machine, native Docker Engine 29.8.1, Linux x86_64.
- **Image:** `skillc-trial:latest`, id `sha256:d1b2ced9dc6d…`, the same image
  #10, #11 and #106 ran.
- **Client:** codex-cli 0.157.1 on the operator's normal subscription login
  (ADR 0005 rule 6). There was no judge call and no metered spend. Token use
  was not measured.
- **Collection:** `cpp-codex` @ `85e9b03a`, content digest `sha256:ceba20f1…`,
  74 skills. It was installed into the treatment arm's home only; the
  baseline arm's home received nothing. At this revision, codex's own listing
  discovers all 74 skills (#10/#11,
  [support matrix](../../../docs/specs/evaluation-facility/support-matrix.md)).
- **Grading:** a separate grading container with `network=none`.
- **Bounds:** one attempt per arm, as set by
  [`run-manifest.json`](../run-manifest.json).

## 1. Selection run: three cases, both arms

- **When:** 14:26–14:31Z (289 s wall time).
- **Code:** main `0b91e82`, driving `selection_probe.agent_trial_runner` and
  `run_planned_selection_probe` from a one-off script. The pytest harness that
  existed then could not reach a credential (see §3). The `skillc
  selection-probe` command added later makes the same calls in the same
  order. Experiment `selection-probe-724e3a76`.

| Case | Arm | Disposition | Selection | Task | Invoked |
|---|---|---|---|---|---|
| intended-use (`qa-test` applicable) | treatment | captured | not-selected | PASS | none |
| intended-use | baseline | captured | not-selected | PASS | none |
| near-miss (none applicable) | treatment | captured | not-selected | PASS | none |
| near-miss | baseline | captured | not-selected | PASS | none |
| overlapping-choice (`security-scan` / `security-deep`) | treatment | captured | not-selected | PASS | none |
| overlapping-choice | baseline | captured | not-selected | PASS | none |

- Every attempt exited 0, its liveness canary was confirmed, and it exported
  4 artifacts.
- No baseline was contaminated.
- Detection is heuristic throughout. Codex has no structural skill marker, so
  an invocation is inferred from the agent reading
  `…/skills/<name>/SKILL.md`.

## 2. Detection control

- **Command:** `SKILLC_ALLOW_REAL_AGENT=1 skillc selection-probe
  --detection-control`, exit 0.
- **When:** 17:28–17:30Z.
- **Code:** branch commit `ecee226`.
- **Declaration:** [`detection-control.json`](../detection-control.json) was
  committed in `8229361` and pushed before any control ran.
- **Experiment:** `selection-probe-detection-control-15c54f4f`.
- **Setup:** the intended-use case only. The canary instruction names
  `qa-test`, so this run tests detection; it is not a selection result.

```
selection-probe-intended-use treatment: disposition=captured selection=selected task_success=True invoked=['qa-test'] (heuristic detection)
selection-probe-intended-use baseline: disposition=inconclusive selection=unknown task_success=None invoked=[] (heuristic detection) - prompt_delivered=True, canary_satisfied=False - neither selection nor outcome is reported for an attempt the transcript did not confirm
verdict: ok - control detected in treatment; baseline observed with no invocation
```

- **Treatment arm:** the skill was installed and named. The pipeline reported
  a real invocation of it, through the same client, adapter and recorded
  `skill_invocations` the selection run used.
- **Baseline arm:** nothing was installed. Its transcript was found and read,
  and it shows no invocation of any skill. With no skill to read, the named
  canary cannot be satisfied, so the attempt is inconclusive; this shape was
  predeclared.
- **Required by the control's verdict:** the baseline must be observed, not
  merely "not selected". Observed means its transcript was read AND that
  transcript's first user message is this attempt's own prompt
  (`prompt_delivered=True` above, which carries the attempt's nonce). A
  re-review added that binding after this run. The run's own output already
  shows the baseline satisfying it, so the verdict stands under the final
  rule. A baseline that never launched, or whose recorded
  invocations the failed canary would have hidden, now fails the control.
- **An earlier run under a weaker rule:** at 17:20Z, commit `8229361`,
  experiment `…-a5be57db`. It gave the same arm results, and its baseline's
  own observation record shows `files_found=1, skill_invocations=[]`. Its
  verdict rule did not yet require that observation. Cross-model review
  caught the gap, and the run above re-checks under the fixed rule.

## 3. What this does and does not show

- **Within this one configuration, codex never visibly opened an installed
  skill on its own**, and it fixed the task in all six arms. That includes the
  intended-use case, where `qa-test` was plainly applicable. The case contract
  allows this: "a correct result without invoking the skill can still be
  valid".
- **The near-miss case showed no false positive.**
- **The overlapping pair was never exercised**, so this says nothing about how
  the agent chooses between two skills.
- **The zeros in §1 are real observations, not a blind detector.** The control
  in §2 shows this pipeline reports a real codex invocation of an installed
  skill.
  - **Limit:** the control proves detection of a skill read by the heuristic's
    own path (`…/skills/<name>/SKILL.md`). An unprompted read by a relative
    path or another tool would still be missed.
  - **Not tested:** sensitivity to a subtle description change. That is the
    degraded-description variant suggested on #26, and it was not run.
- **Limits of scale:** n=1 per arm, one client, one collection. This makes no
  benefit claim and no qualification (#26's own bounds). At most, it suggests
  that `qa-test`'s description did not pull the agent toward it for this
  prompt. That informs the description-revision decision without settling it.
- **Harness defect found during this work, and fixed:**
  - #114's original `SKILLC_ALLOW_REAL_AGENT` pytest test could never launch
    an agent: `tests/conftest.py` keeps every test away from a real
    credential. It still reported PASSED on six `unavailable` attempts.
  - It is replaced by `skillc selection-probe`, which exits 1 unless every
    attempt is captured.
  - A non-captured attempt's report now keeps the record's `reason`.

Each attempt's own observation record (`observation-<attempt>.json`, #142)
and the command's `selection-probe-report.json` were written to the
operator's run store. They are not copied here; the tables above transcribe
them.
