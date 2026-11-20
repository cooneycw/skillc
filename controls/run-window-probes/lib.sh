# shellcheck shell=sh
# shellcheck disable=SC2034  # verdict tokens are used by the sourcing probes
# Shared helpers for the run-window probes (#797 section 7). Sourced, never run.
#
# Every probe has two phases with one classifier between them:
#   observe  - LIVE mode only: touches the host, writes "ARM KEY VALUE" lines
#              to a readings file, and records ERR for any failed observation.
#   classify - pure: reads the readings file and prints one verdict per arm.
# `--classify FILE` runs only the classifier over committed fixture readings,
# so CI can qualify every verdict rule without root, Docker or a VM.
#
# Verdicts (exactly one per arm):
#   CONFIRMED_NEGATIVE  the observation succeeded and found nothing
#   SURVIVOR_OBSERVED   the observation succeeded and found a survivor
#   OBSERVATION_FAILED  the observation could not be made completely
# A missing, duplicated, malformed, out-of-range or failed reading is
# OBSERVATION_FAILED, never a zero. No error text is ever matched; only exit
# statuses, errno numbers and parsed numbers or fixed tokens decide.
#
# Live-mode resources (processes, containers, mounts, scratch) are tracked as
# they are created and released by probe_cleanup, which verifies each is gone.
# finish() runs probe_cleanup BEFORE printing the final PROBE line, so a
# QUALIFIED or MISMATCH line is never printed over live residue.

PROBE_NEG=CONFIRMED_NEGATIVE
PROBE_SURV=SURVIVOR_OBSERVED
PROBE_FAIL=OBSERVATION_FAILED
PROBE_MISMATCH=0
PROBE_PIDS=
PROBE_CONTAINERS=
PROBE_NAMES=
PROBE_VOLUMES=
PROBE_MOUNTS=
PROBE_SCRATCH=
PROBE_KEEP=0
PROBE_MODE=classify

probe_die() {
    if ! probe_cleanup; then printf 'INFO cleanup-unverified\n'; fi
    printf 'PROBE %s REFUSED %s\n' "${PROBE_NAME:-unknown}" "$1"
    exit 2
}

# is_uint VALUE: 1 to 18 ASCII digits (always within the shell's integer range).
is_uint() {
    case $1 in
        '' | *[!0-9]*) return 1 ;;
    esac
    [ "${#1}" -le 18 ]
}

# rd ARM KEY: print the single recorded value, or fail. Fails on a missing or
# duplicated key, a line that is not exactly three fields, and the ERR marker.
rd() {
    awk -v a="$1" -v k="$2" '
        $1 == a && $2 == k { n++; if (NF != 3) bad = 1; v = $3 }
        END { if (n != 1 || bad || v == "" || v == "ERR") exit 1; print v }
    ' "$PROBE_READINGS"
}

rd_uint() {
    _v=$(rd "$1" "$2") || return 1
    is_uint "$_v" || return 1
    printf '%s\n' "$_v"
}

rd_bool() {
    _v=$(rd "$1" "$2") || return 1
    case $_v in 0 | 1) printf '%s\n' "$_v" ;; *) return 1 ;; esac
}

# record ARM KEY VALUE: append one reading (live mode only). A value that is
# not a single token is recorded as ERR rather than splitting into fields.
record() {
    case ${3:-} in
        '' | *[!A-Za-z0-9:._-]*) printf '%s %s ERR\n' "$1" "$2" >>"$PROBE_READINGS" ;;
        *) printf '%s %s %s\n' "$1" "$2" "$3" >>"$PROBE_READINGS" ;;
    esac
}

arm() {
    printf 'ARM %s %s\n' "$1" "$3"
    if [ "$3" != "$2" ]; then
        PROBE_MISMATCH=1
    fi
}

info() {
    printf 'INFO %s\n' "$*"
}

# finish: release and verify every live resource, then exit 0 when every arm
# gave its expected verdict, 1 otherwise.
finish() {
    if ! probe_cleanup; then
        printf 'PROBE %s REFUSED cleanup-failed\n' "$PROBE_NAME"
        exit 2
    fi
    if [ "$PROBE_MISMATCH" = 0 ]; then
        printf 'PROBE %s QUALIFIED\n' "$PROBE_NAME"
        exit 0
    fi
    printf 'PROBE %s MISMATCH\n' "$PROBE_NAME"
    exit 1
}

parse_common() {
    PROBE_MODE=live
    PROBE_READINGS=
    PROBE_IMAGE_ID=
    PROBE_RUNNER_UNIT=
    while [ "$#" -gt 0 ]; do
        case $1 in
            --classify)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_MODE=classify
                PROBE_READINGS=$2
                shift 2
                ;;
            --image-id)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_IMAGE_ID=$2
                shift 2
                ;;
            --runner-unit)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_RUNNER_UNIT=$2
                shift 2
                ;;
            *)
                PROBE_MODE=classify
                probe_die 'usage'
                ;;
        esac
    done
    if [ "$PROBE_MODE" = classify ]; then
        if [ ! -f "$PROBE_READINGS" ] || [ ! -r "$PROBE_READINGS" ]; then
            probe_die 'readings-unreadable'
        fi
    else
        trap 'probe_cleanup || true; printf "PROBE %s REFUSED interrupted\n" "$PROBE_NAME"; exit 2' \
            HUP INT TERM
        trap 'probe_cleanup || true' EXIT
    fi
}

