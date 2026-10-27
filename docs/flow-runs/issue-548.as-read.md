<!-- flow-run n=1 id=4ee3a6da7cc246e8b646161d535ad2ef -->
## Run 1 - issue #548 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #548
- Read at:      2026-10-27T13:38:38Z
- updatedAt:    2026-10-24T11:56:24Z   (context only - moves on comments and labels)
- Body digest:  65c76dde8dfaf21927f25a426b39026f1e2704997a89e2bee398dc2427b8e0c1   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15214 of 15214 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G7).

## Problem
Identity checks verify the declaration against static pins, not against the thing that runs. The client version is checked against the checkout's pinned-versions.json, not the binary in the image. The legacy calibration path checks the image ID but not the tag. level3_campaign.check_frozen compares only the static pins and passes on an empty block. level3_campaign plans treated trials without skill_digests pins. The calibration-287 degraded arm names the intact arm's profile, so #432's cross-check would refuse it.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **LOW**: The client-version check compares the manifest's declared codex version against docker/trial/pinned-versions.json (the build pin), never the actual binary inside the resolved image digest.
  - Still present: skillc/cli.py:1516 trial_bootstrap.pinned_cli_version("codex") compared only to declaration.client_version (:1517); image is checked only by digest equality (:1526-1534); no `codex --version` probe of the resolved image anywhere in cli.py/trial_bootstrap.py. Same gap exists for calibration-run, see id 5917953677.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5856507042
- [ ] **LOW**: calibration-run and pilot-run check the declared client version against the CHECKOUT's docker/trial/pinned-versions.json, not the actually-running image; nothing runs codex --version inside the resolved digest, and the observed per-attempt cli_version is never compared back.
  - Still present: skillc/cli.py:1516,1765,2158,2289 all call trial_bootstrap.pinned_cli_version (skillc/trial_bootstrap.py:72-82, reads the checkout file only); no codex --version invocation against a resolved image digest exists anywhere in skillc/. Comment itself notes the practical risk is a false refusal (not a false pass), since image-digest equality is the real pin.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953677
- [ ] **LOW**: cmd_calibration_run's legacy-declaration branch (no receipt_sha256) checks only the daemon-resolved image ID, not that --image's tag equals shared.image.tag, so another tag pointing at the same ID is silently accepted for legacy calibration kinds.
  - Still present: skillc/cli.py:1786 `elif image_digest != declared_digest:` is unchanged; no tag comparison added. New kinds still bind tag+ID+receipt via calibration_run.require_image_binding; legacy kinds (calibration-203/-203-low/-204) remain narrower than their declared `tag` field implies, left deliberately out of #287 P3's scope.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243904179
- [ ] **LOW**: skillc/level3_campaign.py's check_frozen() verifies the frozen codex client name/version only against static pins (subject.json, pinned-versions.json), never against the codex binary actually installed inside the built trial image.
  - Still present: skillc/level3_campaign.py:248-278 (check_frozen) on main 5ece908 still only compares `pinned.get('client',...)` and `pinned_cli.get('codex',...)` to each other and to `frozen['client']`; no in-container `codex --version` measurement is read or compared. Explicitly deferred per the comment (partly fixed: name/version cross-pin checks; remainder deferred: in-container measurement).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6172896012
- [ ] **LOW**: level3_campaign.check_frozen iterates only the keys an input manifest's frozen.runtime block happens to supply, so an empty {} or a manifest missing lock_sha256 reports no problem - a check that can't distinguish 'matched' from 'nothing compared'.
  - Still present: skillc/level3_campaign.py:165 (load_manifest only requires frozen.runtime to be a dict) and :274-275 (`for key, value in frozen["runtime"].items()`) are unchanged. The sibling skillc/fixture_campaign.py has a RUNTIME_KEYS-based fix since #434 PR 3a, but level3_campaign.py was deliberately left byte-identical.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6246046769
- [ ] **LOW**: skillc/level3_campaign.py's plan() builds treated trials without declaring skill_digests pins (#354/#429's protection against an unpinned trial's skill-evidence validating clean even if the installed skill was substituted), unlike calibration_run.py and uptake_study.py which #429 updated.
  - Still present: `grep -n skill_digests skillc/level3_campaign.py` returns nothing on main 5ece908, while skillc/calibration_run.py:130-386,475-517 and skillc/uptake_study.py:398-425 both declare/require skill_digests per #424/#429. level3_campaign.py (used by #375/#376 and #271 via #403) remains the one unpinned planner.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237747319
