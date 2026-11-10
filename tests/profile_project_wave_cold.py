"""Trusted offline cold actor. Helpers are parsed by name, never run as workflows.

Syntax probes qualify installation and interpreter readability for EVERY reached
helper. A separate pure project-init dry-run exercises its actual entry point.
This does not certify network, authentication, native clients or full workflows.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from profile_project_wave_support import inventory

from skillc import profile


class Unsupported(ValueError):
    """An operation outside the offline proof was refused before dispatch."""


def dispatch(operation: str, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    allowed = operation in {'helper-syntax', 'helper-imports', 'project-dry-run', 'wave-functional'}
    if not argv or Path(argv[0]).name in {'gh', 'curl', 'wget', 'ssh', 'codex', 'claude'}:
        allowed = False
    if not allowed:
        raise Unsupported('network/authentication/client/host fallback unsupported')
    return subprocess.run(argv, capture_output=True, text=True, timeout=20, check=True, **kwargs)


def helper_paths(inv: dict[str, Any]) -> list[str]:
    paths = sorted(r['destination'] for r in profile._install_records(inv)
                   if r.get('source') and '/scripts/' in '/' + r['source']
                   and Path(r['source']).suffix in {'.py', '.sh'})
    assert paths and len(paths) == len(set(paths)), 'nonempty unique helper population'
    return paths



def imports(path: Path) -> list[str]:
    """Resolve all AST imports, including lazy ones, using only helper-owned routes."""
    source = path.read_text()
    tree = ast.parse(source)
    nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    statements = [ast.unparse(node) for node in nodes]
    routes = [str(path.parent)]
    # Both pinned non-stdlib consumers explicitly insert their own parent root.
    # Unknown sys.path expressions are not accepted as evidence of loadability.
    if 'sys.path.insert(0, str(REPO_ROOT))' in source:
        assert 'REPO_ROOT = Path(__file__).resolve().parents[1]' in source
        routes.insert(0, str(path.parent.parent))
    elif 'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))' in source:
        routes.insert(0, str(path.parent.parent))
    script = """import sys,ast
routes,statements=ast.literal_eval(sys.argv[1]),ast.literal_eval(sys.argv[2])
# Isolated interpreter: no controller PYTHONPATH, site packages or cwd fallback.
sys.path[:0]=routes
def guard(event,args):
 if event in {'subprocess.Popen','os.system','socket.connect','socket.getaddrinfo'}:
  raise RuntimeError('cold imports must not execute operations')
 if event=='open' and len(args)>1 and isinstance(args[1],str) and any(c in args[1] for c in 'wax+'):
  raise RuntimeError('cold imports must not write')
