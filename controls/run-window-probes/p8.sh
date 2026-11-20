#!/bin/sh
# P8 (#797 fact 2b): container channel isolation. A holder container has
# private network, IPC, mount and PID namespaces (compared by namespace
# identity against PID 1), no bind mount that is or contains a host socket,
# and no socket fd in its init process. A corroborating arm records the known
# limit of queue-length checks: a zero-byte Unix datagram carries SCM_RIGHTS
# while FIONREAD reads 0. ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p8.sh --image-id sha256:<64 hex> --runner-unit <unit>
#
# Each docker arm prints `INFO diag <arm> binds|scan exit <status>` and up to
# 2 KiB of that step's stderr (lib.sh step_diag); no verdict reads them.
#
# Arms and expected verdicts:
#   clean     private namespaces, no socket bind or fd, and
#             no socket file visible inside the container   CONFIRMED_NEGATIVE
#   sockbind  a planted host socket bind, and a planted bind
#             of a directory that contains a socket         SURVIVOR_OBSERVED
#   hostnet   --network host shares the host netns          SURVIVOR_OBSERVED
#   zerobyte  exactly one fd for the planted file arrives in
#             an empty datagram while FIONREAD reads 0      SURVIVOR_OBSERVED
#   fault     the container pid cannot be read              OBSERVATION_FAILED
set -eu
PROBE_NAME=p8
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# socket_binds ID: count bind mounts whose source is a socket or a directory
# containing one. Structured inspect output; any unreadable source fails.
# shellcheck disable=SC2317  # invoked through step_capture
socket_binds() {
    _j=$(docker inspect --format '{{json .Mounts}}' "$1") || return 1
    printf '%s\n' "$_j" | python3 -I -c '
import json, os, stat, sys
mounts = json.load(sys.stdin)
if not isinstance(mounts, list):
    sys.exit(1)
planted = {"/probe-host.sock", "/probe-sockdir"}
count = 0
hit = set()
def fail(err):
    raise err
for m in mounts:
    if not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ("Type", "Source", "Destination")):
        sys.exit(1)
    if m["Type"] not in ("bind", "volume", "tmpfs", "npipe", "cluster", "image"):
        sys.exit(1)
    if m["Type"] != "bind":
        continue
    src, dst = m["Source"], m["Destination"]
    st = os.lstat(src)
    found = 0
    if stat.S_ISSOCK(st.st_mode):
        found = 1
    elif stat.S_ISDIR(st.st_mode):
        for root, dirs, files in os.walk(src, onerror=fail):
            for name in dirs + files:
                if stat.S_ISSOCK(os.lstat(os.path.join(root, name)).st_mode):
                    found += 1
    count += found
    if found and dst in planted:
        hit.add(dst)
print(count, len(hit))
'
}

