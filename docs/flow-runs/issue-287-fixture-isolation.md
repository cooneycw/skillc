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
