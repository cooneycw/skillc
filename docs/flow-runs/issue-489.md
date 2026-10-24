# Flow run record - issue #489

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=f129a2fad5174424b170b282a92b2171 -->
## Run 1

- Run-id:            f129a2fad5174424b170b282a92b2171
- Run-start:         a3e9ba8049c6dd3a97c64fd8d9d35e7296cd3835


- Issue: #489
- Base SHA: a3e9ba8049c6dd3a97c64fd8d9d35e7296cd3835
- Necessity verdict: Partially superseded; explicit control attribution remains needed
- Approval: granted
- Approver: skillc-complete orchestrator, corrected gate-489.md, after independently replaying the real population and parser
- Scope ruling: actual nested pytest producers; ci/negative-control.sh remains unchanged

### Section B evidence
B. Necessity: partially superseded; explicit attribution still needed

- Current skillc main a3e9ba8 has ci/negative-control.sh unchanged since #30.
  It runs skillc selftest/check, not pytest. tests/test_negative_control.py
  captures shell output but does not launch an inner pytest session.
- Real current CPP origin/main fb588389 includes #1502 / 6fa9a4e1 (nested
  summary exclusion) and #1503's implementation #1511 / b6117e7b (fences).
  Inspecting the actual parser establishes selftest/check text is unsupported.
  Actual shell output parses as None. Fencing that raw text produces an
  unknown control, not the intended known-bad count: control_invocations=1,
  control_failed=0, control_unexpected=[removed-control]. Do not wrap it blindly.
- On the actual retained #547 main pytest stream, the old local CPP runner
  reported 6904 passed,331 failed,121 xfailed,27 invocations although pytest
  itself reported 6904 passed,1 failed,5 skipped. Replaying that single
  captured stream through actual current CPP outcomes.py gives exactly
  6904 passed,1 failed,5 skipped,1 invocation,0 controls. Thus #1502 has
  already fixed this population's count inflation; upgrading that historical
  helper would be an operator tooling action, not a skillc code fix.
- The 26 extra child sessions are the pytester.runpytest calls in
  tests/test_property_held_xfail_pattern.py (14 call sites expanded by params).
  They deliberately run failures to prove targeted xfail discrimination and
  are echoed by pytest's -rA capture reporting. Explicit protocol attribution
  remains absent even with current CPP: control_invocations=0.
- Evidence population digest: c56ae60aee4ce9d5d1cf85d305ead96ac40d953ee479ccaaf7f5ab763ce3e88b.
  Source parser digest: b5154d41810882c2e12b3fc3fa0ba487ded8c2a55f1257428fa9ff125d4fef67.
  Local files: /tmp/skillc-489-actual-test-stream.txt and
  /tmp/cpp-outcomes-main-for-489.py. No paid run or new full suite used.


Issue evidence: https://github.com/cooneycw/skillc/issues/489#issuecomment-6390475664.
The current body was read before this run; root's corrected scope explicitly
supersedes the original file-target assumption, not the user-visible intent.

### Section C - approved corrected plan
1. tests/test_property_held_xfail_pattern.py: introduce a small local wrapper
   around each of its 14 pytester.runpytest call sites, emitting reserved
   BEGIN/END lines around that invocation's own unchanged output. END in a
   finally block makes a child exception visible as unknown rather than
   silently opening a fence. Stable colon-free per-case names. BAD/GOOD is
   declared before running from the test's expected fixture/case outcome,
   never derived from the child's observed exit or counts. BAD for expected
   hard failures; GOOD for expected no hard failures (including the intentional
   widened-marker all-xfail child). Keep every current assert_outcomes and
   per-node assertion; a fence never substitutes for behavioral checks.
   Check actual pytester stream behavior; if any child summary uses stderr,
   capture and emit its raw streams together under ONE fence instead of
   duplicating counts with two fences or leaving a summary outside its fence.
2. tests/test_control_output_fences.py (new): drive the wrapper through real
   pytester children. Prove one BAD failing child and one GOOD clean child,
   BAD unexpectedly clean, GOOD unexpectedly failed, missing/unknown summary,
   child exception and outer real failure remain legible. Assert per-invocation
   nesting/balance/labels and retain raw output; never wrap the entire main
   suite. Run missing-fence regression red before touching the producer.