# isolation ARM ID: record shared namespaces, socket binds and socket fds.
isolation() {
    pid=$(docker inspect --format '{{.State.Pid}}' "$2" 2>/dev/null) || pid=
    if ! is_uint "$pid" || [ "$pid" -eq 0 ] || [ ! -d "/proc/$pid" ]; then
        record "$1" shared_ns ERR
        record "$1" socket_binds ERR
        record "$1" socket_fds ERR
        return
    fi
    ident=$(proc_identity "$pid") || ident=
    shared=0
    ok=1
    [ -n "$ident" ] || ok=0
    shared_net=0
    for ns in net ipc mnt pid; do
        if c=$(readlink "/proc/$pid/ns/$ns") && h=$(readlink "/proc/1/ns/$ns"); then
            if [ "$c" = "$h" ]; then
                shared=$((shared + 1))
                if [ "$ns" = net ]; then shared_net=1; fi
            fi
        else
            ok=0
            info "diag $1 ns-$ns unreadable"
        fi
    done
    if [ "$ok" = 1 ]; then
        record "$1" shared_ns "$shared"
        record "$1" shared_net "$shared_net"
    else
        record "$1" shared_ns ERR
        record "$1" shared_net ERR
    fi
    _rc=0
    b=$(step_capture "$PROBE_SCRATCH/$1.binds.err" socket_binds "$2") || _rc=$?
    step_diag "$1" binds "$_rc" "$PROBE_SCRATCH/$1.binds.err"
    if [ "$_rc" -eq 0 ] && is_uint "${b% *}" && is_uint "${b#* }"; then
        record "$1" socket_binds "${b% *}"
        record "$1" planted_binds "${b#* }"
    else
        record "$1" socket_binds ERR
        record "$1" planted_binds ERR
    fi
    # The container's own view: socket files it can see outside /proc and /sys.
    # `set -e` plus a plain assignment: a find(1) that fails, or is missing,
    # fails the whole scan rather than counting zero.
    # shellcheck disable=SC2016
    # Prints the total and how many of the two planted destinations show a
    # socket (the file bind itself; anything beneath the directory bind).
    _rc=0
    # shellcheck disable=SC2016  # expands inside the container
    # The scan prunes directories this uid cannot search (lib.sh SCAN_LIB) and
    # fails on one it can search but not list. The prune rule ASSUMES a
    # quiescent container (an idle sleep plus this scan, checked first by
    # scan_quiescent); it must not be reused as-is against a container with
    # live participant processes.
    v=$(step_capture "$PROBE_SCRATCH/$1.scan.err" docker exec "$2" sh -c "$SCAN_LIB"'set -e
scan_quiescent sleep || { printf "scan: container not quiescent\n" >&2; exit 3; }
t=$(mktemp -d)
trap "rm -rf \"$t\"" EXIT
o=$(scan "$t/pruned" / all "/proc /sys" -type s)
scan_quiescent sleep || { printf "scan: container not quiescent after the scan\n" >&2; exit 3; }
n=$(printf "%s\n" "$o" | awk "NF > 0 { c++ } END { print c + 0 }")
p=0
if [ -S /probe-host.sock ]; then p=$((p + 1)); fi
if [ -d /probe-sockdir ]; then
    d=$(find /probe-sockdir -type s -print)
    if [ -n "$d" ]; then p=$((p + 1)); fi
fi
printf "%s %s\n" "$n" "$p"
pruned_lines "$t/pruned"') || _rc=$?
    # Bounded stderr and the exit status of the in-container scan, so a failed
    # scan names its cause. Diagnostic only: the readings are unchanged.
    step_diag "$1" scan "$_rc" "$PROBE_SCRATCH/$1.scan.err"
    if [ "$_rc" -eq 0 ] && scan_report "$1" "$v" && is_uint "${SCAN_HEAD% *}" \
        && is_uint "${SCAN_HEAD#* }"; then
        record "$1" visible_sockets "${SCAN_HEAD% *}"
        record "$1" visible_planted "${SCAN_HEAD#* }"
    else
        record "$1" visible_sockets ERR
        record "$1" visible_planted ERR
    fi
    # One listing; entry names in /proc/<pid>/fd never contain whitespace.
    if names=$(ls -1A -- "/proc/$pid/fd" 2>/dev/null) && [ -n "$names" ]; then
        sockets=0
        bad=0
        for n in $names; do
            if t=$(readlink -- "/proc/$pid/fd/$n"); then
                case $t in socket:*) sockets=$((sockets + 1)) ;; esac
            else
                bad=1
            fi
        done
        running=$(docker inspect --format '{{.State.Running}}' "$2" 2>/dev/null) || running=
        now=$(proc_identity "$pid") || now=gone
        if [ "$bad" = 0 ] && [ "$running" = true ] && [ -n "$ident" ] && [ "$now" = "$ident" ]; then
            record "$1" socket_fds "$sockets"
        else
            record "$1" socket_fds ERR
        fi
    else
        record "$1" socket_fds ERR
    fi
}

