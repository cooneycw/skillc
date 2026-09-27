# Issue #122 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #122
- Read at:      2026-09-27T13:10:47Z
- updatedAt:    2026-09-27T11:24:15Z   (context only - moves on comments and labels)
- Body digest:  e63bc0f74fb817439c66c3a339a1e792efebcbb43c30f8c0932474afa5bcad07   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3241 of 3241 (cap 16384)

## Body as read
Refs #10, Refs #79, Refs #81.

## Why

The operator's live run of `skillc demo` at 8e06030 (evidence: https://github.com/cooneycw/skillc/issues/10#issuecomment-5855368984) showed these on a real Docker daemon: the success path, and the three seeded controls in `--control` (reply-only client, container left running, leaky composition). Every other failure path in #79's matrix is proven only against the fake `docker` CLI and `FakeBackend`.

The owner ruled on 2026-09-27 to accept that coverage for #10 and to file this follow-up for the two paths where real Docker semantics most plausibly differ from the fake:

- **Timeout.** On a real daemon the limit is enforced across `docker exec` and `docker kill`. Whether the exec session ends, the container stops, and `confirm_stopped` reads the truth from `docker inspect` depends on the daemon's own behaviour, not on logic the fake shares.
- **Operator cancellation.** A real SIGINT delivered mid-trial to `skillc demo` must reach the right process, must reap only this run's recorded attempts (#120), and must leave no owned container running. Signal delivery and a live exec session are exactly what a fake cannot reproduce.

## Scope

Add real-daemon seeds for these two paths to `skillc demo --control`, each reported in the leak-checked paste-back block:

1. **Timeout:** an attempt whose command sleeps past a short limit. Expected: a timeout disposition that is never the agent's FAIL, `confirm_stopped` confirmed from the daemon, and a reap outcome for the attempt.
2. **Cancellation:** a trial interrupted by a real SIGINT while its exec is in flight. Expected: the fixed interrupt line, exit 1, this run's attempt reaped, and a foreign skillc-owned container untouched.

`--control` exits non-zero unless both are caught.

## Out of scope, and why

These stay proven against the fake only. Each is hard to seed honestly on an operator's real daemon:

- **Provider unavailable:** requires making the daemon itself unreachable mid-run, which means stopping the operator's Docker service.
- **Capture failure:** requires `docker cp`/export to fail on a live container without faking the CLI. No portable, non-destructive way is known.
- **Empty task selection:** decided before any container exists. The driver logic is identical on either daemon, so a real run adds nothing.
- **Teardown failure:** requires a real `docker rm` to fail or lie, which cannot be forced generically on an operator's daemon.
- **Launch failure:** needs an image or argv the daemon rejects. It is partly seeded already, since a missing image is covered by #118's tests, and adds little over the fake.
- **Kill-by-signal (of the container):** needs an external `docker kill` from a second process at a precise moment. It is timing-fragile and overlaps the timeout seed's `docker kill` path.

## Acceptance

- [ ] Both seeds are committed, each with a red case: disable the timeout enforcement, or the interrupt handler's scoping, and `--control` must report NOT caught.
- [ ] Tests pass against the fake `docker` (the green this rests on).
- [ ] **An operator live run on a real daemon**, posted here as the leak-checked block with EXIT lines, shows both paths caught. This issue closes only on that run.

