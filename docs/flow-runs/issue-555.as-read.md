<!-- flow-run n=1 id=69e4fce986894ebb9e8c79d605242211 -->
## Run 1 - issue #555 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #555
- Read at:      2026-11-19T03:08:15Z
- updatedAt:    2026-10-24T11:56:31Z   (context only - moves on comments and labels)
- Body digest:  b4f6aa6fb4ab6e9a739412c6940d49a354ac5a1599e194fb6c46812939085a9b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 16384 of 17441 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G15).

## Problem
CLI and small-path defects. PasteBackRefused prints the withheld finding VALUES to stderr at most call sites. degrade-subject accepts removing a checksum-listed file and writes the receipt before persisting. git_fixture crashes on an all-empty stash. uptake uses the deprecated `_fixture_surface`. The default claude argv has no server-side-channel-off flags. Two bool/int sites remain unchecked. test_private_citations doesn't scan issue or PR bodies. agent_trial needs a concrete DockerBackend, which blocks #64.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **LOW**: PasteBackRefused's leak-check finding values (not just categories) are still printed raw to stderr at most CLI call sites, so a withheld value still reaches the terminal/log.
  - Still present: skillc/cli.py:992 (cmd_collection_run, the site named in the comment), and :1479, :1895, :2381 still do `print(f"skillc: {exc}", file=sys.stderr)`; only cmd_demo (:809) and one cmd_calibration_run site (:1196) were fixed to strip values - the proliferation the comment warned about ("worth a shared helper") happened instead.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5858174851
- [ ] **LOW**: degrade-subject still accepts a --remove-file of a file listed in the skill's checksum_manifest (exit 0, receipt written), only refusing the resulting tree later at collection-run --degraded preparation (materialize._verify_checksums) - the same late-refusal shape #198 fixed for overrides, not for deletions.
  - Still present: skillc/degrade.py docstring (~line 180) still states verbatim: "Deletions are not re-pinned; a deleted listed file is still refused at preparation."; _apply_mutation (~220-266) unlinks a removed file with no manifest check, then _rewrite_manifests only re-pins edits with content is not None (skips deletions). No change since #198/PR #200.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5911765894
- [ ] **LOW**: cmd_degrade_subject writes out/receipt.json BEFORE calling degrade.persist_skills(degraded, out); if persist_skills raises partway, out/ is left with a receipt.json describing a tree that was never actually persisted, and nothing rolls it back.
  - Still present: skillc/cli.py:2562-2567: `(out / "receipt.json").write_text(...)` precedes `skills_dir = degrade.persist_skills(degraded, out)`; only a `finally: shutil.rmtree(degraded.staging, ...)` guards staging cleanup, not out/receipt.json.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5930470564
- [ ] **LOW**: git_fixture.py build() still crashes with a raw subprocess.CalledProcessError on an all-empty-stash declaration instead of a clean Refused; no committed declaration exercises this, so it has never fired.
  - Still present: skillc/git_fixture.py:143 unconditionally runs `git rev-parse refs/stash` after build(); no 'empty-stash' entry exists among the Refused() reasons in the file.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6012275869
- [ ] **LOW**: uptake_study.run_study still calls the deprecated collection_conformance._fixture_surface instead of the unified surface_mapping(task_surface(...)) path #267 introduced elsewhere; safe to migrate whenever, not yet done.
  - Still present: skillc/uptake_study.py:468 `cc._fixture_surface(task_root / "fixture")`; collection_conformance.py:107-108,606-616 still marks _fixture_surface/_FIXTURE_SRC_DIRNAME DEPRECATED.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6007378828
