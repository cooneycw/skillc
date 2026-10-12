# Isolate the profile mutation control

Refs #287; separate validation repair for PR #372.

## Approved bounded plan

The orchestrator granted this separate repair from main 1ff273e after the
endpoint's full run at ba8bd83 failed: 1 failed, 3777 passed, 15 skipped.
The tamper control writes a tracked shared fixture while parallel readers
validate it. The finding is recorded at
https://github.com/cooneycw/skillc/issues/20#issuecomment-6134188584.

1. `tests/test_profile_installed_home_files.py`: copy the real snapshot into
   the tamper test's temporary directory before validation and mutation. Keep
   the digest-refusal assertion. Add a deterministic interleaved-reader
   regression and demonstrate its failure before the isolation fix.
2. This evidence record: retain the original failure, repair validation and
   independent review scope/result.

No production change, fixture edit or blanket test serialization. The risk
is weakening the mutation control while isolating it; its exact digest-change
refusal and a positive reader observation must still execute. Full verification
and exact-head CI are required. #287 remains open; no study is authorized.

## Initial evidence

The interleaved-reader regression ran against the original mutation logic
and failed because the reader observed a flow-check gate-lib.sh checksum
mismatch during tampering. Only the test's unused tmp_path argument and new
regression were added for that red run; no isolation fix was present.
The fixed test copies the real snapshot before validation and mutation.
All eight tests in the file then passed. The original source digest-change
refusal still executes, and the interleaved reader must return a nonempty
verified mapping exactly once. This is a deterministic call boundary, not
a timing-dependent concurrent stress test.

The separate two-file repair is now ready for independent review and full
verification. It changes no production code or committed fixture bytes.

## Independent repair review

One substantive gpt-6.1-sol review of the two-file repair at 310b2c1 found
no defects. The native implementer is gpt-6-astra. Actual reviewer rollout
01a13257-c464-7821-a721-0be61724aa83 contains only gpt-6.1-sol contexts;
no formatting resume or additional review ran. The reviewer inspected the
diff/source without executing tests and affirmed both the private mutation
refusal and the original-fixture reader's nonempty result, observed once.
Root's own integration read likewise found no issue. This is a separate
repair review, not a third substantive endpoint review.

The official parser returned unparseable despite the explicit clean verdict
and Red cases section; no report was rewritten to force acceptance. The
actual receipt writer refused because it cannot find this native implementer
as a Claude transcript. No official receipt, false skip or machine-gate pass
is claimed. The original stream, rollout, report, patch and red evidence are
archived in persistent private state. Root retains the native-review ruling
and merge authority. Full verification and final-head CI remain required.

Observed repair diff SHA256: 49600abc760057173db7eaeff0467dff79f33fac81f1ea46eb0a56e4a39747f5.
Original report SHA256: c75f1ccc5cf826fa3d4b4a98fb82c965ed923eaec654424bbf7d4e29b7188c91.
Original reviewer rollout SHA256: 57234d0e488b807b27cafa7190293b0e9a2df730054e4fe4cc494dd47d93c6aa.
