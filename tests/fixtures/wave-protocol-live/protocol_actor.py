"""Model-free role actor for #620 PR-B B8c: speaks the task protocol only
through the installed skillc-task-protocol client, writes no state of its
own, and plants a REAL residue (a leftover branch and a stash) in "residue"
mode. Request numbers come from the operation, so nothing is stored."""
import glob
import subprocess
import sys
import uuid
from pathlib import Path

role, mode, *turn = sys.argv[1:]
session = turn[1] if turn[0] == "resume" else str(uuid.uuid4())
sys.stderr.write("OpenAI Codex v0.157.1\n--------\nsession id: " + session + "\n--------\n")
sys.stderr.flush()
if turn[0] != "resume":
    raise SystemExit(0)  # the bootstrap turn performs no protocol operation
text = turn[2]
clients = glob.glob("/opt/skillc-task-protocol/*/skillc-task-protocol")
if len(clients) != 1:
    raise SystemExit(5)
number = {"offer": 1, "ack": 2, "complete": 3}[text]
args = [text, "--request", str(number)] + ([] if text == "offer" else ["--offer", "offer-" + role])
code = subprocess.run(["python3", "-I", "-S", clients[0], *args], check=False).returncode
if text == "complete" and mode == "residue":
    git = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]
    subprocess.run([*git, "branch", "leftover-" + role], check=True, capture_output=True)
    Path("stash-me.txt").write_text("planted residue\n")
    subprocess.run([*git, "stash", "push", "--include-untracked", "-m", "leftover-" + role],
                   check=True, capture_output=True)
raise SystemExit(code)
