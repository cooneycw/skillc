# Flow run record - issue #540

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=1abb7c593acf4539810ce1350e69b644 -->
## Run 1

- Run-id:            1abb7c593acf4539810ce1350e69b644
- Run-start:         12db6909350bc69afc0a40160312e220d2f0b0f7
- Issue:             #540
- Base SHA:          12db690
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved" in this session
- Recorded at:       2026-10-28T00:00:00Z

### Section B evidence
Commits since 2026-10-24 on the relevant paths: 20a0359 (#590), 1c7c4c7 (#583), a924c5f (#565); none change prepare()'s cleanup. Merged PRs #559-#598 checked; #590 explicitly leaves #540 residue untouched. Neighbours #549 (item 3 is a different, interrupted-test leak) and #551 (fake docker divergence); no duplicate. No sibling worktree for #540.

Root cause (from the creating run's own log, session e365f3aa, base 552eaa6): `docker run -d` killed at the 5.0 s bound; the single `rm -f` cleanup completed (BackendUnavailable, not TimeoutExpired) and removed nothing; the daemon's in-flight create landed afterwards, leaving a created-never-started container.

### Section C - the approved plan
1. `skillc/docker_backend.py` - prepare(): on a timed-out `run -d`, wait one more daemon_timeout for the CLI's own answer before `rm -f`; if still unanswered, kill, `rm -f`, and report an unconfirmed-cleanup clause naming the attempt label.
2. `tests/fixtures/docker-backend/fake_docker.py` - `.late-create-run` sentinel: a detached child writes the `created` record after N seconds; the CLI waits for it.
3. `tests/test_docker_backend.py` - regression test (late create within the grace leaves no record; fails pre-fix) and a reported-not-silent test (late create after the grace yields the clause).
Scope: 3 files, ~120-160 lines. Risks: failing prepare() can take up to 2x the bound; a daemon stalled beyond 2x still leaks, reported not silent; sibling egress-proxy race routed to the nit store. Post-merge: remove the kyle19 residue container.
