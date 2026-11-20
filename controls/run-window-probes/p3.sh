#!/bin/sh
# P3 (#797 facts 3 and 4): a held fd blocks a non-lazy unmount (EBUSY, by
# errno number, never by message text); after a real unmount no readable
# mount table lists the tmpfs superblock; bind aliases and lazy detach are
# observable survivors. ROOT REQUIRED. No Docker.
#
# Arms and expected verdicts:
#   held    umount2(flags=0) with an fd held returns EBUSY  SURVIVOR_OBSERVED
#   clean   unmounted with no fd: superblock in no table    CONFIRMED_NEGATIVE
#   alias   source unmounted, bind alias still listed       SURVIVOR_OBSERVED
#   lazy    MNT_DETACH: gone from tables, fd still reads    SURVIVOR_OBSERVED
#   fault   mount-table scan over a planted unreadable table OBSERVATION_FAILED
set -eu
PROBE_NAME=p3
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

EBUSY=16

# umount2 PATH FLAGS: prints the errno number (0 on success), or ERR.
umount2() {
    python3 -I -c '
import ctypes, sys
libc = ctypes.CDLL(None, use_errno=True)
r = libc.umount2(sys.argv[1].encode(), int(sys.argv[2]))
print(0 if r == 0 else ctypes.get_errno())
' "$1" "$2" 2>/dev/null || printf 'ERR\n'
}

# sb_listed ROOT MAJMIN: prints "LISTED UNREADABLE" over every pid's mountinfo.
sb_listed() {
    listed=0
    unreadable=0
    for p in "$1"/[0-9]*; do
        [ -d "$p" ] || continue
        if t=$(cat -- "$p/mountinfo" 2>/dev/null); then
            n=$(printf '%s\n' "$t" | awk -v d="$2" '$3 == d { c++ } END { print c + 0 }')
            listed=$((listed + n))
        elif [ -d "$p" ]; then
            unreadable=$((unreadable + 1))
        fi
    done
    printf '%s %s\n' "$listed" "$unreadable"
}

record_sb() {
    if out=$(sb_listed "$2" "$3"); then
        record "$1" listed "${out% *}"
        record "$1" unreadable "${out#* }"
    else
        record "$1" listed ERR
        record "$1" unreadable ERR
    fi
}

# fresh_tmpfs PATH: mount a new tmpfs and set $dev to its major:minor. Called
# directly, never in $(...), so a refusal exits the probe, not a subshell.
fresh_tmpfs() {
    mkdir -p "$1"
    mount -t tmpfs -o size=1m,mode=0700 skillc-dev-probe "$1" || probe_die 'mount-failed'
    dev=$(mountpoint -d "$1") || probe_die 'majmin-unreadable'
    printf '%s\n' "$dev" | grep -Eq '^[0-9]+:[0-9]+$' || probe_die 'majmin-malformed'
}

observe() {
    require_root
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        for m in "$PROBE_SCRATCH/m" "$PROBE_SCRATCH/alias"; do
            if mountpoint -q "$m" 2>/dev/null; then umount "$m" || true; fi
        done
        scratch_remove
    }
    trap cleanup EXIT
    m="$PROBE_SCRATCH/m"

    # held, then clean (same superblock, after the fd closes).
    fresh_tmpfs "$m"
    exec 9<"$m"
    record held errno "$(umount2 "$m" 0)"
    exec 9<&-
    e=$(umount2 "$m" 0)
    record clean errno "$e"
    record_sb clean /proc "$dev"

    # alias: bind the tmpfs elsewhere, unmount the source, look for the superblock.
    fresh_tmpfs "$m"
    mkdir -p "$PROBE_SCRATCH/alias"
    mount --bind "$m" "$PROBE_SCRATCH/alias" || probe_die 'bind-failed'
    record alias errno "$(umount2 "$m" 0)"
    record_sb alias /proc "$dev"
    umount "$PROBE_SCRATCH/alias" || probe_die 'alias-cleanup-failed'

    # lazy: detach with an fd held; the tables lose it, the fd still reads it.
    fresh_tmpfs "$m"
    printf 'skillc-dev-marker\n' >"$m/marker"
    exec 9<"$m"
    record lazy errno "$(umount2 "$m" 2)"
    record_sb lazy /proc "$dev"
    if [ -r "/proc/$$/fd/9/marker" ]; then record lazy fd_reads 1; else record lazy fd_reads 0; fi
    exec 9<&-

    # fault: a planted pid whose mountinfo cannot be read (a dangling link).
    mkdir -p "$PROBE_SCRATCH/fakeproc/4242"
    ln -s "$PROBE_SCRATCH/absent-table" "$PROBE_SCRATCH/fakeproc/4242/mountinfo"
    record fault errno 0
    record_sb fault "$PROBE_SCRATCH/fakeproc" "$dev"
}

v_held() {
    e=$(rd_uint held errno) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$e" -eq "$EBUSY" ]; then printf '%s\n' "$PROBE_SURV"
    elif [ "$e" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"
    else printf '%s\n' "$PROBE_FAIL"; fi
}

# v_table ARM: the unmount must have succeeded and every table been read.
v_table() {
    e=$(rd_uint "$1" errno) || { printf '%s\n' "$PROBE_FAIL"; return; }
    u=$(rd_uint "$1" unreadable) || { printf '%s\n' "$PROBE_FAIL"; return; }
    l=$(rd_uint "$1" listed) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$e" -ne 0 ] || [ "$u" -ne 0 ]; then printf '%s\n' "$PROBE_FAIL"; return; fi
    if [ "$l" -eq 0 ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

v_lazy() {
    base=$(v_table lazy)
    r=$(rd_uint lazy fd_reads) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$base" = "$PROBE_FAIL" ]; then printf '%s\n' "$PROBE_FAIL"; return; fi
    # Tables empty but the content still readable is a survivor the tables miss.
    if [ "$r" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$base"; fi
}

classify() {
    arm held "$PROBE_SURV" "$(v_held)"
    arm clean "$PROBE_NEG" "$(v_table clean)"
    arm alias "$PROBE_SURV" "$(v_table alias)"
    arm lazy "$PROBE_SURV" "$(v_lazy)"
    arm fault "$PROBE_FAIL" "$(v_table fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
