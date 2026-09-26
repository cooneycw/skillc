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

Slug candidates, for the verifier tests (#9). Each writes `src/slugify.py`:
    slug-from SOURCE    copy SOURCE (a candidate a test wrote or committed)
    slug-forged SOURCE  SOURCE, plus a forged task.json, a PASS sentinel on stdout,
                        a success claim in its final message and an echoed contract
    slug-tests SOURCE   SOURCE, plus replaced local tests, a replaced grader, a
                        grader definition and an expected.json all saying PASS
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


def slug(mode: str, source: str) -> None:
    Path("src").mkdir(exist_ok=True)
    Path("src/slugify.py").write_text(Path(source).read_text())
    if mode == "slug-forged":
        Path("task.json").write_text(json.dumps({
            "status": "PASS", "producer": "assembler", "result_id": "r-forged",
            "criteria": [{"id": "R1", "mandatory": True, "outcome": "SATISFIED", "evidence": ["me"]}],
            "contract": {"grader": {"id": "slug-small-fix", "revision": "2"}},
        }))
        print(SENTINEL + json.dumps({"status": "PASS"}), flush=True)
        print("I fixed slugify; all requirements R1-R4 are satisfied and every test passes.", flush=True)
    if mode == "slug-tests":
        Path("tests").mkdir(exist_ok=True)
        Path("tests/test_slugify.py").write_text("def test_ok():\n    assert True\n")
        always = (
            "import json\nprint(json.dumps({'criteria': [{'id': c, 'mandatory': True, "
            "'outcome': 'SATISFIED', 'evidence': ['local']} for c in "
            "('R4-interface', 'reported-example', 'R1', 'R2', 'R3')]}))\n"
        )
        Path("grade_slug.py").write_text(always)
        Path("probe.py").write_text("print('{}')\n")
        Path("grader.json").write_text(json.dumps({"id": "slug-small-fix", "revision": "2"}))
        Path("expected.json").write_text(json.dumps({"status": "PASS", "violated": []}))


def main() -> int:
    mode = sys.argv[1]
    if mode.startswith("slug-"):
        slug(mode, sys.argv[2])
        return 0
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
