#!/bin/sh
# P8 (#797 fact 2b): container channel isolation. A holder container has
# private network, IPC, mount and PID namespaces (compared by namespace
# identity against PID 1), no host socket bind, and no inherited socket fd.
# A corroborating arm records the known limit of queue-length checks: a
# zero-byte Unix datagram carries SCM_RIGHTS while the receive queue reads 0.
# ROOT REQUIRED. TOUCHES DOCKER.
# Usage: p8.sh --image-id sha256:<64 hex> --runner-unit <unit>
#
# Arms and expected verdicts:
#   clean      private namespaces, no socket bind or fd      CONFIRMED_NEGATIVE
#   sockbind   a planted host Unix socket bind              SURVIVOR_OBSERVED
#   hostnet    --network host shares the host netns          SURVIVOR_OBSERVED
#   zerobyte   fd queued in a zero-byte datagram, queue 0    SURVIVOR_OBSERVED
#   fault      the container pid cannot be read              OBSERVATION_FAILED
set -eu
PROBE_NAME=p8
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# isolation ARM CONTAINER: record shared namespaces, socket binds, socket fds.
isolation() {
    pid=$(docker inspect --format '{{.State.Pid}}' "$2" 2>/dev/null) || pid=
    if ! is_uint "$pid" || [ "$pid" -eq 0 ] || [ ! -d "/proc/$pid" ]; then
        record "$1" shared_ns ERR
        record "$1" socket_binds ERR
        record "$1" socket_fds ERR
        return
    fi
    shared=0
    ok=1
    for ns in net ipc mnt pid; do
        if c=$(readlink "/proc/$pid/ns/$ns") && h=$(readlink "/proc/1/ns/$ns"); then
            if [ "$c" = "$h" ]; then shared=$((shared + 1)); fi
        else
            ok=0
        fi
    done
    if [ "$ok" = 1 ]; then record "$1" shared_ns "$shared"; else record "$1" shared_ns ERR; fi
    if srcs=$(docker inspect --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$2"); then
        binds=0
        for s in $srcs; do
            if [ -S "$s" ]; then binds=$((binds + 1)); fi
        done
        record "$1" socket_binds "$binds"
    else
        record "$1" socket_binds ERR
    fi
    if ls -- "/proc/$pid/fd" >/dev/null 2>&1; then
        sockets=0
        bad=0
        for e in "/proc/$pid/fd"/*; do
            [ -L "$e" ] || continue
            if t=$(readlink -- "$e"); then
                case $t in socket:*) sockets=$((sockets + 1)) ;; esac
            else
                bad=1
            fi
        done
        if [ "$bad" = 0 ]; then record "$1" socket_fds "$sockets"; else record "$1" socket_fds ERR; fi
    else
        record "$1" socket_fds ERR
    fi
}

observe() {
    require_root
    require_runner_idle
    require_image
    scratch_make "${PROBE_SCRATCH_PARENT:-/run}"
    names=
    # shellcheck disable=SC2317  # invoked by the EXIT trap
    cleanup() {
        for n in $names; do docker rm -f "$n" >/dev/null 2>&1 || true; done
        scratch_remove
    }
    trap cleanup EXIT
    run() {
        n="skillc-dev-probe-p8-$1-$$"
        names="$names $n"
        shift
        docker run -d --name "$n" --log-driver none "$@" -- "$PROBE_IMAGE_ID" sleep 120 >/dev/null \
            || probe_die 'run-failed'
    }
    run clean --network none --ipc private
    isolation clean "skillc-dev-probe-p8-clean-$$"

    python3 -I -c '
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind(sys.argv[1])
' "$PROBE_SCRATCH/host.sock" || probe_die 'socket-plant-failed'
    run sockbind --network none --ipc private \
        --mount "type=bind,source=$PROBE_SCRATCH/host.sock,target=/probe-host.sock"
    isolation sockbind "skillc-dev-probe-p8-sockbind-$$"

    run hostnet --network host --ipc private
    isolation hostnet "skillc-dev-probe-p8-hostnet-$$"

    # zerobyte: the limit fact 2b's construction exists to avoid.
    if z=$(python3 -I -c '
import array, fcntl, os, socket, struct, sys, termios
a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
fd = os.open(sys.argv[1], os.O_RDONLY)
a.sendmsg([b""], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
inq = struct.unpack("i", fcntl.ioctl(b.fileno(), termios.FIONREAD, b"\0\0\0\0"))[0]
msg, anc, flags, addr = b.recvmsg(1, socket.CMSG_LEN(4))
got = sum(1 for level, kind, _ in anc if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS)
print(inq, got)
' "$PROBE_SCRATCH/readings" 2>/dev/null); then
        record zerobyte inq "${z% *}"
        record zerobyte fd_received "${z#* }"
    else
        record zerobyte inq ERR
        record zerobyte fd_received ERR
    fi

    isolation fault "skillc-dev-probe-p8-absent-$$"
}

v_iso() {
    s=$(rd_uint "$1" shared_ns) || { printf '%s\n' "$PROBE_FAIL"; return; }
    b=$(rd_uint "$1" socket_binds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    f=$(rd_uint "$1" socket_fds) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$s" -eq 0 ] && [ "$b" -eq 0 ] && [ "$f" -eq 0 ]; then
        printf '%s\n' "$PROBE_NEG"
    else
        printf '%s\n' "$PROBE_SURV"
    fi
}

v_zero() {
    q=$(rd_uint zerobyte inq) || { printf '%s\n' "$PROBE_FAIL"; return; }
    g=$(rd_uint zerobyte fd_received) || { printf '%s\n' "$PROBE_FAIL"; return; }
    # A descriptor delivered while the queue read 0 is a survivor that a
    # queue-length check cannot see.
    if [ "$q" -eq 0 ] && [ "$g" -ge 1 ]; then printf '%s\n' "$PROBE_SURV"
    elif [ "$g" -eq 0 ]; then printf '%s\n' "$PROBE_FAIL"
    else printf '%s\n' "$PROBE_NEG"; fi
}

classify() {
    arm clean "$PROBE_NEG" "$(v_iso clean)"
    arm sockbind "$PROBE_SURV" "$(v_iso sockbind)"
    arm hostnet "$PROBE_SURV" "$(v_iso hostnet)"
    arm zerobyte "$PROBE_SURV" "$(v_zero)"
    arm fault "$PROBE_FAIL" "$(v_iso fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
