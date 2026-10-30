"""Trusted #568 oracle driver, executed only inside a disposable container.

The parent stays root; candidate programs run as nobody. Captured bytes never
run on the controller. A subreaper sweeps even escaped descendants before the
parent independently reads SQLite state. No candidate process writes the parent
report or receives its expected observations.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_TEST_RUNNER = r'''
import json, unittest
suite = unittest.defaultTestLoader.discover('tests')
def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()
names = list(ids(suite))
result = unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({'count': result.testsRun, 'ids': names,
                  'skipped': [test.id() for test, reason in result.skipped],
                  'ok': result.wasSuccessful()}))
'''


def children() -> list[int]:
    found = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[1]) == os.getpid():
                found.append(int(p.name))
        except (OSError, ValueError, IndexError):
            continue
    return found


def sweep() -> None:
    end = time.monotonic() + 2
    while time.monotonic() < end:
        for pid in children():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
        if not children():
            return
        time.sleep(0.01)
    raise RuntimeError('candidate descendants could not be swept')


def execute(argv: list[str], cwd: Path, budget: Any, seconds: float = 5,
            output_limit: int = 1024 * 1024) -> tuple[int, str, str]:
    budget.check()
    cwd.chmod(0o777)
    for p in cwd.iterdir():
        if p.name == 'db' and p.is_file():
            p.chmod(0o666)

    launcher = ("import os,resource,sys; n=int(sys.argv[1]);"
                "resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execvp(sys.argv[2],sys.argv[2:])")
    command = [sys.executable, '-I', '-S', '-B', '-c', launcher, str(output_limit), *argv]

    with tempfile.TemporaryDirectory(prefix='oracle-output-') as temp:
        out, err = Path(temp) / 'out', Path(temp) / 'err'
        with out.open('xb') as stdout, err.open('xb') as stderr:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, user=65534, group=65534,
                                       extra_groups=[], umask=0o022,
                                       env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
                                            'HOME': str(cwd), 'TMPDIR': str(cwd)})
            budget.processes += 1
            try:
                process.wait(timeout=min(seconds, max(0.01, budget.deadline - time.monotonic() - 2)))
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise RuntimeError('candidate probe timeout') from exc
            finally:
                sweep()
        sizes = out.stat().st_size + err.stat().st_size
        if out.stat().st_size >= output_limit or err.stat().st_size >= output_limit:
            raise RuntimeError('candidate output limit')
        if sizes > budget.capacity - budget.used:
            raise RuntimeError('retained output budget')
        budget.used += sizes
        return process.returncode, out.read_text(encoding='utf-8'), err.read_text(encoding='utf-8')


def stage_files(files: dict[str, bytes], modes: dict[str, str], root: Path, budget: Any) -> None:
    for path, data in files.items():
        if modes[path] not in ('100644', '100755'):
            raise RuntimeError('unsupported captured mode')
        target = root / path
        budget.write(target, data)
        target.chmod(0o755 if modes[path] == '100755' else 0o644)


def protection(files: dict[str, bytes], manifest: dict[str, Any], sources: dict[str, bytes],
               engine: dict[str, Any], budget: Any, modes: dict[str, str]) -> list[dict[str, Any]]:
    """Run the ACTUAL delivered suite, with no fixed test-count requirement."""
    rows = []
    for name in ('reference', 'alternative', 'csv-only', 'jsonl-only', 'partial', 'replace', 'legacy-api'):
        with tempfile.TemporaryDirectory(prefix='oracle-suite-') as temp:
            root = Path(temp)
            # Each implementation sees the same delivered project/tests; only
            # the implementation under test is replaced by the trusted control.
            stage_files(files, modes, root, budget)
            code = engine['program']('reference' if name == 'legacy-api' else name, manifest, sources)
            if name == 'legacy-api':
                code += b'\nif __name__ != "__main__":\n def set_quantity(*args, **kwargs): raise ValueError("legacy API removed")\n'
            budget.write(root / 'inventory.py', code)
            code, out, _ = execute([sys.executable, '-B', '-c', _TEST_RUNNER], root, budget)
            try:
                row = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                row = {}
            ids, skipped = row.get('ids'), row.get('skipped')
            valid = (code == 0 and isinstance(ids, list) and all(isinstance(x, str) for x in ids)
                     and len(ids) == len(set(ids)) and isinstance(skipped, list)
                     and type(row.get('count')) is int and row['count'] == len(ids)
                     and row['count'] > len(skipped)
                     and type(row.get('ok')) is bool)
            rows.append({'program': name, 'population_valid': valid,
                         'ok': row.get('ok') if valid else None, 'count': row.get('count')})
    return rows


def evaluate_vector(files: dict[str, bytes], row: dict[str, Any], budget: Any, engine: dict[str, Any],
                    modes: dict[str, str]) -> dict[str, Any]:
    # B1's independent literal-state checks, extended to the full delivered
    # project. Oracle databases/inputs live outside that project so filenames
    # chosen by an implementation cannot collide with grader scratch.
    seed, state, bounded = engine['seed'], engine['state'], execute
    start_steps = budget.processes
    with tempfile.TemporaryDirectory(prefix="568-vector-") as tmp:
        parent = Path(tmp)
        parent.chmod(0o711)
        d, scratch = parent / 'project', parent / 'scratch'
        d.mkdir()
        scratch.mkdir()
        scratch.chmod(0o777)
        stage_files(files, modes, d, budget)
        db, data = scratch / 'db', scratch / 'input'
        seed(db, row.get("db"), row.get("extra_items", ()))
        if db.exists():
            db.chmod(0o666)
        before = state(db)
        if not row.get("missing_input"):
            budget.write(data, bytes.fromhex(row["hex"]) if "hex" in row else row["input"].encode())
        else:
            assert not data.exists()
        if row["action"] == "import":
            argv = [sys.executable, "inventory.py", "--db", str(db), "import", "--format", row["format"], str(data)]
        else:
            action = {"set": f"inventory.set_quantity({str(db)!r},'A',8);",
                      "new": f"inventory.set_quantity({str(db)!r},'B',2);", "list": ""}[row["action"]]
            checks = (f"DB={str(db)!r}\n" + "for sku,quantity in [(' A',8),('A',True),('A',-1)]:\n"
                      " try: inventory.set_quantity(DB,sku,quantity)\n"
                      " except ValueError: pass\n"
                      " else: raise AssertionError('legacy validation lost')\n") if row["action"] == "set" else ""
            argv = [sys.executable, "-c", "import inventory,json\n" + checks + action
                    + f"\nprint(json.dumps(inventory.list_items({str(db)!r})))"]
        rc, stdout, stderr = bounded(argv, d, budget)
        after = state(db)
        observed_states = [after]
        try:
            output_ok = (stdout.endswith("\n") and json.loads(stdout) == row["stdout"]) if row["code"] == 0 else stdout == ""
        except ValueError:
            output_ok = False
        output_ok &= rc == row["code"]
        output_ok &= stderr == "" if row["code"] == 0 else stderr.startswith(row["prefix"]) and len(stderr) > len(row["prefix"])
        if row["action"] != "import":
            # CLI gets an independent identical seed; it cannot borrow an API write.
            db.unlink()
            seed(db, row.get("db"), row.get("extra_items", ()))
            if db.exists():
                db.chmod(0o666)
            cli = [sys.executable, "inventory.py", "--db", str(db)]
            calls = [(cli + ["list"], row["stdout"])]
            if row["action"] != "list":
                sku, quantity = ("A", "8") if row["action"] == "set" else ("B", "2")
                calls.insert(0, (cli + ["put", sku, quantity], {"updated": 1}))
            for command, wanted in calls:
                status, out, err = bounded(command, d, budget)
                try:
                    output_ok &= status == 0 and err == "" and out.endswith("\n") and json.loads(out) == wanted
                except ValueError:
                    output_ok = False
                observed_states.append(state(db))
            after = state(db)
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
            feature = True
            legacy = bool(output_ok and preserved and all(
                observed["items"] == expected and observed["audit"] == before["audit"]
                and observed["schema"] == before["schema"] for observed in observed_states))
        return {"id": row["id"], "feature": bool(feature), "legacy": legacy, "code": rc,
                "stdout": stdout, "stderr": stderr, "items": after["items"], "audit": after["audit"],
                "observed_states": observed_states,
                "managed_steps": budget.processes - start_steps}



def container_parent() -> bool:
    # The Docker command starts this driver as PID 1 in its own namespace.
    # Refuse accidental direct host invocation, even by a root controller.
    return os.getpid() == 1 and os.geteuid() == 0


def evaluate(job: dict[str, Any]) -> dict[str, Any]:
    if not container_parent() or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('isolated container parent/subreaper unavailable')
    files = {p: base64.b64decode(row['data_b64'], validate=True) for p, row in job['files'].items()}
    modes = {p: row['mode'] for p, row in job['files'].items()}
    engine: dict[str, Any] = {'__file__': '/trusted/evals/level3/change-with-regression-568/oracle.py'}
    exec(compile(job['engine'], engine['__file__'], 'exec'), engine)  # noqa: S102 - trusted controller code, in the oracle container only
    engine['bounded'] = execute
    budget = engine['Budget']()
    sources = {p: base64.b64decode(data, validate=True) for p, data in job['sources'].items()}
    manifest = job['manifest']
    rows = []
    for vector in manifest['vectors']:
        try:
            rows.append(evaluate_vector(files, vector, budget, engine, modes))
        except sqlite3.DatabaseError:
            rows.append({'id': vector['id'], 'feature': False, 'legacy': False})
    tests = protection(files, manifest, sources, engine, budget, modes)
    budget.check()
    return {'status': 'ran', 'vectors': [{'id': row['id'], 'feature': row['feature'],
                                        'legacy': row['legacy']} for row in rows],
            'protection': tests}


def main() -> None:
    job = json.loads(sys.stdin.read())
    try:
        result = evaluate(job)
    except Exception as exc:  # noqa: BLE001 - no oracle exception may become a task PASS
        result = {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}
    print(job['nonce'] + json.dumps(result))


if __name__ == '__main__':
    main()
