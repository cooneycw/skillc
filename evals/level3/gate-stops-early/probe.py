#!/usr/bin/env python3
"""Probe for the Level 3 gate-stops-early task: the ONLY grading code that
runs candidate code.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin:
`{"oracle_cases": [...], "restore": {...}, "baseline_tests": [...]}`.

Reports observations, never a verdict - grade_gate_stops_early.py --judge
holds every expected value and compares:

  - `oracle`: the judge's own held-out (args, expected) pairs for
    `rangekit.windows.sliding_window`, called directly against the
    candidate's DELIVERED source (`functional-windows-fix`). Never the
    candidate's own test file.
  - `tests_delivered`: every `test_*.py` file anywhere under the candidate's
    `tests/`, discovered by walking the filesystem directly (never through
    the candidate's own `ci/check.py`) and run function-by-function.
  - `gate_delivered`: the candidate's own `ci/check.py`, run on a copy of its
    clean, delivered tree (`gate-green`).
  - `tests_hybrid` / `gate_hybrid`: the same two observations again, on a
    FRESH copy of the candidate with `restore.file` (the one function file
    ISSUE.md reports) overwritten back to `restore.content` - its ORIGINAL,
    unfixed bytes, pinned in inputs.json. Everything else in the candidate's
    tree - its own `ci/check.py`, its own added test(s) - is untouched. This
    is `regression-fails-on-original`.

`restore.file` absent from the candidate's tree is reported as
`restore_error`, and the hybrid-tree observations are skipped entirely - a
candidate that deleted or renamed the file under test gives no proof either
way.

Runs under `python -I -S -B` (skillc.verify). The candidate's gate is
launched with `-E -s -B`, cwd set to the tree copy it checks - the public
`python3 ci/check.py` invocation's own import semantics, without the
evaluator's environment or user site.
"""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GATE_TIMEOUT = 15
GATE_FILE = os.path.join("ci", "check.py")
MAX_LINE = 400


def _discover_test_files(tree_root: Path) -> list[Path]:
    tests_root = tree_root / "tests"
    if not tests_root.is_dir():
        return []
    return sorted(tests_root.rglob("test_*.py"))


def _clear_rangekit_modules() -> None:
    for name in list(sys.modules):
        if name == "rangekit" or name.startswith("rangekit."):
            del sys.modules[name]


def _run_test_file(path: Path, tree_root: Path) -> dict:
    rel = path.relative_to(tree_root).as_posix()
    sys.path.insert(0, str(tree_root))
    try:
        spec = importlib.util.spec_from_file_location(f"probe_test_{abs(hash(rel))}", path)
        if spec is None or spec.loader is None:
            return {"file": rel, "load_error": "could not be loaded", "functions": {}}
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
            return {"file": rel, "load_error": f"{type(exc).__name__}: {exc}", "functions": {}}
    finally:
        sys.path.remove(str(tree_root))
    functions = {}
    for name in dir(module):
        fn = getattr(module, name)
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                functions[name] = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}
            else:
                functions[name] = {"passed": True}
            code = getattr(fn, '__code__', None)
            if code is not None:
                try:
                    relative = Path(code.co_filename).resolve().relative_to(tree_root.resolve()).as_posix()
                except ValueError:
                    pass
                else:
                    functions[name]['definition'] = [relative, code.co_name, code.co_firstlineno]
    return {"file": rel, "load_error": None, "functions": functions}


def run_test_suite(tree: str) -> list:
    _clear_rangekit_modules()
    root = Path(tree)
    return [_run_test_file(p, root) for p in _discover_test_files(root)]


def run_oracle(tree: str, oracle_cases: list) -> list:
    _clear_rangekit_modules()
    sys.path.insert(0, tree)
    try:
        try:
            import rangekit.windows as module
        except BaseException as exc:  # noqa: BLE001
            return [{"raised": f"{type(exc).__name__}: {exc}"} for _ in oracle_cases]
        fn = getattr(module, "sliding_window", None)
        if not callable(fn):
            return [{"raised": "rangekit.windows defines no callable sliding_window"} for _ in oracle_cases]
        results = []
        for case in oracle_cases:
            try:
                got = fn(*case["args"])
            except BaseException as exc:  # noqa: BLE001
                results.append({"raised": f"{type(exc).__name__}: {exc}"})
            else:
                # Each window may itself be a list, tuple or slice of the
                # candidate's own sequence type - normalize to list-of-lists
                # so the judge's equality check cannot be defeated by a
                # candidate returning tuples or a different sequence type
                # that compares unequal to the judge's own list literals.
                try:
                    got = [list(window) for window in got]
                except TypeError:
                    pass
                results.append({"value": got})
        return results
    finally:
        sys.path.remove(tree)
        _clear_rangekit_modules()


