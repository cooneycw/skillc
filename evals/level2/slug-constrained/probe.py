#!/usr/bin/env python3
"""Probe for the Level 2 slug-constrained task: the ONLY grading code that runs
candidate code.

Usage: probe.py CANDIDATE_DIR, with a JSON list of input titles on stdin.

Extends Level 1's slug-small-fix probe (evals/level1/slug-small-fix/probe.py)
with three more OBSERVATIONS, none of them a verdict - the judge
(grade_constrained.py --judge) holds every expected value and compares:

  - `outputs`: what `slugify(text)` returned for each input, one positional
    argument only, exactly like Level 1 - drives the functional-* criteria
    AND, together with `signature_ok` below, constraint-interface-stability.
  - `imports`: every top-level module name `src/slugify.py`'s SOURCE TEXT
    imports, found by `ast.parse` - never by executing the file. A static
    check on purpose: a dynamic check (this probe's own `-S` site-packages-
    disabled run, inherited from Level 1's R4/functional-interface) only
    ever sees an import that is actually REACHED, so it cannot catch one
    sitting behind a branch none of the functional inputs exercises. See
    wrong/deferred-import and README.md's "Held-out" section.
  - `signature_ok`/`signature_repr`: whether `inspect.signature(fn)` shows
    every parameter after the first carrying a default - a structural check,
    independent of any one input, for constraint-interface-stability.
  - `notes_digest`/`notes_size`: the candidate's own `NOTES.md`, sha256 hex
    and byte count, or both `None` if the file is missing - constraint-
    data-preservation. The judge holds the ONE expected digest (computed
    once from fixture/NOTES.md, never re-read at grade time) and compares.

Candidate prints go to stderr, so ordinary output cannot mix with the
report, written to a duplicate of the original stdout - candidate code
shares this process and could write that duplicate itself, but gains
nothing it could not gain by returning values or writing NOTES.md itself:
the judge reads every field strictly, and none of them is a verdict.

Runs under `python -I -S -B` (skillc.verify): -S disables site-packages, so
functional-interface's "standard library only at runtime" is enforced by
the run itself. `imports` is a SEPARATE, static check of the same rule,
independent of what a run happens to reach - see above.
"""

import ast
import hashlib
import inspect
import json
import os
import sys

STDLIB = frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)

report = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
candidate = sys.argv[1]
inputs = json.loads(sys.stdin.read())

result: dict = {}

# --- static: imports (never executes the file) -----------------------------
src_path = os.path.join(candidate, "src", "slugify.py")
try:
    with open(src_path, encoding="utf-8") as handle:
        source = handle.read()
except OSError as exc:
    result["ast_error"] = f"{type(exc).__name__}: {exc}"
else:
    try:
        tree = ast.parse(source, filename="slugify.py")
    except SyntaxError as exc:
        result["ast_error"] = f"SyntaxError: {exc}"
    else:
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        result["imports"] = sorted(names)

# --- static: NOTES.md digest -------------------------------------------------
notes_path = os.path.join(candidate, "NOTES.md")
try:
    with open(notes_path, "rb") as handle:
        notes_bytes = handle.read()
except OSError:
    result["notes_digest"] = None
    result["notes_size"] = None
else:
    result["notes_digest"] = hashlib.sha256(notes_bytes).hexdigest()
    result["notes_size"] = len(notes_bytes)

# --- dynamic: import, signature, outputs ------------------------------------
sys.path.insert(0, os.path.join(candidate, "src"))
try:
    import slugify as module
except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
    result["import_error"] = f"{type(exc).__name__}: {exc}"
    report.write(json.dumps(result))
    report.flush()
    sys.exit(0)

fn = getattr(module, "slugify", None)
if not callable(fn):
    result["import_error"] = "src/slugify.py defines no callable slugify"
    report.write(json.dumps(result))
    report.flush()
    sys.exit(0)

try:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    result["signature_repr"] = str(sig)
    result["signature_ok"] = bool(params) and all(
        p.default is not inspect.Parameter.empty for p in params[1:]
    )
except (TypeError, ValueError) as exc:
    result["signature_repr"] = f"{type(exc).__name__}: {exc}"
    result["signature_ok"] = False

outputs = []
for text in inputs:
    try:
        got = fn(text)
    except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
        outputs.append({"raised": f"{type(exc).__name__}: {exc}"})
        continue
    if isinstance(got, str):
        outputs.append({"value": got})
    else:
        outputs.append({"not_str": repr(got)})
result["outputs"] = outputs

report.write(json.dumps(result))
report.flush()
