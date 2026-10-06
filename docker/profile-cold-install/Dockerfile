# The cold-container-install proof's image (#266 acceptance item 2).
#
# Pre-warms a `uv` package cache from the PINNED CPP lockfile at
# image-build time (network available here), so the per-test-run container
# can `uv sync --locked` completely offline, `--network none`, with zero
# bind mounts. The cache is built ONLY from the lockfile baked into this
# image - never a live fetch at test-run time - and that lockfile's own
# sha256 is recorded as an image label (`org.skillc.coldinstall.
# lockfile_sha256`), passed in as a build arg computed by the caller BEFORE
# `docker build` runs. The live test asserts this label equals the sha256
# of the uv.lock it is actually installing from at run time: that is the
# check that makes "the cache is what makes this work" a provable claim
# rather than an assumption, and what `coldinstall:cold-cache` (an image
# built WITHOUT this layer) exists to falsify.
#
# Deliberately NOT docker/trial/Dockerfile or the `skillc-trial` tag -
# that image and tag belong to #237's own live-trial study (#305's stated
# exclusion, confirmed again for #266 by the orchestrator).
#
# What this image proves at BUILD time: the pinned `uv` binary installs
# and the cache layer populates from the declared lockfile. Whether the
# INSTALLED PROFILE (copied in per test run via `docker cp`, never baked
# in here - a baked-in installed home would be a SHARED seed across every
# test run, the same hazard docker/trial/Dockerfile's own comment names
# for its seed content) runs its gate helper against the real lib.cicd
# runner is the live test's job, not this image's.
FROM python:3.12-slim

# Pinned uv binary - astral's documented multi-stage copy, no network
# needed for this layer. Bump this version deliberately, never silently;
# a moving `uv` would make "the same lockfile produces the same cache"
# untestable.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

# The pinned CPP lockfile/pyproject, copied in at BUILD time (network
# available then) - never fetched or resolved inside the --network-none
# test container. This is the SAME pin the #287 study runs against
# (evals/subjects/cpp-codex-flow-check-ea6dbfa/, CPP ea6dbfa) - the build
# caller supplies these two files from that fixture, verbatim, never a
# separately-maintained copy that could drift from it.
COPY pyproject.toml uv.lock /cache-src/

# Populates uv's package cache (~/.cache/uv) from THIS lockfile only.
# --no-install-project: there is no project source here to install, only
# dependencies to resolve and cache - the throwaway .venv this creates is
# discarded with the build context; only the populated cache persists into
# the image layer. --locked refuses silently if pyproject.toml and
# uv.lock disagree, the same guarantee the offline run-time sync will also
# need to hold.
RUN cd /cache-src && uv sync --locked --no-install-project

# Recorded so the live test can confirm, AT RUN TIME, that the cache this
# image carries was built from the SAME lockfile it is about to install
# from - never a label that merely claims to describe the image without
# the test ever reading it back. The build caller computes this from the
# pinned uv.lock's own sha256sum BEFORE calling `docker build` (see
# docker/profile-cold-install/README.md), so there is exactly one place
# that lockfile's digest is computed, never a value hand-typed here.
ARG CPP_LOCKFILE_SHA256
LABEL org.skillc.coldinstall.lockfile_sha256="${CPP_LOCKFILE_SHA256}"

# No fixed WORKDIR/USER here: the test copies a disposable installed home
# in per run (via `docker cp`, never a bind mount) and decides the run
# user/home itself, matching #266's own "nothing borrowed from the host"
# constraint - baking in a user here would make this image's identity a
# silent input to that decision instead of the test's own explicit one.
