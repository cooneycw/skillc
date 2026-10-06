# The `<agent-host>` real-Docker runner (#315)

Certifies #183's live-channel test, #326's trial-image build test, and
#269's gate-witness test (and, once it exists, #266) against a REAL Docker
daemon, on an isolated VM, with no Woodpecker involved at all. The main
Woodpecker server is untouched; nothing here registers anything with it.

**A file tagged `@pytest.mark.real_docker` is collected and run, but NOT
certified, until `ci/check_real_docker_ran.py`'s `DECLARED_REAL_DOCKER_
FILES` also names it (orchestrator review).** The marker alone only
decides what `pytest -m real_docker` runs; the declared-files floor is what
catches that file going silent - skipped, renamed, erroring at collection -
in a run where every OTHER declared file still passes. Without the floor
entry, such a run posts SUCCESS: green on the VM with no evidence from that
file at all. Adding a file to the floor is a code change in the INSTALLED
runner, so it takes effect only on the next explicit reinstall from a
reviewed main sha (R1) - never implicitly at the next tick.

**No machine identities appear in this repository.** `<agent-host>`,
`<dedicated-user>`, `<server-url>` and similar are placeholders the operator
fills in at install time, never committed values.

## What runs where

| Component | Lives in | Updated |
|---|---|---|
| `ci/check_real_docker_ran.py`, `ci/real_docker_summary.py`, `ci/real_docker_isolation.py`, `ci/real_docker_trigger.py`, `ci/real_docker_post.py`, `ci/real-docker/*` | the INSTALLED copy (`$INSTALLED_ROOT`, e.g. `/opt/skillc-real-docker-runner`) - a git checkout pinned to a reviewed main SHA | explicit operator step only (`git fetch && git checkout <reviewed-sha>` in `$INSTALLED_ROOT`), never implicitly |
| `tests/` (whatever `real_docker`-marked tests the requested commit carries) | the WORK checkout (`$WORK_CHECKOUT`) - re-fetched and re-detached to the requested sha on every run | every run |

**Why the split (R1):** the requested sha is untrusted input - it is either
an ordinary main commit or an owner-authorized ad hoc sha, but either way it
is still code the runner is about to execute tests from. If the verdict
function, the summary formatter, or the posting logic were read from that
same checkout, a commit could redefine its own grade and post `success` for
itself. `run-real-docker` always invokes the installed copy's
`ci/real_docker_post.py` by absolute path, with `PYTHONPATH` set to
`$INSTALLED_ROOT` only, from a working directory that is never the checkout
- see `tests/test_real_docker_post.py`'s subprocess-based red case for a
reproduction of exactly this attack and proof it does not work.

**What R1 does NOT close (stated so nobody reads it as more than it is,
orchestrator review):** pinning the verdict/summary/posting CODE stops a
requested commit from redefining its own grade, but that commit still
PRODUCES the JUnit report the pinned code is handed - code that has already
run can shape what gets written to that file. R1 is not a defence against a
malicious test run forging its own report; it only stops the reporting
layer itself from being substituted. This is exactly why only main (already
reviewed and merged) and explicitly owner-requested shas are ever run
automatically (see "Trigger mechanism" below) - the residual trust that
matters is in WHICH commits run at all, not in what R1 covers.

## Setup (operator, over SSH on `<agent-host>`)

1. Install Docker, `git`, `uv`, and whatever this repo's own `make test`
   needs (no new dependency - the VM is dedicated to this work already).
2. Create a dedicated, non-login OS user in the `docker` group
   (`<dedicated-user>` in the systemd units below).
3. Install the runner:
   ```
   git clone https://github.com/cooneycw/skillc.git /opt/skillc-real-docker-runner
   cd /opt/skillc-real-docker-runner && git checkout <reviewed-main-sha>
   ```
4. Create `/etc/skillc-real-docker/config.env` (mode 600, owned by
   `<dedicated-user>`) from the template below.
5. Create the GitHub token (see "Token", below) at the path
   `GITHUB_TOKEN_FILE` names, mode 600.
6. Install the systemd units:
   ```
   cp ci/real-docker/skillc-real-docker.{service,timer} /etc/systemd/system/
   # edit the <dedicated-user> placeholder in the .service file
   systemctl daemon-reload
   ```
7. **Isolation verification, before enabling anything (R6):** set
   `LAN_PROBE_TARGET` to a `host:port` on the LAN that is DETECTABLY
   reachable when nothing blocks it (a real listening service, not a bare
   IP with nothing on that port - otherwise even a fully open LAN would
   read "unreachable" and this check would prove nothing; see B2).
   - With the hypervisor-level firewall OFF: run
     `ci/real-docker/run-real-docker <any-sha>` by hand and confirm it
     refuses with "isolation not verified" (posts `error`, runs no tests).
   - With it ON: run the same command and confirm it proceeds past the
     preflight.
   - **Record both outcomes on this issue**, generically (no addresses) -
     this is the committed evidence that the detector actually detects
     something, on this specific host, not only in the unit tests.
8. **#183/#269 break-mode verification (R2):** `--break` takes `none` or
   `<family>:<mode>`, resolved from a closed table in `break-lib.sh` - an
   unknown family or mode is refused with exit 2 before any checkout or
   docker operation. The three bare `channel` spellings below (no
   `channel:` prefix) also still work, kept for compatibility with runs
   recorded before family prefixes existed (#315 follow-up); a bare
   `witness` mode has no such form and is refused.
   ```
   run-real-docker <post-#300-main-sha> --break none                           # expect SUCCESS
   run-real-docker <post-#300-main-sha> --break channel:omit-mount             # expect FAILURE
   run-real-docker <post-#300-main-sha> --break channel:wrong-uid              # expect FAILURE
   run-real-docker <post-#300-main-sha> --break channel:flip-decision          # expect FAILURE
   run-real-docker <post-#300-main-sha> --break witness:stale-confirm-lie      # expect FAILURE
   run-real-docker <post-#300-main-sha> --break witness:kill-wrong-pid         # expect FAILURE
   run-real-docker <post-#300-main-sha> --break witness:gate-in-fresh-container # expect FAILURE
   ```
   Break-mode runs post only to `skillc/real-docker-control`
   (never the certifying `skillc/real-docker` context) and are labelled
   EXPECTED-RED. Record all seven results on this issue.
9. `systemctl enable --now skillc-real-docker.timer`.

## `config.env` template

```bash
INSTALLED_ROOT=/opt/skillc-real-docker-runner
WORK_CHECKOUT=/var/lib/skillc-real-docker/checkout
LOCK_FILE=/var/lib/skillc-real-docker/run.lock
LOCK_WAIT_SECONDS=240                                    # bounded wait, not instant failure - see S1 below
STATE_FILE=/var/lib/skillc-real-docker/state.json
GITHUB_TOKEN_FILE=/etc/skillc-real-docker/github-token   # mode 600
GITHUB_REPO=cooneycw/skillc
GITHUB_COMMENT_ISSUE=                                    # optional; an issue/PR number to also comment on
LAN_PROBE_TARGET=                                        # host:port to TCP-probe FROM INSIDE a throwaway
                                                           # container - VM-local, never committed; see R6.
                                                           # A bare host with no port is refused (unconfigured).
PREFLIGHT_IMAGE=python:3.12-slim                          # must carry python3 - the same image this repo's
                                                           # own live-Docker tests already use (SKILLC_LIVE_TEST_IMAGE)
```

## Token

A fine-grained GitHub PAT scoped to `cooneycw/skillc` only:
`Commit statuses: write`, `Issues and pull requests: write` (the second
also covers reading comments, needed for the trigger poll). Stored at
`GITHUB_TOKEN_FILE`, `chmod 600`, read once per run. **Never appears in any
process's argv** (visible to any local user via `ps`): `curl` reads it from
a private, mode-600 `-K` config file created fresh for each invocation and
removed on exit, never as a `-H`/`-d` command-line argument.

**`<agent-host>` holds no SSH keys to any other host.** This token is the
only credential on the VM.

## Network isolation (R6)

**The enforced boundary is a hypervisor-level firewall on `<agent-host>`'s
network interface**, set up by the operator from a private runbook outside
this repository - described here only as "hypervisor-level isolation
verified by the operator." A privileged container is root on the VM and can
flush any firewall running *inside* it, so an in-VM firewall cannot be the
boundary itself.

**In-VM rules (nftables/ufw) are defence in depth, not the boundary:**
- deny outbound to private ranges (RFC 1918, link-local, CGNAT, IPv6 ULA
  and link-local), except the specific gateway/DNS addresses needed;
- allow outbound internet; allow inbound SSH only;
- **the same deny rules must also sit in the `DOCKER-USER` chain** (or the
  nftables equivalent) - Docker's own rules otherwise bypass a plain `ufw`
  policy for forwarded container traffic entirely;
- **the deny rules must DROP, or REJECT with `icmp-host-prohibited`/
  `icmp-admin-prohibited` - never REJECT with a bare TCP reset.** A
  tcp-reset reject is indistinguishable, to the probe, from a real host
  answering and refusing the connection: `ConnectionRefusedError` is
  exactly what the probe script sees either way, so a reset-based deny
  rule makes the LAN probe read "reachable" and the runner refuse EVERY
  run, permanently - fail-closed (safe), but confusing to diagnose if the
  operator does not know this in advance. `ufw`'s default deny already
  drops; this matters mainly if the operator's own convention uses
  `REJECT` instead.

**The preflight (`run-real-docker`'s first step, before any checkout) is a
DETECTOR, not a proof.** From inside a throwaway container it runs a
TCP-connect probe (python3's `socket.create_connection`, tri-state: a
connection REFUSED still proves a host answered and counts as reachable;
only a timeout or routing failure counts as unreachable; anything else -
DNS failure, the probe itself unable to run - is its own `probe_error`
state, which also refuses) against the configured LAN target (must be
unreachable) and `github.com:443` (must be reachable, the probe's own
positive control). A passing result means "the LAN was unreachable from
this container right now" - never "isolation is proven." `ci/real_docker_
isolation.py` is the pure classifier; its tests (`tests/test_real_docker_
isolation.py`) cover every refusal reason plus the one proceed case, with
two mutation checks (a classifier blind to the LAN probe, and one that
folds `probe_error` into `unreachable` the way the original `|| echo
unreachable` fallback effectively did).

## Trigger mechanism (R3 + R4)

Two sources, both run with `--break none` only - break-mode runs are a
by-hand operator action (step 8 above), never reachable automatically:

1. **New commits on main.** Already reviewed and merged code - never
   arbitrary PR code.
2. **An explicit `/run-real-docker <sha>` comment** (exactly 40 hex
   characters - never an abbreviation, since `run-real-docker` compares
   against the checkout's full `rev-parse HEAD` byte-for-byte), author
   checked against the repository's own `owner.login` (fetched fresh each
   poll), never the comment's own text. `ci/real_docker_trigger.py`
   processes each comment id exactly once, at first sight - an edit to an
   old comment (which the GitHub API resurfaces because `updated_at`
   changed) is never re-examined, closing the "post something innocuous,
   edit in the command later" gap.

**Fetching comments newest-first (orchestrator review, B1):** GitHub's
`issues/comments` endpoint defaults to oldest-first with no `sort`/
`direction` given, so a plain fetch would return the same 100 oldest
comments in the repository's history forever on anything but a brand-new
repo - any real trigger comment would never be seen. `poll-triggers` fetches
`sort=created&direction=desc` and paginates forward only until it reaches a
comment id already recorded as processed (everything after that point, in
descending order, is necessarily already known), capped at 20 pages as a
sanity bound.

**R4's credential-vs-decision distinction, stated here as well as in the
review:** `user.login == owner.login` proves the comment was posted through
the *owner's credential*. It does not prove a human personally decided to
trigger the run. Fleet sessions acting for the owner post through that same
credential and are an accepted source of trigger comments - the VM's
isolation (not an assumption that only a human types the command) is what
makes that acceptable.

## Rollback

```
systemctl disable --now skillc-real-docker.timer
```
Revoke the fine-grained token from GitHub's token settings; delete the
local token file. Nothing on the main Woodpecker server or in
`cooneycw/skillc`'s branch protection needs touching - this design never
registered anything there.

## Lock contention (S1)

`run-real-docker` waits up to `LOCK_WAIT_SECONDS` (default 240s, comfortably
inside the 5-minute timer interval) for the lock rather than failing
immediately - a non-blocking lock would let a manual run's hold on it cause
a timer-decided sha to be silently marked done without ever running.
Exit code 3 means the lock was never acquired at all (the run never
started); `poll-triggers` checks for exactly this code and does NOT persist
that sha/comment as processed, so it is retried on the next tick. Exit
codes 0/1/2 (SUCCESS/FAILURE/ERROR) all mean a run actually happened and
reported something, and ARE persisted.

## Known simplifications (stated, not hidden)

- The bash scripts (`run-real-docker`, `poll-triggers`) are reviewed and
  syntax-checked (`bash -n`), and their embedded Python decision logic has
  been exercised directly against sample data, but the scripts **as whole
  processes are not exercised end-to-end here** - this sandbox has no real
  Docker daemon or GitHub token to run them against, the same honest
  limitation `ci/docker-tests-control.sh`'s absent `good-all-ran.xml`
  already states for a different control. Steps 7-8 above are how the
  operator closes that gap on the real host.
- `poll-triggers`' pagination cap (20 pages, 2000 comments) bounds a
  first-ever run against a repository with a very large, entirely
  unprocessed comment history; ordinary ticks stop within one page once
  they reach an already-processed id.
