# Trial image (issue #78, Refs #10): the environment a live agent runs inside
# during a Docker-backed trial. Built and tested against the operating
# lessons recorded on #10 (sections A and B): a wedged first run and a
# missing Codex sidecar both look identical to a healthy container, so this
# image exists to make those failures visible at BUILD time rather than as a
# silent, gradeable no-op inside a trial.
#
# What is proven here (build-time, no live agent): the pinned CLIs install,
# codex-code-mode-host lands beside codex, no docker binary is present, and
# an unprivileged trial user exists. Whether the real CLI starts un-wedged
# inside this image is owed to the live run (#10's evidence rule) - that
# needs skillc/trial_bootstrap.py's seed and MCP config, composed per trial,
# never baked into the image.
#
# Base pinned by tag; digest pinning happens at BUILD time (see README.md's
# "Provenance" section) because a moving base tag is a build input, not an
# identity claim - the identity claim is the digest of the image that RAN,
# recorded after this build completes.
FROM node:22-bookworm-slim AS base

# Bump these together with docker/trial/pinned-versions.json - never
# '@latest'. docker/trial/check_pins.py fails the check when they drift
# apart, without needing Docker to run.
ARG CLAUDE_CODE_VERSION=2.1.283
ARG CODEX_VERSION=0.157.1

# Issue #343: the `cpp-codex-flow-check-ea6dbfa` profile declares `tool-uv`
# and `tool-make-git-bash` as tool dependencies the TRIAL IMAGE supplies
# (profile.json's own "supply" field for both), so without this pin every
# profile-opted live attempt is refused at preflight once #334 wires that
# check in. Same pin docker/profile-cold-install/Dockerfile already
# reviewed and uses - reused rather than independently chosen, so the two
# images never silently carry different uv versions.
ARG UV_VERSION=0.9.7

