#!/bin/sh
# P5 (#797 section 2.2): a controller-owned host tmpfs, directory-bind-mounted
# as a container's home, leaves nothing in the overlay upper directory and
# survives the container's removal. ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p5.sh --image-id sha256:<64 hex> --runner-unit <unit>
# Refuses while the runner unit is active. Container uid: PROBE_USER (1000:1000).
#
# Arms and expected verdicts:
#   clean     host-tmpfs write absent from the upper dir and
#             still on the host tmpfs after `docker rm`      CONFIRMED_NEGATIVE
#   survivor  a write to the container root filesystem is
#             present in the upper dir                       SURVIVOR_OBSERVED
#   fault     the same search over an absent upper dir       OBSERVATION_FAILED
set -eu
PROBE_NAME=p5
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# count_found DIR FIND-ARGS...: prints the number of matches, or ERR when the
# search itself failed (any find error, including an unreadable subtree).
count_found() {
    _dir=$1
    shift
    if _out=$(find "$_dir" "$@" -print 2>/dev/null); then
        printf '%s\n' "$_out" | awk 'NF > 0 { c++ } END { print c + 0 }'
    else
        printf 'ERR\n'
    fi
}

observe() {
    require_root
    require_runner_idle
    require_image
    require_overlay2
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    name="skillc-dev-probe-p5-$$"
    home="$PROBE_SCRATCH/home"
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        docker rm -f "$name" >/dev/null 2>&1 || true
        if mountpoint -q "$home" 2>/dev/null; then umount "$home" || true; fi
        scratch_remove
    }
    trap cleanup EXIT
    mkdir -p "$home"
    mount -t tmpfs -o size=1m,mode=0700 skillc-dev-probe "$home" || probe_die 'mount-failed'
    chown "${PROBE_USER:-1000:1000}" "$home" || probe_die 'chown-failed'
    docker create --name "$name" --user "${PROBE_USER:-1000:1000}" \
        --mount "type=bind,source=$home,target=/probe-home" \
        -- "$PROBE_IMAGE_ID" sh -c \
        'echo skillc-dev-marker > /probe-home/t && echo skillc-dev-marker > /tmp/probe-disk' \
        >/dev/null || probe_die 'create-failed'
    # Foreground start: returns only after the writes finished, with their status.
    docker start -a "$name" >/dev/null || probe_die 'container-writes-failed'
    up=$(docker inspect --format '{{.GraphDriver.Data.UpperDir}}' "$name") || probe_die 'inspect-failed'
    [ -d "$up" ] || probe_die 'upperdir-missing'
    record clean tmpfs_in_upper "$(count_found "$up" -path '*/probe-home/t')"
    record survivor disk_in_upper "$(count_found "$up" -name probe-disk)"
    record fault disk_in_upper "$(count_found "$PROBE_SCRATCH/absent-upper" -name probe-disk)"
    docker rm "$name" >/dev/null || probe_die 'rm-failed'
    if [ -f "$home/t" ]; then record clean host_present 1; else record clean host_present 0; fi
}

v_clean() {
    n=$(rd_uint clean tmpfs_in_upper) || { printf '%s\n' "$PROBE_FAIL"; return; }
    p=$(rd_uint clean host_present) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$n" -gt 0 ]; then printf '%s\n' "$PROBE_SURV"; return; fi
    # Absent from the upper dir is only meaningful if the write really landed.
    if [ "$p" -eq 1 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_FAIL"; fi
}

v_disk() {
    n=$(rd_uint "$1" disk_in_upper) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$n" -gt 0 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$PROBE_NEG"; fi
}

classify() {
    arm clean "$PROBE_NEG" "$(v_clean)"
    arm survivor "$PROBE_SURV" "$(v_disk survivor)"
    arm fault "$PROBE_FAIL" "$(v_disk fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