# probe_uuid: a fresh random token for container names.
probe_uuid() {
    tr -d '-' </proc/sys/kernel/random/uuid
}

# scratch_make PARENT: create a fresh private scratch directory, refusing reuse.
scratch_make() {
    [ -d "$1" ] || probe_die 'scratch-parent-missing'
    PROBE_SCRATCH="$1/skillc-dev-probe-$PROBE_NAME-$$"
    mkdir -m 0700 "$PROBE_SCRATCH" || { PROBE_SCRATCH=; probe_die 'scratch-exists'; }
    PROBE_READINGS="$PROBE_SCRATCH/readings"
    : >"$PROBE_READINGS"
}

# track_pid PID / track_container ID / track_mount PATH: register for cleanup.
track_pid() { PROBE_PIDS="$PROBE_PIDS $1"; }
track_container() { PROBE_CONTAINERS="$PROBE_CONTAINERS $1"; }
# track_name NAME: a random, probe-unique container name registered BEFORE its
# create runs, so a container the daemon made after the client lost the
# response is still found and removed.
track_name() { PROBE_NAMES="$PROBE_NAMES $1"; }
track_mount() { PROBE_MOUNTS="$1 $PROBE_MOUNTS"; }

# is_mounted PATH: exit 0 if PATH is a mountpoint in this namespace, 1 if it
# is not, 2 if the mount table could not be read completely. Absence is only
# reported from a successful read that printed its own answer token.
is_mounted() {
    _r=$(awk -v m="$1" '$5 == m { f = 1 } END { if (NR < 1) exit 3; print f ? "FOUND" : "ABSENT" }' \
        /proc/self/mountinfo 2>/dev/null) || return 2
    case $_r in FOUND) return 0 ;; ABSENT) return 1 ;; *) return 2 ;; esac
}

# proc_identity PID: "STARTTIME" of a live, non-zombie process, or fail. The
# comm field may contain spaces, so fields are counted after its last ")".
proc_identity() {
    _s=$(cat -- "${PROBE_PROC:-/proc}/$1/stat" 2>/dev/null) || return 1
    _s=${_s##*) }
    case $_s in Z* | X* | x*) return 1 ;; esac
    printf '%s\n' "$_s" | awk 'NF >= 20 { print $20; ok = 1 } END { exit ok ? 0 : 1 }'
}

# container_absent ID: 0 only when the daemon answered and listed nothing.
container_absent() {
    _out=$(docker ps -a -q --no-trunc --filter "id=$1") || return 1
    [ -z "$_out" ]
}

# path_absent PATH: 0 only when PATH's parent was listed successfully and the
# name is not in that listing (no reliance on `test -e`, which cannot tell a
# missing path from a lookup failure). Nonzero otherwise.
path_absent() {
    _parent=$(dirname -- "$1")
    _base=$(basename -- "$1")
    _list=$(ls -1A -- "$_parent" 2>/dev/null) || return 1
    _nl='
'
    case "$_nl$_list$_nl" in *"$_nl$_base$_nl"*) return 1 ;; esac
    return 0
}

