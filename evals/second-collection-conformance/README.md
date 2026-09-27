# Second-collection conformance, through the real Docker backend (#11)

[`run-manifest.json`](run-manifest.json) prepares the run #11's own text
asks for: the same client, Level 1 fixture, contract and grader, run against
BOTH declared subjects - [cpp-codex](../subjects/cpp-codex/SUBJECT.md) (the
whole 74-skill pack) and [mattpocock-skills](../subjects/mattpocock-skills/SUBJECT.md)
(`tdd`, `diagnosing-bugs`) - through the real `DockerBackend`, not the host
adapter path both subjects' existing evidence already proves.

**Prepared, not run**, exactly like [the matched pilot](../matched-pilot/README.md)
and for the same reason: execution needs a live capability that does not
exist in this repository yet - a `--subject <name>` flag that materializes
the named subject through `materialize.py`, installs it via
`DockerBackend.install()` into a real container, and observes client-side
discovery plus an in-container digest re-verification against the
installation receipt, with no model call (the design the orchestrator
ruled on, msg 1474/1479). **As of msg 1488 (`w1`), this flag is being split
out of #81/#97 into its own follow-up PR under #11**: PR #97 (already
open) carries an EARLIER, materialize-only `--subject` shape (no container
install, no discovery, no digest check), built before the fuller design was
settled, and is not being widened to match it - the fuller design lands
separately. Once that follow-up PR exists, these two runs execute in the
SAME operator session as #81's own live demo - one runbook, not two, per
the orchestrator's instruction (msg 1470).

## What this delivers, and what it does not

Delivered here:

- **The exact command per subject** (`run-manifest.json`'s `runs`), stated
  as `AGREED, not yet implemented` rather than guessed at - the design was
  confirmed by direct question to w1 before this manifest was written
  (`skillc/demo.py`'s WIP, as of `ad3fdf3`, does not yet materialize any
  skill collection at all; asking first rather than building against a
  guess avoided real rework).
- **The expected paste-back shape per subject**: an installation-receipt
  summary matching each subject's ALREADY-recorded host evidence
  (`evals/subjects/*/evidence/report.json`) - proving the Docker-backed run
  is expected to reproduce the SAME facts the host adapter path already
  established, not a new claim - plus a `discovered` field. That field is
  explicitly `owed to #81's client-listing discovery step`, never invented,
  in case w1 splits that step into a follow-up PR (the orchestrator's own
  contingency, msg 1474).
- **Citations, not re-proofs**, for the two acceptance bullets already
  closed by existing work: no-project-name-branch (the genericity guard,
  #94) and unsupported-formats-refused-before-selection
  (`test_a_malformed_subject_declaration_is_refused`'s 10 parametrized
  cases, generic to `materialize.Subject.from_dict` and therefore already
  covering both subjects). Re-demonstrating either here would be redundant
  work the orchestrator explicitly said to skip (msg 1474).
- **The bounded compatibility statement**, below.
- **The acceptance status against #11's four bullets** (`run-manifest.json`'s
  `acceptance_status`), stated plainly per orchestrator ruling (msg 1479,
  relayed from the operator): the no-agent demo this manifest prepares -
  installation plus discovery plus an in-container digest re-verification
  against the receipt - gives conformance evidence for bullets 1, 3 and
  part of 4. It does **not** satisfy bullet 2 ("the same client, Level 1
  fixture, contract and grader"), which needs an agent actually WORKING
  the Level 1 task with each collection installed - a real model call this
  no-agent demo deliberately never makes. **#11 stays open after this
  manifest's own two runs execute**; one item remains, below.

Explicitly NOT delivered here, per #11's own "do not build a second large
benchmark" and the same discipline the matched pilot follows:

- No live Docker run, no image build, no real client invocation - all owed
  to the operator's live session, alongside #81's.
- No claim about which collection helps an agent more, no task-outcome
  measurement, no paid model call of any kind - #10 (the live run itself),
  #12 (the matched pilot) and #26 (selection behavior) own those questions,
  not this manifest.
- No new skill selection, layout support, or adapter change -
  `mattpocock-skills/subject.json`'s existing `select: [tdd,
  diagnosing-bugs]` is reused verbatim; this manifest does not revisit that
  choice or attempt the 14 policy-hidden skills the Nit Store (#20) already
  flags as a separate, undecided gap.

## The bounded compatibility statement

**What is shown compatible, and by what kind of evidence - kept separate on
purpose (codex review of this PR: the first draft blurred them into one
"end to end" claim the evidence does not support):**

- **By actual execution:** `skillc materialize` has been RUN against both
  `cpp-codex` and `mattpocock-skills`, on the host, with no adapter change
  between them (`mattpocock-skills/SUBJECT.md`'s own finding, #71/#11:
  "proving the adapter needed no change for an independently authored
  collection with a different layout"). This is real, executed evidence -
  the installation counts and readiness facts this manifest cites are from
  those actual runs.
- **By static proof, never by execution:** `trial.py`, `verify.py`,
  `backend.py` and `docker_backend.py` carry no subject-name branch
  (cited above, not re-proven) - a structural guarantee that NEITHER
  subject could be special-cased in that code, whether or not either has
  ever actually been run through it.
- **Not shown at all, by either kind of evidence:** that the trial
  controller, the verifier, or a real execution backend has ever actually
  processed EITHER subject end to end. No full trial (plan an attempt,
  dispatch it through a backend, capture, grade) has been run for
  `cpp-codex` or `mattpocock-skills` - only `materialize.py`'s own
  installation step has real execution evidence. That is precisely the gap
  this manifest's two runs are prepared to close, once #81's `--subject`
  flag and a real Docker daemon exist to run them against - not a gap this
  document can claim closed by citing the adapter-only evidence or the
  genericity guard.

**What is NOT shown, and is not claimed to be:**

- That either collection makes an agent MORE LIKELY to complete a task, or
  complete it faster, or more safely. This manifest never runs a real
  model against either collection at all.
- That `mattpocock-skills`' other 23 shipped-but-unselected skills, or its
  13 unshipped drafts, behave the same way - they are out of this
  manifest's declared surface entirely, for the reasons
  `mattpocock-skills/SUBJECT.md`'s own "report unsupported formats"
  section already states.
- That a third, fourth, or Nth independently-authored collection would
  behave identically. Two is what #11 asks for ("do not build a second
  large benchmark"); generalizing further is future work, not a
  conclusion this evidence supports.
- Anything about Claude Code specifically. Both subjects' evidence, and
  this manifest's expected discovery step, are Codex-only
  (`codex debug prompt-input`); Claude Code has no equivalent no-model
  render command as of this writing (`skillc/exposure.py`'s own module
  docstring states the same limit for its rung-2 check).

## Process note: asking before building

The design question this manifest depends on - what `--subject` actually
parametrizes - was genuinely ambiguous from #81's WIP alone: neither of its
two existing demos (`run_lifecycle_demo`, `run_grading_demo`) touched
`materialize.py` or any subject declaration at the time this manifest was
written. Rather than guess and risk rework, the question was asked directly
(of `w1`, who owns `#81`) with the two readings that seemed possible from
the code as it stood; the orchestrator settled it (msg 1474) before this
manifest's `runs` section was written. The same discipline applies going
forward: if `w1`'s eventual implementation diverges from what is stated
here, this manifest is wrong and should be corrected against the real
interface, not defended against it.
