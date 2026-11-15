# Flow run record - issue #727

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=3f96b8d8eec0430c9f3c9ef82858e005 -->
## Run 1

- Run-id:            3f96b8d8eec0430c9f3c9ef82858e005
- Run-start:         bca9ea234ea1ae9ffa62ce681ac000aebd2a1f30
- Issue:             #727
- Base SHA:          bca9ea2
- Necessity verdict: Still needed
- Approval:          granted (GO-WITH-CONDITIONS)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 25
- Recorded at:       2026-11-15T12:05:00Z

### Section B evidence
- reproduced at bca9ea2: under umask 0002 the 5 named tests fail (51 pass); under 022 all 56 pass
- commits since 2026-11-14T20:42:24Z touching skillc/clutter*.py or tests/test_clutter*: none
- PRs: none; dup/super: none; host: no sibling worktree with unpushed clutter commits

### Section C - the approved plan
1. `skillc/clutter_delivery.py` - selectors() return, per delivered key, the expectation (file: execute flag plus content digest; symlink: digest); accepts() checks an observed digest against the 256 permission modes in 0o777 whose S_IXUSR agrees with the blob, computed only for added keys; setuid, setgid and sticky are never accepted
2. `skillc/clutter.py` - classify's delivered match uses accepts() instead of digest equality; captures stay raw; SCHEMA_VERSION stays 1
3. `tests/test_clutter_umask.py` - under umask 022, 0002 and 077: delivered reads delivered; an undelivered extra, a content change, an execute-bit change (both directions) and a setuid copy are clutter; unit tests of the git rule; a bounded-cost test over many delivered additions; and the delivered case red first on bca9ea2 under 0002
4. `docs/specs/evaluation-facility/clutter.md` - the bit rule, and the blind spot: a delivered regular file may carry any 0o677 bit (group- or world-writable too) and still read delivered; setuid, setgid and sticky stay clutter
5. `changelog.d/727.md` - fragment

Conditions (rev 25): only S_IXUSR plus content; tolerance in delivery matching only; three umasks; red-first; the 5 named tests are not edited (stop and report if one hard-codes a mode); the blind spot documented; the cost pinned; targeted set under umask 0002 too; up to 3 counter-model passes; nothing pushed until a CI slot is given
Scope: 5 paths, ~250 lines. Risk: a widened instrument, answered by the committed NOT_CLEAN cases under three umasks and by keeping the tolerance to delivery matching only

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test - Woodpecker CI (full-suite gate); host `make verify` targeted set only, under umask 022, 0002 and 077; real-Docker runner VM not applicable |
| Execution backend | will test - DockerBackend: the fake `docker` the clutter tests use; real daemon not covered; ManagedBackend not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | not applicable |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (uv sync, editable) via the suite; built wheel in a clean venv not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: classify() and every clutter report consumer. A verdict changes only for delivered regular files whose non-execute permission bits differ from 0o644/0o755: NOT_CLEAN becomes CLEAN. Compatibility: the three-umask controls.

### Lane correction (counter-model review, pass 1)
- Execution backend: **not covered**. The new tests drive the host `Inventory` path (`test_clutter_capture.inventory()`, which reads the filesystem directly, with empty daemon surfaces). They do not drive DockerBackend, faked or real. The delivery matching that changed sits behind both, in `classify()`.
