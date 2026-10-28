# #546 uptake report accounting - TESTED UNCOMMITTED

Actual run `7bdf309f5ea846c69b5e445e70109edf`, branch `issue-546-uptake-report-accounting`, worktree `[local-artifact-path]`, unchanged HEAD `16c6b4b65b5e0d35d72ae811163625d7cd8347a7`. Implemented only the exact approved three product and two canonical workflow paths. No commit/checkpoint/review/receipt/full/push/PR/issue edit/claim release/worktree cleanup. No Docker/client/model or qualification run. Owner03's PR598 monitor was untouched.

## Behavior and scope

`skillc/uptake_study.py` retains additive version1 and the raw `decided` boolean. `decision_applicable` is true for captured/inconclusive, false for not-run/unavailable, null for unknown/missing/malformed raw dispositions, including unhashable lists/dicts. Undecided counts applicable false-classifier rows only. Both tested and screen reports include separate not_run/unavailable/unknown_disposition totals. All raw rows/values remain. Applicability is not launch/contact/spend proof; unknown observation remains unknown.

`_decided` and `_scores` functions are byte-for-byte unchanged. The patch does not change target/any selection, model/confirmation eligibility, cell denominators or Fisher calculations. The public text consumer displays a complete valid new counter set; legacy JSON with all counters absent retains its old text. Partial/malformed new counters raise StudyRefused, including bool/negative/noninteger/unhashable values, instead of displaying clean zeros. Non-probe output has no cutoff claim.

New direct-bullet `changelog.d/546-uptake-not-run-accounting.md`; shipped546 fragment untouched. Workflow Run3 was appended canonically; full current131-line body snapshot stored without truncation. Previous Run1/Run2 prefixes remain exact bytes.

Exact A+D:

| Path | A+D |
|---|---:|
| skillc/uptake_study.py | 23 |
| tests/test_uptake_study.py | 121 |
| changelog.d/546-uptake-not-run-accounting.md | 1 |
| docs/flow-runs/issue-546.md | 28 |
| docs/flow-runs/issue-546.as-read.md | 148 |

Product145; reserved future receipt60 yields205 <=300. Workflow176 <=250. No receipt leaf allocated/enrolled/written. Changelog is intent-to-add, not a commit; all work remains uncommitted.

## Executed evidence

- **Genuine old public-API VALUE red before production edit:** `test_not_run_is_excluded_from_public_probe_undecided` failed exactly `assert 2 == 1`. It drives existing build_report then paste_back with captured zero-call, captured selected, and not-run/no-observation. Production bytes matched the original snapshot. The same-API all-captured healthy twin passed. Preserved old source/test bytes, raw log and JUnit; no missing-new-key or setup error counted as the red.
- **Same two IDs green:** 2 passed after the minimal partition repair.
- **Deliberate actual consumer blind #1:** disabled ONLY `decision_applicable is True` in the aggregate, leaving the rest of production intact. Mixed JSON and independent public text assertions both failed; all-captured twin passed (2F/1P). Raw mutant source/log/JUnit retained.
- **Deliberate actual consumer blind #2:** replaced ONLY `_decided`'s body with return True. All-captured healthy twin, captured-zero-call and pending-call controls failed (3F/0P). Original production bytes were restored exactly in finally; restoration SHA recorded. These failures prove the consumer controls distinguish the opposite verdict, not a replacement constant reporter. Opposite-case inputs are in the test diff for later commit; no commit is claimed now.
- **Final focused:** `tests/test_uptake_study.py` plus `tests/test_description_optimizer.py`: **103 PASS, zero failures/errors/skips**. Independent collect-only identities match JUnit by exact multiset, not count alone. Raw/JUnit/collected/executed IDs retained. This includes both report branches, probe/nonprobe, all disposition groups including missing and unhashable values, raw boolean preservation, JSON/text, unchanged cells/scores/primary result, wrong-model/unconfirmed exclusion, existing pending/unrecognized controls and actual optimizer consumer compatibility.
- Ruff final: all checks passed for the two owned Python paths. Scoped mypy using actual project configuration: success, two source files. `git diff --check` passed.
- Leak scan of exact five owned files copied externally: exit0; known healthy exit0; seeded home-path bad fixture exit1. Hostname deny-list was not configured: no all-hostname absence claim. Initial invocation used unsupported `python -m skillc` and failed with no __main__; that launcher error is preserved separately, then actual entry `python -m skillc.cli` was used. It is not a product regression/red.

An earlier 97-case uptake pass preceded final test additions/static annotation corrections and is retained separately, not substituted for final103. Initial mypy diagnostics identified object narrowing in counter validation and test assertions; corrected within the approved files, originals preserved. No unexpected product/assertion/instrument failure was encountered: expected red/blinding failures and permitted launcher/static corrections are distinguished.

## Native and guard evidence

Canonical begin/plan/approve used this NEW run and actual root implementation clearance. A manual rounded `Recorded at: 07:00:00Z` was noticed immediately after the first stamp. Before any production edit, I preserved that initial record/baseline, corrected ONLY the timestamp to actual UTC, and invoked canonical approve again for the identical substantive contract/scope. This correction and both stamps are disclosed in `timestamp-correction.json` and `initial-*` artifacts; no hidden new approval or run reset. Final baseline is `cda68b92fc3eb8da15bb5ff8afe6ec00d18801c48c1ee6f1bd6bb7df02a33059`. Current stability reports UNCHANGED against it; previous run prefixes did not change.

Actual native thread/CODEX_SESSION `01a17cec-fab5-7860-b0e9-aeef446e1806`, CLAUDE session absent, owning claim PID2186472/start33985101. No force/steal/alias/identity override. Registry exact five files/repo/new cwd/policy3; transport verification remains false and toolchain advisory UNKNOWN, not manufactured agreement. Native run and claim files are archived externally.

Observed normal guard results: live driver clear before first edit; stale base current; plan file-set agreement (3 planned/5 touched) and record stability unchanged; issue body drift clean; strict worktree no tracked main leak; lane exact5 with zero ungranted/unclaimed/extra/unused/contested; default BLOCKING ignored-additions exit0 after exact own diagnostic disposition. No advisory mode used. No canonical HEAD check was attempted before the separately gated checkpoint.

The original blocking ignored-additions exit3 named only `reports/failure-context.jsonl`. Standing exact-file protocol was used AFTER all owned pytest sessions terminated: producer `tests/conftest.py`/`tests/failure_context.py` identified and source-hashed; all six JSONL failure IDs matched actual failures in old-red and both mutant JUnits; consumer/raw accounting retained; regular nonsymlink inode/dev/size/mtime and bytes stayed stable across copying; all5484 bytes were archived and hash-verified; ONLY that exact file was unlinked. Original refusal transcript/summary, bytes and disposition proof remain. No unrelated cleanup or global prune.

## Physical preservation and stop

Final checks prove 6,231 off-lane tracked bytes/modes unchanged, strict physical389 fixture membership/bytes/modes equal the prior accepted manifest, both historical workflow prefixes unchanged, old5465741 tracked bytes/modes/HEAD/status/registration/claim block unchanged. Current primary HEAD remains its older1c7c4c7; no shared pull/reset/stash. Own HEAD is still16c6 and there is no new commit.

Evidence includes the exact five-path patch, final five source files/hashes, old source/fixture snapshots, raw red/green/blinds/final focused/static logs, exact IDs, native approval/claim, physical proof, diagnostic disposition and scope counts. No full or independent review claimed. STOP for root's direct uncommitted-diff judgment and next gate; #546 remains OPEN for its other residuals.
