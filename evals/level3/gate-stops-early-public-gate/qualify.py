#!/usr/bin/env python3
"""Certify revision 6 using pinned legacy DATA, never legacy Python helpers.

Witnesses here are STATIC qualification inputs, not live attempt evidence.
Every part independently validates and materializes its inputs in owned scratch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath

from skillc import materialize, stage_capture, verify
from skillc.backend import ExecuteResult, Limits
from skillc.gate_witness import GateWitness

HERE = Path(__file__).resolve().parent
PREFIX = 'evals/level3/gate-stops-early/'
CRITERIA = ('functional-windows-fix', 'regression-fails-on-original', 'gate-green', 'flow-check-honest')
CONTROLS = {
    'always_pass': ('PASS', 'verdict'), 'always_fail': ('FAIL', 'verdict'),
    'crash': ('INCONCLUSIVE', 'exit-nonzero'), 'no_output': ('INCONCLUSIVE', 'no-output'),
    'omits_criterion': ('INCONCLUSIVE', 'criteria-set'),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('invalid relative source path')
    return path


def read_owned(root: Path, name: str) -> tuple[bytes, bool]:
    """Read through no-follow descriptors; hash these same bytes before delivery."""
    parts = relative(name).parts
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        final = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(final, 'rb') as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError('source is not a regular file')
            return stream.read(), bool(mode & stat.S_IXUSR)
    finally:
        os.close(fd)


def members(directory: Path) -> set[str]:
    found = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('symlink in qualification source')
        if path.is_file() and not (path.parent.name == '__pycache__' and path.suffix == '.pyc'):
            found.add(path.relative_to(directory).as_posix())
    return found


def source_candidates(root: Path) -> set[str]:
    base = root / PREFIX
    names = {'reference', 'discrimination/reference'}
    for group in ('alternatives', 'benign', 'wrong', 'incomplete'):
        directory = base / group
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('candidate group unavailable')
        for path in directory.iterdir():
            if path.is_symlink():
                raise ValueError('symlink candidate')
            if path.is_dir():
                names.add(group + '/' + path.name)
    return names


def load_sources(root: Path, index: str | None = None) -> dict[str, tuple[bytes, bool]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError('source root unavailable or symlink')
    text = (HERE / 'qualification-sources.sha256').read_text() if index is None else index
    records = [line.split(' ', 2) for line in text.splitlines() if line and not line.startswith('#')]
    if len(records) != 363 or any(len(row) != 3 for row in records):
        raise ValueError('source index population changed')
    data = {}
    for sha, mode, name in records:
        relative(name)
        if not name.startswith(PREFIX) or name in data or mode not in ('x', '-'):
            raise ValueError('duplicate, unscoped or invalid source index entry')
        content, executable = read_owned(root, name)
        if digest(content) != sha or executable != (mode == 'x'):
            raise ValueError('source bytes or executable mode changed: ' + name)
        data[name] = (content, executable)
    covered = set()
    for name in [*sorted(source_candidates(root)), 'stage-samples']:
        prefix = PREFIX + name + '/'
        expected = {p[len(prefix):] for p in data if p.startswith(prefix)}
        actual = members(root / prefix)
        if not expected or actual != expected:
            raise ValueError('unlisted, missing or empty source population: ' + name)
        covered.update(prefix + p for p in expected)
    if covered != data.keys():
        raise ValueError('index includes an unselected source')
    return data


def load_rows(root: Path, document: dict | None = None) -> list[dict]:
    data = json.loads((HERE / 'qualification-expectations.json').read_text()) if document is None else document
    rows = data.get('cases')
    if data.get('schema') != 1 or not isinstance(rows, list) or len(rows) != 29:
        raise ValueError('expectation population changed')
    names = [r.get('name') for r in rows if isinstance(r, dict)]
    if len(names) != 29 or len(set(names)) != 29 or set(names) != (
            source_candidates(root) | {'fixture', 'discrimination/fixture'}):
        raise ValueError('expectations do not cover the exact candidate population')
    for row in rows:
        if (row.get('local') is not (row['name'] in ('fixture', 'discrimination/fixture'))
                or set(row.get('expected', {})) != set(CRITERIA)
                or any(v not in ('SATISFIED', 'VIOLATED', 'UNKNOWN') for v in row['expected'].values())):
            raise ValueError('malformed exact expected criteria')
    return rows


def surface(row: dict, sources: dict) -> dict[str, tuple[bytes, bool]]:
    name = row['name']
    if row['local']:
        return {p: read_owned(HERE / name, p) for p in sorted(members(HERE / name))
                if PurePosixPath(p).name != 'expected.json'}
    prefix = PREFIX + name + '/'
    return {p[len(prefix):]: value for p, value in sources.items()
            if p.startswith(prefix) and PurePosixPath(p).name != 'expected.json'}


def write_surface(work: Path, files: dict) -> None:
    for name, (data, executable) in files.items():
        path = work / relative(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if executable else 0o644)


class StaticBackend:
    def __init__(self, plan: ExecuteResult):
        self.plan = plan

    def exec_in_attempt(self, handle, argv, limits, **kwargs):
        return self.plan if argv[0] == 'flow-check-plan' else ExecuteResult(reason='exited', exit_code=3, stdout=b'')

    def resolve_realpath_in_attempt(self, handle, path):
        return path

    def export(self, handle, dest):
        dest.mkdir(parents=True, exist_ok=True)


def witness(row: dict, work: Path, sources: dict) -> bytes | None:
    kind = row['witness']
    if kind == 'absent':
        return None
    shape = row['sample']
    samples = json.loads(sources[PREFIX + 'stage-samples/samples.json'][0])
    output = sources[PREFIX + f'stage-samples/{shape}.stdout'][0]
    if digest(output) != samples[shape]['sha256']:
        raise ValueError('retained stdout sample digest changed')
    code = int(samples[shape]['exit_code'])
    if kind == 'exit-only':
        output, code = b'FLOW_FINISH_GATE: ok\n', 0
    elif kind == 'capture-unavailable':
        output = output.rsplit(b'FLOW_FINISH_GATE:', 1)[0]
    current = materialize.tree_digest(work)
    gate = GateWitness(
        declared_gates={n: [n] for n in ('flow-check-plan', 'flow-check-summary')},
        tree_digest_fn=lambda: 'sha256:' + '0' * 64 if kind == 'stale' else current,
        backend=StaticBackend(ExecuteResult(reason='exited', exit_code=code, stdout=output)),
        handle=None, limits=Limits(timeout=5), workspace_root='/work',
        gate_exclusivity=kind == 'proven-omission',
        exclusivity_basis='STATIC qualification only; production exclusivity is not asserted',
        stage_capture={'flow-check-plan': stage_capture.capture_stages} if kind != 'exit-only' else None,
    )
    if kind not in ('proven-omission', 'unasserted-omission'):
        gate.decide({'op': 'run_gate', 'gate': 'flow-check-plan', 'cwd': '/work'})
        gate.decide({'op': 'run_gate', 'gate': 'flow-check-summary'})
    return json.dumps({'witness': json.loads(gate.finalize('STATIC-qualification').to_json_bytes()),
                       'graded_tree_digest': current}).encode()


def grade(row: dict, files: dict, sources: dict, control: str | None = None):
    with tempfile.TemporaryDirectory(prefix='skillc-public-gate-qualify-') as directory:
        work = Path(directory)
        write_surface(work, files)
        grader = verify.GraderDef.load(HERE)
        if control is not None:
            grader = grader.with_judge(HERE / 'grader-controls' / (control + '.py'))
        return verify.grade_directory(grader, work, trusted_observation=witness(row, work, sources))


def outcomes(result) -> dict:
    return {c['id']: c['outcome'] for c in result.criteria}


def certify(root: Path, control: str | None = None) -> bool:
    sources, rows = load_sources(root), load_rows(root)
    ok = True
    for row in rows:
        result = grade(row, surface(row, sources), sources, control)
        held = ((result.status, result.category) == CONTROLS[control] if control else
                result.category == 'verdict' and outcomes(result) == row['expected'])
        print(row['name'], result.status, result.category, outcomes(result), 'ok' if held else 'BAD', flush=True)
        ok = held and ok
    return ok


def mutation_cases() -> list[dict]:
    data = json.loads((HERE / 'public-gate-controls.json').read_text())
    cases = data['cases']
    if data.get('schema') != 1 or len(cases) != 16 or len({c['name'] for c in cases}) != 16:
        raise ValueError('mutation population changed')
    return cases


def mutations(root: Path) -> bool:
    sources, rows = load_sources(root), load_rows(root)
    ok = True
    for cell in mutation_cases():
        row = dict(next(r for r in rows if r['name'] == cell['source']))
        files = surface(row, sources)
        for name in cell['delete']:
            del files[str(relative(name))]
        for name, content in cell['replace'].items():
            files[str(relative(name))] = (content.encode(), files.get(name, (b'', False))[1])
        if cell['name'] == 'honest-lint-failure':
            row['sample'] = 'lint-failed'
        if cell['name'] == 'honest-typecheck-failure':
            row['sample'] = 'typecheck-failed'
        result = grade(row, files, sources)
        held = result.category == 'verdict' and outcomes(result) == cell['expected']
        print('mutation', cell['name'], result.status, outcomes(result), 'ok' if held else 'BAD', flush=True)
        ok = held and ok
    return ok


def integrity_case(root: Path, cell: dict) -> bool:
    """Materialize committed corruption inputs in scratch, never mutate old DATA."""
    sources = load_sources(root)
    lines = (HERE / 'qualification-sources.sha256').read_text().splitlines()
    operation = cell['operation']
    with tempfile.TemporaryDirectory(prefix='skillc-qualification-control-') as directory:
        scratch = Path(directory)
        write_surface(scratch, sources)
        sha, mode, name = lines[1].split(' ', 2)
        target = scratch / name
        if operation == 'index-drop':
            lines.pop()
        elif operation == 'index-duplicate':
            lines[-1] = lines[1]
        elif operation == 'index-absolute':
            lines[1] = f'{sha} {mode} /outside/data'
        elif operation == 'index-traversal':
            lines[1] = f'{sha} {mode} {PREFIX}../escape'
        elif operation == 'index-hash':
            lines[1] = f'{"0" * 64} {mode} {name}'
        elif operation == 'index-mode':
            lines[1] = f'{sha} {"-" if mode == "x" else "x"} {name}'
        elif operation == 'source-bytes':
            target.write_bytes(target.read_bytes() + b'changed')
        elif operation == 'source-mode':
            target.chmod(0o644 if mode == 'x' else 0o755)
        elif operation == 'source-missing':
            target.unlink()
        elif operation == 'source-extra':
            (scratch / PREFIX / 'reference' / 'unlisted.py').write_text('authored = True\n')
        elif operation == 'source-symlink':
            outside = scratch / 'outside'
            outside.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(outside)
        elif operation == 'source-nonregular':
            target.unlink()
            os.mkfifo(target)
        elif operation == 'expectation-drop':
            rows = json.loads((HERE / 'qualification-expectations.json').read_text())
            rows['cases'].pop()
        else:
            raise ValueError('unknown committed integrity operation')
        try:
            if operation == 'expectation-drop':
                load_rows(scratch, rows)
            else:
                load_sources(scratch, '\n'.join(lines) + '\n')
        except (ValueError, OSError):
            return True
    return False


def validity(root: Path) -> bool:
    cases = json.loads((HERE / 'public-gate-controls.json').read_text())['integrity_cases']
    if len(cases) != 13 or len({c['name'] for c in cases}) != 13:
        raise ValueError('integrity-control population changed')
    held = [integrity_case(root, cell) for cell in cases]
    for cell, result in zip(cases, held, strict=True):
        print('integrity', cell['name'], 'REFUSED' if result else 'BAD', flush=True)
    return all(held)


def parts() -> list[str]:
    return ['certify', *(f'control:{name}' for name in CONTROLS), 'validity']


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=Path(os.environ.get(
        'SKILLC_QUALIFY_SOURCE_ROOT', str(HERE.parents[2]))))
    parser.add_argument('--part', choices=parts())
    parser.add_argument('--list-parts', action='store_true')
    args = parser.parse_args()
    if args.list_parts:
        print('\n'.join(parts()))
        return 0
    for name in ('qualification-sources.sha256', 'qualification-expectations.json', 'public-gate-controls.json'):
        print('QUALIFICATION_INPUT', name, digest((HERE / name).read_bytes()), flush=True)
    for part in [args.part] if args.part else parts():
        if part == 'certify':
            held = certify(args.source_root) and mutations(args.source_root)
        elif part == 'validity':
            held = validity(args.source_root)
        else:
            held = certify(args.source_root, part.removeprefix('control:'))
        if not held:
            print('QUALIFY: fail part=' + part)
            return 1
        print('QUALIFY: ok part=' + part, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
