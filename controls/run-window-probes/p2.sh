#!/bin/sh
# P2 (#797 fact 2 corroboration): a /proc fd and map_files census can see a
# holder of a deleted tmpfs file, and reports whether every pid was readable.
# Run unprivileged first; a nonzero `unreadable` there is the measurement that
# the controller needs root (owner Q2: root approved). No Docker.
#
# Arms and expected verdicts:
#   fd      a sleeper holds an fd to a deleted file         SURVIVOR_OBSERVED
#   mmap    a process holds only a mapping of a deleted file SURVIVOR_OBSERVED
#   reaped  both holders reaped and confirmed gone          CONFIRMED_NEGATIVE
#   fault   census over a planted unreadable fd entry       OBSERVATION_FAILED
# Any pid whose fd or map_files entries could not be read makes that arm
# OBSERVATION_FAILED, never a zero.
set -eu
PROBE_NAME=p2
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# census ROOT IDENTITY: prints "FOUND UNREADABLE" for kernel identity dev:ino.
census() {
    found=0
    unreadable=0
    for p in "$1"/[0-9]*; do
        [ -d "$p" ] || continue
        for sub in fd map_files; do
            if ! ls -- "$p/$sub" >/dev/null 2>&1; then
                # A pid that exited mid-census is not unreadable; a live one is.
                if [ -d "$p" ]; then unreadable=$((unreadable + 1)); fi
                continue
            fi
            for e in "$p/$sub"/*; do
                [ -L "$e" ] || continue
                if id=$(stat -L -c '%d:%i' -- "$e" 2>/dev/null); then
                    if [ "$id" = "$2" ]; then found=$((found + 1)); fi
                elif [ -L "$e" ]; then
                    unreadable=$((unreadable + 1))
                fi
            done
        done
    done
    printf '%s %s\n' "$found" "$unreadable"
}

record_census() {
    if out=$(census "$2" "$3"); then
        record "$1" found "${out% *}"
        record "$1" unreadable "${out#* }"
    else
        record "$1" found ERR
        record "$1" unreadable ERR
    fi
}

wait_for() {
    i=0
    while [ "$i" -lt 50 ]; do
        if [ -e "$1" ]; then return 0; fi
        sleep 0.1
        i=$((i + 1))
    done
    return 1
}

observe() {
    scratch_make "${PROBE_TMPFS:-/dev/shm}"
    holders=
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        for h in $holders; do kill "$h" 2>/dev/null || true; done
        scratch_remove
    }
    trap cleanup EXIT
    info "uid=$(id -u)"
    a="$PROBE_SCRATCH/held-fd"
    b="$PROBE_SCRATCH/held-map"
    : >"$a"
    head -c 4096 /dev/zero >"$b"
    ida=$(stat -c '%d:%i' -- "$a")
    idb=$(stat -c '%d:%i' -- "$b")
    sleep 600 3<"$a" &
    h1=$!
    holders="$h1"
    wait_for "/proc/$h1/fd/3" || probe_die 'fd-holder-not-ready'
    python3 -I -c '
import mmap, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
m = mmap.mmap(fd, 4096)
os.close(fd)
open(sys.argv[2], "w").close()
time.sleep(600)
' "$b" "$PROBE_SCRATCH/map-ready" &
    h2=$!
    holders="$h1 $h2"
    wait_for "$PROBE_SCRATCH/map-ready" || probe_die 'map-holder-not-ready'
    rm -- "$a" "$b"
    record_census fd /proc "$ida"
    record_census mmap /proc "$idb"
    kill "$h1" "$h2" 2>/dev/null || true
    wait "$h1" 2>/dev/null || true
    wait "$h2" 2>/dev/null || true
    holders=
    if [ -d "/proc/$h1" ] || [ -d "/proc/$h2" ]; then
        record reaped found ERR
        record reaped unreadable ERR
    else
        out_a=$(census /proc "$ida") || out_a='ERR ERR'
        out_b=$(census /proc "$idb") || out_b='ERR ERR'
        fa=${out_a% *} ua=${out_a#* } fb=${out_b% *} ub=${out_b#* }
        if is_uint "$fa" && is_uint "$fb" && is_uint "$ua" && is_uint "$ub"; then
            record reaped found $((fa + fb))
            record reaped unreadable $((ua + ub))
        else
            record reaped found ERR
            record reaped unreadable ERR
        fi
    fi
    # Fault: a planted fd entry whose target cannot be resolved.
    mkdir -p "$PROBE_SCRATCH/fakeproc/4242/fd" "$PROBE_SCRATCH/fakeproc/4242/map_files"
    ln -s "$PROBE_SCRATCH/absent-target" "$PROBE_SCRATCH/fakeproc/4242/fd/3"
    record_census fault "$PROBE_SCRATCH/fakeproc" "$ida"
}

verdict() {
    u=$(rd_uint "$1" unreadable) || { printf '%s\n' "$PROBE_FAIL"; return; }
    f=$(rd_uint "$1" found) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$u" -ne 0 ]; then printf '%s\n' "$PROBE_FAIL"; return; fi
    if [ "$f" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

classify() {
    arm fd "$PROBE_SURV" "$(verdict fd)"
    arm mmap "$PROBE_SURV" "$(verdict mmap)"
    arm reaped "$PROBE_NEG" "$(verdict reaped)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
