<!-- flow-run n=1 id=efb0e2b868404b9f9a438241b086f9c0 -->
## Run 1 - issue #542 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #542
- Read at:      2026-10-27T10:36:43Z
- updatedAt:    2026-10-24T11:56:18Z   (context only - moves on comments and labels)
- Body digest:  9015c837e41a33b59fd4702ba703248eee5596dec76961288a5d48aabe53caab   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15562 of 15562 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G1).

## Problem
Several gates and negative controls can report green without checking what they claim. The typecheck control sabotages whichever `test_*.py` sorts first, even a fixture the gate never collects. `mypy` excludes `evals/`, and those files already hold 14 latent errors. The version and cold-cache oracles are substring matches. changelog-check reads only committed history.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: ci/typecheck-control.sh's negative-control probe targets whatever test_*.py sorts first under tests/, including fixture test files the typecheck gate never collects, silently disarming the control.
  - Still present: ci/typecheck-control.sh:51 is unchanged: target=$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1). No exclude-fixtures or explicit-target fix landed; no tracking issue found via gh search.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062
- [ ] **MEDIUM**: Same defect as 6241922062, with a concrete reproduction: ci/typecheck-control.sh's probe target can be hijacked by an earlier-sorting tests/fixtures/.../test_*.py, so the control's own committed red case stops discriminating.
  - Still present: ci/typecheck-control.sh:51 unchanged; reproduced against #280's fixture tests/fixtures/cicd-local/project/tests/test_calc.py (worked around there by renaming to check_calc.py, instrument itself untouched). No exclude-fixtures fix or new red case has landed.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356
- [ ] **MEDIUM**: pyproject.toml's [tool.mypy] files list still excludes evals/, so hand-duplicated _WitnessBackend Protocol-signature test doubles get zero static-type signal; the count of such doubles has grown from 3 to 6+ since this comment, meaning the recurring-break risk it warned about is larger today, not smaller.
  - Still present: pyproject.toml:46 `files = ["skillc", "tests", "ci"]` unchanged; grep finds _WitnessBackend classes in evals/level3/{flow-auto-step6-gate,claims-outran-evidence,flow-auto-necessity,verify-stops-early,gate-stops-early-auto6}/qualify.py (5-6 copies vs the original 3).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843
