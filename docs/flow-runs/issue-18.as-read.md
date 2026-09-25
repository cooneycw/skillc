# Issue #18 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #18
- Read at:      2026-09-25T13:13:55Z
- updatedAt:    2026-09-25T13:13:36Z   (context only - moves on comments and labels)
- Body digest:  267529b3c76ac16c613019093aca769eedf2653efd67ffc8167cec2b7d523b1f   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1950 of 1950 (cap 16384)

## Body as read
## Problem

skillc has no CI. Every "verified" claim so far — including PR #17's `selftest && pytest && ruff check . && mypy skillc` — was a local run. The repo has now been added to Woodpecker, but it has no `.woodpecker/ci.yml` yet.

## Outcome

A Woodpecker pipeline runs the existing four-command gate on push and pull_request, and includes a step that proves the gate can fail.

## Acceptance

- [ ] `.woodpecker/ci.yml` runs on `push` and `pull_request`: `skillc selftest`, `pytest`, `ruff check .`, `mypy skillc`. Use a slim Python 3.11+ image. The runtime stays stdlib-only; dev tools come from `uv.lock`/`pyproject.toml`.
- [ ] **Negative-control step** (the gate lets work through, so it needs one): run `skillc selftest --controls <copy>` against a controls copy with one rule's control directory removed, and REQUIRE exit 1 (UNPROVEN). The step fails if selftest exits 0. This is the only failing case the checker detects today; the empty-population, unparseable-bad-case and unknown-`--rule` cases join it when #2 lands.
- [ ] Show the gate going red before merge: one pipeline run where a check fails (e.g. a pushed commit with a deliberate lint error, then reverted), citing the pipeline number and the step that failed. Also show green on the final head SHA.
- [ ] No Docker-in-Docker, secrets, deploy step or model credentials.
- [ ] State in the README/AGENTS.md which checks CI runs.

## Known limitation

A green run does not yet mean what it appears to: `selftest` still reports 11/11 when a good population is empty or a bad case is unparseable (reproduced 2026-09-24; see #2). CI runs the instrument faithfully; #2 makes the instrument trustworthy. Land this first, then #2 on top so its fixes are seen flipping in CI.

## Scope

Static checker only. Eval/Docker stages wait for #6/#10. Branch-protection changes (required status `ci/woodpecker/pr/ci`) are the owner's call and not part of this issue.

Parent roadmap: #1

