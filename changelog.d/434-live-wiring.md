- **A live flow:auto attempt against a fixture-service task** (#434, PR 2b).
  `run_one_attempt(fixture=...)` runs the PR 1 task's fixture inside the
  attempt and grades it from controller-held records, with no controller git
  on anything the subject can write.
  - `skillc/exec_git_remote.py`: the service's git calls run INSIDE the
    attempt, as the candidate, confined to `/work`, under a fixed environment.
    It is refused without `witness_io` (an exec would otherwise write into the
    workspace), on a stopped attempt, and on incomplete output. Its answers
    match `LocalGitRemote`'s, writes included, on identically built fixtures.
  - After the stop, the service finalizes against a `SnapshotGitRemote` over
    the exported remote (`FixtureService.finalize(remote=...)`), and the git
    state is captured from the exported bytes.
  - `skillc/fixture_attempt.py`: the gh and codex-guard routes share the one
    trigger socket with the gate witness through `fixture_service.dispatch`.
    `verify`'s new `trusted_extras` carries the case, service record, git
    capture, final report and guard record beside the witness; a colliding
    key is refused.
  - `skillc/fixture_overlay.py`: the gh shim and the nested-codex guard are
    placed root-owned and verified: not pre-planted, bytes read back, file and
    directory candidate-unwritable, and found first on the measured PATH.
  - The nested-codex guard (`docker/fixture-service/skillc-codex-guard.py`,
    D3) sits at `/usr/local/sbin/codex`. A codex launched under a codex
    ancestor (exact exe/script identity, never a name) exits 3 as
    unavailable; unreadable ancestry fails closed; the harness launch passes
    through with argv and environment byte for byte. Each decision goes to a
    controller-held record (`skillc/codex_guard.py`), and the credit gate
    refuses credit when a nested codex is observed or suspected, or the count
    is unknown. Proven in a real trial container with a real nested codex.
  - `docker/fixture-service/flow-auto-gate-shim.py` witnesses flow-auto's one
    bare finish-gate call.
  - A fixture attempt keeps #442's default egress allowlist; a widened one is
    refused before any container exists.
  - `evals/subjects/cpp-codex-flow-auto-86641e8/` declares flow-auto plus
    flow-eli5 at CPP `86641e8`, closed against a committed snapshot that
    carries its provenance and the upstream MIT licence. Measured against the
    pinned receipt writer: a nested refusal is read as a skip but leaves no
    counter-model receipt in a codex trial.
  - Eleven PR 1 qualify candidates, replayed through the live wiring, grade
    exactly as committed.
