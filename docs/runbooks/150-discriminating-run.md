# #150 discriminating run: operator runbook

- Governs: skillc #150, acceptance items 3 (discrimination) and 4 (export), and the live evidence for item 5 (the agent-path installation receipt reaching PASS on a codex arm).
- Consumer: claude-power-pack #1084 reads `docs/measurements/behavioral-eval/` with `scripts/check-behavioral-eval.py`.
- Cost: ADR 0005 rule 6. Agent attempts use the operator's normal codex subscription login. No judge or API spend; the finish-close-ref grader is deterministic.

Run everything from a skillc checkout at a revision that contains #153, #155, #157, #160, #162 and 150-D. It needs Docker and the trial image.

## 0. Record the declaration first

Fill this in and keep it with the evidence before running anything. A result is only interpretable against what was declared beforehand.

| Field | Value |
|---|---|
| skillc revision | `git rev-parse HEAD` |
| Subject | `cpp-codex` at the pin in `evals/subjects/cpp-codex/subject.json` |
| Client | codex-cli at the version pinned in subject.json; model and effort as pinned (#141) |
| Image | `skillc-trial:<tag>`; record `docker image inspect --format '{{.Id}}' skillc-trial:<tag>` |
| Task | `evals/level1/finish-close-ref` (its grader.json id and revision) |
| Arms | NORMAL (the pinned subject) and DEGRADED (the rule removed at its five locations) |
| Attempts | one positive control, then one NORMAL and one DEGRADED attempt |
| Time cap | `--agent-timeout` (seconds) per attempt |

**Why codex:** only codex has a model-free skill listing, so only a codex arm can derive `installation-ready` SATISFIED and therefore a PASS (ADR 0005, B1 as narrowed, and the 2026-09-28 ruling on the fresh listing container). A Claude Code arm stays INCONCLUSIVE by design.

## 1. Preconditions

Each of these must hold before step 2. If any fails, stop.

1. `make verify` is green on the checkout being run.
2. The image digest is recorded, as in step 0.
3. You have a claude-power-pack checkout at the pinned revision, for the degraded arm.

## 2. Positive control: the environment, not discrimination

An environment fault must never read as discrimination. The CPP #1084 comment of 2026-09-21 records both arms agreeing on a false negative after an IPC fault. So first run the NORMAL subject on the default task, which every prior live run has passed:

```
SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run cpp-codex
```

This must end with the attempt captured, graded PASS, and the installation receipt's discovery listing SATISFIED. If it doesn't, the environment is broken (image, credential, listing or daemon). Stop and diagnose; nothing from steps 3 to 5 would mean anything.

## 3. Build the degraded subject

```
python3 evals/level1/finish-close-ref/degraded/prepare.py \
  --checkout <cpp-checkout-at-pin> --out <runs>/prepared
```

`prepare.py` checks every original file's sha256 against `degrade.toml` (refusing any mismatch), deletes only the declared ranges, and checks each result's sha256. It then runs `bash -n` on the scripts and runs the rule grep. The grep must hit every original, must miss every result, and must find no other statement of the rule anywhere in the tree. Finally it prints the exact `degrade-subject` command. Run that command with `--out <runs>/degraded`. It has the form:

```
skillc degrade-subject cpp-codex --checkout <cpp-checkout-at-pin> \
  --override-file <skill>:<path>=<runs>/prepared/<...>   # once for each of the five locations
  --out <runs>/degraded
```

Check `<runs>/degraded/receipt.json`: `mutation.locations` must list exactly the five locations in `DEGRADATION.md`, and the revision must be a `degraded:` label, never the pin. `manifest_rewrites` must list exactly two lines, `flow-auto/scripts/SHA256SUMS` and `flow-merge/scripts/SHA256SUMS` re-pinning `gh-pr-merge.sh` to its override's hash (#198). That is checksum bookkeeping, not a sixth location.

Every `collection-run` below launches a real agent, which `skillc` refuses (`RealAgentBlocked`) unless `SKILLC_ALLOW_REAL_AGENT=1` is set for that command.

## 4. The two arms

NORMAL:

```
SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run cpp-codex --task evals/level1/finish-close-ref \
  --evidence <runs>/normal-evidence
```

DEGRADED:

```
SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run cpp-codex --task evals/level1/finish-close-ref \
  --degraded <runs>/degraded \
  --evidence <runs>/degraded-evidence --evidence-role control
```

`--evidence-role control` is required. Without it, a degraded-arm export is refused, so that a FAIL can never be published as a measurement by habit.

## 5. Verdict

| NORMAL | DEGRADED | Reading |
|---|---|---|
| PASS | FAIL | **Discriminates.** Export the NORMAL arm (step 6). |
| PASS | PASS | **Non-discriminating.** Report it as such, never as a pass, and export nothing. Check first whether the agent read flow-finish at all (transcript). Then check the one documented residual: the retained incidental guard's code handles negation internally, although no prose states the rule (`DEGRADATION.md`). |
| FAIL or INCONCLUSIVE | any | **Not a usable measurement.** Diagnose the listing, the agent, or the grader. |

Read *why* DEGRADED failed. It must fail on `no-closing-match`, not on `artifact-present` or `issue-ref`. A degraded FAIL for any other reason is not discrimination.

## 6. Consumer checks, then hand-off

Using claude-power-pack's real `scripts/check-behavioral-eval.py` at CPP's current main:

- pointed at `<runs>/normal-evidence`, it must exit 0 (PASS, re-derived);
- pointed at `<runs>/degraded-evidence`, it must exit non-zero. This is the one-shot negative control for CPP's gate.

Hand `<runs>/normal-evidence` to the CPP group. It is already leak-checked and clean under `check-records`. They write it into `docs/measurements/behavioral-eval/`. **Never commit the DEGRADED export to CPP's measurements directory**: a FAIL there turns CPP's gate red permanently. Record the run on skillc #150 with the step-0 declaration and both verdicts.