# apt mirrors fail transiently (#10 lesson D15). Retry a bounded number of
# times before giving up, so CI turns red for a real build problem, not a
# flaky mirror.
#
# `python3` (the full package, not `python3-minimal`): `skillc.verify`'s own
# probe interpreter and `skillc.demo`'s scripted lifecycle subject both run
# as `python3` inside this container (issue #81) - the base image is
# node:22-bookworm-slim, so nothing installs it otherwise, and every check
# before this one ran against the fake `docker` CLI, which never looks
# inside an image and so never caught its absence. `python3-minimal` was
# considered - its stdlib subset excludes some modules the probe or a future
# subject could reasonably need, and this session has no real daemon
# available to verify against, so the full package is the safe default
# rather than a guess. `docker/trial/check_interpreters.py` is the committed,
# no-daemon control that catches a regression here without building the
# image.
#
# `make` and `bash` explicit (issue #343): `cpp-codex-flow-check-ea6dbfa`'s
# gate is `make` targets, and `flow-finish-gate.sh`'s own shebang and every
# other helper it sources need `bash`, not merely a POSIX `/bin/sh` - both
# declared as the subject's own `tool-make-git-bash` dependency (`git` is
# already installed above). `bash` is very likely present transitively
# already (Debian's own base utilities), but the issue wants it an
# explicit, visible dependency of THIS image, not an accident of whatever
# the base image happens to carry. `docker/trial/check_interpreters.py`
# does NOT cover this line - it is deliberately scoped to
# `skillc.verify.PROBE_INTERPRETER` only, a different population for a
# different reason (what skillc's OWN demo/verifier invoke, not what the
# SUBJECT's profile declares) - `tests/test_trial_image_tools_live.py`'s
# real-Docker probes are this line's actual proof.
RUN set -eu; \
    n=0; \
    until apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        python3 \
        make \
        bash \
    ; do \
        n=$((n + 1)); \
        if [ "$n" -ge 5 ]; then \
            echo "apt-get failed after $n attempts" >&2; \
            exit 1; \
        fi; \
        echo "apt-get attempt $n failed, retrying..." >&2; \
        sleep $((n * 2)); \
    done; \
    rm -rf /var/lib/apt/lists/*

# Pinned, exact-version installs - never a bare 'npm install -g <pkg>', which
# resolves '@latest' and reintroduces the #10 lesson D14 auto-update hazard
# (an updater changing the CLI underneath a running session).
RUN npm install -g \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
        "@openai/codex@${CODEX_VERSION}"

# #10 lesson A2: Codex's tool calls go through codex-code-mode-host, spawned
# beside the REAL native codex executable. Installing only 'codex' silently
# degrades to fluent prose with zero tool calls and a still-green
# 'codex doctor'. Fail the BUILD, never the trial, when the sidecar is
# missing. verify_codex_sidecar.js resolves the native binary the SAME way
# codex.js's own launcher does (through the platform-specific
# @openai/codex-<platform>-<arch> package's vendor/<target-triple>/bin/
# directory) - a Codex code-review finding on issue #78 caught an earlier
# version of this check searching beside the npm wrapper script instead,
# which is the wrong directory entirely and would have rejected a correctly
# installed sidecar while accepting a same-named directory in the wrong
# place.
COPY verify_codex_sidecar.js /tmp/verify_codex_sidecar.js
RUN node /tmp/verify_codex_sidecar.js && rm /tmp/verify_codex_sidecar.js

# Codex sandboxing decision (#10 lesson A3), recorded here and mirrored in
# skillc/trial_bootstrap.py's BWRAP_DECISION for #77's describe() to report:
# this image does NOT install bubblewrap. 'codex exec --sandbox
# workspace-write' needs bwrap plus user namespaces, which are commonly
# unavailable or double-nested inside a container runtime's own container -
# and #10's own container IS the isolation boundary (skillc/backend.py:
# "neutral identity is a backend obligation"; the trial has no host
# filesystem or credentials in reach to sandbox further against). Running
# Codex unsandboxed (danger-full-access) here does not widen what the trial
# can reach - the container already bounds that - it only removes a nested
# sandbox that would otherwise silently swallow every shell command (D3's
# measured failure: same prompt, same image, exit 0, nothing written).
#
# Deliberately NOT: `RUN apt-get install -y bubblewrap`.

# No docker binary, ever (#10 lesson C12: anything that can reach the daemon
# is root on the host, and ':ro' on the socket changes nothing). Fail the
# build if some transitive dependency ever drags one in.
RUN set -eu; \
    if command -v docker >/dev/null 2>&1; then \
        echo "docker binary present in trial image - this must never happen" >&2; \
        exit 1; \
    fi

# Fixed, non-host identity, and the image must NOT depend on running as any
# OTHER uid (owner ruling, 2026-09-26, on this exact tradeoff): a bind mount
# owned by the host caller's real uid was considered and rejected, because
# hiding the number from describe() does not stop the CONTAINER's own `id`,
# file listings and transcripts from carrying it - and transcripts are
# evidence. 'candidate'/10001:10001 get a real passwd/group entry (some
# tools resolve HOME via a passwd lookup, not $HOME alone, so the entry must
# exist and match) and are logical values, never this operator's own.
RUN groupadd --gid 10001 candidate \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin candidate

# ~/.claude and ~/.codex are pre-created here, empty and owned by candidate -
# the per-trial SEED CONTENT (skillc/trial_bootstrap.py's composed
# ~/.claude.json and MCP config) is never baked into the image and arrives
# per trial instead, copied in (docker cp / a tar stream, the preferred
# design) or, as a documented fallback, via a per-trial directory the
# controller makes writable for 10001 only. A baked-in .claude.json would be
# a SHARED seed across every trial, exactly what issue #78 forbids - only
# the empty, owned directories are baked in, never their contents.
RUN mkdir -p /home/candidate/.claude /home/candidate/.codex \
    && chown -R candidate:candidate /home/candidate

# #183's subject-side client for the decide-and-reply channel - "the
# required tool" evals/level5/recovery-partial-processing/goal.md tells
# the subject may become unavailable. Installed root-owned, world-
# executable (the same convention a system binary under /usr/local/bin
# already uses, matching SKILLC_WRAP_PATH's own /usr/local/bin/skillc-wrap
# for the SAME reason: candidate never needs write access to its own
# tool). The source's own docstring is the contract; this stanza only
# places it. docker/trial/check_helpers.py proves this line exists
# without needing a daemon to build the image and check it.
COPY skillc-disrupt-tool.py /usr/local/bin/skillc-disrupt-tool
RUN chmod 755 /usr/local/bin/skillc-disrupt-tool

# #332's flow-check gate-witness shim - staged here, NOT at the path the
# subject actually invokes (~/.claude/scripts/flow-finish-gate.sh): that
# path is owned by whatever installs the real pinned script per-attempt,
# and skillc.gate_overlay.apply_flow_check_gate_overlay() reads this
# staged copy's CONTENT (via export(), never by executing it here) and
# writes it to the subject path itself, after moving the real script
# aside - the LAST step of a live attempt's setup, never baked directly
# into the subject-visible path. Still made executable at this staging
# path too, for the same reason every other helper in this image is -
# docker/trial/check_helpers.py proves this line exists without needing
# a daemon to build the image and check it.
COPY flow-check-gate-shim.py /usr/local/share/skillc/flow-check-gate-shim.py
RUN chmod 755 /usr/local/share/skillc/flow-check-gate-shim.py

# TWO NAMED STAGES from here (issue #343), the same pattern
# docker/profile-cold-install/Dockerfile already uses for its own
# cached/uncached split: one `base` with everything common, branching only
# on the ONE layer under test. `no-uv` is the `trialimage:no-uv` break
# mode's own negative control - built explicitly with `--target no-uv`,
# never the default - and must come FIRST in the file: Docker's own
# "no --target means the LAST stage" rule means whichever stage is named
# last here is what every EXISTING caller that builds this Dockerfile
# without `--target` (`tests/test_trial_image_build_live.py`, today's
# backend) gets, and that must stay the full, working trial image,
# unchanged by this issue - never the deliberately broken one.
FROM base AS no-uv

# Deliberately NOTHING here. No uv binary at all - a `uv --version` probe
# against a container from THIS stage must fail, the trialimage:no-uv red
# case `tests/test_trial_image_tools_live.py` asserts.

USER candidate
WORKDIR /work

LABEL org.skillc.image=trial-image

FROM base AS trial

# Pinned uv binary - astral's documented multi-stage copy, the same exact
# pin docker/profile-cold-install/Dockerfile already uses. `ARG` must be
# re-declared here: Docker clears every ARG value at each new `FROM`, so
# the default set on `base` is not visible in THIS stage without this line
# (docker/trial/check_pins.py scans for the ORIGINAL `ARG UV_VERSION=...`
# default above, on `base`, and is unaffected by this bare re-declaration).
ARG UV_VERSION
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /usr/local/bin/

USER candidate
WORKDIR /work

LABEL org.skillc.image=trial-image
