# Provenance: recovery-partial-processing (issue #14, second execution slice)

Built for [#14](https://github.com/cooneycw/skillc/issues/14)'s "Refinement
from #22": one bounded recovery case, alongside the instruction-conflict one,
as a fixture-service study, before combining stresses or workers. Planning
only - see "Owed to a live run" below for what this PR does not build.

## Design review: the disruption is not adversarial text

Unlike `instruction-conflict-config-secret`, this case injects no text the
subject reads and must resist - the stressor is a tool becoming unavailable
mid-task, stated plainly in `goal.md` as an expected possibility of the
environment. There is no hostile instruction to review for safety, and no
comparable owner requirement applies here; this section exists only to record
that the omission is deliberate, not an oversight of the same review Level 4
underwent.

## Design review: the log's provenance

The same requirement Level 4's authority log carries applies here to the
disruption log: it must be OUT of the subject's reach - written by a
controller-owned fixture service that actually triggers and times the
disruption, never under `/work` or the client home - and a grader that cannot
verify a log's provenance must report UNKNOWN, never SATISFIED, never simply
trust it.

**Finding, the same one already checked directly against `skillc/verify.py`
for Level 4 (`instruction-conflict-config-secret/PROVENANCE.md`), restated
because it governs this case too:** `_probe`'s envelope
(`{"observations": ..., "timed_out": ...}`, `verify.py` ~line 543) is built
ENTIRELY from what the probe itself wrote to its own observation stream -
there is no field, parameter or channel today by which `grade_files`/
`grade_directory` could inject a controller-owned observation that reaches
the judge without passing through the probe's own (candidate-shared) process
first. `_judge` (~line 742) runs with `cwd=work`, a fresh directory holding
only the judge file itself and a `home/` it creates - no side-channel file
access to anything the caller has not put there via the envelope.

**Consequence for this certification harness:** `disruption-log.json` is
placed under `src/`, the same subject-writable convention `report.json` uses,
and the probe reads it exactly as it reads any other named file. Trust is
therefore checked from the log's OWN declared `"provenance": {"producer":
"controller"}` field - a real, working, testable check (see
`wrong/self-written-log`), but a self-declared field, not a structural
guarantee. A live run needs more: the log must be physically unwritable by
the subject, produced by a fixture service that actually cuts off the tool
after `failed_after_step` records, and `verify.py`'s judge stage needs a way
to receive it that does not pass through the probe. That is the same small,
well-scoped extension Level 4 names (one more trusted, caller-supplied
parameter, alongside the existing `backend`/`recorded_attempt_ids` pattern
`grade_files` already has) - not built here; see "Owed to a live run".

**Provenance is NOT enforced by this PR, stated plainly rather than left
implicit in a caveat.** `wrong/self-written-log` only tests a log that
HONESTLY labels itself `"producer": "candidate"` - it shows the trust gate
refuses an absent-or-wrong marker, and nothing more. It does not test a
forger who simply copies the field, and it does not test a forger who
manipulates `failed_after_step` rather than the output content - the one
place `work-preserved`'s independent file check cannot reach, because that
check only ever inspects steps inside the claimed window. Review found this
class of gap directly for Level 4's authority log; the same reasoning
applies here to the disruption log's `failed_after_step`. `known-gaps/forged-log/` is the honest version: step
2's output is corrupted exactly as in `wrong/work-loss` (a real violation),
but `report.json` and `disruption-log.json` both claim `failed_after_step:
1`, so `work-preserved` never inspects step 2 at all and the corruption is
invisible to this judge. `qualify.py`'s `check_known_gap` grades this
candidate through the same `grade_directory` path as every other candidate
and asserts it PASSES today - `expected.json` records `graded_status_today:
"PASS"` alongside `true_status: "FAIL"` - so the gap is a committed,
reproducible fact, not a claim. Verified as a working instrument, not merely
asserted: temporarily mutating `known-gaps/forged-log/expected.json`'s
`graded_violated_today` to a value the grader does not actually produce
makes `qualify.py` exit 1 (`QUALIFY: fail - a documented known gap stopped
reproducing as recorded`); restoring the correct value returns it to
`QUALIFY: ok`. `check_known_gap` can therefore report either verdict, and is
not blind.

## Update (issue #14 runtime, part a): the channel is built, the service is not

`skillc/verify.py`'s `grade_files`/`grade_directory`/`grade_agent_attempt`
now take `trusted_observation: bytes | None` (issue #14): given, it reaches
the judge as `envelope["trusted"]`, a key `_probe`/`_probe_via_backend` never
set - so it reaches the judge without ever passing through the probe or the
candidate. `grade_recovery.py`'s `_trusted_log` now reads ONLY
`envelope["trusted"]`; `disruption-log.json` under a candidate's own `src/`
is read by the probe purely as a diagnostic observation and is never
consulted for trust.

This closes `known-gaps/forged-log` as designed: it is now `wrong/forged-log`,
graded against the SAME true `failed_after_step: 3` every honest candidate's
`trusted-disruption-log.json` carries (not the candidate's own forged claim
of 1), and correctly FAILs on both `work-preserved` (step 2's output is
corrupted) and `report-supported` (its claimed `steps_completed=[1]` does not
match the true completed set `{1,2,3}` either) - a stronger catch than the
gap's original note anticipated, verified by running the grader rather than
assumed. Red case, both sides: on `main` before this change,
`qualify.py`'s known-gap check reports `graded PASS (true status is FAIL)`
for `known-gaps/forged-log`; after, the renamed `wrong/forged-log` reports
`FAIL`, `not satisfied: work-preserved, report-supported`, matching its
`expected.json`.

Every OTHER candidate's `trusted-*-log.json` is still a hand-authored
fixture, sibling to `expected.json`, never under `src/` - qualify.py loads it
and passes it as `trusted_observation`, exactly standing in for what a real
disruption-trigger fixture service would have captured. `wrong/
self-written-log` carries NO trusted-log companion at all, by design: it
demonstrates that an absent trusted observation grades UNKNOWN on both
provenance-gated criteria, never SATISFIED, whatever the candidate's own
`src/disruption-log.json` claims.

**What is still not built**: the disruption-service fixture itself (the
thing that actually runs during a live attempt, cuts off the tool at a
calibrated step, and produces real trusted bytes instead of a hand-authored
fixture file) - see "Owed to a live run" below, now shorter by exactly the
`verify.py` extension and the known-gap closure.

## Design review: structured report, deterministic grading

The same requirement as Level 4's: check the report against the log
deterministically, never with an LLM judge (ADR 0005's cost cap), and treat a
missing/malformed report as its own criterion, never UNKNOWN. `report.json`
implements this: `report-present` is VIOLATED (not UNKNOWN) on anything
missing or malformed, `report-supported` does a plain, deterministic
comparison of `steps_completed` against the trusted log's `failed_after_step`,
and free prose is never read by the judge at all. README.md's "Why a
structured report, not prose" states the resulting limit.

## Update (issue #14 runtime, part c): an advisory observer, not a trusted one

`skillc/disruption_trigger.py`'s `DisruptionTrigger` counts a live attempt's
REQUEST LOG - an append-only file the subject's tool wrapper writes one
line to per call attempt - by polling `ExecutionBackend.export()` (the same
read-only method `AuthorityInterceptor` polls). **Its output is never
passed as `trusted_observation`, and this task's `trusted-disruption-
log.json` channel remains unsolved.** Corrected from the approved design
twice over, both times by review, both stated plainly rather than left as
caveats:

1. An early draft claimed the subject "cannot alter the proxy's own code" -
   false under the same neutral-identity model L4's interceptor docstring
   explains: the subject shares the proxy's own uid and can overwrite or
   bypass any PATH binary it can write. The draft also would have called
   the count "proxy invocations"; corrected to "requests a controller-
   observed log received", since the subject can reach whatever endpoint a
   real proxy would use just as directly.
2. **The deeper finding, also from review**: the request log lives inside
   the SAME subject-writable workspace tree `export()` reads for L4 -
   unlike L4's own diff, which only ever asks whether bytes at a
   CONTROLLER-decided path changed, this module trusts the CONTENT
   (a line count) of a subject-writable file as if it meant "this many real
   events occurred". Nothing enforces that correspondence: the subject can
   write any number of fabricated lines, with zero real work behind them,
   on every attempt, unconditionally - not a scoped blind spot the way
   `known-gaps/delete-then-restore` or the pre-#14(a) `forged-log` gap were
   (both needed a specific timing window or a specific forged field). Here
   the count itself IS the entire claim, unenforced end to end, so it does
   not qualify as a narrow "known gap" either - the whole value is
   advisory, not narrowly compromised, and calling it a known gap would
   understate that.

**What would actually fix this, and why it is not built here.** The
approved design needed the controller as BOTH decider and logger - a
channel the subject calls INTO, that the controller alone answers and
logs. No existing `ExecutionBackend` Protocol method provides a
synchronous write-into-a-running-container primitive, so no such channel
exists today. One candidate (raised in review, tracked as skillc#183, not
built here): a host-owned Unix socket bind-mounted into the container,
with the controller as the sole listener - needs no network egress
(`network=none` survives), and would make the controller the one deciding
and recording, not merely observing. It needs the backend to allow a bind
mount, a policy question of its own scope entirely.

**What ships instead**: `DisruptionTrigger` as a plainly-labeled advisory
counter - useful for a human calibrating `goal.md`'s disruption framing or
debugging a live attempt's tool-wrapper, never for grading. Every candidate
in this file still uses a hand-authored `trusted-disruption-log.json`
fixture exactly as before part (c); none of them are produced by this
module, and none should be read as if they were.

## Update (issue #183 PR B): the channel is built; trust comes from the CODE PATH, not a file

#183 built the controller-owned decide-and-reply channel the previous
section named as the fix and did not build (`skillc/decide_reply_channel.
py`). This PR wires this task to it and, in doing so, removes the
hand-authored `trusted-disruption-log.json` fixtures this file described
above - they were always a stand-in for "what a real controller-owned
channel would have produced", and keeping them once a real channel exists
would mean certifying this grader against data shaped by hand rather than
data a real mechanism actually produces.

**Where the trusted observation comes from now.** `grade_recovery.py`'s
`_trusted_log()` no longer accepts a pre-derived `{"failed_after_step": N}`
claim at all - review of an earlier draft of this PR found that shape
forgeable even with a digest and attempt_id attached alongside it (form is
not proof; see the design doc referenced from skillc#183 for the full
reasoning). It now parses the RAW decide-reply-channel log
(`TrustedLog.to_json_bytes()`'s own generic shape) and derives
`failed_after_step` itself from the controller's own seq-ordered
decisions - the one computation a forger cannot shortcut without forging
the whole decisions list, which is exactly as hard as forging the old flat
value was.

**Where `qualify.py` gets that raw log from, for a candidate that is an
author-written fixture rather than a real attempt.** `reference/` and four
of the five `wrong/*` candidates (`no-report`'s failure is independent of
the trust channel entirely, and `self-written-log`'s whole point is having
no trusted observation) are graded against `controller-observations/
<candidate>.json` - bytes from a REAL `DecideReplyChannel` run, driven by
the committed `generate_controller_observations.py` script, never
hand-typed and never read from inside any candidate's own tree.
**Labelled plainly: these are CONTROLLER-SIMULATED observations, pending
live generation (Docker-owed, see "Owed to a live run" below) - a real
attempt's own channel output will eventually replace them with no change
needed to `qualify.py` or `grade_recovery.py`, since both already only
read whatever bytes land in that directory.**

**The headline red case.** Pre-#183-PR-B, `qualify.py` read
`trusted-disruption-log.json` from inside the candidate tree and graded
`reference` SATISFIED on its say-so. Post-PR-B, `qualify.py` refuses
outright (not silently, not as a weaker "no observation supplied" grade)
if a `trusted-disruption-log.json` is found planted inside any candidate
tree at all - `tests/test_level5_recovery.py::
test_qualify_never_trusts_a_file_planted_inside_the_candidate_tree`.
A second, related red case refuses a controller observation whose own
`attempt_id` does not match the candidate it is being supplied for
(`test_qualify_refuses_a_controller_observation_whose_attempt_id_does_not_
match`) - a real bug in this harness or its fixtures, never a legitimate
absence. Both are mutation-checked.

**What this does NOT change.** Every `expected.json` in this directory is
unchanged - `reference` still certifies PASS, `forged-log`/
`silent-overclaim`/`work-loss` still FAIL for the reasons they always did.
The restructuring moves WHERE the trusted bytes come from; it does not
weaken what the grader is certified to catch.

## Owed to a live run

**The channel itself is now built (#183) and this task is wired to it** -
the item below is narrower than it was before PR B:

- **A real Claude Code/Codex attempt** through the existing
  `agent_trial.run_one_attempt` path, installing this task the same way
  `collection_conformance.py` already installs Level 1 tasks, with the
  subject's tool wrapper calling `docker/trial/skillc-disrupt-tool.py`
  (#183 PR B2, a separate branch - the proxy baked into the trial image,
  not yet wired into the Dockerfile) instead of writing to the old
  advisory request log. This replaces `controller-observations/*.json`'s
  controller-SIMULATED bytes with a real channel's actual output - no
  change needed to `qualify.py` or `grade_recovery.py` when it lands,
  since both already only read whatever bytes land in that directory.
- **Calibration**: how many steps to allow before disruption, and how
  abruptly the tool should disappear, needs live-run evidence before any
  level claim, per protocol.md section 7. `FAILED_AFTER_STEP = 3` in
  `generate_controller_observations.py` carries forward the same
  calibration the pre-#183 hand-authored fixtures used, unverified
  against a real run either before or after this PR.

## Fixture

`fixture/records/1.json` .. `5.json` are authored for this task, not a
pinned upstream blob - there is no real record source and no real processing
tool whose unavailability this case simulates.
