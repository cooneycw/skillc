#!/usr/bin/env python3
"""What a real `docker cp -` write-back looks like to a concurrent reader (#761).

`DockerBackend.execute()` writes `observations` back into the workspace with
`docker cp -` while an authority interceptor may be polling it. This probe
measures, against a REAL daemon, which in-between states such a reader can
see: the file's identity changing (replaced, not rewritten in place), the
file ABSENT, or its content partly written.

It starts one throwaway container from an image that is ALREADY present (it
never pulls), seeds `/w/observations`, runs a short in-container stat loop
(a measurement only - the interceptor itself never watches from inside), and
copies a small payload over the file. Then it removes the container.

Small by design: the default payload is 4 MiB and the loop runs about 1.5 s.
The hosts it runs on also run other work.

    python3 scripts/probe_docker_cp_writeback.py [--image alpine:3] [--mib 4]

It prints one JSON line:
`{"daemon": ..., "samples": N, "inodes": K, "absent": A, "sizes": S}`.
`inodes` > 1 proves the file was replaced; 1 does NOT prove it was rewritten
in place, since a filesystem may reuse a just-freed inode number at once (seen
on this host: 200 MiB read 2 inodes, 4 MiB read 1). `absent` > 0 means a
reader saw the file missing. `sizes` > 2 means partial content was visible. A
zero is a sample, never a proof that the state cannot happen.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import uuid

LOOP = (
    "i=0; while [ $i -lt {n} ]; do "
    "if [ -e /w/observations ]; then stat -c '%i %s' /w/observations; else echo ABSENT; fi; "
    "i=$((i+1)); done > /tmp/watch.log 2>&1; touch /tmp/watch.done"
)


def _docker(*args: str, data: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", *args], input=data, capture_output=True, check=check, timeout=120)


def _tar(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", default="alpine:3", help="an image ALREADY present; never pulled")
    parser.add_argument("--mib", type=int, default=4, help="payload size in MiB (default 4; keep it small)")
    parser.add_argument("--samples", type=int, default=3000, help="stat loop iterations (default 3000)")
    args = parser.parse_args(argv)
    if not 1 <= args.mib <= 16:
        parser.error("--mib must be 1..16: this probe is deliberately small")
    if _docker("image", "inspect", args.image, check=False).returncode != 0:
        print(f"probe: image {args.image} is not present; this probe never pulls", file=sys.stderr)
        return 2
    daemon = _docker("version", "--format", "{{.Server.Version}}").stdout.decode().strip()
    name = f"skillc-761-probe-{uuid.uuid4().hex[:8]}"
    _docker("run", "-d", "--rm", "--name", name, args.image, "sh", "-c",
            "mkdir -p /w && echo seed > /w/observations && sleep 120")
    try:
        _docker("exec", "-d", name, "sh", "-c", LOOP.format(n=args.samples))
        # the loop must be sampling the SEED before the copy starts
        _docker("exec", name, "sh", "-c", "while [ ! -s /tmp/watch.log ]; do sleep 0.01; done")
        _docker("cp", "-", f"{name}:/w", data=_tar("observations", os.urandom(args.mib * 1024 * 1024)))
        _docker("exec", name, "sh", "-c", "while [ ! -e /tmp/watch.done ]; do sleep 0.05; done")
        lines = _docker("exec", name, "cat", "/tmp/watch.log").stdout.decode().splitlines()
    finally:
        _docker("rm", "-f", name, check=False)
    present = [line.split() for line in lines if line != "ABSENT"]
    print(json.dumps({
        "daemon": daemon, "image": args.image, "mib": args.mib, "samples": len(lines),
        "inodes": len({p[0] for p in present}), "absent": len(lines) - len(present),
        "sizes": len({p[1] for p in present if len(p) > 1}),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