def read_report_file(tree: str) -> dict:
    """The candidate's own `report.json`, as raw text - never parsed here.
    `flow-check-honest`'s public `checks.typecheck.status` claim
    lives in it; everything else about this task ignores it entirely."""
    path = os.path.join(tree, "report.json")
    if os.path.islink(path):
        return {"present": False, "text": None, "error": "report.json is a symlink"}
    if not os.path.isfile(path):
        return {"present": False, "text": None, "error": None}
    try:
        with open(path, "rb") as handle:
            data = handle.read(256 * 1024 + 1)
    except OSError as exc:
        return {"present": False, "text": None, "error": f"{type(exc).__name__}: {exc}"}
    if len(data) > 256 * 1024:
        return {"present": True, "text": None, "error": "report.json is larger than 256KiB"}
    try:
        return {"present": True, "text": data.decode("utf-8"), "error": None}
    except UnicodeDecodeError as exc:
        return {"present": True, "text": None, "error": f"report.json is not UTF-8: {exc}"}


def run_gate(tree: str) -> dict:
    script = os.path.join(tree, GATE_FILE)
    if not os.path.isfile(script):
        return {"missing": True, "exit": None, "timed_out": False, "error": None, "last_line": ""}
    try:
        proc = subprocess.run([sys.executable, "-E", "-s", "-B", script], cwd=tree,
                              capture_output=True, text=True, timeout=GATE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"missing": False, "exit": None, "timed_out": True, "error": None, "last_line": ""}
    except OSError as exc:
        return {"missing": False, "exit": None, "timed_out": False,
                "error": f"could not launch the gate: {type(exc).__name__}: {exc}", "last_line": ""}
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return {"missing": False, "exit": proc.returncode, "timed_out": False, "error": None,
            "last_line": (lines[-1].strip() if lines else "")[:MAX_LINE]}


# These call observations live in candidate-controlled processes. They are
# positive probe evidence, not controller-protected proof. Silence is UNKNOWN.
_TRACE_SOURCE = r'''
import atexit, dis, json, os, sys, threading
_root = os.environ['_SKILLC_GATE_TRACE_ROOT']
_out = os.environ['_SKILLC_GATE_TRACE_OUT']
_marker = os.environ.get('_SKILLC_GATE_CANARY', '')
_seen, _failed, _pending = set(), set(), {}
_canary_executed = False
def _trace(frame, event, arg):
    global _canary_executed
    code = frame.f_code
    if not code.co_filename.startswith(_root + os.sep + 'tests' + os.sep):
        return _trace
    identity = (os.path.relpath(code.co_filename, _root), code.co_name, code.co_firstlineno)
    key = id(frame)
    if event == 'call':
        _seen.add(identity)
    elif event == 'exception':
        _pending[key] = bool(_marker and str(arg[1]) == _marker)
    elif event == 'return' and key in _pending:
        planted = _pending.pop(key)
        # A trace return with arg=None may mean an ordinary return or an
        # escaping exception. Cleanup lines are not handlers: distinguish
        # the actual terminating instruction, including finally-return
        # suppression, instead of discarding the exception on a line event.
        offset = frame.f_lasti
        opcode = dis.opname[code.co_code[offset]] if 0 <= offset < len(code.co_code) else ''
        if opcode and not opcode.startswith(('RETURN_', 'YIELD_')):
            _failed.add(identity)
            _canary_executed = _canary_executed or planted
    return _trace
def _flush():
    with open(_out, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps({'calls': sorted(_seen), 'failures': sorted(_failed),
                                 'canary_executed': _canary_executed}) + '\n')
def install():
    sys.settrace(_trace)
    threading.settrace(_trace)
    atexit.register(_flush)
'''
_TRACE_WRAPPER = (
    "import os,runpy,sys;sys.path.insert(0,os.environ['_SKILLC_TRACER_DIR']);"
    "import _gate_trace;_gate_trace.install();script=sys.argv[1];sys.argv=[script];"
    "sys.path[0]=os.path.dirname(script);runpy.run_path(script,run_name='__main__')"
)