- [ ] **LOW**: evals/level3/gate-stops-early/qualify.py and verify-stops-early/qualify.py each have 14 mypy errors (predating #419) that the project gate never sees because mypy's configured scope excludes evals/, even though these scripts decide grader fitness (QUALIFY: ok/fail).
  - Still present: Ran `.venv/bin/mypy evals/level3/gate-stops-early/qualify.py` on main 5ece908: 14 errors, matching the comment's count exactly; pyproject.toml:46 `[tool.mypy] files = ["skillc", "tests", "ci"]` still excludes evals/.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665
- [ ] **MEDIUM**: test_uv_is_present_at_the_pinned_version still uses a substring containment check, so a longer neighboring version (e.g. 0.9.70) would satisfy a 0.9.7 pin; an instrument overclaiming exact-version evidence.
  - Still present: tests/test_trial_image_tools_live.py:76,135 unchanged `_PINNED_UV_VERSION in uv_version.stdout`; commit 9bda3c5 (#363) commit message: 'Supplemental finding: exact uv-version substring check can accept a longer neighboring version; recorded separately at ...issuecomment-6126726298.'
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298
- [ ] **LOW**: tests/test_profile_install_cold_container_live.py's coldinstall:cold-cache oracle is a raw substring check (`"wasn't found in the cache" in sync.stderr`) that could land inside uv's line-wrapped diagnostic text for a longer package name/URL, turning the expected-red into an ordinary assertion failure.
  - Still present: tests/test_profile_install_cold_container_live.py:408 (`assert "wasn't found in the cache" in sync.stderr`) unchanged on main 5ece908; no whitespace-normalised oracle (_offline_cache_miss pattern) adopted here. Passes today on real Docker per the comment; not a live defect, just fragile.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195
- [ ] **LOW**: make verify's changelog-check step diffs only committed history (merge-base(origin/main,HEAD)..HEAD via git diff/git show), unlike every other verify step which reads the working tree - so running it before committing (the flow:auto/codex:auto step ordering) reports a stale 'ok'.
  - Still present: ci/changelog_check.py:172-199 main(): _merge_base, git diff --name-only, _show("HEAD", path) - all git-ref based, no git status/working-tree check anywhere in the file. #439 (changelog.d/ fragments) changed the entry format but not this sequencing; the trap is unchanged.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062 (2026-10-17)</summary>

**Severity: medium (a negative control can be silently disarmed).** Found while orchestrating #280 (reported by session skillc-worker-B; filed by skillc-400). `ci/typecheck-control.sh` plants its probe in **the first `tests/**/test_*.py` it finds**. #280's fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` sorted first, so the control probed a FIXTURE, and its committed red case (`tests/test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red`) could no longer go red. The gate caught it this time only because that red-case test exists. Any future fixture or helper named `test_*.py` that sorts earlier could hijack the target the same way. #280 worked around it by renaming its fixture to `check_calc.py`. **Fix options:** target an explicit, declared probe file (or a list) instead of glob order; or exclude `tests/fixtures/**` and assert the chosen target is a real top-level test module; plus a test that a planted early-sorting fixture `test_*.py` doesn't change the target.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356 (2026-10-18)</summary>

**ci/typecheck-control.sh:51: the probe target is whatever test file sorts first under tests/, including fixture test files that the gate never collects.**

`target="$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1)"` picks the first `test_*.py` anywhere under `tests/`. When a fixture project ships its own `tests/fixtures/.../tests/test_*.py` and that path sorts first, the control plants its deliberate type error in a file that the measured typecheck population does not include. `test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red` then stops discriminating.

Why it matters: this instrument exists to prove the typecheck step can go red. A neighbouring fixture can switch it off silently, and the failure looks like an ordinary red on the PR that added the fixture, so it gets "fixed" by renaming the fixture instead of being recognised as an instrument defect.

Found while coordinating #280 (skillc-worker-B). Its fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` triggered the failure in the 18:01 verify run. #280 worked around it by renaming the fixture module to `check_calc.py`; the instrument is unchanged. It does not reproduce on main 358f21b (7/7 pass).

Possible fix: select the target from the same population the typecheck step measures (for example, exclude `tests/fixtures/`), and add a red case: a fixture `test_*.py` that sorts first must not become the target.

Severity: low-medium. It is silent harm to a gate instrument, but needs a specific fixture layout to trigger.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843 (2026-10-07)</summary>

`pyproject.toml`'s `[tool.mypy] files = ["skillc", "tests", "ci"]` does not include `evals/`. The three `_WitnessBackend` test doubles in `evals/level3/{claims-outran-evidence,report-outran-evidence,gate-stops-early}/qualify.py` (hand-duplicated copies of `ExecutionBackend.exec_in_attempt`'s signature) therefore go stale against a real Protocol signature change with zero static-type signal from `make typecheck` - only `tests/test_qualify_scripts_run.py` actually invoking them catches it, and only by running the full suite.

This has now happened twice for the identical reason: #270 (when `cwd`/`env` were added to the Protocol) and again on #338 (when `confine_root` was added) - both times discovered only by a full-suite run going red with `TypeError: _WitnessBackend.exec_in_attempt() got an unexpected keyword argument ...`, never by the lint/typecheck gates that run before it. Worth deciding deliberately whether `evals/` should be in mypy's `files` list, or whether these three doubles should be deduplicated into one shared helper `tests/test_qualify_scripts_run.py` imports, rather than hand-copied a fourth time the next Protocol change.

Found while implementing #338 (the cwd-confinement TOCTOU fix) - not fixed structurally here, only patched at the three call sites to restore the suite to green.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665 (2026-10-17)</summary>

**Severity: low.** Found while orchestrating #419 (reported by session skillc-avail; filed by skillc-400). `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py` each show **14 mypy errors** when checked directly. All are in lines that predate #419; none is in its additions. `evals/` is outside mypy's configured scope (`mypy` covers skillc/ and tests/), so the gate never sees them. **Why it matters:** these scripts decide whether a grader is fit to grade (QUALIFY: ok/fail), so a type error there could hide a control that silently checks the wrong thing. **Options:** fix the 14 per script, or bring `evals/**/qualify.py` into mypy's scope with a baseline.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298 (2026-10-12)</summary>

**Verified supplemental finding from #341 / PR #358 replay review and #356 design: the live uv probe does not enforce its documented exact version.**

`tests/test_trial_image_tools_live.py::test_uv_is_present_at_the_pinned_version` uses `_PINNED_UV_VERSION in uv_version.stdout`. On main `450445d`, the committed pin is `0.9.7`, but the actual function accepts `uv 0.9.70\n` with exit 0. Verified without Docker by loading the actual module with daemon discovery disabled and replacing only `subprocess.run` with that completed observation; the function returned without raising. This establishes the predicate gap, not that such an image was built.

Impact: a neighboring version that contains the pinned string can satisfy the claimed exact-version evidence. Existing generic wrong-version controls (`0.0.0`) do not detect this case.

Suggested follow-up: parse and compare the uv version token exactly, retaining any documented build metadata format, and add controls for both the intended pin and a prefix-sharing wrong version. Keep Docker launch/infrastructure failure discrimination. This is outside #341's exception-isolation edit scope; coordinate with the current #356 owner before changing its acceptance probe. No separate issue created.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195 (2026-10-13)</summary>

**Severity: low.** `tests/test_profile_install_cold_container_live.py:408`: the `coldinstall:cold-cache` break mode's oracle is a raw substring check, `"wasn't found in the cache" in sync.stderr`. uv wraps its diagnostics at a fixed width. On uv 0.9.7's real offline output the break falls before "requested data wasn't found in the cache" (see `tests/fixtures/uv-offline-cache-miss-0.9.7.txt`), so the check passes today. But a longer package name, URL or path can move the wrap point into the phrase. That would make the break mode fail as an ordinary assertion instead of a targeted expected-red, the same failure shape #360 just fixed in the closure-preflight test. Suggested fix: reuse a whitespace-normalised oracle (the `_offline_cache_miss` pattern added for #360) and add a phrase-internal wrap case. Found while fixing #360's live oracle (flow:auto #360). It passes on real Docker today, so this is not a live defect.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296 (2026-10-01)</summary>

\`make verify\`'s \`changelog-check\` target (\`git fetch origin main --quiet; python3 ci/changelog_check.py origin/main\`) diffs \`merge-base(origin/main, HEAD)..HEAD\` - i.e. **committed** history only, via \`git diff --name-only\` and \`git show HEAD:CHANGELOG.md\`. Every other step in \`make verify\` (lint, typecheck, test, leak-check) reads the actual files on disk, so it reflects uncommitted edits. \`changelog-check\` is the one step in the aggregate that does not: it is blind to anything not yet committed.

Reproduced directly: checked out a commit that changes \`skillc/\` with no new \`[Unreleased]\` line, in an isolated worktree, and ran the exact target.
\`\`\`
$ git rev-parse HEAD
<a commit touching skillc/, no changelog entry>
$ make changelog-check
git fetch origin main --quiet
python3 ci/changelog_check.py origin/main
changelog-check: FAIL - skillc/ changed but CHANGELOG.md's [Unreleased] section gained no new line since the merge-base - a deletion or reformat is not an entry
make: *** [Makefile:78: changelog-check] Error 1
\`\`\`
So the check itself is correct and matches CI exactly at a given commit - this is not a tooling bug. The trap is sequencing: running \`make verify\` (or just \`make changelog-check\`) **before committing** pending changes to \`skillc/\` reports \`changelog-check: ok\`, because at that point \`HEAD\` is still the unchanged parent and \`git diff merge-base..HEAD\` is empty - there's nothing yet for the diff to see. The \`ok\` is technically true of HEAD as it stood, but reads as "this change is clean" to whoever ran it, since every sibling step in the same \`make verify\` run DID evaluate the real pending change.

This is exactly the ordering \`/codex:auto\` and \`/flow:auto\` use by design: Step 6 (quality gates) runs before Step 7 (commit/finish). Any run that follows that ordering gets a silently-blind pass on this one step. Found while working #199 (PR #218): local \`make verify\` reported \`changelog-check: ok\` run before the commit existed; CI, against the real committed diff, correctly failed it. Not fixed here - filing per the orchestrator's request rather than widening #218.

Possible angle for whoever picks this up: have the target (or a wrapping \`verify\`) also compare against the dirty worktree, or at minimum print which ref it diffed so an \`ok\` is legible as "committed-state ok" rather than unqualified.

</details>


<!-- end of body -->

<!-- flow-run n=2 id=061d26d23f314847840a3c86d83b20c6 -->
## Run 2 - issue #542 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #542
- Read at:      2026-10-27T10:50:10Z
- updatedAt:    2026-10-24T11:56:18Z   (context only - moves on comments and labels)
- Body digest:  9015c837e41a33b59fd4702ba703248eee5596dec76961288a5d48aabe53caab   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15562 of 15562 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G1).

## Problem
Several gates and negative controls can report green without checking what they claim. The typecheck control sabotages whichever `test_*.py` sorts first, even a fixture the gate never collects. `mypy` excludes `evals/`, and those files already hold 14 latent errors. The version and cold-cache oracles are substring matches. changelog-check reads only committed history.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: ci/typecheck-control.sh's negative-control probe targets whatever test_*.py sorts first under tests/, including fixture test files the typecheck gate never collects, silently disarming the control.
  - Still present: ci/typecheck-control.sh:51 is unchanged: target=$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1). No exclude-fixtures or explicit-target fix landed; no tracking issue found via gh search.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062
- [ ] **MEDIUM**: Same defect as 6241922062, with a concrete reproduction: ci/typecheck-control.sh's probe target can be hijacked by an earlier-sorting tests/fixtures/.../test_*.py, so the control's own committed red case stops discriminating.
  - Still present: ci/typecheck-control.sh:51 unchanged; reproduced against #280's fixture tests/fixtures/cicd-local/project/tests/test_calc.py (worked around there by renaming to check_calc.py, instrument itself untouched). No exclude-fixtures fix or new red case has landed.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356
- [ ] **MEDIUM**: pyproject.toml's [tool.mypy] files list still excludes evals/, so hand-duplicated _WitnessBackend Protocol-signature test doubles get zero static-type signal; the count of such doubles has grown from 3 to 6+ since this comment, meaning the recurring-break risk it warned about is larger today, not smaller.
  - Still present: pyproject.toml:46 `files = ["skillc", "tests", "ci"]` unchanged; grep finds _WitnessBackend classes in evals/level3/{flow-auto-step6-gate,claims-outran-evidence,flow-auto-necessity,verify-stops-early,gate-stops-early-auto6}/qualify.py (5-6 copies vs the original 3).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843
- [ ] **LOW**: evals/level3/gate-stops-early/qualify.py and verify-stops-early/qualify.py each have 14 mypy errors (predating #419) that the project gate never sees because mypy's configured scope excludes evals/, even though these scripts decide grader fitness (QUALIFY: ok/fail).
  - Still present: Ran `.venv/bin/mypy evals/level3/gate-stops-early/qualify.py` on main 5ece908: 14 errors, matching the comment's count exactly; pyproject.toml:46 `[tool.mypy] files = ["skillc", "tests", "ci"]` still excludes evals/.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665
- [ ] **MEDIUM**: test_uv_is_present_at_the_pinned_version still uses a substring containment check, so a longer neighboring version (e.g. 0.9.70) would satisfy a 0.9.7 pin; an instrument overclaiming exact-version evidence.
  - Still present: tests/test_trial_image_tools_live.py:76,135 unchanged `_PINNED_UV_VERSION in uv_version.stdout`; commit 9bda3c5 (#363) commit message: 'Supplemental finding: exact uv-version substring check can accept a longer neighboring version; recorded separately at ...issuecomment-6126726298.'
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298
- [ ] **LOW**: tests/test_profile_install_cold_container_live.py's coldinstall:cold-cache oracle is a raw substring check (`"wasn't found in the cache" in sync.stderr`) that could land inside uv's line-wrapped diagnostic text for a longer package name/URL, turning the expected-red into an ordinary assertion failure.
  - Still present: tests/test_profile_install_cold_container_live.py:408 (`assert "wasn't found in the cache" in sync.stderr`) unchanged on main 5ece908; no whitespace-normalised oracle (_offline_cache_miss pattern) adopted here. Passes today on real Docker per the comment; not a live defect, just fragile.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195
- [ ] **LOW**: make verify's changelog-check step diffs only committed history (merge-base(origin/main,HEAD)..HEAD via git diff/git show), unlike every other verify step which reads the working tree - so running it before committing (the flow:auto/codex:auto step ordering) reports a stale 'ok'.
  - Still present: ci/changelog_check.py:172-199 main(): _merge_base, git diff --name-only, _show("HEAD", path) - all git-ref based, no git status/working-tree check anywhere in the file. #439 (changelog.d/ fragments) changed the entry format but not this sequencing; the trap is unchanged.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062 (2026-10-17)</summary>

**Severity: medium (a negative control can be silently disarmed).** Found while orchestrating #280 (reported by session skillc-worker-B; filed by skillc-400). `ci/typecheck-control.sh` plants its probe in **the first `tests/**/test_*.py` it finds**. #280's fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` sorted first, so the control probed a FIXTURE, and its committed red case (`tests/test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red`) could no longer go red. The gate caught it this time only because that red-case test exists. Any future fixture or helper named `test_*.py` that sorts earlier could hijack the target the same way. #280 worked around it by renaming its fixture to `check_calc.py`. **Fix options:** target an explicit, declared probe file (or a list) instead of glob order; or exclude `tests/fixtures/**` and assert the chosen target is a real top-level test module; plus a test that a planted early-sorting fixture `test_*.py` doesn't change the target.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356 (2026-10-18)</summary>

**ci/typecheck-control.sh:51: the probe target is whatever test file sorts first under tests/, including fixture test files that the gate never collects.**

`target="$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1)"` picks the first `test_*.py` anywhere under `tests/`. When a fixture project ships its own `tests/fixtures/.../tests/test_*.py` and that path sorts first, the control plants its deliberate type error in a file that the measured typecheck population does not include. `test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red` then stops discriminating.

Why it matters: this instrument exists to prove the typecheck step can go red. A neighbouring fixture can switch it off silently, and the failure looks like an ordinary red on the PR that added the fixture, so it gets "fixed" by renaming the fixture instead of being recognised as an instrument defect.

Found while coordinating #280 (skillc-worker-B). Its fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` triggered the failure in the 18:01 verify run. #280 worked around it by renaming the fixture module to `check_calc.py`; the instrument is unchanged. It does not reproduce on main 358f21b (7/7 pass).

Possible fix: select the target from the same population the typecheck step measures (for example, exclude `tests/fixtures/`), and add a red case: a fixture `test_*.py` that sorts first must not become the target.

Severity: low-medium. It is silent harm to a gate instrument, but needs a specific fixture layout to trigger.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843 (2026-10-07)</summary>

`pyproject.toml`'s `[tool.mypy] files = ["skillc", "tests", "ci"]` does not include `evals/`. The three `_WitnessBackend` test doubles in `evals/level3/{claims-outran-evidence,report-outran-evidence,gate-stops-early}/qualify.py` (hand-duplicated copies of `ExecutionBackend.exec_in_attempt`'s signature) therefore go stale against a real Protocol signature change with zero static-type signal from `make typecheck` - only `tests/test_qualify_scripts_run.py` actually invoking them catches it, and only by running the full suite.

This has now happened twice for the identical reason: #270 (when `cwd`/`env` were added to the Protocol) and again on #338 (when `confine_root` was added) - both times discovered only by a full-suite run going red with `TypeError: _WitnessBackend.exec_in_attempt() got an unexpected keyword argument ...`, never by the lint/typecheck gates that run before it. Worth deciding deliberately whether `evals/` should be in mypy's `files` list, or whether these three doubles should be deduplicated into one shared helper `tests/test_qualify_scripts_run.py` imports, rather than hand-copied a fourth time the next Protocol change.

Found while implementing #338 (the cwd-confinement TOCTOU fix) - not fixed structurally here, only patched at the three call sites to restore the suite to green.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665 (2026-10-17)</summary>

**Severity: low.** Found while orchestrating #419 (reported by session skillc-avail; filed by skillc-400). `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py` each show **14 mypy errors** when checked directly. All are in lines that predate #419; none is in its additions. `evals/` is outside mypy's configured scope (`mypy` covers skillc/ and tests/), so the gate never sees them. **Why it matters:** these scripts decide whether a grader is fit to grade (QUALIFY: ok/fail), so a type error there could hide a control that silently checks the wrong thing. **Options:** fix the 14 per script, or bring `evals/**/qualify.py` into mypy's scope with a baseline.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298 (2026-10-12)</summary>

**Verified supplemental finding from #341 / PR #358 replay review and #356 design: the live uv probe does not enforce its documented exact version.**

`tests/test_trial_image_tools_live.py::test_uv_is_present_at_the_pinned_version` uses `_PINNED_UV_VERSION in uv_version.stdout`. On main `450445d`, the committed pin is `0.9.7`, but the actual function accepts `uv 0.9.70\n` with exit 0. Verified without Docker by loading the actual module with daemon discovery disabled and replacing only `subprocess.run` with that completed observation; the function returned without raising. This establishes the predicate gap, not that such an image was built.

Impact: a neighboring version that contains the pinned string can satisfy the claimed exact-version evidence. Existing generic wrong-version controls (`0.0.0`) do not detect this case.

Suggested follow-up: parse and compare the uv version token exactly, retaining any documented build metadata format, and add controls for both the intended pin and a prefix-sharing wrong version. Keep Docker launch/infrastructure failure discrimination. This is outside #341's exception-isolation edit scope; coordinate with the current #356 owner before changing its acceptance probe. No separate issue created.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195 (2026-10-13)</summary>

**Severity: low.** `tests/test_profile_install_cold_container_live.py:408`: the `coldinstall:cold-cache` break mode's oracle is a raw substring check, `"wasn't found in the cache" in sync.stderr`. uv wraps its diagnostics at a fixed width. On uv 0.9.7's real offline output the break falls before "requested data wasn't found in the cache" (see `tests/fixtures/uv-offline-cache-miss-0.9.7.txt`), so the check passes today. But a longer package name, URL or path can move the wrap point into the phrase. That would make the break mode fail as an ordinary assertion instead of a targeted expected-red, the same failure shape #360 just fixed in the closure-preflight test. Suggested fix: reuse a whitespace-normalised oracle (the `_offline_cache_miss` pattern added for #360) and add a phrase-internal wrap case. Found while fixing #360's live oracle (flow:auto #360). It passes on real Docker today, so this is not a live defect.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296 (2026-10-01)</summary>

\`make verify\`'s \`changelog-check\` target (\`git fetch origin main --quiet; python3 ci/changelog_check.py origin/main\`) diffs \`merge-base(origin/main, HEAD)..HEAD\` - i.e. **committed** history only, via \`git diff --name-only\` and \`git show HEAD:CHANGELOG.md\`. Every other step in \`make verify\` (lint, typecheck, test, leak-check) reads the actual files on disk, so it reflects uncommitted edits. \`changelog-check\` is the one step in the aggregate that does not: it is blind to anything not yet committed.

Reproduced directly: checked out a commit that changes \`skillc/\` with no new \`[Unreleased]\` line, in an isolated worktree, and ran the exact target.
\`\`\`
$ git rev-parse HEAD
<a commit touching skillc/, no changelog entry>
$ make changelog-check
git fetch origin main --quiet
python3 ci/changelog_check.py origin/main
changelog-check: FAIL - skillc/ changed but CHANGELOG.md's [Unreleased] section gained no new line since the merge-base - a deletion or reformat is not an entry
make: *** [Makefile:78: changelog-check] Error 1
\`\`\`
So the check itself is correct and matches CI exactly at a given commit - this is not a tooling bug. The trap is sequencing: running \`make verify\` (or just \`make changelog-check\`) **before committing** pending changes to \`skillc/\` reports \`changelog-check: ok\`, because at that point \`HEAD\` is still the unchanged parent and \`git diff merge-base..HEAD\` is empty - there's nothing yet for the diff to see. The \`ok\` is technically true of HEAD as it stood, but reads as "this change is clean" to whoever ran it, since every sibling step in the same \`make verify\` run DID evaluate the real pending change.

This is exactly the ordering \`/codex:auto\` and \`/flow:auto\` use by design: Step 6 (quality gates) runs before Step 7 (commit/finish). Any run that follows that ordering gets a silently-blind pass on this one step. Found while working #199 (PR #218): local \`make verify\` reported \`changelog-check: ok\` run before the commit existed; CI, against the real committed diff, correctly failed it. Not fixed here - filing per the orchestrator's request rather than widening #218.

Possible angle for whoever picks this up: have the target (or a wrapping \`verify\`) also compare against the dirty worktree, or at minimum print which ref it diffed so an \`ok\` is legible as "committed-state ok" rather than unqualified.

</details>


<!-- end of body -->

<!-- flow-run n=3 id=c6a6873f35334f95af263e66703303ad -->
## Run 3 - issue #542 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #542
- Read at:      2026-10-28T01:52:20Z
- updatedAt:    2026-10-27T11:35:15Z   (context only - moves on comments and labels)
- Body digest:  cadbeb7395da9bfd475323b000635bae94aba59221e3f202a884531f17289a60   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 16332 of 16332 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G1).

## Problem
Several gates and negative controls can report green without checking what they claim. The typecheck control sabotages whichever `test_*.py` sorts first, even a fixture the gate never collects. `mypy` excludes `evals/`, and those files already hold 14 latent errors. The version and cold-cache oracles are substring matches. changelog-check reads only committed history.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [x] **MEDIUM**: ci/typecheck-control.sh's negative-control probe targets whatever test_*.py sorts first under tests/, including fixture test files the typecheck gate never collects, silently disarming the control.
  - Still present: ci/typecheck-control.sh:51 is unchanged: target=$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1). No exclude-fixtures or explicit-target fix landed; no tracking issue found via gh search.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062
- [x] **MEDIUM**: Same defect as 6241922062, with a concrete reproduction: ci/typecheck-control.sh's probe target can be hijacked by an earlier-sorting tests/fixtures/.../test_*.py, so the control's own committed red case stops discriminating.
  - Still present: ci/typecheck-control.sh:51 unchanged; reproduced against #280's fixture tests/fixtures/cicd-local/project/tests/test_calc.py (worked around there by renaming to check_calc.py, instrument itself untouched). No exclude-fixtures fix or new red case has landed.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356
- [ ] **MEDIUM**: pyproject.toml's [tool.mypy] files list still excludes evals/, so hand-duplicated _WitnessBackend Protocol-signature test doubles get zero static-type signal; the count of such doubles has grown from 3 to 6+ since this comment, meaning the recurring-break risk it warned about is larger today, not smaller.
  - Still present: pyproject.toml:46 `files = ["skillc", "tests", "ci"]` unchanged; grep finds _WitnessBackend classes in evals/level3/{flow-auto-step6-gate,claims-outran-evidence,flow-auto-necessity,verify-stops-early,gate-stops-early-auto6}/qualify.py (5-6 copies vs the original 3).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843
- [ ] **LOW**: evals/level3/gate-stops-early/qualify.py and verify-stops-early/qualify.py each have 14 mypy errors (predating #419) that the project gate never sees because mypy's configured scope excludes evals/, even though these scripts decide grader fitness (QUALIFY: ok/fail).
  - Still present: Ran `.venv/bin/mypy evals/level3/gate-stops-early/qualify.py` on main 5ece908: 14 errors, matching the comment's count exactly; pyproject.toml:46 `[tool.mypy] files = ["skillc", "tests", "ci"]` still excludes evals/.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665
- [x] **MEDIUM**: test_uv_is_present_at_the_pinned_version still uses a substring containment check, so a longer neighboring version (e.g. 0.9.70) would satisfy a 0.9.7 pin; an instrument overclaiming exact-version evidence.
  - Still present: tests/test_trial_image_tools_live.py:76,135 unchanged `_PINNED_UV_VERSION in uv_version.stdout`; commit 9bda3c5 (#363) commit message: 'Supplemental finding: exact uv-version substring check can accept a longer neighboring version; recorded separately at ...issuecomment-6126726298.'
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298
- [ ] **LOW**: tests/test_profile_install_cold_container_live.py's coldinstall:cold-cache oracle is a raw substring check (`"wasn't found in the cache" in sync.stderr`) that could land inside uv's line-wrapped diagnostic text for a longer package name/URL, turning the expected-red into an ordinary assertion failure.
  - Still present: tests/test_profile_install_cold_container_live.py:408 (`assert "wasn't found in the cache" in sync.stderr`) unchanged on main 5ece908; no whitespace-normalised oracle (_offline_cache_miss pattern) adopted here. Passes today on real Docker per the comment; not a live defect, just fragile.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195
- [ ] **LOW**: make verify's changelog-check step diffs only committed history (merge-base(origin/main,HEAD)..HEAD via git diff/git show), unlike every other verify step which reads the working tree - so running it before committing (the flow:auto/codex:auto step ordering) reports a stale 'ok'.
  - Still present: ci/changelog_check.py:172-199 main(): _merge_base, git diff --name-only, _show("HEAD", path) - all git-ref based, no git status/working-tree check anywhere in the file. #439 (changelog.d/ fragments) changed the entry format but not this sequencing; the trap is unchanged.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062 (2026-10-17)</summary>

**Severity: medium (a negative control can be silently disarmed).** Found while orchestrating #280 (reported by session skillc-worker-B; filed by skillc-400). `ci/typecheck-control.sh` plants its probe in **the first `tests/**/test_*.py` it finds**. #280's fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` sorted first, so the control probed a FIXTURE, and its committed red case (`tests/test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red`) could no longer go red. The gate caught it this time only because that red-case test exists. Any future fixture or helper named `test_*.py` that sorts earlier could hijack the target the same way. #280 worked around it by renaming its fixture to `check_calc.py`. **Fix options:** target an explicit, declared probe file (or a list) instead of glob order; or exclude `tests/fixtures/**` and assert the chosen target is a real top-level test module; plus a test that a planted early-sorting fixture `test_*.py` doesn't change the target.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356 (2026-10-18)</summary>

**ci/typecheck-control.sh:51: the probe target is whatever test file sorts first under tests/, including fixture test files that the gate never collects.**

`target="$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1)"` picks the first `test_*.py` anywhere under `tests/`. When a fixture project ships its own `tests/fixtures/.../tests/test_*.py` and that path sorts first, the control plants its deliberate type error in a file that the measured typecheck population does not include. `test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red` then stops discriminating.

Why it matters: this instrument exists to prove the typecheck step can go red. A neighbouring fixture can switch it off silently, and the failure looks like an ordinary red on the PR that added the fixture, so it gets "fixed" by renaming the fixture instead of being recognised as an instrument defect.

Found while coordinating #280 (skillc-worker-B). Its fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` triggered the failure in the 18:01 verify run. #280 worked around it by renaming the fixture module to `check_calc.py`; the instrument is unchanged. It does not reproduce on main 358f21b (7/7 pass).

Possible fix: select the target from the same population the typecheck step measures (for example, exclude `tests/fixtures/`), and add a red case: a fixture `test_*.py` that sorts first must not become the target.

Severity: low-medium. It is silent harm to a gate instrument, but needs a specific fixture layout to trigger.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843 (2026-10-07)</summary>

`pyproject.toml`'s `[tool.mypy] files = ["skillc", "tests", "ci"]` does not include `evals/`. The three `_WitnessBackend` test doubles in `evals/level3/{claims-outran-evidence,report-outran-evidence,gate-stops-early}/qualify.py` (hand-duplicated copies of `ExecutionBackend.exec_in_attempt`'s signature) therefore go stale against a real Protocol signature change with zero static-type signal from `make typecheck` - only `tests/test_qualify_scripts_run.py` actually invoking them catches it, and only by running the full suite.

This has now happened twice for the identical reason: #270 (when `cwd`/`env` were added to the Protocol) and again on #338 (when `confine_root` was added) - both times discovered only by a full-suite run going red with `TypeError: _WitnessBackend.exec_in_attempt() got an unexpected keyword argument ...`, never by the lint/typecheck gates that run before it. Worth deciding deliberately whether `evals/` should be in mypy's `files` list, or whether these three doubles should be deduplicated into one shared helper `tests/test_qualify_scripts_run.py` imports, rather than hand-copied a fourth time the next Protocol change.

Found while implementing #338 (the cwd-confinement TOCTOU fix) - not fixed structurally here, only patched at the three call sites to restore the suite to green.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665 (2026-10-17)</summary>

**Severity: low.** Found while orchestrating #419 (reported by session skillc-avail; filed by skillc-400). `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py` each show **14 mypy errors** when checked directly. All are in lines that predate #419; none is in its additions. `evals/` is outside mypy's configured scope (`mypy` covers skillc/ and tests/), so the gate never sees them. **Why it matters:** these scripts decide whether a grader is fit to grade (QUALIFY: ok/fail), so a type error there could hide a control that silently checks the wrong thing. **Options:** fix the 14 per script, or bring `evals/**/qualify.py` into mypy's scope with a baseline.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298 (2026-10-12)</summary>

**Verified supplemental finding from #341 / PR #358 replay review and #356 design: the live uv probe does not enforce its documented exact version.**

`tests/test_trial_image_tools_live.py::test_uv_is_present_at_the_pinned_version` uses `_PINNED_UV_VERSION in uv_version.stdout`. On main `450445d`, the committed pin is `0.9.7`, but the actual function accepts `uv 0.9.70\n` with exit 0. Verified without Docker by loading the actual module with daemon discovery disabled and replacing only `subprocess.run` with that completed observation; the function returned without raising. This establishes the predicate gap, not that such an image was built.

Impact: a neighboring version that contains the pinned string can satisfy the claimed exact-version evidence. Existing generic wrong-version controls (`0.0.0`) do not detect this case.

Suggested follow-up: parse and compare the uv version token exactly, retaining any documented build metadata format, and add controls for both the intended pin and a prefix-sharing wrong version. Keep Docker launch/infrastructure failure discrimination. This is outside #341's exception-isolation edit scope; coordinate with the current #356 owner before changing its acceptance probe. No separate issue created.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195 (2026-10-13)</summary>

**Severity: low.** `tests/test_profile_install_cold_container_live.py:408`: the `coldinstall:cold-cache` break mode's oracle is a raw substring check, `"wasn't found in the cache" in sync.stderr`. uv wraps its diagnostics at a fixed width. On uv 0.9.7's real offline output the break falls before "requested data wasn't found in the cache" (see `tests/fixtures/uv-offline-cache-miss-0.9.7.txt`), so the check passes today. But a longer package name, URL or path can move the wrap point into the phrase. That would make the break mode fail as an ordinary assertion instead of a targeted expected-red, the same failure shape #360 just fixed in the closure-preflight test. Suggested fix: reuse a whitespace-normalised oracle (the `_offline_cache_miss` pattern added for #360) and add a phrase-internal wrap case. Found while fixing #360's live oracle (flow:auto #360). It passes on real Docker today, so this is not a live defect.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296 (2026-10-01)</summary>

\`make verify\`'s \`changelog-check\` target (\`git fetch origin main --quiet; python3 ci/changelog_check.py origin/main\`) diffs \`merge-base(origin/main, HEAD)..HEAD\` - i.e. **committed** history only, via \`git diff --name-only\` and \`git show HEAD:CHANGELOG.md\`. Every other step in \`make verify\` (lint, typecheck, test, leak-check) reads the actual files on disk, so it reflects uncommitted edits. \`changelog-check\` is the one step in the aggregate that does not: it is blind to anything not yet committed.

Reproduced directly: checked out a commit that changes \`skillc/\` with no new \`[Unreleased]\` line, in an isolated worktree, and ran the exact target.
\`\`\`
$ git rev-parse HEAD
<a commit touching skillc/, no changelog entry>
$ make changelog-check
git fetch origin main --quiet
python3 ci/changelog_check.py origin/main
changelog-check: FAIL - skillc/ changed but CHANGELOG.md's [Unreleased] section gained no new line since the merge-base - a deletion or reformat is not an entry
make: *** [Makefile:78: changelog-check] Error 1
\`\`\`
So the check itself is correct and matches CI exactly at a given commit - this is not a tooling bug. The trap is sequencing: running \`make verify\` (or just \`make changelog-check\`) **before committing** pending changes to \`skillc/\` reports \`changelog-check: ok\`, because at that point \`HEAD\` is still the unchanged parent and \`git diff merge-base..HEAD\` is empty - there's nothing yet for the diff to see. The \`ok\` is technically true of HEAD as it stood, but reads as "this change is clean" to whoever ran it, since every sibling step in the same \`make verify\` run DID evaluate the real pending change.

This is exactly the ordering \`/codex:auto\` and \`/flow:auto\` use by design: Step 6 (quality gates) runs before Step 7 (commit/finish). Any run that follows that ordering gets a silently-blind pass on this one step. Found while working #199 (PR #218): local \`make verify\` reported \`changelog-check: ok\` run before the commit existed; CI, against the real committed diff, correctly failed it. Not fixed here - filing per the orchestrator's request rather than widening #218.

Possible angle for whoever picks this up: have the target (or a wrapping \`verify\`) also compare against the dirty worktree, or at minimum print which ref it diffed so an \`ok\` is legible as "committed-state ok" rather than unqualified.

</details>

## Delivered selected slice, 2026-10-27

PR #579 shipped the generic authored-test probe repair (both duplicate bullets above) and exact uv-version matching, merged as `028dde512f2f43f1c47cb77abff6740b4cf86ca6`. Required PR pipeline 1118 and actual main push pipeline 1120 both passed; tested and merged trees match. New controls produced 11 failures on unchanged predicates, then 116 focused passes. Full local finish passed 7,395 tests with five explicit skips and all 7,400 collected/executed identities matching; actual Docker tool-version probes ran.

This issue remains open for evals typing coverage/latent errors, cold-cache diagnostic fragility, and committed-history changelog sequencing. The selected repair did not change #568 snapshot-specific exclusions.


<!-- end of body -->

<!-- flow-run n=4 id=a7a19d2097f1484cb522cf39a213bb3a -->
## Run 4 - issue #542 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #542
- Read at:      2026-10-28T04:22:19Z
- updatedAt:    2026-10-28T04:21:08Z   (context only - moves on comments and labels)
- Body digest:  d4cf3a1acf9566fde914c10a5d405ebd13ecfa00e8b97d6e06f831caac5e0b69   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 16332 of 16332 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G1).

## Problem
Several gates and negative controls can report green without checking what they claim. The typecheck control sabotages whichever `test_*.py` sorts first, even a fixture the gate never collects. `mypy` excludes `evals/`, and those files already hold 14 latent errors. The version and cold-cache oracles are substring matches. changelog-check reads only committed history.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [x] **MEDIUM**: ci/typecheck-control.sh's negative-control probe targets whatever test_*.py sorts first under tests/, including fixture test files the typecheck gate never collects, silently disarming the control.
  - Still present: ci/typecheck-control.sh:51 is unchanged: target=$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1). No exclude-fixtures or explicit-target fix landed; no tracking issue found via gh search.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062
- [x] **MEDIUM**: Same defect as 6241922062, with a concrete reproduction: ci/typecheck-control.sh's probe target can be hijacked by an earlier-sorting tests/fixtures/.../test_*.py, so the control's own committed red case stops discriminating.
  - Still present: ci/typecheck-control.sh:51 unchanged; reproduced against #280's fixture tests/fixtures/cicd-local/project/tests/test_calc.py (worked around there by renaming to check_calc.py, instrument itself untouched). No exclude-fixtures fix or new red case has landed.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356
- [ ] **MEDIUM**: pyproject.toml's [tool.mypy] files list still excludes evals/, so hand-duplicated _WitnessBackend Protocol-signature test doubles get zero static-type signal; the count of such doubles has grown from 3 to 6+ since this comment, meaning the recurring-break risk it warned about is larger today, not smaller.
  - Still present: pyproject.toml:46 `files = ["skillc", "tests", "ci"]` unchanged; grep finds _WitnessBackend classes in evals/level3/{flow-auto-step6-gate,claims-outran-evidence,flow-auto-necessity,verify-stops-early,gate-stops-early-auto6}/qualify.py (5-6 copies vs the original 3).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843
- [ ] **LOW**: evals/level3/gate-stops-early/qualify.py and verify-stops-early/qualify.py each have 14 mypy errors (predating #419) that the project gate never sees because mypy's configured scope excludes evals/, even though these scripts decide grader fitness (QUALIFY: ok/fail).
  - Still present: Ran `.venv/bin/mypy evals/level3/gate-stops-early/qualify.py` on main 5ece908: 14 errors, matching the comment's count exactly; pyproject.toml:46 `[tool.mypy] files = ["skillc", "tests", "ci"]` still excludes evals/.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665
- [x] **MEDIUM**: test_uv_is_present_at_the_pinned_version still uses a substring containment check, so a longer neighboring version (e.g. 0.9.70) would satisfy a 0.9.7 pin; an instrument overclaiming exact-version evidence.
  - Still present: tests/test_trial_image_tools_live.py:76,135 unchanged `_PINNED_UV_VERSION in uv_version.stdout`; commit 9bda3c5 (#363) commit message: 'Supplemental finding: exact uv-version substring check can accept a longer neighboring version; recorded separately at ...issuecomment-6126726298.'
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298
- [ ] **LOW**: tests/test_profile_install_cold_container_live.py's coldinstall:cold-cache oracle is a raw substring check (`"wasn't found in the cache" in sync.stderr`) that could land inside uv's line-wrapped diagnostic text for a longer package name/URL, turning the expected-red into an ordinary assertion failure.
  - Still present: tests/test_profile_install_cold_container_live.py:408 (`assert "wasn't found in the cache" in sync.stderr`) unchanged on main 5ece908; no whitespace-normalised oracle (_offline_cache_miss pattern) adopted here. Passes today on real Docker per the comment; not a live defect, just fragile.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195
- [x] **LOW**: make verify's changelog-check step diffs only committed history (merge-base(origin/main,HEAD)..HEAD via git diff/git show), unlike every other verify step which reads the working tree - so running it before committing (the flow:auto/codex:auto step ordering) reports a stale 'ok'.
  - Still present: ci/changelog_check.py:172-199 main(): _merge_base, git diff --name-only, _show("HEAD", path) - all git-ref based, no git status/working-tree check anywhere in the file. #439 (changelog.d/ fragments) changed the entry format but not this sequencing; the trap is unchanged.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241922062 (2026-10-17)</summary>

**Severity: medium (a negative control can be silently disarmed).** Found while orchestrating #280 (reported by session skillc-worker-B; filed by skillc-400). `ci/typecheck-control.sh` plants its probe in **the first `tests/**/test_*.py` it finds**. #280's fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` sorted first, so the control probed a FIXTURE, and its committed red case (`tests/test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red`) could no longer go red. The gate caught it this time only because that red-case test exists. Any future fixture or helper named `test_*.py` that sorts earlier could hijack the target the same way. #280 worked around it by renaming its fixture to `check_calc.py`. **Fix options:** target an explicit, declared probe file (or a list) instead of glob order; or exclude `tests/fixtures/**` and assert the chosen target is a real top-level test module; plus a test that a planted early-sorting fixture `test_*.py` doesn't change the target.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6243564356 (2026-10-18)</summary>

**ci/typecheck-control.sh:51: the probe target is whatever test file sorts first under tests/, including fixture test files that the gate never collects.**

`target="$(cd "$scratch/tree" && find tests -name 'test_*.py' | sort | head -n 1)"` picks the first `test_*.py` anywhere under `tests/`. When a fixture project ships its own `tests/fixtures/.../tests/test_*.py` and that path sorts first, the control plants its deliberate type error in a file that the measured typecheck population does not include. `test_typecheck_control.py::test_an_empty_test_population_turns_the_step_red` then stops discriminating.

Why it matters: this instrument exists to prove the typecheck step can go red. A neighbouring fixture can switch it off silently, and the failure looks like an ordinary red on the PR that added the fixture, so it gets "fixed" by renaming the fixture instead of being recognised as an instrument defect.

Found while coordinating #280 (skillc-worker-B). Its fixture `tests/fixtures/cicd-local/project/tests/test_calc.py` triggered the failure in the 18:01 verify run. #280 worked around it by renaming the fixture module to `check_calc.py`; the instrument is unchanged. It does not reproduce on main 358f21b (7/7 pass).

Possible fix: select the target from the same population the typecheck step measures (for example, exclude `tests/fixtures/`), and add a red case: a fixture `test_*.py` that sorts first must not become the target.

Severity: low-medium. It is silent harm to a gate instrument, but needs a specific fixture layout to trigger.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6034604843 (2026-10-07)</summary>

`pyproject.toml`'s `[tool.mypy] files = ["skillc", "tests", "ci"]` does not include `evals/`. The three `_WitnessBackend` test doubles in `evals/level3/{claims-outran-evidence,report-outran-evidence,gate-stops-early}/qualify.py` (hand-duplicated copies of `ExecutionBackend.exec_in_attempt`'s signature) therefore go stale against a real Protocol signature change with zero static-type signal from `make typecheck` - only `tests/test_qualify_scripts_run.py` actually invoking them catches it, and only by running the full suite.

This has now happened twice for the identical reason: #270 (when `cwd`/`env` were added to the Protocol) and again on #338 (when `confine_root` was added) - both times discovered only by a full-suite run going red with `TypeError: _WitnessBackend.exec_in_attempt() got an unexpected keyword argument ...`, never by the lint/typecheck gates that run before it. Worth deciding deliberately whether `evals/` should be in mypy's `files` list, or whether these three doubles should be deduplicated into one shared helper `tests/test_qualify_scripts_run.py` imports, rather than hand-copied a fourth time the next Protocol change.

Found while implementing #338 (the cwd-confinement TOCTOU fix) - not fixed structurally here, only patched at the three call sites to restore the suite to green.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237333665 (2026-10-17)</summary>

**Severity: low.** Found while orchestrating #419 (reported by session skillc-avail; filed by skillc-400). `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py` each show **14 mypy errors** when checked directly. All are in lines that predate #419; none is in its additions. `evals/` is outside mypy's configured scope (`mypy` covers skillc/ and tests/), so the gate never sees them. **Why it matters:** these scripts decide whether a grader is fit to grade (QUALIFY: ok/fail), so a type error there could hide a control that silently checks the wrong thing. **Options:** fix the 14 per script, or bring `evals/**/qualify.py` into mypy's scope with a baseline.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6126726298 (2026-10-12)</summary>

**Verified supplemental finding from #341 / PR #358 replay review and #356 design: the live uv probe does not enforce its documented exact version.**

`tests/test_trial_image_tools_live.py::test_uv_is_present_at_the_pinned_version` uses `_PINNED_UV_VERSION in uv_version.stdout`. On main `450445d`, the committed pin is `0.9.7`, but the actual function accepts `uv 0.9.70\n` with exit 0. Verified without Docker by loading the actual module with daemon discovery disabled and replacing only `subprocess.run` with that completed observation; the function returned without raising. This establishes the predicate gap, not that such an image was built.

Impact: a neighboring version that contains the pinned string can satisfy the claimed exact-version evidence. Existing generic wrong-version controls (`0.0.0`) do not detect this case.

Suggested follow-up: parse and compare the uv version token exactly, retaining any documented build metadata format, and add controls for both the intended pin and a prefix-sharing wrong version. Keep Docker launch/infrastructure failure discrimination. This is outside #341's exception-isolation edit scope; coordinate with the current #356 owner before changing its acceptance probe. No separate issue created.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6154670195 (2026-10-13)</summary>

**Severity: low.** `tests/test_profile_install_cold_container_live.py:408`: the `coldinstall:cold-cache` break mode's oracle is a raw substring check, `"wasn't found in the cache" in sync.stderr`. uv wraps its diagnostics at a fixed width. On uv 0.9.7's real offline output the break falls before "requested data wasn't found in the cache" (see `tests/fixtures/uv-offline-cache-miss-0.9.7.txt`), so the check passes today. But a longer package name, URL or path can move the wrap point into the phrase. That would make the break mode fail as an ordinary assertion instead of a targeted expected-red, the same failure shape #360 just fixed in the closure-preflight test. Suggested fix: reuse a whitespace-normalised oracle (the `_offline_cache_miss` pattern added for #360) and add a phrase-internal wrap case. Found while fixing #360's live oracle (flow:auto #360). It passes on real Docker today, so this is not a live defect.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5930833296 (2026-10-01)</summary>

\`make verify\`'s \`changelog-check\` target (\`git fetch origin main --quiet; python3 ci/changelog_check.py origin/main\`) diffs \`merge-base(origin/main, HEAD)..HEAD\` - i.e. **committed** history only, via \`git diff --name-only\` and \`git show HEAD:CHANGELOG.md\`. Every other step in \`make verify\` (lint, typecheck, test, leak-check) reads the actual files on disk, so it reflects uncommitted edits. \`changelog-check\` is the one step in the aggregate that does not: it is blind to anything not yet committed.

Reproduced directly: checked out a commit that changes \`skillc/\` with no new \`[Unreleased]\` line, in an isolated worktree, and ran the exact target.
\`\`\`
$ git rev-parse HEAD
<a commit touching skillc/, no changelog entry>
$ make changelog-check
git fetch origin main --quiet
python3 ci/changelog_check.py origin/main
changelog-check: FAIL - skillc/ changed but CHANGELOG.md's [Unreleased] section gained no new line since the merge-base - a deletion or reformat is not an entry
make: *** [Makefile:78: changelog-check] Error 1
\`\`\`
So the check itself is correct and matches CI exactly at a given commit - this is not a tooling bug. The trap is sequencing: running \`make verify\` (or just \`make changelog-check\`) **before committing** pending changes to \`skillc/\` reports \`changelog-check: ok\`, because at that point \`HEAD\` is still the unchanged parent and \`git diff merge-base..HEAD\` is empty - there's nothing yet for the diff to see. The \`ok\` is technically true of HEAD as it stood, but reads as "this change is clean" to whoever ran it, since every sibling step in the same \`make verify\` run DID evaluate the real pending change.

This is exactly the ordering \`/codex:auto\` and \`/flow:auto\` use by design: Step 6 (quality gates) runs before Step 7 (commit/finish). Any run that follows that ordering gets a silently-blind pass on this one step. Found while working #199 (PR #218): local \`make verify\` reported \`changelog-check: ok\` run before the commit existed; CI, against the real committed diff, correctly failed it. Not fixed here - filing per the orchestrator's request rather than widening #218.

Possible angle for whoever picks this up: have the target (or a wrapping \`verify\`) also compare against the dirty worktree, or at minimum print which ref it diffed so an \`ok\` is legible as "committed-state ok" rather than unqualified.

</details>

## Delivered selected slice, 2026-10-27

PR #579 shipped the generic authored-test probe repair (both duplicate bullets above) and exact uv-version matching, merged as `028dde512f2f43f1c47cb77abff6740b4cf86ca6`. Required PR pipeline 1118 and actual main push pipeline 1120 both passed; tested and merged trees match. New controls produced 11 failures on unchanged predicates, then 116 focused passes. Full local finish passed 7,395 tests with five explicit skips and all 7,400 collected/executed identities matching; actual Docker tool-version probes ran.

This issue remains open for evals typing coverage/latent errors, cold-cache diagnostic fragility, and committed-history changelog sequencing. The selected repair did not change #568 snapshot-specific exclusions.


<!-- end of body -->