# probe_cleanup: release every tracked resource and verify it is gone. Returns
# nonzero, keeping the scratch directory, if anything could not be verified.
# Idempotent: released resources are removed from the tracking lists.
probe_cleanup() {
    [ "$PROBE_MODE" = live ] || return 0
    _ok=0
    for _p in $PROBE_PIDS; do
        kill "$_p" 2>/dev/null || true
        wait "$_p" 2>/dev/null || true
        if [ -d "/proc/$_p" ]; then _ok=1; fi
    done
    PROBE_PIDS=
    _left=
    for _c in $PROBE_CONTAINERS; do
        docker rm -f -v "$_c" >/dev/null 2>&1 || true
        if ! container_absent "$_c"; then _ok=1; _left="$_left $_c"; fi
    done
    PROBE_CONTAINERS=$_left
    _left=
    for _n in $PROBE_NAMES; do
        if _ids=$(docker ps -a -q --no-trunc --filter "name=^/$_n\$"); then
            for _c in $_ids; do docker rm -f -v "$_c" >/dev/null 2>&1 || true; done
            if ! _ids=$(docker ps -a -q --no-trunc --filter "name=^/$_n\$") || [ -n "$_ids" ]; then
                _ok=1; _left="$_left $_n"
            fi
        else
            _ok=1; _left="$_left $_n"
        fi
    done
    PROBE_NAMES=$_left
    _left=
    for _v in $PROBE_VOLUMES; do
        docker volume rm -f "$_v" >/dev/null 2>&1 || true
        if ! _out=$(docker volume ls -q --filter "name=^$_v\$") || [ -n "$_out" ]; then
            _ok=1; _left="$_left $_v"
        fi
    done
    PROBE_VOLUMES=$_left
    # A volume that appeared during the probe and was not tracked is possible
    # residue. It is never removed here (it may not be ours); its presence makes
    # cleanup unverified, and its name is reported for the operator.
    if [ -n "${PROBE_VOLS_BEFORE:-}" ]; then
        if _now=$(docker volume ls -q); then
            for _v in $_now; do
                case " $PROBE_VOLS_BEFORE " in *" $_v "*) continue ;; esac
                printf 'INFO untracked-volume %s\n' "$_v"
                _ok=1
            done
        else
            _ok=1
        fi
    fi
    _left=
    for _m in $PROBE_MOUNTS; do
        if is_mounted "$_m"; then umount "$_m" 2>/dev/null || true; fi
        # Written as an if so `set -e` cannot end cleanup on the expected 1.
        if is_mounted "$_m"; then _st=0; else _st=$?; fi
        if [ "$_st" != 1 ]; then _ok=1; _left="$_left $_m"; fi
    done
    PROBE_MOUNTS=$_left
    # Once any cleanup could not be verified, the scratch directory is kept for
    # inspection for the rest of the run, including the EXIT trap's retry.
    if [ "$_ok" != 0 ]; then PROBE_KEEP=1; fi
    if [ "$PROBE_KEEP" = 0 ] && [ -n "$PROBE_SCRATCH" ]; then
        # --one-file-system: never descend into a mount cleanup failed to see.
        rm -rf --one-file-system -- "$PROBE_SCRATCH" 2>/dev/null || true
        if path_absent "$PROBE_SCRATCH"; then PROBE_SCRATCH=; else _ok=1; PROBE_KEEP=1; fi
    fi
    return "$_ok"
}

require_root() {
    [ "$(id -u)" = 0 ] || probe_die 'root-required'
}

require_image() {
    printf '%s\n' "$PROBE_IMAGE_ID" | grep -Eq '^sha256:[0-9a-f]{64}$' || probe_die 'image-id-invalid'
    _id=$(docker image inspect --format '{{.Id}}' "$PROBE_IMAGE_ID") || probe_die 'image-absent'
    [ "$_id" = "$PROBE_IMAGE_ID" ] || probe_die 'image-id-mismatch'
}

# runner_idle: the named unit must exist (LoadState loaded) and be inactive or
# failed. A typo'd unit reads LoadState not-found and refuses.
runner_idle() {
    [ -n "$PROBE_RUNNER_UNIT" ] || return 1
    _load=$(systemctl show -p LoadState --value -- "$PROBE_RUNNER_UNIT") || return 1
    [ "$_load" = loaded ] || return 1
    _state=$(systemctl show -p ActiveState --value -- "$PROBE_RUNNER_UNIT") || return 1
    case $_state in inactive | failed) return 0 ;; *) return 1 ;; esac
}

# require_runner_idle: checked at start and again before verdicts
# (recheck_runner). Stated limits: the script cannot prove the named unit IS
# the runner (the operator supplies it), and a runner start between the two
# checks is not excluded. The operator stops the runner's timer for the probe
# run, as for a window.
require_runner_idle() {
    runner_idle || probe_die 'runner-not-idle'
}

recheck_runner() {
    runner_idle || probe_die 'runner-became-active'
}

# ---- Container storage (P5, P6) ----
#
# Two storage kinds are supported, and each is identified by more than its
# driver name:
#   overlay2              the classic graph driver
#   containerd-overlayfs  the containerd image store: driver "overlayfs" with
#                         exactly one DriverStatus driver-type of
#                         io.containerd.snapshotter.v1
# Anything else refuses by name (driver-unsupported). A container's upper
# directory is then read from the KERNEL, not from `docker inspect`: the one
# overlay mount at "/" in its init process's mountinfo (overlay_upper), resolved
# and shape-checked for its kind (upper_resolve), cross-checked against the
# graph driver's own record on overlay2, and finally proven to be this
# container's by a random marker written inside it appearing there.

# storage_kind_from DRIVER STATUS: the storage kind for a `docker info` driver
# name and its DriverStatus pairs (one "key=value" per line). Prints overlay2
# or containerd-overlayfs, or exits 1. Pure.
storage_kind_from() {
    case $1 in
        overlay2) printf 'overlay2\n' ;;
        overlayfs)
            _t=$(printf '%s\n' "$2" | awk -F= '
                $1 == "driver-type" { n++; v = substr($0, 13) }
                END { if (n != 1) exit 1; print v }') || return 1
            [ "$_t" = io.containerd.snapshotter.v1 ] || return 1
            printf 'containerd-overlayfs\n'
            ;;
        *) return 1 ;;
    esac
}