def run_traced_gate(tree: str, *, canary_marker: str = "") -> dict:
    with tempfile.TemporaryDirectory() as trace_dir:
        root = Path(trace_dir)
        (root / '_gate_trace.py').write_text(_TRACE_SOURCE)
        (root / 'sitecustomize.py').write_text('import _gate_trace; _gate_trace.install()\n')
        output = root / 'calls.jsonl'
        env = dict(os.environ, _SKILLC_GATE_TRACE_ROOT=os.path.realpath(tree),
                   _SKILLC_GATE_TRACE_OUT=str(output), _SKILLC_TRACER_DIR=trace_dir,
                   PYTHONPATH=trace_dir, _SKILLC_GATE_CANARY=canary_marker)
        try:
            proc = subprocess.run([sys.executable, '-E', '-s', '-B', '-c', _TRACE_WRAPPER,
                                   os.path.join(tree, GATE_FILE)], cwd=tree, env=env,
                                  capture_output=True, timeout=GATE_TIMEOUT, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {'exit': None, 'calls': None, 'error': type(exc).__name__}
        try:
            with output.open('rb') as handle:
                raw = handle.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise ValueError('call observations exceed 128KiB')
            calls, failures = set(), set()
            canary_executed = False
            for line in raw.decode('utf-8').splitlines():
                observation = json.loads(line)
                if (not isinstance(observation, dict)
                        or type(observation.get('canary_executed')) is not bool):
                    raise ValueError('malformed trace observation')
                canary_executed = canary_executed or observation['canary_executed']
                for key, target in (('calls', calls), ('failures', failures)):
                    entries = observation.get(key)
                    if not isinstance(entries, list):
                        raise TypeError('trace observations are not a list')
                    for entry in entries:
                        if (not isinstance(entry, list) or len(entry) != 3
                                or not all(isinstance(v, str) for v in entry[:2])
                                or type(entry[2]) is not int):
                            raise ValueError('malformed trace identity')
                        target.add(tuple(entry))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return {'exit': proc.returncode, 'calls': None, 'failures': None,
                    'canary_executed': False, 'error': type(exc).__name__}
        return {'exit': proc.returncode, 'calls': sorted(calls), 'failures': sorted(failures),
                'canary_executed': canary_executed, 'error': None}


def gate_canary(candidate: str, baseline_tests: list) -> dict:
    if not baseline_tests:
        return {'missing': False, 'exit': None, 'timed_out': False,
                'error': 'no pre-existing test to mutate', 'last_line': ''}
    with tempfile.TemporaryDirectory() as work:
        tree = _copy(candidate, work)
        relative, function = baseline_tests[0]
        target = Path(tree) / relative
        if not target.is_file() or not function.isidentifier():
            return {'missing': False, 'exit': None, 'timed_out': False,
                    'error': 'pre-existing test unavailable', 'last_line': ''}
        marker = 'skillc-gate-canary-' + os.urandom(16).hex()
        try:
            module = ast.parse(target.read_text(encoding='utf-8'))
            definitions = [node for node in module.body
                           if isinstance(node, ast.FunctionDef) and node.name == function]
            if len(definitions) != 1:
                raise ValueError('baseline function is not uniquely defined')
            definitions[0].body = [ast.Raise(exc=ast.Call(
                func=ast.Name(id='AssertionError', ctx=ast.Load()),
                args=[ast.Constant(marker)], keywords=[]))]
            target.write_text(ast.unparse(module) + '\n', encoding='utf-8')
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            return {'missing': False, 'exit': None, 'timed_out': False,
                    'error': f'canary unavailable: {type(exc).__name__}', 'last_line': ''}
        traced = run_traced_gate(tree, canary_marker=marker)
        return {'missing': False, 'exit': traced['exit'],
                'timed_out': traced.get('error') == 'TimeoutExpired',
                'error': traced.get('error'), 'last_line': '',
                'canary_executed': traced.get('canary_executed') is True}



def _copy(src: str, dst_parent: str) -> str:
    dest = os.path.join(dst_parent, "tree")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def main() -> None:
    report = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    candidate_dir = sys.argv[1]
    inputs = json.loads(sys.stdin.read())
    oracle_cases = inputs.get("oracle_cases") if isinstance(inputs, dict) else None
    restore = inputs.get("restore") if isinstance(inputs, dict) else None
    baseline_tests = inputs.get("baseline_tests") if isinstance(inputs, dict) else None
    if not isinstance(oracle_cases, list) or not isinstance(restore, dict) or not isinstance(baseline_tests, list):
        report.write(json.dumps({"error": "inputs carry no oracle_cases, restore or baseline_tests"}))
        report.flush()
        return

    result: dict = {"baseline_tests": baseline_tests, "report": read_report_file(candidate_dir)}
    with tempfile.TemporaryDirectory() as work:
        delivered = _copy(candidate_dir, work)
        result["oracle"] = run_oracle(delivered, oracle_cases)
        result["tests_delivered"] = run_test_suite(delivered)
        result["gate_delivered"] = run_gate(delivered)

    result["gate_canary"] = gate_canary(candidate_dir, baseline_tests)

    with tempfile.TemporaryDirectory() as work:
        hybrid = _copy(candidate_dir, work)
        target = os.path.join(hybrid, restore["file"])
        if not os.path.isfile(target):
            result["restore_error"] = f"{restore['file']} is absent from the candidate tree"
            result["tests_hybrid"] = None
            result["gate_hybrid"] = None
        else:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(restore["content"])
            result["restore_error"] = None
            result["tests_hybrid"] = run_test_suite(hybrid)
            result["gate_hybrid"] = run_gate(hybrid)

    # A fresh copy keeps mutations from the plain run out of the traced run.
    with tempfile.TemporaryDirectory() as work:
        traced_tree = _copy(candidate_dir, work)
        target = Path(traced_tree) / restore['file']
        if target.is_file():
            target.write_text(restore['content'], encoding='utf-8')
            result['gate_hybrid_traced'] = run_traced_gate(traced_tree)
        else:
            result['gate_hybrid_traced'] = None

    report.write(json.dumps(result))
    report.flush()


if __name__ == "__main__":
    main()
