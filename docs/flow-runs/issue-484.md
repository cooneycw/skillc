# Flow run record - issue #484

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b6dc259e2fd243c0841ee0b4104f0578 -->
## Run 1

- Run-id:            b6dc259e2fd243c0841ee0b4104f0578
- Run-start:         048e2ffe3bd2e873d9015751c87271789602f303
- Issue:             #484
- Base SHA:          0e6711e
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved" in this session
- Recorded at:       2026-10-28T12:22:56Z

### Section B evidence
WIP commits 0943e30, 048e2ff (prior session, replay-only monitor). Commits on main touching ci/ since filing:
000753d, 028dde5, 1e7ae69, 80eca1d, f4060c7 - none stall-related. Merged PRs #560-#601 - none touching stall
capture. Related/duplicate issues considered: #462 (load-timing test family, separate). Post-migration
pipelines ~1091-1167: failures 1140 (real failure, psi_io10 0.05), 1095 (real failure), 1111 (stall-like,
psi_io10 30-45, five 120 s setup timeouts, 16-CPU agent, 2026-10-25). Owner migrated VM disks 2026-10-22.

### Section C - the approved plan
Land the replay-only monitor as the measurement instrument; keep #484 open (Refs, not Closes); post a
post-migration status comment. Nothing runs on any host.

1. `ci/stall_capture/README.md` - merge main in; add post-migration note (pipeline 1111 stall, two CI agents: live run must name the sampled host)
2. `ci/stall_capture/__init__.py` - land as-is; fix only what lint/mypy/full gate flags
3. `ci/stall_capture/attribute.py` - land as-is; fix only what lint/mypy/full gate flags
4. `ci/stall_capture/guest.py` - land as-is; fix only what lint/mypy/full gate flags
5. `ci/stall_capture/host.py` - land as-is; fix only what lint/mypy/full gate flags
6. `ci/stall_capture/loop.py` - land as-is; fix only what lint/mypy/full gate flags
7. `ci/stall_capture/procfs.py` - land as-is; fix only what lint/mypy/full gate flags
8. `tests/test_stall_capture.py` - land; negative control: mutate stall threshold, confirm induced-stall and cpu-burn cases go red
9. `tests/fixtures/stall-capture/cpuburn.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
10. `tests/fixtures/stall-capture/cpuburn.host.jsonl` - land unchanged (drift-tested synthetic fixture)
11. `tests/fixtures/stall-capture/device.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
12. `tests/fixtures/stall-capture/device.host.jsonl` - land unchanged (drift-tested synthetic fixture)
13. `tests/fixtures/stall-capture/discard.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
14. `tests/fixtures/stall-capture/discard.host.jsonl` - land unchanged (drift-tested synthetic fixture)
15. `tests/fixtures/stall-capture/make_fixtures.py` - land unchanged (drift-tested synthetic fixture)
16. `tests/fixtures/stall-capture/mixed.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
17. `tests/fixtures/stall-capture/mixed.host.jsonl` - land unchanged (drift-tested synthetic fixture)
18. `tests/fixtures/stall-capture/neighbour.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
19. `tests/fixtures/stall-capture/neighbour.host.jsonl` - land unchanged (drift-tested synthetic fixture)
20. `tests/fixtures/stall-capture/quiet.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
21. `tests/fixtures/stall-capture/quiet.host.jsonl` - land unchanged (drift-tested synthetic fixture)
22. `tests/fixtures/stall-capture/steal.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
23. `tests/fixtures/stall-capture/steal.host.jsonl` - land unchanged (drift-tested synthetic fixture)
24. `tests/fixtures/stall-capture/throttle.guest.jsonl` - land unchanged (drift-tested synthetic fixture)
25. `tests/fixtures/stall-capture/throttle.host.jsonl` - land unchanged (drift-tested synthetic fixture)

Not a file: issue comment on #484 with the post-migration evidence and the next gated step (one live sampler
window per CI agent over a few full-suite runs, on owner GO).

Scope: ~1,330 lines already written; new edits likely <30 lines.
Risks: current-main tree-scanning / no-subject-name tests may trip on the new ci/ and fixture files; skillc CI
hold needs lock 2; landing does not close #484.