# overlay_upper MOUNTINFO: the raw upperdir= value of the one overlay mount at
# "/" in a mountinfo table. Exits 1 unless every row is well formed (the "-"
# separator after at least six fields, exactly three fields after it, numeric
# ids, major:minor, absolute root and mountpoint), exactly one row is mounted
# at "/", that row is overlay, and its super options carry exactly one
# non-empty upperdir=. Pure.
overlay_upper() {
    awk '
        NF == 0 { next }
        {
            s = 0
            for (i = 7; i <= NF; i++) if ($i == "-") { s = i; break }
            if (!s || NF != s + 3 || $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9]+$/ \
                || $3 !~ /^[0-9]+:[0-9]+$/ || $4 !~ /^\// || $5 !~ /^\//) { bad = 1; next }
            rows++
            if ($5 != "/") next
            n++
            fs = $(s + 1)
            so = $(s + 3)
        }
        END {
            if (bad || rows < 1 || n != 1 || fs != "overlay") exit 1
            c = split(so, o, ",")
            u = 0
            for (i = 1; i <= c; i++) if (substr(o[i], 1, 9) == "upperdir=") { u++; v = substr(o[i], 10) }
            if (u != 1 || v == "") exit 1
            print v
        }' "$1"
}

# upper_resolve KIND DOCKER-ROOT RAW: the absolute upper directory for a raw
# upperdir= value, or exit 1. Only plain path characters are accepted, so an
# escaped (backslash) value fails closed; no "." or ".." component and no
# empty component. overlay2 must be DOCKER-ROOT/overlay2/<hex id>/diff; the
# driver passes "<hex id>/diff" relative to DOCKER-ROOT/overlay2 when its mount
# options are long, so that one relative shape is resolved. The containerd
# snapshotter must be absolute .../io.containerd.snapshotter.v1.overlayfs/
# snapshots/<number>/fs. Pure.
upper_resolve() {
    _p=$3
    case $2 in /?* ) ;; *) return 1 ;; esac
    for _x in "$2" "$_p"; do
        case $_x in '' | *//* | *[!A-Za-z0-9/._-]*) return 1 ;; esac
        case /$_x/ in */./* | */../*) return 1 ;; esac
    done
    case $1 in
        overlay2)
            case $_p in /*) ;; *) _p=$2/overlay2/$_p ;; esac
            _rest=${_p#"$2"/overlay2/}
            [ "$_rest" != "$_p" ] || return 1
            _id=${_rest%/diff}
            [ "$_id" != "$_rest" ] || return 1
            case $_id in '' | *[!0-9a-f]*) return 1 ;; esac
            ;;
        containerd-overlayfs)
            _base=${_p%/fs}
            [ "$_base" != "$_p" ] || return 1
            is_uint "${_base##*/}" || return 1
            case ${_base%/*} in /?*/io.containerd.snapshotter.v1.overlayfs/snapshots) ;; *) return 1 ;; esac
            ;;
        *) return 1 ;;
    esac
    printf '%s\n' "$_p"
}

# require_overlay_storage: set PROBE_STORAGE and PROBE_DOCKER_ROOT, or refuse.
require_overlay_storage() {
    _driver=$(docker info --format '{{.Driver}}') || probe_die 'driver-unreadable'
    _status=$(docker info --format '{{range .DriverStatus}}{{index . 0}}={{index . 1}}{{println}}{{end}}') \
        || probe_die 'driver-unreadable'
    PROBE_STORAGE=$(storage_kind_from "$_driver" "$_status") || probe_die 'driver-unsupported'
    PROBE_DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}') || probe_die 'driver-unreadable'
    info "storage $PROBE_STORAGE"
}

# _upper_pid_same ID PID IDENT: the container still reports PID as its init,
# and PID is still the same process (same start time).
_upper_pid_same() {
    _n=$(proc_identity "$2") || return 1
    _p=$(docker inspect --format '{{.State.Pid}}' "$1") || return 1
    [ "$_n" = "$3" ] && [ "$_p" = "$2" ]
}

# marker_matches FD TOKEN: exit 0 only if "tmp/TOKEN", resolved relative to
# the directory held on FD, is a regular file whose bytes are exactly TOKEN
# (no trailing newline). The whole lookup is ONE openat2(2) call with
# RESOLVE_BENEATH | RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS: it cannot leave the
# held directory, follow any symlink, or cross a mount (a bind of another
# tree's tmp over this one), and no path can be swapped between a test and
# the read. A kernel without openat2 (before 5.6) fails closed. The syscall
# number is 437 on x86-64 and AArch64 only (other ABIs differ: MIPS n64 is
# 5437), so any other machine exits 3, which the caller refuses by name.
# python3 -I with ctypes (stdlib only); the held FD is inherited by the child.
marker_matches() {
    python3 -I -c '
import ctypes, os, platform, stat, sys
if platform.machine() not in ("x86_64", "aarch64") or ctypes.sizeof(ctypes.c_void_p) != 8:
    sys.exit(3)
fd, tok = int(sys.argv[1]), sys.argv[2]
if not tok or "/" in tok:
    sys.exit(1)
class OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]
RESOLVE_NO_XDEV, RESOLVE_NO_SYMLINKS, RESOLVE_BENEATH = 0x01, 0x04, 0x08
SYS_OPENAT2 = 437  # x86-64 and AArch64 (checked above)
how = OpenHow(os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0,
              RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH)
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
libc.syscall.argtypes = (ctypes.c_long,)
m = libc.syscall(ctypes.c_long(SYS_OPENAT2), ctypes.c_int(fd), ("tmp/" + tok).encode(),
                 ctypes.byref(how), ctypes.c_size_t(ctypes.sizeof(how)))