- [ ] **MEDIUM**: evals/calibration-287/pilot-discrimination-declaration.json's degraded arm names the same subject profile (cpp-codex-flow-check-86641e8) as the intact arm; after #432's inventory-pin-vs-installed-skill cross-check, the degraded arm's deliberately altered SKILL.md digest can never match the intact inventory's pin, so the first attempt to wire the degraded arm would be refused by #432's check, and #287 has not yet decided how the degraded arm should be pinned.
  - Still present: evals/calibration-287/pilot-discrimination-declaration.json still declares both "intact" and "degraded" arms with `"profile": "evals/subjects/cpp-codex-flow-check-86641e8"` on main 5ece908; issue #287 is OPEN; the declaration is still a draft (the CLI does not run discrimination declarations yet, so nothing fails today, matching the comment).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6238427945

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5856507042 (2026-09-27)</summary>

**Severity: low.** Found by the Codex counter-model review while working #12.

`skillc/cli.py` `cmd_pilot_run`: the client-version check compares the manifest's declared codex version with `docker/trial/pinned-versions.json`. That's the version the image was meant to be built with, not the binary inside the resolved image. Since #12's review fix, the image digest itself must equal the declared one, which transitively fixes the binary. But nothing reads `codex --version` inside the image, so an image rebuilt with a different pin and then re-declared would pass without anyone checking the client.

