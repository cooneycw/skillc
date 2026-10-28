# Issue #546 - parked checkpoint, 2026-10-25

Work is parked by owner instruction. This is a resume record, not a review
receipt, delivery certificate, new approval, or replacement for the original run.

## Preserved source

- Pre-feature base: `29d702d8cc7cc24620c64d9275d286b4f34cfefd`.
- Original selected implementation: `8eb87dfb3ccc0a0d5325e3125da9a03785ea1ebc`.
- Fresh repair source: `732142deb6ddb87d4188f7db54bf0866843fb103`.
- Repair tree: `4613fd13d0050228f0865ee2ece3bc560cf101af`.
- The original implementation and fresh repairs have separate attribution.
  Historical run records remain unchanged; they do not attribute the repairs.

The repairs reject malformed completion clock evidence, validate supplied owned-ID
collectors before legacy preparation, and preserve cancellation cause across a
shared deadline. Only the specifically granted calibration test was updated to
expect setup exhaustion while retaining every planned slot in the report. The
existing coordination test file was unchanged. The selected product change is
18 paths / 1,370 added-plus-deleted nonworkflow lines, within its 1,800-line cap.

## Evidence and limits

Fresh regression failures were observed before the repairs. The updated
calibration test failed on the pre-feature base; malformed-clock, collector and
cancellation controls failed on the original selected implementation. Healthy
controls and the repaired cases passed.

Fresh focused verification: 649 passed, one historical-private-evidence skip;
all 650 independently collected identities matched the JUnit report. Lint,
types and the 31-rule selftest passed. The first focused run retained one
orphan-child failure: its child was a zombie adopted by the container's init.
The unchanged test and repeat population passed under an actual child reaper.
The original 706-case and fresh 650-case selections differ: 151 original
pilot/discrimination/verifier cases still lack fresh final-source execution.
Original and fresh evidence are retained separately outside the repository.

One actual `gpt-6-astra` review invocation was blocked before source inspection
because the read-only sandbox could not launch. Providing the normal Bubblewrap
binary exposed a namespace-permission refusal. No sandbox restriction was
weakened. The process exit established no review verdict or findings. The later
content-only review was never started before the owner parked the work.

## Resume requirements

There are zero completed independent reviews. No review receipt, full finish,
PR, required exact-head CI, or merge has been completed. A future review needs
new coordination and must cover the whole base-to-final-source diff, with its
actual scope recorded honestly. Receipt tooling must represent both contributions
without extending historical provenance. Exact receipt-path and finish/PR grants
remain outstanding. Check process capacity before any heavy verification.

Do not repeat the passing focused suite without a change or unresolved concern.
Do not start a review or expand fixes on this parked checkpoint. Broad #546
items, including cap equality, SIGINT and killed-after-dispatch accounting, have
not been resolved here. No live study or physical validation is claimed.
