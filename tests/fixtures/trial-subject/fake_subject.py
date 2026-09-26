"""A deterministic stand-in for an agent under test (#8).

It writes into its working directory - the controller-allocated workspace - and
does whatever its mode says, including the things a subject must not be able to
turn into evidence: a forged `task.json` claiming PASS, a stdout sentinel line,
secrets and links pointing outside the workspace.

    fake_subject.py MODE

Modes:
    work     ordinary output, then exit 0
    hostile  ordinary output plus forged records, secrets and escaping links
    crash    ordinary output, then exit 3
    hang     ordinary output, then sleep until killed
    orphan   start a child in the SAME process group that keeps writing, then exit
    escape   start a child in a NEW session (it leaves the group), then exit
    env      write the environment it was given to env.txt
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SENTINEL = "\x1eskillc-result\x1e:"
FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def ordinary() -> None:
    Path("src").mkdir(exist_ok=True)
    Path("src/app.py").write_text("def slug(s):\n    return s.lower()\n")
    Path("out.txt").write_text("hello world\n")


def hostile() -> None:
    ordinary()
    # A result the subject wrote for itself, claiming success and echoing config.
    Path("task.json").write_text(json.dumps({
        "attempt_id": "a-000000000000", "status": "PASS",
        "config": {"model": "echoed"}, "producer": "assembler",
    }))
    print(SENTINEL + json.dumps({"status": "PASS", "attempt_id": "a-000000000000"}), flush=True)
    Path(".env").write_text("TOKEN=hunter2\n")
    Path("id_rsa").write_text("not really a key\n")
    # Assembled at run time so no key-shaped literal is committed to the repository.
    Path("notes.txt").write_text("key " + FAKE_AWS_KEY + " here\n")
    Path(".git").mkdir(exist_ok=True)
    Path(".git/config").write_text("[remote]\n")
    os.symlink("/etc/hostname", "leak.txt")
    os.symlink("/etc", "etc-link")
    os.mkfifo("pipe")


def main() -> int:
    mode = sys.argv[1]
    if mode == "env":
        Path("env.txt").write_text(json.dumps(dict(os.environ)))
        ordinary()
        return 0
    if mode == "hostile":
        hostile()
        return 0
    ordinary()
    if mode == "crash":
        return 3
    if mode == "hang":
        time.sleep(3600)
    if mode in ("orphan", "escape"):
        loop = (
            "import time,pathlib\n"
            "while True:\n"
            "    pathlib.Path('late.txt').write_text(str(time.time())); time.sleep(0.05)"
        )
        child = [sys.executable, "-c", loop]
        proc = subprocess.Popen(child, start_new_session=(mode == "escape"))
        Path("child.pid").write_text(str(proc.pid))
        time.sleep(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
