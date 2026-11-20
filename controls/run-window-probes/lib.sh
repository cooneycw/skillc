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
    _s=$(cat -- "/proc/$1/stat" 2>/dev/null) || return 1
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

require_overlay2() {
    _driver=$(docker info --format '{{.Driver}}') || probe_die 'driver-unreadable'
    [ "$_driver" = overlay2 ] || probe_die 'driver-not-overlay2'
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
