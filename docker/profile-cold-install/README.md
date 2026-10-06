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

The caller computes the pinned lockfile's own sha256 and passes it as a
build arg - there is exactly one place that digest is computed, never a
value hand-typed into the `Dockerfile`:

```bash
FIXTURE_DIR=tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa
SHA256="$(sha256sum "$FIXTURE_DIR/uv.lock" | cut -d' ' -f1)"
docker build \
    --build-arg "CPP_LOCKFILE_SHA256=$SHA256" \
    -f docker/profile-cold-install/Dockerfile \
    -t skillc-coldinstall:latest \
    "$FIXTURE_DIR"
```

The fixture directory itself is the build context, so the `Dockerfile`'s
`COPY pyproject.toml uv.lock /cache-src/` reaches exactly those two pinned
files and nothing else in the fixture tree.

(The live test builds this programmatically rather than by hand; the
invocation above is for an operator rebuilding or inspecting the image
directly.)

## The cache-freshness check

The live test asserts, at container RUN time, that the image's
`org.skillc.coldinstall.lockfile_sha256` label equals the sha256 of the
`uv.lock` inside the disposable installed home it just `docker cp`'d in -
proving the cache the offline `uv sync` is about to use was actually built
from the SAME lockfile it is installing from, never a stale cache
surviving a pin move. `coldinstall:cold-cache` (a break mode, see
`ci/real-docker/break-lib.sh`) runs the SAME test against an image built
WITHOUT the warm cache layer, where the offline sync must fail - the
negative control proving the cache is what makes the intact run work, not
merely present and unused.

## The claim's exact boundary

This proves an OFFLINE install from a pin-matched cache. It does not
prove, and does not claim to prove, how a live trial container (which
needs the network, for the model API) behaves - that remains #237's own
path, unchanged by this issue.
