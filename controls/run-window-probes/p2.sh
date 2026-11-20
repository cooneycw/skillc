#!/bin/sh
# P2 (#797 fact 2 corroboration): a /proc census of fd and map_files entries
# can see a holder of a deleted tmpfs file, and reports whether every pid was
# readable. Run unprivileged first: a nonzero `unreadable` there is the
# measurement that the controller needs root (owner Q2: root approved). Then
# run as root. No Docker.
#
# Arms and expected verdicts:
#   fd      a sleeper holds an fd to a deleted file: fd hit SURVIVOR_OBSERVED
#   mmap    a process holds ONLY a mapping (its fd closed):
#           map_files hit and no fd hit                     SURVIVOR_OBSERVED
#   reaped  both holders reaped and confirmed gone          CONFIRMED_NEGATIVE
#   fault   census over a planted unresolvable fd entry     OBSERVATION_FAILED
# A census is complete only if every live pid's fd and map_files listing and
# every listed entry could be read, and the planted holders were still alive
# when it ended. Anything else is OBSERVATION_FAILED, never a zero.
set -eu
PROBE_NAME=p2
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# census ROOT IDENTITY: prints "FD_HITS MAP_HITS UNREADABLE SCANNED", where
# IDENTITY is a kernel dev:ino. Each directory is listed exactly once; entry
# names in /proc fd and map_files never contain whitespace.
census() {
    fd_hits=0
    map_hits=0
    unreadable=0
    scanned=0
    for p in "$1"/[0-9]*; do
        [ -d "$p" ] || continue
        scanned=$((scanned + 1))
        for sub in fd map_files; do
            if ! names=$(ls -1A -- "$p/$sub" 2>/dev/null); then
                # A pid that exited mid-census is not unreadable; a live one is.
                if [ -d "$p" ]; then unreadable=$((unreadable + 1)); fi
                continue
            fi
            for n in $names; do
                e="$p/$sub/$n"
                if id=$(stat -L -c '%d:%i' -- "$e" 2>/dev/null); then
                    if [ "$id" = "$2" ]; then
                        if [ "$sub" = fd ]; then
                            fd_hits=$((fd_hits + 1))
                        else
                            map_hits=$((map_hits + 1))
                        fi
                    fi
                elif [ -L "$e" ]; then
                    unreadable=$((unreadable + 1))
                fi
            done
        done
    done
    printf '%s %s %s %s\n' "$fd_hits" "$map_hits" "$unreadable" "$scanned"
}

