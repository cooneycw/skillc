# The cold-container-install proof's image (issue #266)

## What this directory is

The image `tests/test_profile_install_cold_container_live.py` builds and
runs to prove acceptance item 2 of #266: a cold container running the
profile helper against a tiny project with no operator skill mount, home
mount, MCP mount, or secret mount. It is a purpose-built image for that
one proof, separate from `docker/trial/` (#237's live-trial study, a
different tag and a different claim).

## What is proven here vs. owed to the live test

This `Dockerfile` proves, at build time, that the pinned `uv` binary
installs and that a package cache populates from the declared pinned
lockfile. It proves nothing about the INSTALLED PROFILE: the disposable
installed home (produced by `skillc profile install` on the host, where
network is available to resolve the profile itself) is never baked into
this image - it arrives per test run via `docker cp`, exactly as #266
requires, matching `docker/trial/Dockerfile`'s own reasoning for why its
seed content is never baked in either. Whether that installed home's
`flow-finish-gate.sh` reaches the real `lib.cicd` runner inside a
`--network none` container with zero bind mounts is the live test's own
claim, not this image's.

## Building the image

Two named stages, built from the same `Dockerfile`:

```bash
FIXTURE_DIR=tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa

# The normal image - plain `docker build` lands on `cached` because it is
# the LAST stage, but naming it explicitly is clearer at the call site.
docker build --target cached \
    -f docker/profile-cold-install/Dockerfile \
    -t skillc-coldinstall:latest \
    "$FIXTURE_DIR"

# The cold-cache break mode's negative control: the SAME base, with no
# cache-populating layer at all.
docker build --target uncached \
    -f docker/profile-cold-install/Dockerfile \
    -t skillc-coldinstall-uncached:latest \
    "$FIXTURE_DIR"
```

The fixture directory itself is the build context, so the `Dockerfile`'s
`COPY pyproject.toml uv.lock /cache-src/` reaches exactly those two pinned
files and nothing else in the fixture tree. No build arg carries the
lockfile's digest - see "The cache-freshness check" below for why.

(The live test builds both programmatically rather than by hand; the
invocations above are for an operator rebuilding or inspecting either
image directly.)

## The cache-freshness check

`/opt/skillc-coldinstall/lockfile.sha256` is computed INSIDE the image,
in the same `RUN` layer that populates the cache - never taken from a
caller-supplied build arg. A build-arg-sourced value would prove only
what the build CALLER claimed the lockfile's digest was, not what the
cache layer was actually built from; a wrong or stale arg would pass a
run-time check against a cache that does not match it.

The live test reads that file at container RUN time and compares it
against the sha256 of the `uv.lock` inside the disposable installed home
it just `docker cp`'d in - proving the cache the offline `uv sync` is
about to use was actually built from the SAME lockfile it is installing
from, never a stale cache surviving a pin move.

At run time, the offline install uses `uv sync --locked --offline` -
`--offline` is load-bearing, not merely consistent with `--network none`:
without it, a missing cached package would fail only because the network
is blocked, which is true of EVERY run regardless of whether the cache
was ever warmed - `coldinstall:cold-cache` (a break mode, see
`ci/real-docker/break-lib.sh`, running the same test against the
`uncached` stage above) would then pass for the wrong reason. With
`--offline`, a missing distribution fails at `uv`'s own resolution step,
naming the missing package - that specific failure is what the
`cold-cache` mode's assertion checks for, not merely a non-zero exit.
`UV_CACHE_DIR` is baked into the image as a fixed, non-HOME-relative
path (`ENV`, inherited by every container from this image automatically)
so the run-time user - decided by the disposable installed home's own
ownership, not by this image - can still reach it.

## The claim's exact boundary

This proves an OFFLINE install from a pin-matched cache. It does not
prove, and does not claim to prove, how a live trial container (which
needs the network, for the model API) behaves - that remains #237's own
path, unchanged by this issue.
