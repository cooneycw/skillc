#!/bin/sh
# P6 (#797 Contract A for container roots): `docker rm` unlinks the overlay
# upper directory object, read through a held fd. Even a 0 here is
# ABSENT_UNLINKED (VM disk, not erased), which the owner ruled never releases
# (Q1). This probe records the mechanism, not a release path.
# ROOT REQUIRED. TOUCHES DOCKER.
# Storage: overlay2, or the containerd image store's overlayfs snapshotter
# (lib.sh, "Container storage"). Each container runs so its upper directory
# can be read from the kernel and proven to be its own by a marker. Under the
# containerd store, a SURVIVOR on `removed` can mean the snapshot is removed
# later by garbage collection: that is a finding, not a script error.
# Usage: p6.sh --image-id sha256:<64 hex> --runner-unit <unit>
#
# Arms and expected verdicts:
#   removed  held upper dir: positive baseline, then 0 after a
#            checked and verified `docker rm`                CONFIRMED_NEGATIVE
#   kept     a twin that is not removed stays positive       SURVIVOR_OBSERVED
#   fault    a removal that fails, read through an fd closed
#            beforehand, must not read as removed            OBSERVATION_FAILED
set -eu
PROBE_NAME=p6
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

nlink_of_fd() {
    stat -L -c %h "/proc/$$/fd/$1" 2>/dev/null || printf 'ERR\n'
}

observe() {
    require_root
    require_runner_idle
    require_image
    require_overlay_storage
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"

    create_container --log-driver none -- "$PROBE_IMAGE_ID" sleep 120
    c1=$cid
    docker start "$c1" >/dev/null || probe_die 'start-failed'
    # Held on fd 9 before it is proven; nlink is read through that handle.
    upper_dir_of "$c1" 9
    record removed baseline "$(nlink_of_fd 9)"
    if docker rm -f -v "$c1" >/dev/null && container_absent "$c1"; then
        record removed rm_ok 1
    else
        record removed rm_ok 0
    fi
    record removed after "$(nlink_of_fd 9)"
    exec 9<&-

    create_container --log-driver none -- "$PROBE_IMAGE_ID" sleep 120
    c2=$cid
    docker start "$c2" >/dev/null || probe_die 'start-failed'
    upper_dir_of "$c2" 8
    record kept baseline "$(nlink_of_fd 8)"
    record kept rm_ok 1
    record kept after "$(nlink_of_fd 8)"
    exec 8<&-

    # Fault: removing an ID this probe never created fails; fd 7 is closed
    # explicitly so an inherited descriptor cannot answer for it.
    exec 7<&-
    absent_id=$(probe_uuid)$(probe_uuid)
    if docker rm "$absent_id" >/dev/null 2>&1; then record fault rm_ok 1; else record fault rm_ok 0; fi
    record fault baseline "$(nlink_of_fd 7)"
    record fault after "$(nlink_of_fd 7)"
    recheck_runner
}

verdict() {
    b=$(rd_uint "$1" baseline) || { printf '%s\n' "$PROBE_FAIL"; return; }
    ok=$(rd_bool "$1" rm_ok) || { printf '%s\n' "$PROBE_FAIL"; return; }
    a=$(rd_uint "$1" after) || { printf '%s\n' "$PROBE_FAIL"; return; }
    # A failed removal, or a held dir that never had a positive link count, is
    # not evidence of anything.
    if [ "$ok" -ne 1 ] || [ "$b" -lt 1 ]; then printf '%s\n' "$PROBE_FAIL"; return; fi
    if [ "$a" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

classify() {
    arm removed "$PROBE_NEG" "$(verdict removed)"
    arm kept "$PROBE_SURV" "$(verdict kept)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