if m < 0:
    sys.exit(1)
try:
    if not stat.S_ISREG(os.fstat(m).st_mode):
        sys.exit(1)
    want = tok.encode()
    sys.exit(0 if os.read(m, len(want) + 1) == want else 1)
finally:
    os.close(m)
' "$1" "$2" 2>/dev/null
}

# upper_dir_of ID FD: open a RUNNING container's upper directory on FD (8 or
# 9) and set PROBE_UPPER to /proc/$$/fd/FD, or refuse by name. Called directly
# (never in a command substitution), so a refusal ends the probe. The
# directory is HELD before it is proven, and the proof and every later read go
# through that handle, so renaming or re-linking any ancestor afterwards
# cannot substitute another directory. The init pid is revalidated after the
# mountinfo read and again after the proof. PROBE_PROC (default /proc) is the
# procfs the container's pid is read from; the self-test points it at a stub.
upper_dir_of() {
    PROBE_UPPER=
    case $2 in 8 | 9) ;; *) probe_die 'upper-fd-invalid' ;; esac
    _pid=$(docker inspect --format '{{.State.Pid}}' "$1") || probe_die 'inspect-failed'
    if ! is_uint "$_pid" || [ "$_pid" -eq 0 ]; then probe_die 'container-pid-invalid'; fi
    _ident=$(proc_identity "$_pid") || probe_die 'container-pid-gone'
    _raw=$(overlay_upper "${PROBE_PROC:-/proc}/$_pid/mountinfo") || probe_die 'upperdir-unreadable'
    _upper_pid_same "$1" "$_pid" "$_ident" || probe_die 'container-pid-changed'
    if ! _up=$(upper_resolve "$PROBE_STORAGE" "$PROBE_DOCKER_ROOT" "$_raw"); then
        # The refused value, scrubbed and bounded, so a new runtime shape is
        # recorded rather than only refused.
        info "diag setup upperdir-raw $(printf '%s' "$_raw" | head -c 512 | LC_ALL=C tr -c '[:print:]' '?')"
        probe_die 'upperdir-shape'
    fi
    if [ "$PROBE_STORAGE" = overlay2 ]; then
        _gd=$(docker inspect --format '{{.GraphDriver.Data.UpperDir}}' "$1") || probe_die 'inspect-failed'
        [ "$_gd" = "$_up" ] || probe_die 'upperdir-disagrees'
    fi
    if [ ! -d "$_up" ] || [ -L "$_up" ]; then probe_die 'upperdir-missing'; fi
    # `command` keeps a failed redirection from ending the shell (exec is a
    # special builtin), so a vanished directory refuses by name.
    if [ "$2" = 9 ]; then
        command exec 9<"$_up" || probe_die 'upperdir-open-failed'
    else
        command exec 8<"$_up" || probe_die 'upperdir-open-failed'
    fi
    _held=/proc/$$/fd/$2
    # Proof of identity: a fresh random token, written by this container into
    # its own /tmp, must read back exactly through the held handle
    # (marker_matches, descriptor-relative throughout).
    _tok=$(probe_uuid) || probe_die 'uuid-failed'
    case $_tok in '' | *[!0-9a-f]*) probe_die 'uuid-failed' ;; esac
    [ "${#_tok}" -eq 32 ] || probe_die 'uuid-failed'
    _tok=skillc-dev-probe-id-$_tok
    docker exec "$1" sh -c 'printf "%s" "$1" >"/tmp/$1"' sh "$_tok" >/dev/null 2>&1 \
        || probe_die 'upperdir-mark-failed'
    _mm=0
    marker_matches "$2" "$_tok" || _mm=$?
    case $_mm in
        0) ;;
        3) probe_die 'marker-arch-unsupported' ;;
        *) probe_die 'upperdir-unverified' ;;
    esac
    _upper_pid_same "$1" "$_pid" "$_ident" || probe_die 'container-pid-changed'
    PROBE_UPPER=$_held
}

