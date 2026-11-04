"""Pinned source/closure controls only; installed subject code runs in Docker."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/fixtures/profile-cpp-codex-project-wave-auto-87ecb097'
DECLARATION = ROOT / 'evals/subjects/cpp-codex-project-wave-auto-87ecb097/profile.json'
CONTROLS = ROOT / 'controls/profile-project-wave'


def check_source(root: Path = SOURCE, manifest_path: Path = CONTROLS / 'source-manifest.json') -> None:
    data = manifest_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == '9e2a435f17fff815e27e04f91f8e46bf633ed2dc588ccfe880d838bd61d37a98'
    manifest = json.loads(data)
    assert manifest['revision'] == '87ecb0970f70aace9e0323feee00c9ca57dda133'
    rows = manifest['files']
    assert len(rows) == 315 and len({r['source'] for r in rows}) == 315
    assert sum(r['bytes'] for r in rows) == 7_027_797
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    assert actual == {r['source'] for r in rows} | {'README.md'}
    for row in rows:
        path = root / row['source']
        assert not path.is_symlink()
        data = path.read_bytes()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        assert profile.git_blob_id(data) == row['git_blob']
        assert ('100755' if path.stat().st_mode & 0o111 else '100644') == row['mode']


def test_source_population_and_combined_closure() -> None:
    check_source()
    tree = profile.DirTree(SOURCE)
    inv = profile.validate(profile.Profile.load(DECLARATION), tree)
    assert inv['selection'] == ['claude-md-lint', 'flow-auto', 'flow-eli5', 'flow-register',
                                'flow-wave', 'github-issue-create', 'project-init']
    assert len(profile.installed_home_files(inv, tree)) == 320


@pytest.mark.parametrize('case', json.loads((CONTROLS / 'cases.json').read_text()), ids=lambda c: c['name'])
def test_missing_transitive_dependency_cases(case: dict[str, Any]) -> None:
    raw = json.loads(DECLARATION.read_text())
    if case['remove_dependency']:
        raw['dependencies'] = [r for r in raw['dependencies'] if r['id'] != case['remove_dependency']]
    candidate = profile.Profile.from_dict(raw, DECLARATION.parent)
    if case['expected'] == 'REFUSED':
        with pytest.raises(profile.Refused):
            profile.validate(candidate, profile.DirTree(SOURCE))
    else:
        inv = profile.validate(candidate, profile.DirTree(SOURCE))
        assert len(profile.installed_home_files(inv, profile.DirTree(SOURCE))) == case['installed_files']


@pytest.mark.parametrize('fault', ['changed', 'missing', 'extra', 'mode'])
def test_source_manifest_distinguishes_committed_mutations(tmp_path: Path, fault: str) -> None:
    root = tmp_path / 'source'
    shutil.copytree(SOURCE, root)
    target = root / 'scripts/flow-wave-lexicon.sh'
    if fault == 'changed':
        target.write_bytes(target.read_bytes() + b'\n# changed control\n')
    elif fault == 'missing':
        target.unlink()
    elif fault == 'extra':
        (root / 'authored_probe.py').write_text('authored: int = "not vendor data"\n')
    else:
        target.chmod(0o644)
    with pytest.raises(AssertionError):
        check_source(root)


def test_changed_manifest_cannot_relabel_changed_source_as_pinned(tmp_path: Path) -> None:
    raw = json.loads((CONTROLS / 'source-manifest.json').read_text())
    raw['files'][0]['sha256'] = '0' * 64
    path = tmp_path / 'source-manifest.json'
    path.write_text(json.dumps(raw, indent=2) + '\n')
    with pytest.raises(AssertionError):
        check_source(SOURCE, path)


def test_snapshot_citation_exemption_does_not_hide_neighbors() -> None:
    from test_private_citations import _is_excluded
    prefix = SOURCE.relative_to(ROOT).as_posix()
    assert _is_excluded(prefix + '/scripts/flow-plan-record.py')
    assert not _is_excluded(prefix + 'x/scripts/flow-plan-record.py')
    assert not _is_excluded('tests/test_profile_project_wave.py')


def test_snapshot_mypy_exemption_keeps_authored_tests_checked(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text((ROOT / 'pyproject.toml').read_text())
    prefix = SOURCE.relative_to(ROOT).as_posix()
    paths = [prefix + '/probe.py', prefix + 'x/sibling.py', 'tests/test_profile_project_wave.py',
             'tests/test_profile_project_wave_cold_live.py']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value: int = 'control type error'\n")
    result = subprocess.run([sys.executable, '-m', 'mypy', 'tests'], cwd=tmp_path,
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 1
    assert [p for p in paths if p + ':1: error:' in result.stdout] == paths[1:]


def test_collection_exclusion_keeps_neighbor_and_authored_tests_visible(tmp_path: Path) -> None:
    module = ast.parse((ROOT / 'tests/conftest.py').read_text())
    assignment = next(n for n in module.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'collect_ignore_glob' for t in n.targets))
    ignored = ast.literal_eval(assignment.value)
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'conftest.py').write_text('collect_ignore_glob = ' + repr(ignored) + '\n')
    prefix = SOURCE.relative_to(ROOT).as_posix()
    paths = [prefix + '/test_vendor_probe.py', prefix + 'x/test_sibling_probe.py',
             'tests/test_authored_probe.py']
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('def test_control():\n    assert True\n')
    result = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', 'tests'],
                            cwd=tmp_path, env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [path for path in paths if path + '::test_control' in result.stdout] == paths[1:]
