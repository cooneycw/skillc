# Flow run record - issue #761

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ff3d58f7e61748219920b24c5f38ac51 -->
## Run 1

- Run-id:            ff3d58f7e61748219920b24c5f38ac51
- Run-start:         63883c6d749bf8e622f14020f09c1b1593c7cfee
- Issue:             #761
- Base SHA:          63883c6d749bf8e622f14020f09c1b1593c7cfee
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #761 (mailbox rev 32, 2026-11-15T16:44Z)
- Recorded at:       2026-11-15T16:50:00Z

### Section B evidence
- commits on main since 2026-11-15T14:18Z on these paths: none
- PRs: #181, #190, #195 merged (the interceptor, settled-value resolution, write-back check); open #767 touches only tests/test_docker_backend.py, not planned here
- dup/super: none (#186 closed: a symlink or special file at observations is recorded at once, kept)
- host daemon measurement (Docker 29.9.2): `docker cp -` replaces observations with a NEW inode, and partial content is visible (475 sizes sampled); no ABSENT was sampled, but it is not ruled out

### Section C - the approved plan
1. `skillc/backend.py` - ExecuteResult gains observations_write (started, ended monotonic; digest of the exact bytes written), None when no write-back was attempted
2. `skillc/docker_backend.py` - execute()'s tail fills observations_write around its existing docker cp write-back; no behaviour change
3. `skillc/authority_interceptor.py` - per-poll export times; observations bytes kept (bounded by the stdout cap, oversize degrades to kept); deletes at observations deferred; stop_and_finalize(write_back=None) drops a transition only if (a) its poll overlapped [started, ended], (b) its value is ABSENT or a byte prefix of the written bytes, and (c) the settled value equals write_back.digest; write_back=None keeps today's rule; symlink/special still recorded at once (#186); the residual gap documented by name in the docstring
4. `tests/fixtures/docker-backend/fake_docker.py` - opt-in cp HOLD (FAKE_DOCKER_CP_HOLD=<dir>, truncate or remove mode): held marker, waits for release, bounded timeout; default unchanged
5. `tests/test_authority_interceptor.py` - red-first on 63883c6 with the window held deterministically (release after one recording poll inside it, no sleeps): clean run truncate and remove modes no entry; subject different content kept; subject EMPTY file kept; subject delete kept; orphan overwrite after write-back flagged; write_back=None pinned unchanged; the memory bound asserted
6. `scripts/probe_docker_cp_writeback.py` - a small real-docker probe (a few MB, short stat loop) for the host and skillc's own real-Docker runner VM, never Kyle's series-25 VM
7. `changelog.d/761.md` - fragment

### Gate conditions (rev 32)
- runner VM: skillc's own real-Docker runner VM only, never Kyle's series-25 remote VM (#1476); if unsure, ask; small probe only; else stated unmeasured, PR Refs #761
- the memory bound asserted in a test
- targeted set only; directory-sweeping gates if the fixture change trips one
- counter-model review up to 3 passes, pass-3 findings deferred; mailbox-gated push in a free slot

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | not applicable - no checkout-relative paths |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host targeted set; real-Docker runner VM (installed runner pin vs requested commit): docker cp measured there if reachable, else not tested |
| Execution backend | will test - DockerBackend against the fake CLI with a held write-back; the real host daemon's docker cp measured (29.9.2); other backends: write_back=None pinned unchanged |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | not applicable - Level 4 harness subjects are synthetic scripts |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (`uv sync`, editable); built wheel in a clean venv: not tested |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: stop_and_finalize reading ExecuteResult.observations_write | tested against real output - DockerBackend's own execute() on the fake CLI |
| Reader: grade_agent_attempt / stayed-in-bounds reading the trusted log | tested against real output - the existing level-4 tests, entries shape unchanged |
