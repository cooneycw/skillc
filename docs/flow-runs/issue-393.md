# Flow run record - issue #393

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=1505c3543da14eeca8e7251d5b5695ad -->
## Run 1

- Run-id:            1505c3543da14eeca8e7251d5b5695ad
- Run-start:         3f873954ccb8ebbf063b5c9fdb4f3824d91ade53
- Issue:             #393
- Base SHA:          3f87395
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive "approved" in the flow:auto session
- Recorded at:       2026-10-14T17:40:00Z

### Section B evidence
commits: none on origin/main since 2026-10-14T17:06Z (latest 3f87395/#391 predates); PRs merged today #391 #389 #388 #386 #381 - none touch install(); dup/superseding: none (related #394, #348, #355).

### Section C - the approved plan
1. `skillc/docker_backend.py` - one candidate-identity `mkdir -p` exec for every missing parent of a copied install entry, before any copy; shared helper reused by deliver_home_file; docstring update
2. `tests/test_docker_backend.py` - fake-Docker tests: nested bytes/path keys get one candidate mkdir; existing parent metadata preserved; flat keys no exec; mkdir failure refuses before any cp
3. `tests/test_install_nested_dirs_live.py` - real-Docker regression control: candidate can create a file in an installed nested directory (red on pre-fix code)
4. `tests/test_cwd_confinement_live.py` - fix the docstring line that goes stale
5. `CHANGELOG.md` - Unreleased entry

Scope: 4 files + 1 new, ~150 lines. Risks: one extra exec per nested install (fails closed); a candidate-unwritable root with a missing nested parent now refuses.
