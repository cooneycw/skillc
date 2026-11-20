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
#   lazy    MNT_DETACH succeeded, the superblock is in no
#           table, and the planted marker is READ back
#           through the held fd                             SURVIVOR_OBSERVED
#   fault   mount-table scan over a planted unreadable table OBSERVATION_FAILED
set -eu
PROBE_NAME=p3
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

EBUSY=16
MARKER=skillc-dev-marker

# umount2 PATH FLAGS: prints the errno number (0 on success), or ERR.
umount2() {
    python3 -I -c '
import ctypes, sys
libc = ctypes.CDLL(None, use_errno=True)
r = libc.umount2(sys.argv[1].encode(), int(sys.argv[2]))
print(0 if r == 0 else ctypes.get_errno())
' "$1" "$2" 2>/dev/null || printf 'ERR\n'
}

# sb_listed ROOT MAJMIN: prints "LISTED UNREADABLE SCANNED" over every pid's
# mountinfo; fails if any per-table count could not be computed.
sb_listed() {
    listed=0
    unreadable=0
    scanned=0
    for p in "$1"/[0-9]*; do
        [ -d "$p" ] || continue
        if t=$(cat -- "$p/mountinfo" 2>/dev/null); then
            n=$(printf '%s\n' "$t" | awk -v d="$2" '$3 == d { c++ } END { print c + 0 }') || return 1
            is_uint "$n" || return 1
            listed=$((listed + n))
            scanned=$((scanned + 1))
        elif [ -d "$p" ]; then
            unreadable=$((unreadable + 1))
        fi
    done
    printf '%s %s %s\n' "$listed" "$unreadable" "$scanned"
}

record_sb() {
    if out=$(sb_listed "$2" "$3"); then
        _l=${out%% *}
        _rest=${out#* }
        _u=${_rest%% *}
        _s=${_rest#* }
        if ! is_uint "$_s" || [ "$_s" -lt 1 ]; then _u=ERR; fi
        record "$1" listed "$_l"
        record "$1" unreadable "$_u"
    else
        record "$1" listed ERR
        record "$1" unreadable ERR
    fi
}

# fresh_tmpfs PATH: mount and track a new tmpfs; set $dev to its major:minor.
# Called directly, never in $(...), so a refusal exits the probe.
fresh_tmpfs() {
    mount_tmpfs "$1"
    dev=$(mountpoint -d "$1") || probe_die 'majmin-unreadable'
    printf '%s\n' "$dev" | grep -Eq '^[0-9]+:[0-9]+$' || probe_die 'majmin-malformed'
}

observe() {
    require_root
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    m="$PROBE_SCRATCH/m"

    fresh_tmpfs "$m"
    exec 9<"$m"
    record held errno "$(umount2 "$m" 0)"
    exec 9<&-
    record clean errno "$(umount2 "$m" 0)"
    record_sb clean /proc "$dev"

    fresh_tmpfs "$m"
    mkdir -p "$PROBE_SCRATCH/alias"
    mount --bind "$m" "$PROBE_SCRATCH/alias" || probe_die 'bind-failed'
    track_mount "$PROBE_SCRATCH/alias"
    record alias errno "$(umount2 "$m" 0)"
    record_sb alias /proc "$dev"
    umount "$PROBE_SCRATCH/alias" || probe_die 'alias-cleanup-failed'

    fresh_tmpfs "$m"
    printf '%s\n' "$MARKER" >"$m/marker"
    exec 9<"$m"
    record lazy errno "$(umount2 "$m" 2)"
    record_sb lazy /proc "$dev"
    if got=$(cat -- "/proc/$$/fd/9/marker" 2>/dev/null); then
        if [ "$got" = "$MARKER" ]; then record lazy fd_reads 1; else record lazy fd_reads ERR; fi
    else
        record lazy fd_reads ERR
    fi
    exec 9<&-

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

# v_lazy: only "gone from every table AND still read through the fd" is the
# survivor this arm exists to show. A superblock still listed means the
# detach did not do what was planted.
v_lazy() {
    base=$(v_table lazy)
    r=$(rd_bool lazy fd_reads) || { printf '%s\n' "$PROBE_FAIL"; return; }
    case $base in
        "$PROBE_NEG") if [ "$r" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$PROBE_NEG"; fi ;;
        *) printf '%s\n' "$PROBE_FAIL" ;;
    esac
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
