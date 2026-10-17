#!/bin/bash
# Run-scoped cleanup for run-real-docker (#414). Sourced, never executed.
#
# The runner used to end every run with `docker container prune -f` and
# `docker image prune -f`. Those are HOST-WIDE: the image prune deleted every
# untagged image on the VM, including campaign images `build.py` built and
# receipts name only by ID, so any timer tick broke the next receipt-driven
# campaign. A run now removes only what it created, and that is decided by
# two facts together, never one:
#
#   - a skillc label: `skillc.managed=true` on containers (DockerBackend sets
#     it), `org.skillc.image` on images (docker/trial/Dockerfile sets it);
#   - absence from the snapshot taken before this run started.
#
# A label alone is not ownership: build.py's output builds FROM the trial
# stage and inherits `org.skillc.image`, and a co-tenant campaign's stopped
# DockerBackend containers carry `skillc.managed=true` too. run.lock already
# serialises runner runs against campaigns, so "created during this run" is
# well defined - and ONLY under that lock: a caller without it, on a shared
# daemon, could remove a neighbour's artifacts created in the same window.
# That is why tests/test_real_docker_cleanup_live.py runs only under the
# runner (SKILLC_REAL_DOCKER_RUN_LOCK_HELD=1).
#
# Only DANGLING images and STOPPED containers are candidates, removed without
# `-f` and with `--no-prune`: a tagged image, anything still in use, and an
# untagged parent of a removed image are all left alone.

SNAPSHOT_SENTINEL="#snapshot-complete"

# snapshot_runner_artifacts FILE - every image ID and container ID present
# now, one per line, ending in SNAPSHOT_SENTINEL. When either listing fails
# the file is left WITHOUT the sentinel, and remove_runner_artifacts then
# removes nothing: an incomplete snapshot would make everything look new.
snapshot_runner_artifacts() {
    local file="$1" images containers
    if images="$(docker images -aq --no-trunc)" && containers="$(docker ps -aq --no-trunc)"; then
        printf '%s\n' "$images" "$containers" "$SNAPSHOT_SENTINEL" > "$file"
    else
        : > "$file"
        echo "run-real-docker: WARNING: could not snapshot images/containers; this run's cleanup will remove nothing" >&2
    fi
}

# remove_runner_artifacts FILE - remove the stopped skillc-managed containers
# and the dangling org.skillc.image images that are NOT in the snapshot.
remove_runner_artifacts() {
    local file="$1" ids id
    if ! grep -qxF "$SNAPSHOT_SENTINEL" "$file" 2>/dev/null; then
        echo "run-real-docker: cleanup skipped: no complete pre-run snapshot" >&2
        return 0
    fi
    if ids="$(docker ps -aq --no-trunc --filter label=skillc.managed=true \
            --filter status=exited --filter status=dead --filter status=created)"; then
        for id in $ids; do
            grep -qxF "$id" "$file" || docker rm "$id" >/dev/null 2>&1 || true
        done
    fi
    if ids="$(docker images -q --no-trunc --filter dangling=true --filter label=org.skillc.image)"; then
        for id in $ids; do
            # --no-prune: a removed image's untagged PARENTS would otherwise go
            # with it, including one that predates this run (#414 review).
            grep -qxF "$id" "$file" || docker image rm --no-prune "$id" >/dev/null 2>&1 || true
        done
    fi
    return 0
}
