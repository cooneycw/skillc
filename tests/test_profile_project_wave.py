"""Authored positive/negative controls for the bounded combined-profile proof."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from profile_project_wave_cold import (
    Unsupported,
    dispatch,
    helper_paths,
    imports,
    probe,
    require_population,
    shell_siblings,
    syntax,
)
from profile_project_wave_support import DECL, EXTRA, ROOT, Source, inventory

from skillc import profile


def test_computed_inventory_is_exact_and_preserves_every_existing_profile() -> None:
    inv, _ = inventory()
    assert inv == json.loads((DECL / 'inventory.json').read_text())
    assert inv['selection'] == ['flow-auto', 'flow-register', 'flow-wave', 'project-init']
    assert len(helper_paths(inv)) == 74
    pins = json.loads((DECL / 'preserved-profiles.json').read_text())
    assert len(pins) == 11
    for path, digest in pins.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest


def test_boundary_records_every_unsupported_route_without_claiming_full_workflow() -> None:
    raw = json.loads((DECL / 'profile.json').read_text())
    refs = {r['reference']: r['reason'] for r in raw['unsupported']}
    for key in ['~/.claude/sessions', '$HOME/.claude/sessions', '~/Projects/my-awesome-app',
                '$CPP_DIR/.claude/commands', '$CPP_DIR/.claude/skills', 'gh api user',
                'gh repo create --push', 'gh auth', 'vendor fetch', 'vendor revendor']:
        assert refs[key]
    assert 'flow-register' in raw['select'] and '/flow-register' not in refs
    assert 'flow-eli5' not in raw['select']
    for name in ['flow-wave-registry.sh', 'flow-wave-mailbox.sh', 'flow-wave-lexicon.sh']:
        assert '${CLAUDE_PLUGIN_ROOT}/scripts/' + name in refs
    assert '/home/user/Projects/claude-power-pack' in refs
    with pytest.raises(Unsupported):
        dispatch('gh api user', ['must-never-be-executed'])


def installed(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    inv, tree = inventory()
    home = tmp_path / 'home'
    home.mkdir()
    profile.install(inv, tree, home)
    return inv, home


def test_every_named_helper_resolves_in_the_intact_offline_install(tmp_path: Path) -> None:
    inv, home = installed(tmp_path)
    result = probe(home, inv)
    assert result['status'] == 'PASS'
    assert result['full_workflow_executable'] is False
    assert result['register_step']['status'] == 'PASS'
    assert len(result['register_step']['helpers']) == 6
    assert [r['helper'] for r in result['helpers']] == helper_paths(inv)


@pytest.mark.parametrize('case', ['missing', 'syntax', 'mode'], ids=str)
def test_installation_controls_fail_by_helper_name(tmp_path: Path, case: str) -> None:
    inv, home = installed(tmp_path)
    target = home / '.codex/skills/flow-wave/scripts/flow-wave-plan.py'
    if case == 'missing':
        target.unlink()
    elif case == 'syntax':
        target.write_text('def broken(:\n')
    else:
        target.chmod(0o644)
    with pytest.raises(AssertionError, match='installed closure differs'):
        probe(home, inv)
    violated = profile.verify_installed(inv, home)['files']
    assert any(r['destination'] == str(target.relative_to(home)) and r['status'] != 'satisfied' for r in violated)


def test_static_lazy_import_control_cannot_pass_compile_alone(tmp_path: Path) -> None:
    target = tmp_path / 'lazy.py'
    target.write_text('def unused():\n    import missing_cold_sibling_625\n')
    compile(target.read_bytes(), str(target), 'exec')
    with pytest.raises(subprocess.CalledProcessError):
        imports(target)


def test_wrong_library_route_is_not_rescued_by_ambient_pythonpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, home = installed(tmp_path)
    helper = home / '.codex/skills/flow-auto/scripts/eli5-vendor.py'
    real = home / '.codex/skills/flow-auto/lib/vendor.py'
    # Positive imports the helper's actual, already bundled library without main.
    assert any('lib.vendor' in row for row in imports(helper))
    decoy = home / 'Projects/claude-power-pack/lib/vendor.py'
    decoy.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(real, decoy)
    monkeypatch.setenv('PYTHONPATH', str(decoy.parent.parent))
    with pytest.raises(subprocess.CalledProcessError):
        imports(helper)


def test_missing_shell_sourced_sibling_is_not_a_syntax_success(tmp_path: Path) -> None:
    target = tmp_path / 'caller.sh'
    target.write_text('#!/bin/bash\nsource "$HERE/missing-sibling.sh"\n')
    with pytest.raises(AssertionError, match='missing shell sibling: caller.sh:missing-sibling.sh'):
        shell_siblings(target, tmp_path)
    preferred = tmp_path / '.claude/scripts'
    preferred.mkdir(parents=True)
    (preferred / 'missing-sibling.sh').write_text('#!/bin/bash\n')
    with pytest.raises(AssertionError, match='missing shell sibling'):
        shell_siblings(target, tmp_path)
    (tmp_path / 'missing-sibling.sh').write_text('#!/bin/bash\n')
    assert shell_siblings(target, tmp_path) == ['missing-sibling.sh']


def test_clutter_map_explicitly_allows_no_retired_wave_residue() -> None:
    value = json.loads((DECL / 'clutter-map.json').read_text())
    assert value['cpp_revision'] == Source.revision and value['retired_wave_allowed'] == []
    assert set(value['surfaces']) == {'registry', 'mailboxes', 'cursors', 'heartbeats', 'locks', 'claims', 'shared'}
    for row in value['surfaces'].values():
        assert row['selectors'] and row['retired_allowed'] == []
    assert '#639' in value['study_binding']


def test_source_provenance_is_nonempty_and_immutable() -> None:
    tree = Source()
    meta = json.loads((EXTRA / 'provenance.json').read_text())
    assert len(meta['files']) == 10
    assert tree.read('scripts/project-init.py')


CASES = json.loads((ROOT / 'controls/profile-project-wave-cold/cases.json').read_text())


@pytest.mark.parametrize('case', CASES['syntax'], ids=str)
def test_broken_syntax_is_a_named_interpreter_failure(tmp_path: Path, case: str) -> None:
    target = tmp_path / case
    target.write_text('if then\n' if case.endswith('.sh') else 'def broken(:\n')
    with pytest.raises(subprocess.CalledProcessError) as caught:
        syntax(target)
    assert str(target) in caught.value.cmd


@pytest.mark.parametrize('case', CASES['profile_wrong_types'], ids=lambda row: row['field'])
def test_committed_profile_wrong_type_sweep(case: dict[str, Any]) -> None:
    assert len(CASES['profile_wrong_types']) == 7
    for value in case['values']:
        raw = json.loads((DECL / 'profile.json').read_text())
        raw[case['field']] = value
        with pytest.raises(profile.Refused):
            candidate = profile.Profile.from_dict(raw, DECL)
            profile.validate(candidate, Source())


def test_probe_population_refuses_empty_wrong_duplicate_omitted_and_failed_rows() -> None:
    inv, _ = inventory()
    good = [{'helper': path, 'status': 'PASS'} for path in helper_paths(inv)]
    require_population(inv, good)
    for bad in CASES['population']['bad']:
        with pytest.raises(AssertionError, match='helper probe population differs'):
            require_population(inv, bad)
    for mutant in CASES['population']['mutants']:
        rows = [dict(row) for row in good]
        if mutant == 'omit-one':
            rows.pop()
        elif mutant == 'duplicate-one':
            rows[-1] = dict(rows[0])
        elif mutant == 'reorder':
            rows.reverse()
        else:
            rows[0]['status'] = 'FAIL'
        with pytest.raises(AssertionError, match='helper probe population differs'):
            require_population(inv, rows)


def test_network_and_authentication_refusals_never_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: seen.append(args))
    for operation in ['gh api user', 'gh auth', 'gh repo create --push', 'host-fallback', 'native-client']:
        with pytest.raises(Unsupported):
            dispatch(operation, ['must-never-execute'])
    for tool in ['gh', 'curl', 'wget', 'ssh', 'codex', 'claude']:
        with pytest.raises(Unsupported):
            dispatch('helper-syntax', [tool, '--help'])
    assert seen == []


@pytest.mark.parametrize('source', ['source ./missing.sh', '. "./missing.sh"'])
def test_literal_shell_source_path_must_resolve(tmp_path: Path, source: str) -> None:
    target = tmp_path / 'caller.sh'
    target.write_text('#!/bin/bash\n' + source + '\n')
    with pytest.raises(AssertionError, match='missing shell sibling: caller.sh:missing.sh'):
        shell_siblings(target, tmp_path)


def test_no_unapproved_profile_or_clutter_policy_drift_is_hidden() -> None:
    pins = json.loads((DECL / 'preserved-profiles.json').read_text())
    paths = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'evals/subjects').glob('*/profile.json')}
    assert paths == set(pins) | {str(DECL.relative_to(ROOT) / 'profile.json')}


def test_mypy_extra_snapshot_exception_does_not_hide_siblings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import test_profile_flow_auto_87ecb097 as existing
    monkeypatch.setattr(existing, 'SOURCE', EXTRA)
    existing.test_mypy_snapshot_exemption_is_exact(tmp_path)


def test_flow_register_skill_entrypoint_is_required_by_name(tmp_path: Path) -> None:
    inv, home = installed(tmp_path)
    target = home / '.codex/skills/flow-register/SKILL.md'
    if target.exists():
        target.unlink()
    with pytest.raises(AssertionError, match='flow-register.*SKILL.md'):
        probe(home, inv)


def test_committed_fourth_selection_wrong_type_sweep() -> None:
    assert len(CASES['register_selection_invalid']) == 7
    for value in CASES['register_selection_invalid']:
        raw = json.loads((DECL / 'profile.json').read_text())
        raw['select'][3] = value
        with pytest.raises(profile.Refused):
            candidate = profile.Profile.from_dict(raw, DECL)
            profile.validate(candidate, Source())


def test_fourth_skill_additions_match_the_computed_inventory() -> None:
    inv, _ = inventory()
    added = json.loads((ROOT / 'controls/profile-project-wave-cold/register-additions.json').read_text())
    files = sorted(row['destination'] for row in profile._install_records(inv)
                   if row['destination'].startswith('.codex/skills/flow-register/'))
    helpers = [path for path in helper_paths(inv) if path.startswith('.codex/skills/flow-register/')]
    assert len(files) == 10 and files == added['added_files']
    assert len(helpers) == 6 and helpers == added['added_helpers']
