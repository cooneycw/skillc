<!-- flow-run n=1 id=002cba7806264694b4074dfa9136919b -->
## Run 1 - issue #364 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #364
- Read at:      2026-10-12T17:42:39Z
- updatedAt:    2026-10-12T17:41:59Z   (context only - moves on comments and labels)
- Body digest:  6a14a13565c0baf56e6860cf792e5dd839f5aa3e4a153befb07703fc5aad8ce8   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3482 of 3482 (cap 16384)

### Body as read
**Type:** scope:task (CI throughput). Found while landing #361 (Refs #338).

## Problem

The `gate` step is almost the whole pipeline: **1,637 s (~27 min)** on PR #361's pipeline 708, while every other step finishes in seconds and already runs in parallel (`depends_on: []`). Inside `gate`, nearly all of the time is one serial `uv run --no-sync pytest -rA --junit-xml=pytest-report.xml` over ~3,100 tests. Locally the same suite took 1,573 s serial (3118 passed, 3 skipped, `-m "not real_docker"`) on a 24-core host. `make verify` has the same cost, since `make test` is also serial.

The goal is a faster gate with the **same test population and the same evidence**. Removing or narrowing tests is out of scope.

## Proposal (ordered by payoff)

1. **Parallel pytest.** Add `pytest-xdist` to the `dev` extra and run `pytest -n auto` in `gate` and `make test`. Tests build fake-Docker state under their own `tmp_path`, so they look parallel-safe, but prove it: one parallel run and one serial run must give the identical per-test outcome set. Anything order- or host-coupled gets an explicit serial group (`xdist_group` / `--dist loadgroup`), not a skip. Expect roughly 4-8x on the test portion, depending on the CI VM's core count.
2. **A population check that ships with item 1 (negative control).** A parallel run can silently shrink: a crashed worker, or different collection on different workers. Add a step (shaped like `git-tests-control`) that compares the count from `pytest --collect-only -q` with the count of testcases in `pytest-report.xml`, and fails on any mismatch. Commit a known-short report as its red case. `ci/check_git_tests_ran.py` must still pass against the xdist-produced junit.
3. **Shrink real waits, not coverage.** Run `pytest --durations=50` once and list the worst offenders. Many `docker_backend`/`gate_witness` tests spend real seconds on `limits.timeout`, `grace`, `daemon_timeout` joins and stop confirmation. Where a test only needs "the timeout fired", pass a smaller timeout/grace or an injectable clock. Each test keeps asserting the same property.
4. **Split `gate`.** `selftest`, `ruff` and `mypy` become their own parallel steps (each with its own `UV_PROJECT_ENVIRONMENT`, like the other steps). If item 1 is not enough, shard pytest across 2-3 steps by duration, and extend item 2's check to require that the shards' union equals the collected population.
5. **Stop reinstalling tools per step.** Every step runs `apt-get install git` / `pip install uv` from scratch. Use a prebuilt CI image with `uv` and `git` (and cache uv's downloads). `uv sync --locked` stays, so a stale lock still fails.

## Explicitly not proposed

Running only tests near changed files, or skipping slow tests on PRs. Both weaken what green means. #361 is an example: a change to `exec_in_attempt` broke `_WitnessBackend` doubles under `evals/level3/`, far from the files that changed.

## Acceptance

- [ ] `gate` wall time measured before and after, on the same CI VM, and both numbers recorded on this issue.
- [ ] A serial run and a parallel run on the same commit give the identical per-test outcome set (diff attached).
- [ ] The population-count check exists, fails on its committed short-report red case, and passes on the real report.
- [ ] `git-tests-control` still passes, and still fails on its own red case, under the parallel run.
- [ ] `make verify` uses the same parallel invocation as CI (`tests/test_ci_local_gate_coverage.py` stays green).

