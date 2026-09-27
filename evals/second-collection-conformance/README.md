# Second-collection conformance, through the real Docker backend (#11)

[`run-manifest.json`](run-manifest.json) prepares the run #11's own text
asks for: the same client, Level 1 fixture, contract and grader, run against
BOTH declared subjects - [cpp-codex](../subjects/cpp-codex/SUBJECT.md) (the
whole 74-skill pack) and [mattpocock-skills](../subjects/mattpocock-skills/SUBJECT.md)
(`tdd`, `diagnosing-bugs`) - through the real `DockerBackend`, not the host
adapter path both subjects' existing evidence already proves.

**Prepared, not run**, exactly like [the matched pilot](../matched-pilot/README.md)
and for the same reason: execution needs a live capability that does not
fully exist yet. `skillc demo --subject <name>` (#81, #10) already exists in
PR #97, materializing the named subject on the HOST via
`materialize.materialize()`. It does not yet install into the real
container, run discovery there, or re-verify a digest - that fuller
behavior (`DockerBackend.install()`, client-side discovery inside the
container, an in-container digest check against the installation receipt,
no model call) is a follow-up PR under #11. Once that lands, these two runs
execute in the same operator session as #81's own live demo - one runbook,
not two.

## What this delivers, and what it does not

Delivered here:

- **The exact command per subject** (`run-manifest.json`'s `runs`): `skillc
  demo --subject cpp-codex` and `skillc demo --subject mattpocock-skills`,
  the real flag PR #97 already wires - stated with its current (host-only)
  behavior alongside the fuller behavior this manifest's `expected_paste_back`
  describes, so the two are never conflated.
- **The expected paste-back shape per subject**: an installation-receipt
  summary matching each subject's ALREADY-recorded host evidence
  (`evals/subjects/*/evidence/report.json`) - proving the Docker-backed run
  is expected to reproduce the SAME facts the host adapter path already
  established, not a new claim - plus `digest_check` and `discovered`
  fields. Both are explicitly `owed to the follow-up PR under #11`, never
  invented.
- **Citations, not re-proofs**, for the two acceptance bullets already
  closed by existing work: no-project-name-branch (the genericity guard,
  #94) and unsupported-formats-refused-before-selection
  (`test_a_malformed_subject_declaration_is_refused`'s 10 parametrized
  cases, generic to `materialize.Subject.from_dict` and therefore already
  covering both subjects).
- **The bounded compatibility statement**, below.
- **The acceptance status against #11's four bullets** (`run-manifest.json`'s
  `acceptance_status`): the no-agent demo this manifest prepares -
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
purpose (a "proven end to end" claim would blur two different kinds of
evidence into one overclaim):**

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
  this manifest's two runs are prepared to close, once the `--subject`
  follow-up PR and a real Docker daemon exist to run them against - not a
  gap this document can claim closed by citing the adapter-only evidence or
  the genericity guard.

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
- That the remaining agent run (bullet 2, above) is metered or paid-per-call
  spend. It runs on the operator's normal Claude Code/Codex subscription
  login, inside the normal usage budget - quoted verbatim from the ruling
  on #98: "Normal Claude and codex". It is not gated by the #12 $5 cost
  stop, which covers judge calls only (e.g. `mcp-second-opinion`, which use
  provider API keys). The subscription-credential mechanism it needs
  (`skillc/credential.py`, `docker_backend.DockerBackend.deliver_home_file`/
  `read_home_file` - resolved from a documented standard location, delivered
  candidate-owned into the trial container's home directory, never mounted
  or exported, refused below a minimum remaining life) is delivered under
  #98; the agent run itself is still not, and is not this manifest's own
  remaining item to close.