sys.addaudithook(guard)
for statement in statements:exec(compile(statement,'<static-import>','exec'),{})
"""
    dispatch('helper-imports', [sys.executable, '-I', '-S', '-B', '-c', script, repr(routes), repr(statements)])
    return statements


def shell_siblings(path: Path, home: Path) -> list[str]:
    """Literal sibling .sh/.py routes in active shell code; no workflow is run.

    Each basename is discovered from source. Relative self-directory routes
    resolve beside the helper; HOME/CPP_DIR routes resolve only in this home.
    Other-client fallback branches are declared unsupported, never host probes.
    """
    seen: set[str] = set()
    for line in path.read_text().splitlines():
        code = line.strip()
        if not code or code.startswith(('#', 'echo ', 'printf ', 'usage_fail ', 'sed ', 'grep ')):
            continue
        for literal in re.findall(r"(?:^|[; ])(?:source|\.)\s+[\"']?(\.?\.?/[A-Za-z0-9_./-]+\.(?:sh|py))", code):
            target = path.parent / literal
            assert target.is_file(), 'missing shell sibling: ' + path.name + ':' + Path(literal).name
            seen.add(Path(literal).name)
        for prefix, suffix in re.findall(r'(\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\})(/[^\s"\'`;]*?[A-Za-z0-9_.-]+\.(?:sh|py))', code):
            token = Path(suffix).name
            if token == path.name:
                continue
            if 'CLAUDE_PLUGIN_ROOT' in prefix:
                continue  # Explicit unsupported other-client route.
            if prefix in {'$HOME', '${HOME}'}:
                candidates = [home / suffix.lstrip('/')]
            elif prefix in {'$CPP_DIR', '${CPP_DIR}'}:
                candidates = [home / 'Projects/claude-power-pack' / suffix.lstrip('/')]
            else:
                candidates = [path.parent / token]
                # A preferred sibling fallback is accepted only when this shell
                # actually names that fallback; never rescue an unrelated route.
                if ('.claude/scripts/' + token) in path.read_text():
                    candidates.append(home / '.claude/scripts' / token)

            assert any(candidate.is_file() for candidate in candidates), 'missing shell sibling: ' + path.name + ':' + token
            seen.add(token)
    return sorted(seen)


def syntax(path: Path) -> None:
    argv = (['bash', '-n', str(path)] if path.suffix == '.sh' else
            [sys.executable, '-c', 'import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(),sys.argv[1],"exec")', str(path)])
    dispatch('helper-syntax', argv)


def require_population(inv: dict[str, Any], rows: object) -> None:
    assert type(rows) is list and rows, 'helper probe population differs'
    assert all(type(row) is dict and type(row.get('helper')) is str and row.get('status') == 'PASS'
               for row in rows), 'helper probe population differs'
    assert [row['helper'] for row in rows] == helper_paths(inv), 'helper probe population differs'


def probe(home: Path, inv: dict[str, Any]) -> dict[str, Any]:
    observed = profile.verify_installed(inv, home)
    failed = [row['destination'] for row in observed['files'] if row['status'] != 'satisfied']
    assert observed['files'] and not failed, 'installed closure differs: ' + ','.join(failed)
    rows = []
    for relative in helper_paths(inv):
        path = home / relative
        first = path.read_text().splitlines()[0]
        assert first.startswith('#!'), 'missing helper shebang: ' + relative
        interpreter = first[2:].split()[-1]
        assert shutil.which(interpreter), 'missing interpreter: ' + relative
        syntax(path)
        dependencies = shell_siblings(path, home) if path.suffix == '.sh' else imports(path)
        rows.append({'interpreter': interpreter, 'resolved_dependencies': dependencies, 'helper': relative, 'probe': 'bash-n' if path.suffix == '.sh' else 'python-compile', 'status': 'PASS'})
    require_population(inv, rows)
    return {'helpers': rows, 'status': 'PASS', 'scope': 'installed bytes/modes; named interpreter, syntax and static dependency resolution',
            'full_workflow_proven': False, 'full_workflow_executable': False, 'admission_authority': False}



def functional(home: Path) -> list[dict[str, str]]:
    """Only four approved offline fixture consumers, never a workflow main."""
    scripts = home / '.codex/skills/flow-wave/scripts'
    state = home / 'synthetic-state'
    state.mkdir()
    env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'XDG_RUNTIME_DIR': str(state),
           'FLOW_WAVE_REGISTRY_DIR': str(state), 'FLOW_WAVE_MAILBOX_DIR': str(state),
           'FLOW_WAVE_LEXICON_DIR': str(state), 'FLOW_VANTAGE_DECLARE': 'container'}
    issue = home / 'issues.json'
    issue.write_text(json.dumps([{'number': 17, 'title': 'synthetic standalone task', 'body': ''}]))
    commands = [
        ('registry', ['bash', str(scripts / 'flow-wave-registry.sh'), 'list', '--wave', 'cold', '--json']),
        ('mailbox', ['bash', str(scripts / 'flow-wave-mailbox.sh'), 'list', '--wave', 'cold', '--json']),
        ('planner', [sys.executable, str(scripts / 'flow-wave-plan.py'), str(issue), '--in-flight', '']),
        ('lexicon', ['bash', str(scripts / 'flow-wave-lexicon.sh'), 'validate', '--body', 'GATE: GO #17 synthetic fixture']),
    ]
    rows = []
    for name, argv in commands:
        result = dispatch('wave-functional', argv, env=env, cwd=home)
        assert result.stdout.strip(), 'functional probe emitted no evidence: ' + name
        if name == 'planner':
            assert '17' in result.stdout and 'FLOW_WAVE_PLAN_EXIT=0' in result.stderr
        elif name == 'lexicon':
            assert 'FLOW_LEXICON: ok' in result.stdout
        else:
            parsed, end = json.JSONDecoder().raw_decode(result.stdout.lstrip())
            assert isinstance(parsed, (dict, list))
            tail = result.stdout.lstrip()[end:].strip()
            assert all(line.startswith(('FLOW_WAVE', 'FLOW_MAILBOX')) for line in tail.splitlines())
        rows.append({'helper': name, 'status': 'PASS', 'scope': 'authored offline fixture only'})
    return rows


def actor(home: Path) -> dict[str, Any]:
    assert not home.exists(), 'home must be cold'
    inv, tree = inventory()
    home.mkdir()
    profile.install(inv, tree, home)
    # The actor's HOME belongs exclusively to this container/proof.
    os.environ['HOME'] = str(home)
    result = probe(home, inv)
    engine = home / 'Projects/claude-power-pack/scripts/project-init.py'
    dry = dispatch('project-dry-run', [sys.executable, str(engine), '--project-name', 'cold-fixture',
                   '--framework', 'python', '--target-dir', str(home / 'cold-fixture'), '--dry-run'])
    plan = json.loads(dry.stdout)
    assert plan and not (home / 'cold-fixture').exists(), 'dry plan must not apply'
    result['functional'] = functional(home)
    result['project_init'] = 'actual deterministic dry-run; planned commands never executed'
    for unsupported in ['gh api user', 'gh repo create --push', 'gh auth', 'native-client', 'host-fallback']:
        try:
            dispatch(unsupported, ['must-never-execute'])
        except Unsupported:
            continue
        raise AssertionError('unsupported operation dispatched')
    # Same instrument, same independently derived inventory, deliberately missing helper.
    target = home / helper_paths(inv)[0]
    target.unlink()
    try:
        probe(home, inv)
    except AssertionError as exc:
        assert str(exc).startswith('installed closure differs: ')
        result['missing_helper_control'] = {'helper': str(target.relative_to(home)), 'result': 'FAIL'}
    else:
        raise AssertionError('missing helper control blind')
    return result


if __name__ == '__main__':
    print(json.dumps(actor(Path(sys.argv[1]))))
