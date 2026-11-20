#!/bin/sh
# P1 (#797 fact 1): link counts on the runner VM's tmpfs, read through held fds.
# Unprivileged. No Docker. Live scratch: ${PROBE_TMPFS:-/dev/shm}.
#
# Arms and expected verdicts:
#   rmdir     a removed directory reads st_nlink 0           CONFIRMED_NEGATIVE
#   last      a file after its last unlink reads 0           CONFIRMED_NEGATIVE
#   rename    a renamed directory still reads >= 2           SURVIVOR_OBSERVED
#   hardlink  a file with one remaining name reads 1         SURVIVOR_OBSERVED
#   fault     stat of an fd that is not open must fail       OBSERVATION_FAILED
# Every arm also requires the scratch filesystem to read exactly "tmpfs".
set -eu
PROBE_NAME=p1
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

nlink_of_fd() {
    stat -L -c %h "/proc/$$/fd/$1" 2>/dev/null || printf 'ERR\n'
}

observe() {
    scratch_make "${PROBE_TMPFS:-/dev/shm}"
    trap scratch_remove EXIT
    fstype=$(stat -f -c %T "$PROBE_SCRATCH" 2>/dev/null) || fstype=ERR
    for a in rmdir last rename hardlink fault; do record "$a" fstype "$fstype"; done
    d="$PROBE_SCRATCH/d"
    mkdir "$d"
    exec 9<"$d"
    rmdir "$d"
    record rmdir nlink "$(nlink_of_fd 9)"
    exec 9<&-
    e="$PROBE_SCRATCH/e"
    mkdir "$e"
    exec 8<"$e"
    mv "$e" "$e.moved"
    record rename nlink "$(nlink_of_fd 8)"
    exec 8<&-
    rmdir "$e.moved"
    f="$PROBE_SCRATCH/f"
    : >"$f"
    exec 7<"$f"
    ln "$f" "$f.link"
    rm "$f"
    record hardlink nlink "$(nlink_of_fd 7)"
    rm "$f.link"
    record last nlink "$(nlink_of_fd 7)"
    exec 7<&-
    # fd 6 is never opened here; its stat must fail and be recorded as ERR.
    record fault nlink "$(nlink_of_fd 6)"
}

verdict() {
    t=$(rd "$1" fstype) || { printf '%s\n' "$PROBE_FAIL"; return; }
    [ "$t" = tmpfs ] || { printf '%s\n' "$PROBE_FAIL"; return; }
    n=$(rd_uint "$1" nlink) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$n" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

classify() {
    arm rmdir "$PROBE_NEG" "$(verdict rmdir)"
    arm last "$PROBE_NEG" "$(verdict last)"
    arm rename "$PROBE_SURV" "$(verdict rename)"
    arm hardlink "$PROBE_SURV" "$(verdict hardlink)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    # Exact-value checks: a rename must keep >= 2 links, a hard link exactly 1.
    if n=$(rd_uint rename nlink) && [ "$n" -lt 2 ]; then
        arm rename-min2 "$PROBE_SURV" "$PROBE_FAIL"
    fi
    if n=$(rd_uint hardlink nlink) && [ "$n" -ne 1 ]; then
        arm hardlink-is1 "$PROBE_SURV" "$PROBE_FAIL"
    fi
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
