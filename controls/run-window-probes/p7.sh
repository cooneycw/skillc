#!/bin/sh
# P7 (#797 precondition 1.2.5): inside a container built with revision 7's
# containment (read-only root filesystem; host-tmpfs binds for the home and the
# three scratch paths), the container uid can write to exactly the declared
# surfaces. ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p7.sh --image-id sha256:<64 hex> --runner-unit <unit>
#
# Inside the container, the inventory:
# - requires every declared surface to be a listed mountpoint that accepts a
#   real marker write and removal (a missing or read-only surface fails);
# - lists writable directories (GNU find -writable, an access(2) check) on
#   every mount except proc, sysfs and cgroup, and counts any outside the
#   declared surfaces;
# - counts writable non-directory mountpoints (file bind mounts) as extras;
# - reads every path list line by line with globbing off, never word-split.
# If the image lacks a find(1) with -writable, the inventory fails
# (OBSERVATION_FAILED), never reads as clean. /dev/mqueue is searched, so a
# writable IPC filesystem shows as an extra, which PR-1 must then close.
#
# Arms and expected verdicts:
#   clean     only the declared surfaces are writable       CONFIRMED_NEGATIVE
#   survivor  a planted writable directory bind and a
#             planted writable file bind are both found     SURVIVOR_OBSERVED
#   fault     the declared home surface is left unmounted   OBSERVATION_FAILED
set -eu
PROBE_NAME=p7
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

DECLARED='/probe-home /tmp /var/tmp /dev/shm'

# Runs inside the container. Prints "DIRS FILES": writable directories and
# writable non-directory mountpoints outside the declared surfaces. Exits 3 if
# any required observation failed, including any mountpoint mountinfo had to
# escape (a backslash), which fails closed rather than being looked up wrong.
# shellcheck disable=SC2016
INVENTORY='
set -euf
mi=/proc/self/mountinfo
[ -r "$mi" ] || exit 3
# Validate the WHOLE table first: every row needs the "-" separator after at
# least six fields and three fields after it. Prints "FSTYPE OPTIONS MOUNTPOINT".
mounts=$(awk "NF == 0 { next } { s = 0; for (i = 7; i <= NF; i++) if (\$i == \"-\") { s = i; break }; if (!s || NF < s + 3 || \$1 !~ /^[0-9]+\$/ || \$2 !~ /^[0-9]+\$/ || \$3 !~ /^[0-9]+:[0-9]+\$/ || \$4 !~ /^\// || \$5 !~ /^\//) bad = 1; else print \$(s + 1), \$6, \$5; n++ } END { exit (bad || n < 1) ? 1 : 0 }" "$mi") || exit 3
case $mounts in *\\*) exit 3 ;; esac
# Exit 4 with "MISSING-SURFACE <path>" means exactly that a declared surface is
# not mounted, after the table read above succeeded. Any other failure is 3.
for s in $DECLARED; do
    found=0
    while IFS=" " read -r fstype opts mp; do
        if [ "$mp" = "$s" ]; then found=1; fi
    done <<EOT
$mounts
EOT
    if [ "$found" != 1 ]; then printf "MISSING-SURFACE %s\n" "$s"; exit 4; fi
    w="$s/.skillc-dev-probe-write"
    printf "x\n" > "$w" || exit 3
    rm "$w" || exit 3
done
# Writable = access(2) says so, OR (on an rw mount) the mode bits say so for
# this uid or one of its groups. The union means an access(2) error cannot
# hide a path that the bits show writable; find(1) fails on unreadable paths.
# The union may over-report (fail-safe: MISMATCH, never a false clean); see
# the stated limits in README.md for the ACL cases.
uid=$(id -u) || exit 3
gids=$(id -G) || exit 3
set -- \( -writable -o -perm -0002 -o \( -uid "$uid" -perm -0200 \)
for g in $gids; do set -- "$@" -o \( -gid "$g" -perm -0020 \); done
set -- "$@" \)
dirs=$(mktemp -d /tmp/.skillc-dev-probe-XXXXXX) || exit 3
while IFS=" " read -r fstype opts mp; do
    case $fstype in proc | sysfs | cgroup | cgroup2) continue ;; esac
    case ,$opts, in *,ro,*) ro=1 ;; *) ro=0 ;; esac
    if [ -d "$mp" ]; then
        if [ "$ro" = 1 ]; then
            find "$mp" -xdev -type d -writable -print >>"$dirs/dirs" || : >"$dirs/failed"
        else
            find "$mp" -xdev -type d "$@" -print >>"$dirs/dirs" || : >"$dirs/failed"
        fi
    elif [ -e "$mp" ] || [ -L "$mp" ]; then
        if [ "$ro" = 1 ]; then
            find "$mp" -maxdepth 0 -writable -print >>"$dirs/files" || : >"$dirs/failed"
        else
            find "$mp" -maxdepth 0 "$@" -print >>"$dirs/files" || : >"$dirs/failed"
        fi
    else
        : >"$dirs/failed"
    fi