# record_census ARM ROOT IDENTITY [PID:STARTTIME...]: record one census. Its
# `unreadable` is ERR unless every named holder is the same live process after
# it (pid and start time) and at least one pid was scanned.
record_census() {
    _arm=$1 _root=$2 _id=$3
    shift 3
    if out=$(census "$_root" "$_id"); then
        _fd=${out%% *}
        _rest=${out#* }
        _map=${_rest%% *}
        _rest=${_rest#* }
        _unr=${_rest%% *}
        _scan=${_rest#* }
        for h in "$@"; do
            _now=$(proc_identity "${h%%:*}") || _now=gone
            if [ "$_now" != "${h#*:}" ]; then _unr=ERR; fi
        done
        if ! is_uint "$_scan" || [ "$_scan" -lt 1 ]; then _unr=ERR; fi
        record "$_arm" fd_hits "$_fd"
        record "$_arm" map_hits "$_map"
        record "$_arm" unreadable "$_unr"
    else
        record "$_arm" fd_hits ERR
        record "$_arm" map_hits ERR
        record "$_arm" unreadable ERR
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
    info "uid=$(id -u)"
    a="$PROBE_SCRATCH/held-fd"
    b="$PROBE_SCRATCH/held-map"
    : >"$a"
    head -c 4096 /dev/zero >"$b"
    ida=$(stat -c '%d:%i' -- "$a")
    idb=$(stat -c '%d:%i' -- "$b")
    sleep 600 3<"$a" &
    h1=$!
    track_pid "$h1"
    wait_for "/proc/$h1/fd/3" || probe_die 'fd-holder-not-ready'
    st1=$(proc_identity "$h1") || probe_die 'fd-holder-unreadable'
    # libc mmap through ctypes: unlike Python's mmap.mmap, which dup()s the
    # descriptor, this leaves the mapping as the only reference once the fd
    # is closed.
    python3 -I -c '
import ctypes, os, sys, time
libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int,
                      ctypes.c_int, ctypes.c_long]
fd = os.open(sys.argv[1], os.O_RDONLY)
addr = libc.mmap(None, 4096, 1, 1, fd, 0)  # PROT_READ, MAP_SHARED
if addr is None or addr == ctypes.c_void_p(-1).value:
    sys.exit(3)
os.close(fd)
open(sys.argv[2], "w").close()
time.sleep(600)
' "$b" "$PROBE_SCRATCH/map-ready" &
    h2=$!
    track_pid "$h2"
    wait_for "$PROBE_SCRATCH/map-ready" || probe_die 'map-holder-not-ready'
    st2=$(proc_identity "$h2") || probe_die 'map-holder-unreadable'
    rm -- "$a" "$b"
    record_census fd /proc "$ida" "$h1:$st1"
    record_census mmap /proc "$idb" "$h2:$st2"
    kill "$h1" "$h2" 2>/dev/null || true
    wait "$h1" 2>/dev/null || true
    wait "$h2" 2>/dev/null || true
    if [ -d "/proc/$h1" ] || [ -d "/proc/$h2" ]; then
        for r in reaped_a reaped_b; do
            record "$r" fd_hits ERR
            record "$r" map_hits ERR
            record "$r" unreadable ERR
        done
    else
        PROBE_PIDS=
        record_census reaped_a /proc "$ida"
        record_census reaped_b /proc "$idb"
    fi
    mkdir -p "$PROBE_SCRATCH/fakeproc/4242/fd" "$PROBE_SCRATCH/fakeproc/4242/map_files"
    ln -s "$PROBE_SCRATCH/absent-target" "$PROBE_SCRATCH/fakeproc/4242/fd/3"
    record_census fault "$PROBE_SCRATCH/fakeproc" "$ida"
}

# hits ARM: prints "FD MAP" for a complete census, or fails.
hits() {
    u=$(rd_uint "$1" unreadable) || return 1
    [ "$u" -eq 0 ] || return 1
    f=$(rd_uint "$1" fd_hits) || return 1
    m=$(rd_uint "$1" map_hits) || return 1
    printf '%s %s\n' "$f" "$m"
}

v_fd() {
    h=$(hits fd) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "${h% *}" -ge 1 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$PROBE_NEG"; fi
}

v_mmap() {
    h=$(hits mmap) || { printf '%s\n' "$PROBE_FAIL"; return; }
    # This arm qualifies the map_files reader on its own: an fd hit means the
    # holder still had an fd, so the mapping was not the only evidence.
    if [ "${h% *}" -ne 0 ]; then printf '%s\n' "$PROBE_FAIL"
    elif [ "${h#* }" -ge 1 ]; then printf '%s\n' "$PROBE_SURV"
    else printf '%s\n' "$PROBE_NEG"; fi
}

v_reaped() {
    ha=$(hits reaped_a) || { printf '%s\n' "$PROBE_FAIL"; return; }
    hb=$(hits reaped_b) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$ha" = "0 0" ] && [ "$hb" = "0 0" ]; then printf '%s\n' "$PROBE_NEG"
    else printf '%s\n' "$PROBE_SURV"; fi
}

v_fault() {
    h=$(hits fault) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$h" = "0 0" ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

classify() {
    arm fd "$PROBE_SURV" "$(v_fd)"
    arm mmap "$PROBE_SURV" "$(v_mmap)"
    arm reaped "$PROBE_NEG" "$(v_reaped)"
    arm fault "$PROBE_FAIL" "$(v_fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
