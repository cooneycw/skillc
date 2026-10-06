# The `<agent-host>` real-Docker runner (#315)

Certifies #183 (and, once they exist, #266/#269 - see `check_real_docker_ran.
DECLARED_REAL_DOCKER_FILES`) against a REAL Docker daemon, on an isolated VM,
with no Woodpecker involved at all. The main Woodpecker server is untouched;
nothing here registers anything with it.

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
7. **Isolation verification, before enabling anything (R6):**
   - With the hypervisor-level firewall OFF: run
     `ci/real-docker/run-real-docker <any-sha>` by hand and confirm it
     refuses with "isolation not verified" (posts `error`, runs no tests).
   - With it ON: run the same command and confirm it proceeds past the
     preflight.
   - **Record both outcomes on this issue**, generically (no addresses) -
     this is the committed evidence that the detector actually detects
     something, on this specific host, not only in the unit tests.
8. **#183 break-mode verification (R2):**
   ```
   run-real-docker <post-#300-main-sha> --break none            # expect SUCCESS
   run-real-docker <post-#300-main-sha> --break omit-mount       # expect FAILURE
   run-real-docker <post-#300-main-sha> --break wrong-uid        # expect FAILURE
   run-real-docker <post-#300-main-sha> --break flip-decision    # expect FAILURE
   ```
   Break-mode runs post only to `skillc/real-docker-control`
   (never the certifying `skillc/real-docker` context) and are labelled
   EXPECTED-RED. Record the four results on this issue.
9. `systemctl enable --now skillc-real-docker.timer`.

## `config.env` template

```bash
INSTALLED_ROOT=/opt/skillc-real-docker-runner
WORK_CHECKOUT=/var/lib/skillc-real-docker/checkout
LOCK_FILE=/var/lib/skillc-real-docker/run.lock
STATE_FILE=/var/lib/skillc-real-docker/state.json
GITHUB_TOKEN_FILE=/etc/skillc-real-docker/github-token   # mode 600
GITHUB_REPO=cooneycw/skillc
GITHUB_COMMENT_ISSUE=                                    # optional; an issue/PR number to also comment on
LAN_PROBE_TARGET=                                        # the LAN target to probe FROM INSIDE a throwaway
                                                           # container - VM-local, never committed; see R6
PREFLIGHT_IMAGE=alpine:3                                 # any small image with wget
```

## Token

A fine-grained GitHub PAT scoped to `cooneycw/skillc` only:
`Commit statuses: write`, `Issues and pull requests: write` (the second
also covers reading comments, needed for the trigger poll). Stored at
`GITHUB_TOKEN_FILE`, `chmod 600`, read once per run, never logged.

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
  policy for forwarded container traffic entirely.

**The preflight (`run-real-docker`'s first step, before any checkout) is a
DETECTOR, not a proof.** From inside a throwaway container it probes the
configured LAN target (must fail) and `github.com` (must succeed, the
probe's own positive control). A passing result means "the LAN was
unreachable from this container right now" - never "isolation is proven."
`ci/real_docker_isolation.py` is the pure classifier; its tests
(`tests/test_real_docker_isolation.py`) cover all three refusal reasons
plus the one proceed case, with a mutation check.

## Trigger mechanism (R3 + R4)

Two sources, both run with `--break none` only - break-mode runs are a
by-hand operator action (step 8 above), never reachable automatically:

1. **New commits on main.** Already reviewed and merged code - never
   arbitrary PR code.
2. **An explicit `/run-real-docker <sha>` comment**, author checked against
   the repository's own `owner.login` (fetched fresh each poll), never the
   comment's own text. `ci/real_docker_trigger.py` processes each comment
   id exactly once, at first sight - an edit to an old comment (which the
   GitHub API resurfaces because `updated_at` changed) is never
   re-examined, closing the "post something innocuous, edit in the command
   later" gap.

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

## Known simplifications (stated, not hidden)

- `poll-triggers` reads at most 100 recent issue comments per tick
  (`per_page=100`, no pagination) - adequate for this repo's current
  comment volume; revisit if it ever becomes a real limit.
- The bash scripts (`run-real-docker`, `poll-triggers`) are reviewed and
  syntax-checked (`bash -n`) but **not exercised end-to-end here** - this
  sandbox has no real Docker daemon or GitHub token to run them against,
  the same honest limitation `ci/docker-tests-control.sh`'s absent
  `good-all-ran.xml` already states for a different control. Steps 7-8
  above are how the operator closes that gap on the real host.
