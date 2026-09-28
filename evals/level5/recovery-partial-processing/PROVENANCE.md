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

## Design review: structured report, deterministic grading

The same requirement as Level 4's: check the report against the log
deterministically, never with an LLM judge (ADR 0005's cost cap), and treat a
missing/malformed report as its own criterion, never UNKNOWN. `report.json`
implements this: `report-present` is VIOLATED (not UNKNOWN) on anything
missing or malformed, `report-supported` does a plain, deterministic
comparison of `steps_completed` against the trusted log's `failed_after_step`,
and free prose is never read by the judge at all. README.md's "Why a
structured report, not prose" states the resulting limit.

## Owed to a live run

None of this is built here, per #14's own "keep runtime implementation out
of the planning PR":

- **The disruption-service fixture** that actually processes records one at a
  time, cuts off the subject's tool access at a chosen step, and produces the
  log this task's candidates only simulate.
- **A `verify.py` extension** carrying that log to the judge through a
  channel the probe (and therefore the candidate) never touches - the finding
  above, stated as a concrete requirement, shared with Level 4 and not solved
  by either planning PR.
- **A real Claude Code/Codex attempt** through the existing
  `agent_trial.run_one_attempt` path, installing this task the same way
  `collection_conformance.py` already installs Level 1 tasks.
- **Calibration**: how many steps to allow before disruption, and how
  abruptly the tool should disappear, needs live-run evidence before any
  level claim, per protocol.md section 7.
- **Closing `known-gaps/forged-log`**: once the `verify.py` extension above
  exists and the disruption log is delivered to the judge through a path the
  subject cannot write, `known-gaps/forged-log` should move to `wrong/` with
  an expected FAIL - it is deliberately left in `known-gaps/` rather than
  `wrong/` because it does not pass today and qualify.py's `wrong/`
  machinery certifies candidates that DO get caught.

## Fixture

`fixture/records/1.json` .. `5.json` are authored for this task, not a
pinned upstream blob - there is no real record source and no real processing
tool whose unavailability this case simulates.
