#!/bin/sh
# P5 (#797 section 2.2): a controller-owned host tmpfs, directory-bind-mounted
# as a container's home, leaves nothing in the overlay upper directory and
# survives the container's removal. ROOT REQUIRED. TOUCHES DOCKER.
# Storage: overlay2, or the containerd image store's overlayfs snapshotter
# (lib.sh, "Container storage"). The upper directory is read from the kernel
# while the container runs, and proven to be this container's by a marker.
# Usage: p5.sh --image-id sha256:<64 hex> --runner-unit <unit>
# Refuses unless the runner unit exists and is inactive or failed, at start and
# again before verdicts. Container uid: PROBE_USER (default 1000:1000).
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
    require_overlay_storage
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    scratch_private
    home="$PROBE_SCRATCH/home"
    mount_tmpfs "$home"
    chown "${PROBE_USER:-1000:1000}" "$home" || probe_die 'chown-failed'
    # The container stays up, so its overlay root can be read from the kernel.
    create_container --user "${PROBE_USER:-1000:1000}" --log-driver none \
        --mount "type=bind,source=$home,target=/probe-home" \
        -- "$PROBE_IMAGE_ID" sleep 120
    docker start "$cid" >/dev/null || probe_die 'start-failed'
    # A random name, so a stale file in some other snapshot cannot match.
    disk=probe-disk-$(probe_uuid)
    # Foreground exec: returns only after the writes finished, with their status.
    _rc=0
    docker exec "$cid" sh -c \
        'echo skillc-dev-marker > /probe-home/t && echo skillc-dev-marker > "/tmp/$1"' \
        sh "$disk" 2>"$PROBE_SCRATCH/writes.err" || _rc=$?
    if [ "$_rc" -ne 0 ]; then
        step_diag setup writes "$_rc" "$PROBE_SCRATCH/writes.err"
        probe_die 'container-writes-failed'
    fi
    upper_dir_of "$cid"
    up=$PROBE_UPPER
    record clean tmpfs_in_upper "$(count_found "$up" -path '*/probe-home/t')"
    record survivor disk_in_upper "$(count_found "$up" -name "$disk")"
    record fault disk_in_upper "$(count_found "$PROBE_SCRATCH/absent-upper" -name "$disk")"
    docker rm -f -v "$cid" >/dev/null || probe_die 'rm-failed'
    container_absent "$cid" || probe_die 'rm-unverified'
    if [ -f "$home/t" ]; then record clean host_present 1; else record clean host_present 0; fi
    recheck_runner
}

v_clean() {
    n=$(rd_uint clean tmpfs_in_upper) || { printf '%s\n' "$PROBE_FAIL"; return; }
    p=$(rd_bool clean host_present) || { printf '%s\n' "$PROBE_FAIL"; return; }
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
