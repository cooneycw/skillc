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
`{"daemon": ..., "samples": N, "inodes": K, "absent": A, "failed": F,
"sizes": S, "covered": true}`, and exits 3 when `covered` is false: the
samples did not start on the seed and end on the completed payload, so they
say nothing about the copy.
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

#: Every sample is TYPED, so a failed stat is never read as inode/size data
#: (counter-model review): `S <inode> <size>`, `ABSENT`, or `ERR`. The loop
#: runs until the copy is done (`/tmp/cp.done`), then `{n}` samples more.
LOOP = (
    "i=0; while [ ! -e /tmp/cp.done ] || [ $i -lt {n} ]; do "
    "if [ -e /tmp/cp.done ]; then i=$((i+1)); fi; "
    "if out=$(stat -c '%i %s' /w/observations 2>/dev/null); then echo \"S $out\"; "
    "elif [ -e /w/observations ]; then echo ERR; else echo ABSENT; fi; "
    "done > /tmp/watch.log; touch /tmp/watch.done"
)
SEED = b"seed\n"


def summarize(lines: list[str], payload_size: int) -> dict[str, object]:
    """Counts from the typed samples, and whether they COVER the copy: the
    first sample must show the seed and the last the completed payload, or
    the copy's states were not observed and the result says so."""
    samples: list[tuple[str, int]] = []
    absent = failed = 0
    # Nothing before the first SEED sample is about the copy: it is the
    # container starting up (counter-model review, pass 2).
    first = next((i for i, line in enumerate(lines) if line.split()[:1] == ["S"] and line.split()[-1:] == [str(len(SEED))]),
                 len(lines))
    for line in lines[first:]:
        parts = line.split()
        if parts == ["ABSENT"]:
            absent += 1
        elif len(parts) == 3 and parts[0] == "S" and parts[1].isdigit() and parts[2].isdigit():
            samples.append((parts[1], int(parts[2])))
        else:
            failed += 1  # ERR, or anything unparseable: never counted as data
    covered = bool(samples) and samples[0][1] == len(SEED) and samples[-1][1] == payload_size
    return {"samples": len(lines) - first, "inodes": len({i for i, _ in samples}), "absent": absent,
            "failed": failed, "sizes": len({n for _, n in samples}), "covered": covered}


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
    payload = args.mib * 1024 * 1024
    _docker("run", "-d", "--rm", "--name", name, args.image, "sh", "-c",
            "mkdir -p /w && printf 'seed\\n' > /w/observations && sleep 120")
    try:
        # the seed must exist before the watcher starts, so no startup state is sampled
        _docker("exec", name, "sh", "-c", f"until [ \"$(stat -c %s /w/observations 2>/dev/null)\" = {len(SEED)} ]; "
                "do sleep 0.01; done")
        _docker("exec", "-d", name, "sh", "-c", LOOP.format(n=args.samples))
        # the loop must be sampling the SEED before the copy starts
        _docker("exec", name, "sh", "-c", "while [ ! -s /tmp/watch.log ]; do sleep 0.01; done")
        _docker("cp", "-", f"{name}:/w", data=_tar("observations", os.urandom(payload)))
        _docker("exec", name, "touch", "/tmp/cp.done")
        _docker("exec", name, "sh", "-c", "while [ ! -e /tmp/watch.done ]; do sleep 0.05; done")
        lines = _docker("exec", name, "cat", "/tmp/watch.log").stdout.decode().splitlines()
    finally:
        _docker("rm", "-f", name, check=False)
    result = {"daemon": daemon, "image": args.image, "mib": args.mib, **summarize(lines, payload)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["covered"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