Why it matters: "A pin has to be checked, not just declared" (owner comment on #12, citing config-drift-checker).

Fix: run `codex --version` in a throwaway container from the resolved digest before the schedule, compare it with the declaration, and refuse on a mismatch.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953677 (2026-09-30)</summary>

**Severity: LOW** - counter-model finding (OpenAI Codex, `gpt-6-astra`, via `/codex:code_review`), deferred during #207.

`skillc/cli.py` `cmd_calibration_run` (and `cmd_pilot_run`, which has the same posture) checks the declared client version against `trial_bootstrap.pinned_cli_version(...)`, which reads the CHECKOUT's `docker/trial/pinned-versions.json`, not the image being run. Bumping that file refuses an approved declaration whose immutable image (checked separately by digest) is unchanged, and a matching local pin does not prove what client the resolved image contains.

Why it matters: the guard can't tell "the runtime changed" from "a neighbouring build recipe changed". The image-digest equality check is the real pin today, so the practical risk is a false refusal, not a false pass. The observed per-attempt `cli_version` from the rollout (`run_metadata.cli_version`) is available after the fact but not compared.

Possible fix: measure the client version inside the resolved digest before planning (one `docker run <digest> codex --version`), or compare the observed `cli_version` per attempt the way the model is, and drop the checkout-file comparison.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243904179 (2026-10-18)</summary>

**Severity: low.** Found while working #287 P3 (branch `issue-287-p3-complete-declarations`, Codex review pass 1).

`skillc/cli.py`, `cmd_calibration_run`, the `elif image_digest != declared_digest:` branch. This is the path for a declaration whose `shared.image` has no `receipt_sha256`, which today means every legacy calibration declaration without an outcome endpoint (calibration-203, -203-low, -204).

**What's wrong:** this branch compares only the daemon-resolved image ID. It does not check that the operator's `--image` tag equals `shared.image.tag`, so another tag pointing at the same ID is accepted.

**Why it matters:** the image ID is the identity that matters, and that is still bound, so this is not a correctness hole for the image actually run. But the declared tag is not enforced for legacy kinds, while new kinds bind tag, ID and receipt together through `calibration_run.require_image_binding`. That is a narrower contract than the declaration's `tag` field suggests.

P3 deliberately left legacy behaviour unchanged, because re-running a legacy declaration is out of #287's scope.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6172896012 (2026-10-14)</summary>

**`skillc level3-campaign` checks the frozen client version statically, not against the binary that runs** (counter-model finding, codex/gpt-6-astra pass 2 on #375; partly fixed, remainder deferred)

- **Where:** `skillc/level3_campaign.py` `check_frozen()`, added by #375.
- **Fixed:** the frozen client name must be `codex`, and its version must equal both the subject pin (`evals/subjects/cpp-codex-flow-check-86641e8/subject.json`) and the trial image pin (`docker/trial/pinned-versions.json`). Committed controls cover a mismatched name and a mismatched version.
- **Deferred:** the version of the `codex` binary actually inside the built image (which the model-free skill listing runs) is not measured by the campaign. A trial image built from a tree whose pin and actual install diverged would run under a frozen client identity it never checked. Today that would take a broken image build, since the Dockerfile installs `@openai/codex@${CODEX_VERSION}` from the same pin. The natural fix is to have the listing record `codex --version` from the container and compare it in the report.
- **Why deferred:** it needs an in-container measurement in the receipt/listing path, which is outside the campaign harness's scope.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6246046769 (2026-10-18)</summary>

**Severity: LOW. `level3_campaign.check_frozen` compares only the runtime keys a manifest supplies, so an empty `frozen.runtime` passes with nothing checked.**

**Where:** `skillc/level3_campaign.py:165` (`load_manifest` only requires `frozen.runtime` to be a dict) and `:274` (`for key, value in frozen["runtime"].items()`). A manifest whose runtime block is `{}`, or that omits `lock_sha256`, reports no runtime problem: the check iterates the supplied keys, not the identity's required ones.

**Why it matters:** `skillc level3-campaign --manifest <path>` accepts any manifest path and claims to validate its frozen identities. The committed #375 manifest is protected by `test_the_committed_manifest_is_the_freeze_scripts_output`, but a hand-edited or newly written manifest can drop the runtime identity silently. That is a zero that can't tell "matched" from "nothing compared". `caps` is compared the right way round (over `caps()`'s executed keys); runtime is not.

**Possible fix (not applied):** require `set(frozen["runtime"]) == {"runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256"}`, with reds for `{}` and for each omitted key. #434's `skillc/fixture_campaign.py` now does exactly this (`RUNTIME_KEYS`), but `level3_campaign.py` is deliberately left byte-identical in #434 PR 3a, so #375's module is not changed there.

**How it was found:** the counter-model review of #434 PR 3a, pass 1, flagged the same shape in the fixture campaign.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237747319 (2026-10-17)</summary>

**Severity: LOW** - found while rebasing PR #403 (#271) onto main after #429 (#424).

`skillc/level3_campaign.py` `plan()` (around lines 358-380) builds its treated trials without declaring `skill_digests`. #429 made both production planners (`calibration_run`, `uptake_study`) declare #354's pin, because an unpinned trial's `skill-evidence` validates clean even when the installed skill was substituted. The Level-3 production-path campaign (#375/#376, and #271 via #403) is a third planner of treated trials and still plans them unpinned.

Why it matters: campaign rows are certification evidence for the grading path. If the installed flow-check skill bytes differed from the profile's, nothing in the campaign's ledger would refuse it. The scripted actor doesn't depend on skill text, so today's verdicts aren't wrong; the record is simply weaker than the calibration/uptake ones. Fix shape: have `plan()` declare the treatment's skill pins the way `calibration_run` now does, with a red case that substitutes a skill.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6238427945 (2026-10-17)</summary>

**Severity: MEDIUM** - found while fixing #432 (build_treatment pin cross-check).

`evals/calibration-287/pilot-discrimination-declaration.json` arms[1] (`degraded`) names the same profile as the intact arm, `evals/subjects/cpp-codex-flow-check-86641e8`. `skillc calibration-run` builds treatments through `cr.build_treatment(acquired, subject_profile=..., root=...)` (`skillc/cli.py:1760`). After #432 that check compares each inventory pin with the installed skill at the same path, per digest. A degraded arm installs a deliberately altered `flow-check/SKILL.md`, so its body digest can never equal the intact inventory's pin, and the arm would be refused by design.

Why it matters: the CLI doesn't run discrimination declarations today (the declaration is a DRAFT), so nothing fails now. The first attempt to wire the degraded arm will hit this refusal, and the tempting fix, weakening the cross-check, would reopen #424's hole. #287 needs to decide how a degraded arm is pinned: its own degraded inventory, or the profile cross-check skipped for that one arm with the substitution recorded in the ledger.

</details>


<!-- end of body -->

<!-- flow-run n=2 id=a27ef7d7ad674c4aa5d7f8606108c96d -->
## Run 2 - issue #548 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #548
- Read at:      2026-10-27T18:23:50Z
- updatedAt:    2026-10-27T15:19:59Z   (context only - moves on comments and labels)
- Body digest:  2ae9ea6e30e8ac0c2b3bff340802295f030dfec996ce3c3a993f40e8e8d3c4db   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15214 of 15214 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G7).

## Problem
Identity checks verify the declaration against static pins, not against the thing that runs. The client version is checked against the checkout's pinned-versions.json, not the binary in the image. The legacy calibration path checks the image ID but not the tag. level3_campaign.check_frozen compares only the static pins and passes on an empty block. level3_campaign plans treated trials without skill_digests pins. The calibration-287 degraded arm names the intact arm's profile, so #432's cross-check would refuse it.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **LOW**: The client-version check compares the manifest's declared codex version against docker/trial/pinned-versions.json (the build pin), never the actual binary inside the resolved image digest.
  - Still present: skillc/cli.py:1516 trial_bootstrap.pinned_cli_version("codex") compared only to declaration.client_version (:1517); image is checked only by digest equality (:1526-1534); no `codex --version` probe of the resolved image anywhere in cli.py/trial_bootstrap.py. Same gap exists for calibration-run, see id 5917953677.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5856507042
- [ ] **LOW**: calibration-run and pilot-run check the declared client version against the CHECKOUT's docker/trial/pinned-versions.json, not the actually-running image; nothing runs codex --version inside the resolved digest, and the observed per-attempt cli_version is never compared back.
  - Still present: skillc/cli.py:1516,1765,2158,2289 all call trial_bootstrap.pinned_cli_version (skillc/trial_bootstrap.py:72-82, reads the checkout file only); no codex --version invocation against a resolved image digest exists anywhere in skillc/. Comment itself notes the practical risk is a false refusal (not a false pass), since image-digest equality is the real pin.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953677
- [ ] **LOW**: cmd_calibration_run's legacy-declaration branch (no receipt_sha256) checks only the daemon-resolved image ID, not that --image's tag equals shared.image.tag, so another tag pointing at the same ID is silently accepted for legacy calibration kinds.
  - Still present: skillc/cli.py:1786 `elif image_digest != declared_digest:` is unchanged; no tag comparison added. New kinds still bind tag+ID+receipt via calibration_run.require_image_binding; legacy kinds (calibration-203/-203-low/-204) remain narrower than their declared `tag` field implies, left deliberately out of #287 P3's scope.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243904179
- [ ] **LOW**: skillc/level3_campaign.py's check_frozen() verifies the frozen codex client name/version only against static pins (subject.json, pinned-versions.json), never against the codex binary actually installed inside the built trial image.
  - Still present: skillc/level3_campaign.py:248-278 (check_frozen) on main 5ece908 still only compares `pinned.get('client',...)` and `pinned_cli.get('codex',...)` to each other and to `frozen['client']`; no in-container `codex --version` measurement is read or compared. Explicitly deferred per the comment (partly fixed: name/version cross-pin checks; remainder deferred: in-container measurement).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6172896012
- [x] **LOW**: level3_campaign.check_frozen iterates only the keys an input manifest's frozen.runtime block happens to supply, so an empty {} or a manifest missing lock_sha256 reports no problem - a check that can't distinguish 'matched' from 'nothing compared'.
  - Still present: skillc/level3_campaign.py:165 (load_manifest only requires frozen.runtime to be a dict) and :274-275 (`for key, value in frozen["runtime"].items()`) are unchanged. The sibling skillc/fixture_campaign.py has a RUNTIME_KEYS-based fix since #434 PR 3a, but level3_campaign.py was deliberately left byte-identical.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6246046769
- [x] **LOW**: skillc/level3_campaign.py's plan() builds treated trials without declaring skill_digests pins (#354/#429's protection against an unpinned trial's skill-evidence validating clean even if the installed skill was substituted), unlike calibration_run.py and uptake_study.py which #429 updated.
  - Still present: `grep -n skill_digests skillc/level3_campaign.py` returns nothing on main 5ece908, while skillc/calibration_run.py:130-386,475-517 and skillc/uptake_study.py:398-425 both declare/require skill_digests per #424/#429. level3_campaign.py (used by #375/#376 and #271 via #403) remains the one unpinned planner.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237747319
- [x] **MEDIUM**: evals/calibration-287/pilot-discrimination-declaration.json's degraded arm names the same subject profile (cpp-codex-flow-check-86641e8) as the intact arm; after #432's inventory-pin-vs-installed-skill cross-check, the degraded arm's deliberately altered SKILL.md digest can never match the intact inventory's pin, so the first attempt to wire the degraded arm would be refused by #432's check, and #287 has not yet decided how the degraded arm should be pinned.
  - Still present: evals/calibration-287/pilot-discrimination-declaration.json still declares both "intact" and "degraded" arms with `"profile": "evals/subjects/cpp-codex-flow-check-86641e8"` on main 5ece908; issue #287 is OPEN; the declaration is still a draft (the CLI does not run discrimination declarations yet, so nothing fails today, matching the comment).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6238427945

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5856507042 (2026-09-27)</summary>

**Severity: low.** Found by the Codex counter-model review while working #12.

`skillc/cli.py` `cmd_pilot_run`: the client-version check compares the manifest's declared codex version with `docker/trial/pinned-versions.json`. That's the version the image was meant to be built with, not the binary inside the resolved image. Since #12's review fix, the image digest itself must equal the declared one, which transitively fixes the binary. But nothing reads `codex --version` inside the image, so an image rebuilt with a different pin and then re-declared would pass without anyone checking the client.

Why it matters: "A pin has to be checked, not just declared" (owner comment on #12, citing config-drift-checker).

Fix: run `codex --version` in a throwaway container from the resolved digest before the schedule, compare it with the declaration, and refuse on a mismatch.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953677 (2026-09-30)</summary>

**Severity: LOW** - counter-model finding (OpenAI Codex, `gpt-6-astra`, via `/codex:code_review`), deferred during #207.

`skillc/cli.py` `cmd_calibration_run` (and `cmd_pilot_run`, which has the same posture) checks the declared client version against `trial_bootstrap.pinned_cli_version(...)`, which reads the CHECKOUT's `docker/trial/pinned-versions.json`, not the image being run. Bumping that file refuses an approved declaration whose immutable image (checked separately by digest) is unchanged, and a matching local pin does not prove what client the resolved image contains.

Why it matters: the guard can't tell "the runtime changed" from "a neighbouring build recipe changed". The image-digest equality check is the real pin today, so the practical risk is a false refusal, not a false pass. The observed per-attempt `cli_version` from the rollout (`run_metadata.cli_version`) is available after the fact but not compared.

Possible fix: measure the client version inside the resolved digest before planning (one `docker run <digest> codex --version`), or compare the observed `cli_version` per attempt the way the model is, and drop the checkout-file comparison.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243904179 (2026-10-18)</summary>

**Severity: low.** Found while working #287 P3 (branch `issue-287-p3-complete-declarations`, Codex review pass 1).

`skillc/cli.py`, `cmd_calibration_run`, the `elif image_digest != declared_digest:` branch. This is the path for a declaration whose `shared.image` has no `receipt_sha256`, which today means every legacy calibration declaration without an outcome endpoint (calibration-203, -203-low, -204).

**What's wrong:** this branch compares only the daemon-resolved image ID. It does not check that the operator's `--image` tag equals `shared.image.tag`, so another tag pointing at the same ID is accepted.

**Why it matters:** the image ID is the identity that matters, and that is still bound, so this is not a correctness hole for the image actually run. But the declared tag is not enforced for legacy kinds, while new kinds bind tag, ID and receipt together through `calibration_run.require_image_binding`. That is a narrower contract than the declaration's `tag` field suggests.

P3 deliberately left legacy behaviour unchanged, because re-running a legacy declaration is out of #287's scope.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6172896012 (2026-10-14)</summary>

**`skillc level3-campaign` checks the frozen client version statically, not against the binary that runs** (counter-model finding, codex/gpt-6-astra pass 2 on #375; partly fixed, remainder deferred)

- **Where:** `skillc/level3_campaign.py` `check_frozen()`, added by #375.
- **Fixed:** the frozen client name must be `codex`, and its version must equal both the subject pin (`evals/subjects/cpp-codex-flow-check-86641e8/subject.json`) and the trial image pin (`docker/trial/pinned-versions.json`). Committed controls cover a mismatched name and a mismatched version.
- **Deferred:** the version of the `codex` binary actually inside the built image (which the model-free skill listing runs) is not measured by the campaign. A trial image built from a tree whose pin and actual install diverged would run under a frozen client identity it never checked. Today that would take a broken image build, since the Dockerfile installs `@openai/codex@${CODEX_VERSION}` from the same pin. The natural fix is to have the listing record `codex --version` from the container and compare it in the report.
- **Why deferred:** it needs an in-container measurement in the receipt/listing path, which is outside the campaign harness's scope.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6246046769 (2026-10-18)</summary>

**Severity: LOW. `level3_campaign.check_frozen` compares only the runtime keys a manifest supplies, so an empty `frozen.runtime` passes with nothing checked.**

**Where:** `skillc/level3_campaign.py:165` (`load_manifest` only requires `frozen.runtime` to be a dict) and `:274` (`for key, value in frozen["runtime"].items()`). A manifest whose runtime block is `{}`, or that omits `lock_sha256`, reports no runtime problem: the check iterates the supplied keys, not the identity's required ones.

**Why it matters:** `skillc level3-campaign --manifest <path>` accepts any manifest path and claims to validate its frozen identities. The committed #375 manifest is protected by `test_the_committed_manifest_is_the_freeze_scripts_output`, but a hand-edited or newly written manifest can drop the runtime identity silently. That is a zero that can't tell "matched" from "nothing compared". `caps` is compared the right way round (over `caps()`'s executed keys); runtime is not.

**Possible fix (not applied):** require `set(frozen["runtime"]) == {"runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256"}`, with reds for `{}` and for each omitted key. #434's `skillc/fixture_campaign.py` now does exactly this (`RUNTIME_KEYS`), but `level3_campaign.py` is deliberately left byte-identical in #434 PR 3a, so #375's module is not changed there.

**How it was found:** the counter-model review of #434 PR 3a, pass 1, flagged the same shape in the fixture campaign.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237747319 (2026-10-17)</summary>

**Severity: LOW** - found while rebasing PR #403 (#271) onto main after #429 (#424).

`skillc/level3_campaign.py` `plan()` (around lines 358-380) builds its treated trials without declaring `skill_digests`. #429 made both production planners (`calibration_run`, `uptake_study`) declare #354's pin, because an unpinned trial's `skill-evidence` validates clean even when the installed skill was substituted. The Level-3 production-path campaign (#375/#376, and #271 via #403) is a third planner of treated trials and still plans them unpinned.

Why it matters: campaign rows are certification evidence for the grading path. If the installed flow-check skill bytes differed from the profile's, nothing in the campaign's ledger would refuse it. The scripted actor doesn't depend on skill text, so today's verdicts aren't wrong; the record is simply weaker than the calibration/uptake ones. Fix shape: have `plan()` declare the treatment's skill pins the way `calibration_run` now does, with a red case that substitutes a skill.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6238427945 (2026-10-17)</summary>

**Severity: MEDIUM** - found while fixing #432 (build_treatment pin cross-check).

`evals/calibration-287/pilot-discrimination-declaration.json` arms[1] (`degraded`) names the same profile as the intact arm, `evals/subjects/cpp-codex-flow-check-86641e8`. `skillc calibration-run` builds treatments through `cr.build_treatment(acquired, subject_profile=..., root=...)` (`skillc/cli.py:1760`). After #432 that check compares each inventory pin with the installed skill at the same path, per digest. A degraded arm installs a deliberately altered `flow-check/SKILL.md`, so its body digest can never equal the intact inventory's pin, and the arm would be refused by design.

Why it matters: the CLI doesn't run discrimination declarations today (the declaration is a DRAFT), so nothing fails now. The first attempt to wire the degraded arm will hit this refusal, and the tempting fix, weakening the cross-check, would reopen #424's hole. #287 needs to decide how a degraded arm is pinned: its own degraded inventory, or the profile cross-check skipped for that one arm with the substitution recorded in the ledger.

</details>


<!-- end of body -->