done <<EOT
$mounts
EOT
[ ! -e "$dirs/failed" ] || exit 3
outside() {
    c=0
    if [ -e "$1" ]; then
        while IFS= read -r d; do
            inside=0
            for s in $DECLARED; do
                case $d in "$s" | "$s"/*) inside=1 ;; esac
            done
            [ "$inside" = 1 ] || c=$((c + 1))
        done <"$1"
    fi
    printf "%s" "$c"
}
nd=$(outside "$dirs/dirs")
nf=$(outside "$dirs/files")
pd=0
pf=0
if [ -e "$dirs/dirs" ] && grep -qx /probe-extra "$dirs/dirs"; then pd=1; fi
if [ -e "$dirs/files" ] && grep -qx /probe-extra-file "$dirs/files"; then pf=1; fi
rm -rf "$dirs"
printf "%s %s %s %s\n" "$nd" "$nf" "$pd" "$pf"
'

observe() {
    require_root
    require_runner_idle
    require_image
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    scratch_private
    user=${PROBE_USER:-1000:1000}
    for t in home tmp vartmp shm; do
        mount_tmpfs "$PROBE_SCRATCH/$t"
        chown "$user" "$PROBE_SCRATCH/$t" || probe_die 'chown-failed'
    done
    mkdir -p "$PROBE_SCRATCH/extra"
    : >"$PROBE_SCRATCH/extra-file"
    chown "$user" "$PROBE_SCRATCH/extra" "$PROBE_SCRATCH/extra-file" || probe_die 'chown-failed'
    home="type=bind,source=$PROBE_SCRATCH/home,target=/probe-home"
    tmp="type=bind,source=$PROBE_SCRATCH/tmp,target=/tmp"
    vartmp="type=bind,source=$PROBE_SCRATCH/vartmp,target=/var/tmp"
    shm="type=bind,source=$PROBE_SCRATCH/shm,target=/dev/shm"
    xdir="type=bind,source=$PROBE_SCRATCH/extra,target=/probe-extra"
    xfile="type=bind,source=$PROBE_SCRATCH/extra-file,target=/probe-extra-file"

    # inventory ARM MOUNT...: create, run in the foreground, read the count,
    # then remove the container and verify it is gone.
    inventory() {
        _arm=$1
        shift
        _m=
        for _x in "$@"; do _m="$_m --mount $_x"; done
        # shellcheck disable=SC2086  # each element is built above from fixed text
        create_container --read-only --network none --ipc private --log-driver none \
            --user "$user" $_m -e "DECLARED=$DECLARED" \
            -- "$PROBE_IMAGE_ID" sh -c "$INVENTORY"
        _rc=0
        out=$(docker start -a "$cid" 2>/dev/null) || _rc=$?
        if [ "$_arm" = fault ]; then
            # The fault arm must fail exactly at the declared-surface check:
            # exit 4 with the MISSING-SURFACE token, after a good table read.
            if [ "$_rc" -ne 4 ] || [ "$out" != "MISSING-SURFACE /probe-home" ]; then
                probe_die 'fault-arm-not-exercised'
            fi
            set --
        elif [ "$_rc" -eq 0 ]; then
            # shellcheck disable=SC2086  # four space-separated numbers
            set -- $out
        else
            set --
        fi
        if [ "$#" -eq 4 ]; then
            record "$_arm" extra_dirs "$1"
            record "$_arm" extra_files "$2"
            record "$_arm" planted_dir "$3"
            record "$_arm" planted_file "$4"
        else
            for k in extra_dirs extra_files planted_dir planted_file; do record "$_arm" "$k" ERR; done
        fi
        docker rm -v "$cid" >/dev/null || probe_die 'rm-failed'
        container_absent "$cid" || probe_die 'rm-unverified'
    }
    inventory clean "$home" "$tmp" "$vartmp" "$shm"
    inventory survivor "$home" "$tmp" "$vartmp" "$shm" "$xdir" "$xfile"
    # Fault: the home surface is not mounted (Docker supplies its own /dev/shm,
    # so omitting that bind would not exercise the check).
    inventory fault "$tmp" "$vartmp" "$shm"
    recheck_runner
}

# extras ARM: prints "DIRS FILES", or fails.
extras() {
    d=$(rd_uint "$1" extra_dirs) || return 1
    f=$(rd_uint "$1" extra_files) || return 1
    printf '%s %s\n' "$d" "$f"
}

# verdict ARM: all four readings must be valid and consistent (a planted path
# found must also be counted as an extra of its type).
verdict() {
    e=$(extras "$1") || { printf '%s\n' "$PROBE_FAIL"; return; }
    d=$(rd_bool "$1" planted_dir) || { printf '%s\n' "$PROBE_FAIL"; return; }
    f=$(rd_bool "$1" planted_file) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if { [ "$d" -eq 1 ] && [ "${e% *}" -lt 1 ]; } || { [ "$f" -eq 1 ] && [ "${e#* }" -lt 1 ]; }; then
        printf '%s\n' "$PROBE_FAIL"; return
    fi
    if [ "$e" = "0 0" ]; then printf '%s\n' "$PROBE_NEG"; else printf '%s\n' "$PROBE_SURV"; fi
}

# v_survivor: each planted path must be observed on its own, so a broken
# file-bind check cannot hide behind the directory hit.
v_survivor() {
    [ "$(verdict survivor)" != "$PROBE_FAIL" ] || { printf '%s\n' "$PROBE_FAIL"; return; }
    d=$(rd_bool survivor planted_dir) || { printf '%s\n' "$PROBE_FAIL"; return; }
    f=$(rd_bool survivor planted_file) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$d" -eq 1 ] && [ "$f" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"
    else printf '%s\n' "$PROBE_FAIL"; fi
}

classify() {
    arm clean "$PROBE_NEG" "$(verdict clean)"
    arm survivor "$PROBE_SURV" "$(v_survivor)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
