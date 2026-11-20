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
    # its own /tmp, must read back exactly through the held handle.
    _tok=$(probe_uuid) || probe_die 'uuid-failed'
    case $_tok in '' | *[!0-9a-f]*) probe_die 'uuid-failed' ;; esac
    [ "${#_tok}" -eq 32 ] || probe_die 'uuid-failed'
    _tok=skillc-dev-probe-id-$_tok
    docker exec "$1" sh -c 'printf "%s" "$1" >"/tmp/$1"' sh "$_tok" >/dev/null 2>&1 \
        || probe_die 'upperdir-mark-failed'
    _m=$_held/tmp/$_tok
    if [ -L "$_held/tmp" ] || [ ! -f "$_m" ] || [ -L "$_m" ]; then probe_die 'upperdir-unverified'; fi
    _got=$(cat -- "$_m") || probe_die 'upperdir-unverified'
    [ "$_got" = "$_tok" ] || probe_die 'upperdir-unverified'
    _upper_pid_same "$1" "$_pid" "$_ident" || probe_die 'container-pid-changed'
    PROBE_UPPER=$_held
}

# ---- Step diagnostics (P5, P7, P8) ----

# step_drain FILE: read stdin to EOF, keeping only its first 2048 bytes in
# FILE and the count of the rest in FILE.rest. dd reads one byte at a time, so
# nothing past the bound is ever written to disk, whatever the input size,
# and the input is always drained, so the writer never blocks or dies on a
# closed pipe. Never fails its caller.
step_drain() {
    dd bs=1 count=2048 of="$1" 2>/dev/null || :
    wc -c | tr -d ' ' >"$1.rest" || :
}

# step_capture FILE CMD...: run CMD (a command or a function) with its stdout
# passed through unchanged and its stderr drained through step_drain into
# FILE. Returns CMD's own exit status, or 125 if that status could not be
# read back. A failure of the collector never changes the returned status.
step_capture() {
    _ef=$1
    shift
    : >"$_ef.status"
    { { "$@" 2>&3 3>&-; printf '%s\n' "$?" >"$_ef.status"; } 3>&1 1>&4 4>&- | step_drain "$_ef"; } 4>&1
    _s=$(cat -- "$_ef.status" 2>/dev/null) || return 125
    is_uint "$_s" || return 125
    return "$_s"
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