observe() {
    require_root
    require_runner_idle
    require_image
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    # run ARM OPTION...: start a tracked container that just sleeps.
    run() {
        _arm=$1
        shift
        # Create (tracked by ID) before start, so no started container escapes.
        create_container --log-driver none "$@" -- "$PROBE_IMAGE_ID" sleep 120
        docker start "$cid" >/dev/null || probe_die 'start-failed'
    }
    run clean --network none --ipc private
    isolation clean "$cid"

    mkdir -p "$PROBE_SCRATCH/sockdir"
    python3 -I -c '
import socket, sys
for path in sys.argv[1:]:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(path)
' "$PROBE_SCRATCH/host.sock" "$PROBE_SCRATCH/sockdir/inner.sock" || probe_die 'socket-plant-failed'
    run sockbind --network none --ipc private \
        --mount "type=bind,source=$PROBE_SCRATCH/host.sock,target=/probe-host.sock" \
        --mount "type=bind,source=$PROBE_SCRATCH/sockdir,target=/probe-sockdir"
    isolation sockbind "$cid"

    run hostnet --network host --ipc private
    isolation hostnet "$cid"

    : >"$PROBE_SCRATCH/planted"
    if z=$(python3 -I -c '
import array, fcntl, os, socket, struct, sys, termios
path = sys.argv[1]
want = os.stat(path)
a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
b.settimeout(5)
fd = os.open(path, os.O_RDONLY)
a.sendmsg([b""], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
os.close(fd)
inq = struct.unpack("i", fcntl.ioctl(b.fileno(), termios.FIONREAD, b"\0\0\0\0"))[0]
msg, anc, flags, _ = b.recvmsg(16, socket.CMSG_SPACE(16))
fds = []
for level, kind, data in anc:
    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
        fds.extend(array.array("i", data[: len(data) - len(data) % 4]))
ok = (msg == b"" and not flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) and len(fds) == 1)
if ok:
    got = os.fstat(fds[0])
    ok = (got.st_dev, got.st_ino) == (want.st_dev, want.st_ino)
for f in fds:
    os.close(f)
print(inq, 1 if ok else 0)
' "$PROBE_SCRATCH/planted" 2>/dev/null); then
        record zerobyte inq "${z% *}"
        record zerobyte fd_received "${z#* }"
    else
        record zerobyte inq ERR
        record zerobyte fd_received ERR
    fi

    isolation fault "$(probe_uuid)$(probe_uuid)"
    recheck_runner
}

# v_iso ARM: every reading valid and mutually consistent (a shared netns is
# one of the shared namespaces; planted counts never exceed their totals).
v_iso() {
    s=$(rd_uint "$1" shared_ns) || { printf '%s\n' "$PROBE_FAIL"; return; }
    n=$(rd_bool "$1" shared_net) || { printf '%s\n' "$PROBE_FAIL"; return; }
    b=$(rd_uint "$1" socket_binds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    pb=$(rd_uint "$1" planted_binds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    f=$(rd_uint "$1" socket_fds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    v=$(rd_uint "$1" visible_sockets) || { printf '%s\n' "$PROBE_FAIL"; return; }
    vp=$(rd_uint "$1" visible_planted) || { printf '%s\n' "$PROBE_FAIL"; return; }
    # Four namespaces are compared, one of them net.
    if [ "$s" -gt 4 ] || [ "$n" -gt "$s" ] || [ $((s - n)) -gt 3 ] || [ "$pb" -gt "$b" ] \
        || [ "$pb" -gt 2 ] || [ "$vp" -gt "$v" ] || [ "$vp" -gt 2 ]; then
        printf '%s\n' "$PROBE_FAIL"; return
    fi
    if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ] && [ "$v" -eq 0 ]; then
        printf '%s\n' "$PROBE_NEG"
    else
        printf '%s\n' "$PROBE_SURV"
    fi
}

# v_sockbind: both planted binds must be seen, from the host and inside.
v_sockbind() {
    base=$(v_iso sockbind)
    [ "$base" != "$PROBE_FAIL" ] || { printf '%s\n' "$PROBE_FAIL"; return; }
    p=$(rd_uint sockbind planted_binds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    v=$(rd_uint sockbind visible_planted) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$p" -eq 2 ] && [ "$v" -eq 2 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$PROBE_FAIL"; fi
}

# v_hostnet: the survivor must be the shared namespace itself.
v_hostnet() {
    base=$(v_iso hostnet)
    [ "$base" != "$PROBE_FAIL" ] || { printf '%s\n' "$PROBE_FAIL"; return; }
    s=$(rd_bool hostnet shared_net) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$s" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"; else printf '%s\n' "$PROBE_FAIL"; fi
}

v_zero() {
    q=$(rd_uint zerobyte inq) || { printf '%s\n' "$PROBE_FAIL"; return; }
    g=$(rd_bool zerobyte fd_received) || { printf '%s\n' "$PROBE_FAIL"; return; }
    # Only the exact limit (a verified fd delivered while the queue read 0) is
    # the survivor; any other reading fails this arm's qualification.
    if [ "$q" -eq 0 ] && [ "$g" -eq 1 ]; then printf '%s\n' "$PROBE_SURV"
    else printf '%s\n' "$PROBE_FAIL"; fi
}

classify() {
    arm clean "$PROBE_NEG" "$(v_iso clean)"
    arm sockbind "$PROBE_SURV" "$(v_sockbind)"
    arm hostnet "$PROBE_SURV" "$(v_hostnet)"
    arm zerobyte "$PROBE_SURV" "$(v_zero)"
    arm fault "$PROBE_FAIL" "$(v_iso fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
