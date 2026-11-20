#!/bin/sh
# P7 (#797 precondition 1.2.5): inside a container built with revision 7's
# containment (read-only root filesystem; host-tmpfs binds for the home and the
# three scratch paths), the directories writable by the container uid are
# exactly the declared surfaces. ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p7.sh --image-id sha256:<64 hex> --runner-unit <unit>
# The image must provide a find(1) with -writable; if it does not, the
# inventory fails (OBSERVATION_FAILED), never reads as clean.
# proc, sysfs and cgroup mounts are skipped: they hold no file persistence.
# Every other mount is searched, including /dev/mqueue, so a writable IPC
# filesystem shows up as an extra and must be dealt with in PR-1.
#
# Arms and expected verdicts:
#   clean     only the declared surfaces are writable       CONFIRMED_NEGATIVE
#   survivor  a planted extra writable bind is found        SURVIVOR_OBSERVED
#   fault     the inventory is made to search a path that
#             does not exist                               OBSERVATION_FAILED
set -eu
PROBE_NAME=p7
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

DECLARED='/probe-home /tmp /var/tmp /dev/shm'

# Runs inside the container. Prints the number of writable directories that
# lie outside every declared surface; exits nonzero if any search failed.
# shellcheck disable=SC2016
INVENTORY='
set -eu
extra=0
list=$(awk "{ for (i = 7; i <= NF; i++) if (\$i == \"-\") { print \$5, \$(i + 1); break } }" /proc/self/mountinfo)
[ -n "$list" ] || exit 3
search=$(printf "%s\n" "$list" | awk "\$2 != \"proc\" && \$2 != \"sysfs\" && \$2 !~ /^cgroup/ { print \$1 }")
if [ "${PROBE_FAULT:-0}" = 1 ]; then search="$search /skillc-dev-probe-absent"; fi
for mp in $search; do
    out=$(find "$mp" -xdev -type d -writable -print) || exit 3
    for d in $out; do
        inside=0
        for s in $DECLARED; do
            case $d in "$s" | "$s"/*) inside=1 ;; esac
        done
        [ "$inside" = 1 ] || extra=$((extra + 1))
    done
done
printf "%s\n" "$extra"
'

observe() {
    require_root
    require_runner_idle
    require_image
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    user=${PROBE_USER:-1000:1000}
    mounts=
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        for m in $mounts; do
            if mountpoint -q "$m" 2>/dev/null; then umount "$m" || true; fi
        done
        scratch_remove
    }
    trap cleanup EXIT
    binds=
    for t in home tmp vartmp shm; do
        m="$PROBE_SCRATCH/$t"
        mkdir -p "$m"
        mount -t tmpfs -o size=1m,mode=0700 skillc-dev-probe "$m" || probe_die 'mount-failed'
        mounts="$mounts $m"
        chown "$user" "$m" || probe_die 'chown-failed'
    done
    binds="--mount type=bind,source=$PROBE_SCRATCH/home,target=/probe-home"
    binds="$binds --mount type=bind,source=$PROBE_SCRATCH/tmp,target=/tmp"
    binds="$binds --mount type=bind,source=$PROBE_SCRATCH/vartmp,target=/var/tmp"
    binds="$binds --mount type=bind,source=$PROBE_SCRATCH/shm,target=/dev/shm"
    mkdir -p "$PROBE_SCRATCH/extra"
    chown "$user" "$PROBE_SCRATCH/extra" || probe_die 'chown-failed'
    extra_bind="--mount type=bind,source=$PROBE_SCRATCH/extra,target=/probe-extra"

    # inventory ARM FAULT EXTRA_BINDS: the bind list is word-split on purpose;
    # every element is built above from fixed text and the scratch path.
    inventory() {
        # shellcheck disable=SC2086
        if n=$(docker run --rm --read-only --network none --ipc private --log-driver none \
            --user "$user" $binds $3 -e "DECLARED=$DECLARED" -e "PROBE_FAULT=$2" \
            -- "$PROBE_IMAGE_ID" sh -c "$INVENTORY" 2>/dev/null) && is_uint "$n"; then
            record "$1" extra "$n"
        else
            record "$1" extra ERR
        fi
    }
    inventory clean 0 ''
    inventory survivor 0 "$extra_bind"
    inventory fault 1 ''
}

verdict() {
    n=$(rd_uint "$1" extra) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$n" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

classify() {
    arm clean "$PROBE_NEG" "$(verdict clean)"
    arm survivor "$PROBE_SURV" "$(verdict survivor)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
