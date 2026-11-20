#!/bin/sh
# P6 (#797 Contract A for container roots): `docker rm` unlinks the overlay
# upper directory object, read through a held fd. Even a 0 here is
# ABSENT_UNLINKED (VM disk, not erased), which the owner ruled never releases
# (Q1); this probe records the mechanism, not a release path.
# ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p6.sh --image-id sha256:<64 hex> --runner-unit <unit>
#
# Arms and expected verdicts:
#   removed  held upper dir: positive baseline, then 0 after a
#            checked `docker rm`                         CONFIRMED_NEGATIVE
#   kept     a twin that is not removed stays positive   SURVIVOR_OBSERVED
#   fault    removal of a container that does not exist
#            must not read as removed                    OBSERVATION_FAILED
set -eu
PROBE_NAME=p6
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

nlink_of_fd() {
    stat -L -c %h "/proc/$$/fd/$1" 2>/dev/null || printf 'ERR\n'
}

upper_of() {
    docker inspect --format '{{.GraphDriver.Data.UpperDir}}' "$1"
}

observe() {
    require_root
    require_runner_idle
    require_image
    require_overlay2
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    c1="skillc-dev-probe-p6a-$$"
    c2="skillc-dev-probe-p6b-$$"
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        docker rm -f "$c1" "$c2" >/dev/null 2>&1 || true
        scratch_remove
    }
    trap cleanup EXIT

    docker create --name "$c1" -- "$PROBE_IMAGE_ID" true >/dev/null || probe_die 'create-failed'
    up1=$(upper_of "$c1") || probe_die 'inspect-failed'
    [ -d "$up1" ] || probe_die 'upperdir-missing'
    exec 9<"$up1"
    record removed baseline "$(nlink_of_fd 9)"
    if docker rm "$c1" >/dev/null; then record removed rm_ok 1; else record removed rm_ok 0; fi
    record removed after "$(nlink_of_fd 9)"
    exec 9<&-

    docker create --name "$c2" -- "$PROBE_IMAGE_ID" true >/dev/null || probe_die 'create-failed'
    up2=$(upper_of "$c2") || probe_die 'inspect-failed'
    [ -d "$up2" ] || probe_die 'upperdir-missing'
    exec 8<"$up2"
    record kept baseline "$(nlink_of_fd 8)"
    record kept rm_ok 1
    record kept after "$(nlink_of_fd 8)"
    exec 8<&-
    docker rm "$c2" >/dev/null || probe_die 'rm-failed'

    # The fault arm's removal fails; its stale fd 7 is never opened either.
    if docker rm "skillc-dev-probe-p6-absent-$$" >/dev/null 2>&1; then
        record fault rm_ok 1
    else
        record fault rm_ok 0
    fi
    record fault baseline "$(nlink_of_fd 7)"
    record fault after "$(nlink_of_fd 7)"
}

verdict() {
    b=$(rd_uint "$1" baseline) || { printf '%s\n' "$PROBE_FAIL"; return; }
    ok=$(rd_uint "$1" rm_ok) || { printf '%s\n' "$PROBE_FAIL"; return; }
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