3. tests/fixtures/control-output-fences/cases.json (new): committed positive
   and negative protocol cases with fixed expected regular/control counts,
   including unexpectedly clean BAD and malformed/unclosed fence. These drive
   local contract tests; do not duplicate or vendor CPP's parser in skillc.
4. changelog.d/489.md: one fragment describing explicit attribution of nested
   pytest control invocations. Automatic flow-run/as-read records are additional.

No ci/negative-control.sh edit is proposed: its selftest syntax is not accepted
by the current external parser. No skillc production/runtime code, CPP install,
new runtime/CI dependency, fake pytest summary, or external checkout on CI.

Validation and external compatibility proof

- Observe existing missing-fence regression red, then green with wrapper.
- Exercise BAD unexpected-clean and GOOD unexpected-failure through the actual
  wrapper, with unchanged child output and surrounding assertions.
- Capture a targeted -rA run of this test file plus its control tests, with a
  real outer suite summary. In development only, load actual current CPP
  outcomes.py from a recorded origin/main commit via an isolated temporary
  module, and parse the exact captured stream. Assert regular counts equal
  the outer suite only; all child summaries appear under control_*;
  control_unexpected names the deliberately wrong-declared child. Also parse
  malformed/unbalanced controls to show failures stay visible. Record parser
  revision/digest and actual resulting fields in the PR. This is a one-time
  compatibility test, not a committed external runtime dependency.
- Run focused existing marker tests and normal skillc gates. Root exact-head
  review/CI remains required. Full gate follows the wave slot policy.

Bound: control fences are reporting labels, not authentication. A child capable
of printing reserved protocol markers can make its segment ambiguous; preserve
raw output and let CPP's malformed/nesting behavior expose it. Do not infer a
BAD/GOOD declaration from whatever outcome happened or manufacture summaries
for selftest output that the parser cannot understand.


Root conditions: preserve raw streams and every original behavioral assertion;
choose BAD/GOOD before running, stable colon-free names, never invent summaries.
Controls must cover real outer failures and cannot contaminate or hide the outer
verdict. Real current CPP parser compatibility is a development check only; no
vendored parser or external runtime/CI dependency. Full gates, counter-model
review and root exact-head clearance remain required. No frozen #557 edits.


### Execution evidence (approved paths and assertions unchanged)

The actual existing-producer missing-fence regression was run red before edits:
one failure, because no marker-specific-infra BEGIN/END pair existed. After the
wrapper, all 104 focused tests pass, including the original property assertions
and new real-child, wrong-declaration, exception, framing and outer-failure cases.
Selftest 31/31, lint, types and every lightweight control/check passed.

Development compatibility used actual CPP outcomes.py from origin/main
`fb5883897cf37ef62de44b5879748f9bb2423cf2`, parser SHA-256
`b5154d41810882c2e12b3fc3fa0ba487ded8c2a55f1257428fa9ff125d4fef67`.
The production stream reported 104 regular passes and zero regular failures,
26 controls, 330 control failures, 121 control xfails and no unexpected controls.
Its SHA-256 is `6d97d356e952a741d6ea17c2270210b909647d74cdb0949fddf96184e69b2887`.
A separate actual-wrapper compatibility run retained five regular passes and
one deliberate real outer failure, six controls, and named bad-clean,
good-fails and unknown as unexpected. Its stream SHA-256 is
`2109012e1930bee945756161627d7d568eaa8425c182f2ef14d2a0fdc4277529`.
Both the committed malformed input cases and equivalent mutations of actual
wrapper output retain failed=1/control_invocations=0; the unknown-summary case
retains its named unexpected control. No CPP dependency was added to skillc CI.

Counter-model review: measured codex/gpt-6-astra, one pass, no defects found.
Reviewer thread `01a17023-109a-7aa0-a225-481174ca0803`; report SHA-256
`c0d8af7df7e88bfdcbab9407040fb9c7e125cf674eb65ff5505271eeb58b1c55`.
Scope probe unverified (reviewer read surrounding implementation), network
measured blocked, repository-local credentials absent. The existing mixed-model
receipt limitation remains real; no review is fabricated or called skipped.
Machine receipt enrollment remains held for the separately assigned CPP repair.

Plan checker: unknown, because three original Section C path lines use punctuation
its parser cannot derive. The approved record is preserved byte-for-byte above;
it is not rewritten to manufacture agreement. The actual six touched paths are
exactly the registered six-file lane. Appended execution notes also cause the
stability checker to report a changed record; this is reported explicitly.
