"""Trusted committed-fixture qualification, NOT an arbitrary-candidate sandbox."""
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

try:
    import resource
except ImportError:
    resource = None

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
LIMIT = 1024 * 1024
SCHEMA = """CREATE TABLE items(sku TEXT PRIMARY KEY, quantity INTEGER, note TEXT, created_id TEXT);
CREATE TABLE audit(event_id INTEGER PRIMARY KEY, sku TEXT REFERENCES items(sku) ON DELETE CASCADE, detail TEXT);
INSERT INTO items VALUES ('A',3,'keep','original'); INSERT INTO audit VALUES (1,'A','history');"""
SOURCES = {"fixture": "fixture/inventory.py", "reference": "candidates/reference.py",
           "alternative": "candidates/alternative.py", "tests": "candidates/test_import.py",
           "legacy": "fixture/tests/test_legacy.py"}


class Unavailable(Exception):
    """No trustworthy observation; never a task FAIL or a clean qualification."""


class Budget:
    def __init__(self, seconds=450, capacity=64 * LIMIT):
        self.deadline = time.monotonic() + seconds
        self.capacity = capacity
        self.used = 0
        self.processes = 0

    def check(self):
        if time.monotonic() >= self.deadline:
            raise Unavailable("whole qualification deadline")

    def write(self, path, data):
        if len(data) > self.capacity - self.used:
            raise Unavailable("parent staging budget")
        self.used += len(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def load_sources():
    """Accept only this repository's tracked, committed, byte-matching sources."""
    paths = [*SOURCES.values(), "controls.json", "oracle.py", "qualify.py"]
    result = {}
    for rel in paths:
        path = ROOT / rel
        name = path.relative_to(REPO).as_posix()
        try:
            committed = subprocess.check_output(["git", "-C", str(REPO), "show", "HEAD:" + name],
                                                stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Unavailable("trusted source is not committed: " + rel) from exc
        if path.read_bytes() != committed:
            raise Unavailable("trusted source differs from HEAD: " + rel)
        result[rel] = committed
    return result


def program(name, manifest, sources):
    if name in SOURCES and name not in ("tests", "legacy"):
        return sources[SOURCES[name]]
    original = sources[SOURCES["reference"]].decode()
    if name == "benign":
        return ("# harmless comment\n" + original).encode()
    if name not in manifest["mutations"]:
        raise Unavailable("unknown trusted program")
    mutation = manifest["mutations"][name]
    if original.count(mutation["old"]) != 1 or mutation["old"] == mutation["new"]:
        raise Unavailable("mutation precondition failed: " + name)
    return original.replace(mutation["old"], mutation["new"], 1).encode()


def stop_group(p):
    """Signal only the group we created, reap the parent, then stop remaining group members."""
    with suppress(ProcessLookupError):
        os.killpg(p.pid, signal.SIGTERM)
    time.sleep(0.02)
    # The parent has not been reaped: its process-group number cannot be recycled.
    with suppress(ProcessLookupError):
        os.killpg(p.pid, signal.SIGKILL)
    try:
        p.wait(timeout=1)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        try:
            p.wait(timeout=1)
        except subprocess.TimeoutExpired as exc:
            raise Unavailable("parent cleanup failed") from exc


def bounded(argv, cwd, budget, seconds=5, output_limit=LIMIT):
    if os.name != "posix" or resource is None or not hasattr(os, "WNOWAIT"):
        raise Unavailable("POSIX process groups/resource limits unavailable")
    remaining = budget.deadline - time.monotonic() - 2
    if remaining <= 0:
        raise Unavailable("whole qualification deadline")

    if not argv or shutil.which(argv[0]) is None:
        raise Unavailable("selected executable unavailable")
    launcher = ("import os,resource,sys;"
                "n=int(sys.argv[1]);resource.setrlimit(resource.RLIMIT_FSIZE,(n,n));"
                "os.execvp(sys.argv[2],sys.argv[2:])")
    with tempfile.TemporaryDirectory(prefix="568-output-") as tmp:
        out, err = Path(tmp) / "stdout", Path(tmp) / "stderr"
        with out.open("wb") as stdout, err.open("wb") as stderr:
            try:
                p = subprocess.Popen([sys.executable, "-c", launcher, str(output_limit), *argv],
                                     cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                     stderr=stderr, start_new_session=True,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            except OSError as exc:
                raise Unavailable("probe could not launch") from exc
            budget.processes += 1
            timed_out = False
            try:
                end = time.monotonic() + min(seconds, remaining)
                while os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    if time.monotonic() >= end:
                        timed_out = True
                        break
                    time.sleep(0.01)
            finally:
                stop_group(p)
        if timed_out:
            raise Unavailable("probe timeout; parent reaped and owned group signalled")
        sizes = [x.stat().st_size for x in (out, err)]
        if any(n > output_limit or n == output_limit and p.returncode != 0 for n in sizes):
            raise Unavailable("output limit")
        if sum(sizes) > budget.capacity - budget.used:
            raise Unavailable("retained output budget")
        budget.used += sum(sizes)
        try:
            return p.returncode, out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise Unavailable("unreadable probe output") from exc


def state(db):
    if not db.exists():
        return {"exists": False, "schema": [], "items": [], "audit": []}
    with sqlite3.connect(db) as c:
        schema = c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        names = {row[0] for row in schema}
        return {"exists": True, "schema": schema,
                "items": c.execute("SELECT * FROM items ORDER BY sku COLLATE BINARY").fetchall() if "items" in names else [],
                "audit": c.execute("SELECT * FROM audit ORDER BY event_id").fetchall() if "audit" in names else []}


def seed(db, kind=None, extra=()):
    if kind != "missing":
        with sqlite3.connect(db) as c:
            if kind != "empty":
                c.executescript(SCHEMA)
                c.executemany("INSERT INTO items VALUES (?,?,?,?)", extra)


def vector(code, row, budget):
    with tempfile.TemporaryDirectory(prefix="568-vector-") as tmp:
        d = Path(tmp)
        budget.write(d / "inventory.py", code)
        db, data = d / "db", d / "input"
        seed(db, row.get("db"), row.get("extra_items", ()))
        before = state(db)
        if not row.get("missing_input"):
            budget.write(data, bytes.fromhex(row["hex"]) if "hex" in row else row["input"].encode())
        else:
            assert not data.exists()
        if row["action"] == "import":
            argv = [sys.executable, "inventory.py", "--db", str(db), "import", "--format", row["format"], str(data)]
        else:
            action = {"set": "inventory.set_quantity('db','A',8);",
                      "new": "inventory.set_quantity('db','B',2);", "list": ""}[row["action"]]
            checks = ("for sku,quantity in [(' A',8),('A',True),('A',-1)]:\n"
                      " try: inventory.set_quantity('db',sku,quantity)\n"
                      " except ValueError: pass\n"
                      " else: raise AssertionError('legacy validation lost')\n") if row["action"] == "set" else ""
            argv = [sys.executable, "-c", "import inventory,json\n" + checks + action
                    + "\nprint(json.dumps(inventory.list_items('db')))"]
        rc, stdout, stderr = bounded(argv, d, budget)
        after = state(db)
        try:
            output_ok = json.loads(stdout) == row["stdout"] if row["code"] == 0 else stdout == ""
        except ValueError:
            output_ok = False
        output_ok &= rc == row["code"]
        output_ok &= stderr == "" if row["code"] == 0 else stderr.startswith(row["prefix"]) and len(stderr) > len(row["prefix"])
        expected = [tuple(x) for x in row["items"]]
        metadata = {x[0]: x[2:] for x in after["items"]}
        preserved = all(metadata.get(x[0]) == x[2:] for x in before["items"])
        preserved &= before["audit"] == after["audit"] and before["schema"] == after["schema"]
        if row["action"] == "import":
            feature = output_ok and [x[:2] for x in after["items"]] == [x[:2] for x in expected]
            feature &= all(x == next((e for e in expected if e[0] == x[0]), None)
                           for x in after["items"] if x[0] not in {b[0] for b in before["items"]})
            if row["code"] != 0:
                feature &= before == after
            legacy = bool(preserved)
        else:
            feature, legacy = True, bool(output_ok and after["items"] == expected and preserved)
        return {"id": row["id"], "feature": bool(feature), "legacy": legacy, "code": rc,
                "stdout": stdout, "stderr": stderr, "items": after["items"], "audit": after["audit"],
                "managed_steps": 1}


def semantic(name, manifest, sources, budget):
    code = program(name, manifest, sources)
    results = [vector(code, row, budget) for row in manifest["vectors"]]
    return {"feature": all(r["feature"] for r in results), "legacy": all(r["legacy"] for r in results),
            "vectors": results, "program_sha256": hashlib.sha256(code).hexdigest()}


def project_tests(name, manifest, sources, budget):
    with tempfile.TemporaryDirectory(prefix="568-tests-") as tmp:
        d = Path(tmp)
        budget.write(d / "inventory.py", program(name, manifest, sources))
        budget.write(d / "tests/test_legacy.py", sources[SOURCES["legacy"]])
        budget.write(d / "tests/test_import.py", sources[SOURCES["tests"]])
        runner = ("import unittest,json; s=unittest.defaultTestLoader.discover('tests');"
                  "r=unittest.TextTestRunner(verbosity=0).run(s);"
                  "print(json.dumps({'count':r.testsRun,'skipped':len(r.skipped),'ok':r.wasSuccessful()}))")
        rc, stdout, stderr = bounded([sys.executable, "-c", runner], d, budget)
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise Unavailable("test runner output unavailable") from exc
        if rc:
            raise Unavailable("test population unavailable or skipped")
        test_population(result)
        return {"program": name, **result, "stderr": stderr}


def test_population(row):
    if row.get("count") != 5 or row.get("skipped") != 0:
        raise Unavailable("test population unavailable or skipped")


def remote_files(export, remote=".remote/widget.git", max_bytes=64 * LIMIT):
    """Read bytes of this supplied export's remote main, never its local working tree."""
    from skillc.git_snapshot import GitDir, SafeTree, Unreadable
    try:
        git = GitDir(SafeTree(export), remote)
        git.check_plain()
        commit = git.refs()["refs/heads/main"]
        tree = git.tree_of(commit)
        result = {}
        total = 0
        for path, entry in git.tree_files(tree).items():
            mode, blob = entry.split()
            if mode not in ("100644", "100755"):
                raise Unavailable("unsupported remote mode")
            kind, data = git.object(blob)
            if kind != "blob":
                raise Unavailable("remote file is not a blob")
            total += len(data)
            if total > max_bytes or len(result) >= 1024:
                raise Unavailable("remote artifact capture budget")
            result[path] = {"mode": mode, "blob": blob, "data": data}
        if not result:
            raise Unavailable("empty remote artifact")
        return {"commit": commit, "tree": tree, "files": result}
    except (Unreadable, KeyError, ValueError) as exc:
        raise Unavailable("remote unavailable: " + str(exc)) from exc


def identity(files):
    return {p: {"mode": x["mode"], "blob": x["blob"], "sha256": hashlib.sha256(x["data"]).hexdigest()}
            for p, x in files.items()}
