# The cold-container-install proof's image (#266 acceptance item 2).
#
# Pre-warms a `uv` package cache from the PINNED CPP lockfile at
# image-build time (network available here), so the per-test-run container
# can `uv sync --locked --offline` using ONLY that cache, `--network none`,
# with zero bind mounts. The cache is built ONLY from the lockfile baked
# into this image - never a live fetch at test-run time.
#
# TWO NAMED STAGES, not one Dockerfile plus a hand-edited variant: `cached`
# (the normal image - plain `docker build` with no `--target` lands here,
# because it is the LAST stage) and `uncached` (the `coldinstall:cold-
# cache` break mode's negative control - built with `--target uncached`,
# carrying no cache layer at all, so the offline sync has nothing to use).
# Two stages sharing one `base` means the only difference between the
# intact image and its own negative control is the ONE layer under test,
# never a second file that could drift from the first by hand.
#
# The lockfile's sha256 is computed INSIDE THIS IMAGE, in the SAME layer
# that populates the cache (orchestrator review) - never taken from a
# caller-supplied build arg. A build-arg-sourced label would prove only
# what the CALLER claimed the lockfile's digest was, not what the cache
# layer was actually built from; a wrong or stale arg would pass the
# run-time check against a cache that does not match it. The live test
# reads `/opt/skillc-coldinstall/lockfile.sha256` at run time and compares
# it against the digest of the `uv.lock` it is actually installing from -
# that is the check that makes "the cache is what makes this work" a
# provable claim rather than an assumption.
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

FROM python:3.12-slim AS base

# Pinned uv binary - astral's documented multi-stage copy, no network
# needed for this layer. Bump this version deliberately, never silently;
# a moving `uv` would make "the same lockfile produces the same cache"
# untestable.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

# FIXED, non-HOME-relative cache path (orchestrator review): the run
# container's user/HOME is decided by the disposable installed home that
# arrives via `docker cp` at test-run time, not by this image, so a
# default `~/.cache/uv` would land somewhere the run-time process cannot
# predict or rely on. Baked as an image ENV, so it is inherited
# automatically by any process in any container started from this image -
# build time (populating it below, in the `cached` stage only) and run
# time (reading it with `--offline`) alike, with no extra `-e` needed at
# `docker run`. Declaring it here, in `base`, means BOTH stages agree on
# the path - `uncached` simply never populates anything at it.
ENV UV_CACHE_DIR=/opt/skillc-coldinstall/uv-cache

# The pinned CPP lockfile/pyproject, copied in at BUILD time (network
# available then) - never fetched or resolved inside the --network-none
# test container. This is the SAME pin the #287 study runs against
# (evals/subjects/cpp-codex-flow-check-ea6dbfa/, CPP ea6dbfa) - the build
# caller supplies these two files from that fixture, verbatim, never a
# separately-maintained copy that could drift from it.
COPY pyproject.toml uv.lock /cache-src/

FROM base AS cached

# Populates the cache at the fixed path above, from THIS lockfile only,
# and computes the lockfile's own sha256 IN THE SAME LAYER (orchestrator
# review - see the module docstring for why this must not come from a
# build arg instead). --no-install-project: there is no project source
# here to install, only dependencies to resolve and cache - the throwaway
# .venv this creates is discarded with the build context; only the
# populated cache and the digest file persist into the image layer.
# --locked refuses silently if pyproject.toml and uv.lock disagree, the
# same guarantee the offline run-time sync will also need to hold.
#
# World-readable (never writable) at the end: the run-time user is
# whatever the disposable installed home's own ownership dictates, not
# necessarily the root uid this build runs as, and --offline only needs
# to READ the cache - it must never need a UID match with the build.
RUN cd /cache-src \
    && uv sync --locked --no-install-project \
    && mkdir -p /opt/skillc-coldinstall \
    && sha256sum uv.lock | cut -d' ' -f1 > /opt/skillc-coldinstall/lockfile.sha256 \
    && chmod -R a+rX /opt/skillc-coldinstall

FROM base AS uncached

# Deliberately NOTHING here. This stage is the `coldinstall:cold-cache`
# break mode's whole point: no /opt/skillc-coldinstall/uv-cache, no
# lockfile.sha256 - an offline `uv sync` against this image has no cache
# to use at all, and must fail at uv's own resolution step, naming the
# missing distribution.

# No fixed WORKDIR/USER on either stage: the test copies a disposable
# installed home in per run (via `docker cp`, never a bind mount) and
# decides the run user/home itself, matching #266's own "nothing borrowed
# from the host" constraint - baking in a user here would make this
# image's identity a silent input to that decision instead of the test's
# own explicit one.
