# Flow run record - issue #563

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=7c7180522f804e0e850981cbc96f3019 -->
## Run 1

- Run-id:            7c7180522f804e0e850981cbc96f3019
- Run-start:         a3e9ba8049c6dd3a97c64fd8d9d35e7296cd3835


- Issue: #563
- Base SHA: a3e9ba8049c6dd3a97c64fd8d9d35e7296cd3835
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-complete orchestrator, gate-563.md, separate correctness prerequisite

### Section B evidence
B. Necessity: still needed

- Actual PR #562 / pipeline1083 at ffc90c3 gate failed. Its terminal outer
  summary is 1 failed,6875 passed,106 skipped in359.26s; the named failure is
  tests/test_agent_trial.py::test_red_case_gate_entrypoint_declared_but_not_delivered_is_refused,
  FileExistsError at pathlib.mkdir('/tmp/skillc-trigger'). Full gate log is
  retained locally at /tmp/skillc-562-ci1083-gate.log. CI produces a workspace
  JUnit file but uploads no separate artifact, so remote JUnit reconciliation
  is unavailable; the raw outer tail is preserved, not replaced by scraped IDs.
- Main a3e9ba8 and reviewed #536 head have identical docker_backend.py.
  _ensure_private_trigger_dir lines356-359 checks exists then mkdir with no
  FileExistsError handling. All fresh xdist starts share the same default dir.
- Isolated deterministic two-caller reproduction uses actual production helper
  in a TemporaryDirectory child and a barrier forcing both initial absent
  observations: one success, one FileExistsError. No shared host path touched.
- #550 was inspected: its TOCTOU item is cwd/confine_root; there is no trigger
  directory mkdir item. #563 is the separate live-correctness record. No current
  assigned lane changes this function; the prerequisite must stay independent.


### Section C - approved bounded prerequisite
1. `skillc/docker_backend.py` - handle only the concurrent FileExistsError at
   atomic mkdir. A competing creator's path must pass the existing owner and
   exact0700 checks, plus real-directory type/no-symlink validation using lstat.
   Never chmod an existing/competing path. Keep the freshly created directory's
   existing mode-finalization behavior only in the branch that created it;
   preserve other error semantics and caller API. No blanket exist_ok+chmod.
   Update the local docstring to distinguish first creator from validated winner.
2. `tests/test_docker_backend.py` - deterministic two-caller safe race control
   with a barrier at real Path.mkdir, so both old and fixed code hit the same
   race point without timing sleeps. Both callers must succeed and leave a
   correctly owned0700 directory. Add competing-creator cases for safe0700,
   wrong0755 mode, different owner, regular file and symlink; safe winner must
   cause no chmod and unsafe winners must refuse without changing their modes
   or link targets. Keep existing owner/mode controls. Freshly created mode under
   restrictive umask remains correct; scope umask changes to a child process.
   Tests use isolated tmp_path only, with bounded barrier/future waits and no
   Docker/client calls. Observe new safe race red on pre-fix main before edits.
3. `changelog.d/563.md` - one fragment for concurrent startup acceptance with
   unchanged strict validation of an existing winner.

Controls and validation

- Commit the race and owner/mode/type/symlink bad/good cases as tests. These are
  real filesystem inputs, not a stub that merely returns the desired verdict.
- Observe the safe concurrent-start regression red on unchanged main; then
  green after the fix. A controlled unsafe winner must still report refusal,
  including one whose mode would become safe if the implementation chmodded it.
- Run focused backend and the exact failed agent-trial test. If replaying the
  baseline CI failure itself is nondeterministic, say so; the deterministic
  isolated race is the regression proof, not a probabilistic retry.
- Selftest before checker output, relevant lint/types/controls, counter-model
  review, exact-head required CI and root review. Request heavy slot only if
  needed after #489's current full gate; do not overlap it with another full
  suite. Use the receipt repair once available, no fabricated skip or gate green.

Scope and limits

Three planned files plus docs/flow-runs/issue-563{,.as-read}.md. This repairs
startup creation arbitration and validates the winner; it does not claim to
exclude later same-UID writers or close every filesystem replacement race.
No host configuration, privileged cleanup, paid evaluation, pinned subject
change, or frozen557 edit. No source edit before the separate root scope gate.


Root conditions: exact real-directory/owner/0700 validation for the competing
winner, no chmod of an existing winner, no following a symlink. Restrictive
umask finalization is tested in a child; no promise of simultaneous acceptance
while another creator still has an unsafe transient mode. Preserve other errors.
No host path mutation, paid run, frozen557 edit or widening into536/489.


### Execution evidence (approved Section C unchanged)

Eight new regressions failed on unchanged production before the fix: the real
mkdir-barrier safe race, all competing-creator cases, and pre-existing regular
file/symlink acceptance. All ten new controls pass after the fix. The broader
backend suite plus the exact agent-trial test that failed CI1083 pass: 195 tests
in 126.18 seconds. Controls use isolated temporary paths, with umask changes only
in a child process; no shared host trigger path was removed or modified.

Selftest discriminates 31/31. Lint, types, negative/type/leak/secret controls and
README drift pass. The initial pre-note compliance result was file-set agreement
(three planned, five touched) and unchanged stability. This appended execution
evidence preserves the approved bytes above and will truthfully change the
record digest, without changing its scope.

Counter-model review: measured codex/gpt-6-astra, one pass, no defects found.
Reviewer thread `01a1702d-21ae-7e43-9189-2c971698824a`; report SHA-256
`fdc766b4c5b9ddd602a04cdb332120f809c24280dfa316e5e7a598480c3fc2bf`.
Scope probe unverified (reviewer inspected surrounding code), network measured
blocked, repository-local credentials absent. The mixed-model implementer
receipt limitation is unchanged; no fake receipt or skipped review is claimed.
Full verification and exact-head CI remain required, and receipt enrollment
remains held for the separately assigned truthful CPP helper repair.
### Receipt completion after CPP1558

The merged CPP1558 helper generated the actual schema3 ran receipt at
docs/measurements/counter-model/2026-10-25T005206Z-issue-563.json from the original
fresh run and review traces. Implementer codex/gpt-6.1-sol, reviewer
codex/gpt-6-astra, scope unverified, network blocked, local credentials absent.
Initial cleanliness remains unmeasured and approval execution unverified; neither
was reconstructed. Six whole review report entries are proposed; zero are
credited as already covered under the verified all-subcases-before-first-proposal
standard. Zero does not claim that no existing controls covered those cases.
The retained full make verify passed; its outer finish gate originally failed
for the missing receipt. That historical failure remains a failure. Receipt
enrolment and current-base integration are checked separately below.


Current main08a6887053eb7bcf3c7d3fc6545a7aa7aad2ec74 merged cleanly; upstream
paths do not overlap the approved source lane. The ten new trigger-directory
controls plus twenty newly integrated historical replay cases pass:30/30 exact
JUnit identities, make test EXIT0. Source and existing backend test bytes are
unchanged from the reviewed head. The explicit merged-helper enrolment-only gate
exits0 and audit-flow verifies the original captured prefix. This pairs the
retained full make verify EXIT0 with actual receipt enrolment; it does not rename
the historical outer finish failure as a pass or rerun a full suite for metadata.
Final required CI and root exact-head/current-base clearance remain pending.