# ---- In-container scans (P7, P8) ----
#
# SCAN_LIB is sh source the P7 inventory and the P8 socket scan prepend to
# the script they run inside the container, and that the self-test runs
# against crafted trees as an unprivileged uid. It holds the one prune rule.
# shellcheck disable=SC2016  # expands inside the container
SCAN_LIB='
# scan PRUNED ROOT XDEV EXCLUDES TEST...: GNU find over ROOT printing every
# path that matches TEST (find primaries), with two kinds of pruning:
# - each absolute path in EXCLUDES (space-separated) is pruned unexamined;
# - a directory this uid cannot SEARCH is pruned, and its path is appended to
#   PRUNED, but ONLY when every one of these holds: access(2) X_OK as this
#   uid says no (`! -executable`, evaluated once per directory); the mode
#   bits of the class that applies to this uid (group if the directory group
#   is one of its groups, else other) grant no search; it is not owned by
#   this uid (which could chmod it); its full path has no newline; and, checked
#   after the walk, it carries no ACL, so the mode bits are the whole
#   permission and the denial cannot be an I/O error standing in for one. Without
#   search permission nothing at or below the directory can be created,
#   renamed, unlinked or opened (a socket included) by a fresh path lookup
#   from this root. That holds for write without search too: write alone
#   permits no entry change, so such a directory is never counted writable.
# A denial the mode bits do not explain (an ACL, an I/O error), a directory
# owned by this uid, a path containing a newline, or a pruned directory that
# carries an ACL is AMBIGUOUS: it is not descended, and scan returns 1. A directory the uid can search
# but not read is not pruned: find fails to list it and scan returns 1. Any
# other find error returns 1. If anything was pruned, the scan identity must
# also be plain: a non-root uid, real, effective, saved and filesystem ids
# equal, and no effective or permitted capability (so access(2) answers for
# the lookups it stands for). It is read from this shell process status,
# the credentials find is started from; a set-id or file-capability find
# binary is outside the scan scope.
# XDEV is "xdev" or "all". The verdict this supports is scoped to fresh
# pathname lookup from ROOT under this identity, at the observation instant,
# in a quiescent tree: the probe container runs no other process that could
# change it while the scan runs (see the probes README).
scan() {
    _pr=$1
    _root=$2
    _xd=$3
    _ex=$4
    shift 4
    _u=$(id -u) || return 1
    _gs=$(id -G) || return 1
    case "$_u $_gs" in *[!0-9\ ]*) return 1 ;; esac
    _g=
    for _x in $_gs; do _g="$_g${_g:+ -o} -gid $_x"; done
    [ -n "$_g" ] || return 1
    _nlpat=$(printf "*\n*_")
    _nlpat=${_nlpat%_}
    : >"$_pr.amb" || return 1
    # One access(2) evaluation per directory: an unsearchable directory is
    # recorded as AMBIGUOUS or as PRUNED by the same test, then pruned.
    eval "set -- \\( -type d ! -executable \\( \\( \\( -path \"\$_nlpat\" -o -uid $_u -o ! \\( \\( \\( $_g \\) ! -perm -g+x \\) -o \\( ! \\( $_g \\) ! -perm -o+x \\) \\) \\) -fprint \"\$_pr.amb\" \\) -o -fprintf \"\$_pr.new\" \"%D %i %p\\\\n\" \\) -prune \\) -o \\( \"\$@\" \\) -print"
    for _e in $_ex; do set -- \( -path "$_e" -prune \) -o "$@"; done
    if [ "$_xd" = xdev ]; then set -- -xdev "$@"; fi
    find "$_root" "$@" || return 1
    [ ! -s "$_pr.amb" ] || return 1
    if [ -s "$_pr.new" ]; then
        scan_identity_plain || return 1
        scan_recheck "$_pr.new" "$_u" "$_g" || return 1
    fi
    cut -d " " -f 3- "$_pr.new" >>"$_pr" || return 1
    rm -f "$_pr.new" "$_pr.amb"
}
# scan_identity_plain: a non-root uid, real, effective, saved and filesystem
# uids and gids equal, and all-zero effective and permitted capability sets,
# read from /proc/self (the reading process inherits this shell identity).
scan_identity_plain() {
    awk "\$1 == \"Uid:\" { u = (\$2 != 0 && \$2 == \$3 && \$3 == \$4 && \$4 == \$5); nu++ }
         \$1 == \"Gid:\" { g = (\$2 == \$3 && \$3 == \$4 && \$4 == \$5); ng++ }
         \$1 == \"CapEff:\" { c = (\$2 ~ /^0+\$/); nc++ }
         \$1 == \"CapPrm:\" { p = (\$2 ~ /^0+\$/); np++ }
         END { exit (nu == 1 && ng == 1 && nc == 1 && np == 1 && u && g && c && p) ? 0 : 1 }" \
        "/proc/$$/status"
}
# scan_recheck PRUNED U G: after the walk, each pruned directory (recorded as
# "DEV INO PATH") must have no symlink component and no ancestor up to /
# that lets this uid replace a path component (owned or writable by it,
# unless sticky, owned by another, and over an entry it does not own),
# must still be the
# same inode, list (with its inode, which must match) with a plain mode string
# ("d" and nine permission characters, optionally "." for an SELinux context,
# never "+" for an ACL), and then still match the prune predicate: not
# searchable, no search bit in its class, not owned by U. Listing then
# re-matching means a change between the walk and the check is seen, unless
# another uid changes the directory and changes it back in between, which is
# outside the scan scope.
scan_recheck() {
    while IFS= read -r _rec; do
        _d=${_rec%% *}
        _r=${_rec#* }
        _i=${_r%% *}
        _p=${_r#* }
        case $_p in /*) ;; *) return 1 ;; esac
        # No path component may be a symlink, and no ancestor up to / may let
        # this uid replace the next component: the ancestor is neither owned
        # nor writable by this uid, or it is sticky, not owned by this uid,
        # and the next component is not owned by this uid either (a sticky
        # directory lets only the entry or directory owner rename or replace
        # an entry). So no component can be substituted between the steps
        # below.
        _c=$_p
        _a=${_p%/*}
        while :; do
            _y=$(find "$_c" -maxdepth 0 -type l) || return 1
            [ -z "$_y" ] || return 1
            _x=$(find "$_a/" -maxdepth 0 \( -uid "$2" -o -writable \)) || return 1
            if [ -n "$_x" ]; then
                _k=$(find "$_a/" -maxdepth 0 -perm -1000 ! -uid "$2") || return 1
                _o=$(find "$_c" -maxdepth 0 ! -uid "$2") || return 1
                if [ -z "$_k" ] || [ -z "$_o" ]; then return 1; fi
            fi
            [ -n "$_a" ] || break
            _c=$_a
            _a=${_a%/*}
        done
        # The listing carries its inode, which must be the walk inode, so the
        # ACL observation is of the directory the two finds identify.
        _l=$(ls -ldi -- "$_p") || return 1
        [ "${_l%% *}" = "$_i" ] || return 1
        _l=${_l#* }
        case ${_l%% *} in d?????????  | d?????????.) ;; *) return 1 ;; esac
        eval "_m=\$(find \"\$_p\" -maxdepth 0 -type d ! -executable ! -uid $2 \\( \\( \\( $3 \\) ! -perm -g+x \\) -o \\( ! \\( $3 \\) ! -perm -o+x \\) \\) -printf \"%D %i\")" \
            || return 1
        [ "$_m" = "$_d $_i" ] || return 1
    done <"$1"
}
# scan_quiescent: exit 0 only if this pid namespace holds no process outside
# the scan. Every process must be this shell, a descendant of it, or pid 1
# when pid 1 is a different process with no children (P8: an idle sleep that
# the scan was exec-ed beside). Any other process, a parent that cannot be
# found, or a /proc that cannot be listed fails. The prune rule ASSUMES a
# quiescent container; this check is that precondition, run before a scan.
scan_quiescent() {
    _ps=$(for _q in $(ls /proc); do
        case $_q in *[!0-9]*) continue ;; esac
        _pp=$(awk "\$1 == \"PPid:\" { print \$2 }" "/proc/$_q/status" 2>/dev/null) || continue
        [ -n "$_pp" ] && printf "%s %s\n" "$_q" "$_pp"
    done) || return 1
    printf "%s\n" "$_ps" | awk -v me="$$" "
        NF == 2 { pp[\$1] = \$2; n++ }
        END {
            if (n < 1 || !(me in pp)) exit 1
            for (p in pp) if (pp[p] == 1 && me != 1) kids1++
            for (p in pp) {
                q = p; ok = 0
                for (hop = 0; hop < 4096; hop++) {
                    if (q == me) { ok = 1; break }
                    if (q == 1 && me != 1 && !kids1) { ok = 1; break }
                    if (!(q in pp)) break
                    q = pp[q]
                }
                if (!ok) exit 1
            }
        }"
}
# pruned_lines PRUNED: one "PRUNED <path>" line per pruned directory, or
# "PRUNED-W <path>" for one this uid may write but not search. Paths never
# contain a newline (scan refuses those).
pruned_lines() {
    [ -s "$1" ] || return 0
    while IFS= read -r _p; do
        if [ -w "$_p" ]; then printf "PRUNED-W %s\n" "$_p"; else printf "PRUNED %s\n" "$_p"; fi
    done <"$1"
}
'

# scan_report ARM OUTPUT: split an in-container scan's output into its first
# line, set as SCAN_HEAD, and its "PRUNED <path>" / "PRUNED-W <path>" lines.
# A tag must be exact and its path absolute. Each is reported as
# `INFO pruned <arm> <path> unsearchable`, plus
# ` writable-without-search` for PRUNED-W. Bytes outside printable ASCII
# become '?', and at most 64 are listed, then a count. Returns 1 if any other
# line appears, so unexpected output is an observation failure. Pure.
scan_report() {
    SCAN_HEAD=$(printf '%s\n' "$2" | sed -n 1p)
    printf '%s\n' "$2" | LC_ALL=C awk -v a="$1" '
        NR == 1 { next }
        /^PRUNED \// || /^PRUNED-W \// {
            n++
            if (n <= 64) {
                p = substr($0, index($0, " ") + 1)
                gsub(/[^ -~]/, "?", p)
                w = ($1 == "PRUNED-W") ? " writable-without-search" : ""
                print "INFO pruned " a " " p " unsearchable" w
            }
            next
        }
        { bad = 1 }
        END {
            if (n > 64) print "INFO pruned " a " truncated " n
            exit bad ? 1 : 0
        }'
}

# ---- Step diagnostics (P5, P7, P8) ----

# step_drain FILE: read stdin to EOF, keeping only its first 2048 bytes in
# FILE and the count of the rest in FILE.rest. dd reads one byte at a time, so
# nothing past the bound is ever written to disk, whatever the input size. If
# FILE cannot be written, the input is still drained (to /dev/null), so the
# writer never blocks or dies on a closed pipe. Never fails its caller.
step_drain() {
    if ! dd bs=1 count=2048 of="$1" 2>/dev/null; then cat >/dev/null; return 0; fi
    _r=$(wc -c | tr -d ' ') || _r=
    printf '%s\n' "$_r" >"$1.rest" 2>/dev/null || :
}

# step_capture FILE CMD...: run CMD (a command or a function) with its stdout
# passed through unchanged and its stderr drained through step_drain into
# FILE. Returns CMD's own exit status, which travels through a pipe into a
# shell variable, never through a file, so no storage failure (a full or
# unwritable scratch) can replace it. 125 only if the status cannot be read.
step_capture() {
    _ef=$1
    shift
    # The step runs as an `if` condition: under `set -e` (dash applies it in
    # this pipeline subshell) a failing step would otherwise end the subshell
    # before its status is written.
    { _st=$( { { if "$@" 2>&1 1>&4 4>&- 5>&-; then _s=0; else _s=$?; fi
        printf '%s' "$_s" >&5; } \
        | step_drain "$_ef" >/dev/null 2>&1 4>&- 5>&-; } 5>&1 ); } 4>&1
    is_uint "$_st" || return 125
    return "$_st"
}

# step_diag ARM STEP STATUS FILE: report a live step's exit status and the
# kept stderr (at most 2048 bytes) as INFO lines, so an OBSERVATION_FAILED
# names its cause. Every byte outside printable ASCII becomes '?', and every
# line gets the INFO prefix and its own newline, so no stderr text can print
# as an ARM or PROBE line or run into the next line. Diagnostic only: nothing
# here is recorded as a reading, no verdict depends on it, and it never fails
# its caller.
step_diag() {
    printf 'INFO diag %s %s exit %s\n' "$1" "$2" "$3"
    [ -s "$4" ] || return 0
    head -c 2048 -- "$4" | LC_ALL=C tr -c '\n[:print:]' '?' \
        | LC_ALL=C awk -v a="$1" -v s="$2" '{ print "INFO diag " a " " s " stderr: " $0 }' || :
    _bytes=$(wc -c <"$4" | tr -d ' ') || _bytes=
    if [ -f "$4.rest" ]; then
        _rest=$(cat -- "$4.rest") || _rest=
        if is_uint "$_rest" && is_uint "$_bytes"; then _bytes=$((_bytes + _rest)); else _bytes=; fi
    fi
    if is_uint "$_bytes" && [ "$_bytes" -gt 2048 ]; then
        printf 'INFO diag %s %s stderr-truncated %s\n' "$1" "$2" "$_bytes"
    fi
    return 0
}

# scratch_private: make the scratch directory its own PRIVATE mountpoint
# before anything is mounted under it, so no probe mount propagates into peer
# mount namespaces (/ and /run are usually shared on systemd hosts). Making a
# mount private after mounting it would be too late: the mount event has
# already propagated by then.
scratch_private() {
    mount --bind "$PROBE_SCRATCH" "$PROBE_SCRATCH" || probe_die 'scratch-bind-failed'
    track_mount "$PROBE_SCRATCH"
    mount --make-private "$PROBE_SCRATCH" || probe_die 'scratch-private-failed'
}

# mount_tmpfs PATH: mount a 1 MiB 0700 tmpfs at PATH and track it.
mount_tmpfs() {
    mkdir -p "$1"
    mount -t tmpfs -o size=1m,mode=0700 skillc-dev-probe "$1" || probe_die 'mount-failed'
    track_mount "$1"
}

# create_container ARGS...: `docker create`, then track the returned full ID in
# $cid. Cleanup removes only IDs this probe created, never a name match.
create_container() {
    if [ -z "${PROBE_VOLS_BEFORE:-}" ]; then
        _before=$(docker volume ls -q) || probe_die 'volume-list-failed'
        PROBE_VOLS_BEFORE=" $(printf '%s\n' "$_before" | tr '\n' ' ')"
    fi
    _name="skillc-dev-probe-$PROBE_NAME-$(probe_uuid)"
    track_name "$_name"
    cid=$(docker create --name "$_name" "$@") || probe_die 'create-failed'
    printf '%s\n' "$cid" | grep -Eq '^[0-9a-f]{64}$' || probe_die 'create-id-malformed'
    track_container "$cid"
    # Any volume the image declares is created with the container: track it so
    # cleanup removes and verifies it, rather than trusting `rm -v`.
    _vols=$(docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' \
        "$cid") || probe_die 'volume-inspect-failed'
    for _v in $_vols; do PROBE_VOLUMES="$PROBE_VOLUMES $_v"; done
}
