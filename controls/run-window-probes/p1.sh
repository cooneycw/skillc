#!/bin/sh
# P1 (#797 fact 1): link counts on the runner VM's tmpfs, read through held fds.
# Unprivileged. No Docker. Live scratch: ${PROBE_TMPFS:-/dev/shm}.
#
# Arms and expected verdicts (each arm also requires fstype exactly "tmpfs"):
#   rmdir     removed directory: st_nlink 0                 CONFIRMED_NEGATIVE
#   last      file after its last unlink: 0                 CONFIRMED_NEGATIVE
#   rename    renamed directory: st_nlink >= 2              SURVIVOR_OBSERVED
#   hardlink  file with one remaining name: exactly 1       SURVIVOR_OBSERVED
#   fault     stat of an fd closed beforehand must fail     OBSERVATION_FAILED
# A count of the wrong shape for its arm (a rename reading 1, a hard link
# reading 2) is OBSERVATION_FAILED: the arm did not observe what it planted.
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
    # Close fd 6 explicitly, so an inherited descriptor cannot answer for it.
    exec 6<&-
    record fault nlink "$(nlink_of_fd 6)"
}

# verdict ARM SHAPE: SHAPE is zero (expects 0), many (expects >= 2) or one (1).
verdict() {
    t=$(rd "$1" fstype) || { printf '%s\n' "$PROBE_FAIL"; return; }
    [ "$t" = tmpfs ] || { printf '%s\n' "$PROBE_FAIL"; return; }
    n=$(rd_uint "$1" nlink) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$n" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; return; fi
    case $2 in
        many) if [ "$n" -ge 2 ]; then printf '%s\n' "$PROBE_SURV"; return; fi ;;
        one) if [ "$n" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"; return; fi ;;
    esac
    printf '%s\n' "$PROBE_FAIL"
}

classify() {
    arm rmdir "$PROBE_NEG" "$(verdict rmdir zero)"
    arm last "$PROBE_NEG" "$(verdict last zero)"
    arm rename "$PROBE_SURV" "$(verdict rename many)"
    arm hardlink "$PROBE_SURV" "$(verdict hardlink one)"
    arm fault "$PROBE_FAIL" "$(verdict fault zero)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
