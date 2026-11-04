"""Exercise a trusted supervisor's pure load-timer function without running it.

The source must belong to the controller. Only its undecorated `step` function
is compiled; the supervisor's imports, launch, waits and process actions do not
run. This is a policy control, not a measurement of a host's actual load.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

CASES = Path(__file__).resolve().parents[1] / 'controls/heavy-run-load/cases.json'


def check(source: Path) -> dict[str, list[str]]:
    tree = ast.parse(source.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'step']
    if len(functions) != 1 or functions[0].decorator_list:
        raise ValueError('expected exactly one undecorated trusted step function')
    namespace: dict[str, Any] = {'__builtins__': {}}
    module = ast.Module(body=[functions[0]], type_ignores=[])
    exec(compile(module, '<load-control-step>', 'exec'), namespace)  # noqa: S102 - explicit trusted function
    outcomes: dict[str, list[str]] = {'passed': [], 'failed': []}
    for case in json.loads(CASES.read_text()):
        state = None
        actual = []
        for now, load in case['trace']:
            state, abort = namespace['step'](state, now, load)
            actual.append(abort)
        matches = (len(actual) == len(case['abort_after_each_sample'])
                   and all(type(value) is bool for value in actual)
                   and actual == case['abort_after_each_sample'])
        outcomes['passed' if matches else 'failed'].append(case['name'])
    if len(outcomes['passed']) + len(outcomes['failed']) != 4:
        raise ValueError('expected the four committed timer controls')
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='trusted supervisor or committed control source')
    args = parser.parse_args()
    try:
        result = check(args.source)
    except (OSError, SyntaxError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'UNKNOWN', 'reason': str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