- [ ] **LOW**: DEFAULT_CLIENT_ARGVS['claude'] carries no server-side-channel-off flags (unlike codex's --strict-config etc.), so a future live Claude Code study would have an unmeasured server-side route around container egress.
  - Still present: skillc/collection_conformance.py:149-153: DEFAULT_CLIENT_ARGVS['claude'] is still exactly ('claude','-p','--dangerously-skip-permissions'), no equivalent of eg.CODEX_SERVER_SIDE_OFF. No live Claude Code calibration study has run (#288, codex-only, is CLOSED); severity stays LOW per the comment's own conditional rating since the triggering study still hasn't happened.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241342573
- [ ] **LOW**: Repo-wide bool/int-conflation grep: 2 of 4 sites were fixed in #183 (grade_recovery.py, skillc-disrupt-tool.py); the 2 flagged-but-unchecked sites (calibration_run.py, uptake_study.py) are unchanged and still unverified as to whether their input population is externally forgeable.
  - Still present: docker/trial/skillc-disrupt-tool.py:94 and evals/level5/recovery-partial-processing/grade_recovery.py:166 now exclude bool; skillc/calibration_run.py:1628 and skillc/uptake_study.py:644 still use `in (True, False)`.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6021300640
- [ ] **LOW**: tests/test_private_citations.py still scans only tracked repository files, never GitHub issue/PR bodies via the API, so a private-instance-name leak into a public issue body (as #334's own body had) still has no automated catch.
  - Still present: tests/test_private_citations.py:40 comment: '...not...on PR bodies or commit messages - issue #100's own correction comment found...'.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6027991339
- [ ] **MEDIUM**: skillc/agent_trial.py's real-model attempt path needs deliver_home_file/read_home_file/read_home_tree, which are concrete DockerBackend methods, not part of the ExecutionBackend Protocol, and the managed-backend protocol doc has no home-file/home-tree operations -- so #64's real-container conformance could pass while still being unable to run the credential-copy-in/transcript-discovery path a managed backend (needed for kyle#1397 / ADR 0007's amendment) would require.
  - Still present: skillc/agent_trial.py:68-71 docstring still states it is "the first to require a concrete DockerBackend rather than the Protocol alone"; docs/specs/evaluation-facility/managed-backend-protocol.md:3 is still "Status: Proposed - no platform implements this yet" with no home-file/tree ops, on main 5ece908. No tracking issue found (confirmed via gh issue search).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6238464467

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5858174851 (2026-09-27)</summary>

**Severity: low.** In `skillc/cli.py`, `cmd_collection_run` (the `except demo.PasteBackRefused as exc:` at about line 906) and one other command (about line 1135) print the refusal with `print(f"skillc: {exc}", file=sys.stderr)`.

`demo.print_paste_back`'s refusal message lists each leak finding as `<line>: <category>: <value>`. So when a paste-back block is refused for carrying a private IP, a home-directory identity or a denylisted hostname, the value is written to stderr instead of stdout. The block itself is withheld, but the value still reaches the operator's terminal and any captured log.

Found by cross-model re-review while working #26 (PR for `skillc selection-probe`). That command prints finding categories only; the fix is the same three lines at each site. Worth a shared helper in `demo.py` so the next command cannot repeat it.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5911765894 (2026-09-30)</summary>

**Severity: low.** `skillc/degrade.py` `_rewrite_manifests` / `_apply_mutation`: a `--remove-file SKILL:PATH` (`FileEdit(content=None)`) of a file that the skill's declared `checksum_manifest` lists is accepted by `degrade-subject` (exit 0, receipt written). The tree is then refused only later, at `collection-run --degraded` preparation (`materialize._verify_checksums`: "checksum lists a missing file"). #198 (PR #200) deliberately re-pins only overrides, not deletions. Why it matters: the failure surfaces after the operator has built and receipted a tree that can never run, which is the same late-refusal shape #198 fixed for overrides. Options: refuse the deletion at degrade time with a message naming the manifest, or drop the manifest line and record it in `manifest_rewrites`. Found while working #198 (PR #200); Codex's second review pass named the same case as a red case.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5930470564 (2026-10-01)</summary>

\`skillc/cli.py\`'s \`cmd_degrade_subject\` (around the \`degrade-subject\` command) writes \`out/receipt.json\` *before* calling \`degrade.persist_skills(degraded, out)\`. If \`persist_skills\` raises partway (disk full, permission error, etc.), \`out\` is left holding a \`receipt.json\` with no \`skills/\` tree - a receipt describing a tree that was never actually persisted. Not silently dangerous: the function's own pre-check (\`if out.exists() and any(out.iterdir()): refuse\`) means a later retry against the same \`--out\` gets a clean exit 2 rather than building on the partial state. But the receipt itself is momentarily a false statement about what \`out/\` contains, and nothing cleans up the partial write on that path.

Found while working #199 (the degrade-subject staging-collision fix), which touches this same sequence (receipt write -> persist_skills) to add staging cleanup around it. Not fixed there - out of scope for that change. A possible fix: write \`receipt.json\` after \`persist_skills\` succeeds, or stage both into a temp dir and rename atomically into \`out\`, mirroring the pattern \`_publish_collection_evidence\`/\`_export_pilot_evidence\` already use elsewhere in this file.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6012275869 (2026-10-06)</summary>

skillc/git_fixture.py build(): a declaration whose stash.staged and stash.unstaged are both empty crashes with a raw subprocess.CalledProcessError (exit 128 on `git rev-parse refs/stash`) instead of a clean Refused. `git stash push` with nothing to stash is a no-op (prints "No local changes to save", exits 0) and creates no refs/stash, but build() unconditionally reads it afterward to populate `expected["refs"]["refs/stash"]`. Every committed test's declaration() always has non-empty stash content, so this never fires today, and nothing in #275's acceptance requires supporting an empty-stash declaration. Low severity, but worth a clean `Refused('empty-stash')` guard (or making stash optional and skipping the refs/stash lookup when empty) if this module's declaration schema is ever relaxed. Found while reviewing #275 (PR for skillc issue 275).

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6007378828 (2026-10-06)</summary>

skillc/uptake_study.py:378 (Shape A of #267). While the #237 uptake study runs, uptake_study.run_study keeps calling the deprecated skillc/collection_conformance._fixture_surface(task_root / "fixture") instead of the unified surface_mapping(task_surface(...)) #267 introduced everywhere else, because touching the live study's runner is the owner's call, not a worker's. Migrate it once #237 is done, then delete _fixture_surface and _FIXTURE_SRC_DIRNAME from collection_conformance.py (both are marked DEPRECATED / "do not add a new caller" in their docstrings).

Confirmed byte-identical for the study's own fixture (evals/level1/slug-small-fix) before any migration, so the swap is safe whenever it happens: both old and new paths deliver exactly {"src/slugify.py": sha256 1a703199a138cb0cd68336f395df38547ce73e9869fd2ec3504995df8a9e1457}, executable metadata empty either way (slugify.py is not executable). Found and recorded while working #267.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241342573 (2026-10-17)</summary>

**Severity: LOW (now) / HIGH before any Claude Code live study** - found while building #442.

#442 closes codex's server-side channels in its argv (`--strict-config -c web_search="disabled" --disable apps --disable plugins --disable remote_plugin`), and `agent_trial.run_one_attempt` refuses a live codex attempt missing them. Nothing equivalent exists for the **claude** client: `DEFAULT_CLIENT_ARGVS["claude"]` is `claude -p --dangerously-skip-permissions`, and Claude Code's server-side web search runs at the provider, out of reach of container egress. The post-run census (`server_side_tool_uses`) would still catch a `web_search`-typed item if Claude Code's transcript uses that shape, but that hasn't been measured.

Why it matters: #288 runs codex only, so nothing is exposed today. But the first live Claude Code study would silently have a server-side route to the public repository's graders. Before one runs: measure Claude Code's server-side tools (its tool list and transcript shapes for WebSearch and WebFetch), pin them off in its argv or settings, extend the preflight, and add census controls for its transcript format.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6021300640 (2026-10-06)</summary>

Repo-wide grep for the bool/int conflation class (Python's \`1 == True\`/\`0 == False\`, so \`x in (True, False)\` or \`x == True\` accepts an integer standing in for a bool - found twice this session, see below). \`grep -rn 'in (True, False)\|== True\b\|!= True\b\|== False\b' skillc/*.py evals/**/*.py docker/trial/*.py\` (excluding tests) finds 4 sites total:

Fixed this session (skillc #183 PR B1/B2), both on JSON-decoded, externally-sourced data where the conflation is a real security/correctness risk (a forged or malformed trusted-observation/reply could pass validation it should fail):
- \`evals/level5/recovery-partial-processing/grade_recovery.py\` _trusted_log()'s seq validation (fixed to \`isinstance(seq, int) and not isinstance(seq, bool)\`-style exclusion)
- \`docker/trial/skillc-disrupt-tool.py\`'s reply validation (fixed to \`type(result.get("allow")) is not bool\`)

NOT yet checked, found by the same grep, NOT fixed here (out of scope for #183):
- \`skillc/calibration_run.py:446\`: \`if entry.get("skill_opened") in (True, False):\`
- \`skillc/uptake_study.py:627\`: \`if entry["target_selected"] in (True, False) and entry["model_eligible"] is True:\`

Both operate on dict entries that look like decoded study/calibration data (not yet confirmed whether either is externally-forgeable the way a trusted-observation channel is, or purely internal/trusted-pipeline data where the distinction is harmless) - worth a closer look at whether either's input population can actually contain an integer standing in for a bool, and if so whether that's a real gap or genuinely inert. Found while building #183 PR B2.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6027991339 (2026-10-07)</summary>

Finding while filing #338 (TOCTOU in gate-witness cwd confinement, found during #332's pre-PR review): issue #334's own body contains a literal worker instance name ("a worker session") in its Finding section ("a worker session found no captured attempt record to cross-check against"). Issue bodies aren't covered by tests/test_private_citations.py (that guard only scans tracked repo files), so this kind of leak into a public GitHub issue has no automated catch today. Not fixing #334's body myself since it's someone else's filed issue; noting it here as a disposition, not a fix. Worth considering whether the private-citations guard (or an equivalent) should also scan newly-created issue/PR bodies via the GitHub API, not only tracked files.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6238464467 (2026-10-17)</summary>

**`skillc/agent_trial.py:66-7
[TRUNCATED at 16384 bytes of 17441. This extract is INCOMPLETE CONTEXT
 TO RESOLVE by reading the issue - it is not an absence of further constraints.
 The digest above covers the FULL body, so drift beyond this point is still
 DETECTED; it just cannot be LOCALISED from this copy.]

<!-- end of body -->
