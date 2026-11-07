"""Trusted local actor/recipe checks; no Docker or model execution."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / 'docker/trial/Dockerfile'
SYSTEM_TOOLS = json.loads((DOCKERFILE.parent / 'system-tools.json').read_text())
SCRIPTS = ROOT / 'tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts'


def apt_packages(text: str) -> set[str]:
    body = re.search(r'apt-get install\s+([^;]+);', text)
    assert body is not None, 'trial recipe has no apt install population'
    return {item for item in body[1].replace('\\', ' ').split() if not item.startswith('-')}


def test_shared_trial_recipe_supplies_declared_system_tools() -> None:
    assert SYSTEM_TOOLS and 'jq' in SYSTEM_TOOLS
    for tool, command in SYSTEM_TOOLS.items():
        assert command and command[0] == tool
    missing = set(SYSTEM_TOOLS) - apt_packages(DOCKERFILE.read_text())
    assert not missing, f'trial image is missing declared tools: {sorted(missing)}'


def test_recipe_check_distinguishes_missing_jq_from_working_packages() -> None:
    text = DOCKERFILE.read_text()
    broken = re.sub(r'^\s+jq\s+\\\s*$', '', text, flags=re.MULTILINE)
    assert 'git' in apt_packages(broken)  # The extractor must see a known positive.
    assert 'jq' not in apt_packages(broken)
    assert set(SYSTEM_TOOLS) - apt_packages(broken) == {'jq'}


@pytest.mark.parametrize('provide_jq', [False, True], ids=['missing-jq-control', 'recipe-tools'])
def test_recipe_tools_let_the_real_wave_actor_reach_its_hang(
    tmp_path: Path, provide_jq: bool,
) -> None:
    local_jq = shutil.which('jq')
    assert local_jq is not None, 'trusted local jq required for the positive dependency control'
    repo, home, state, tools = [tmp_path / name for name in ('repo', 'home', 'state', 'bin')]
    for path in (repo, home, state, tools):
        path.mkdir()
    shutil.copyfile(ROOT / 'tests/fixtures/docker-wave-live/wave_role_actor.py', repo / 'wave_role_actor.py')
    for name in ('flow-wave-registry.sh', 'flow-wave-mailbox.sh', 'flow-wave-lexicon.sh'):
        shutil.copyfile(SCRIPTS / name, repo / name)
    commands = ('bash', 'id', 'dirname', 'readlink', 'date', 'hostname', 'git', 'stat',
                'uname', 'cat', 'tr', 'grep', 'sed', 'awk', 'realpath', 'sort',
                'mktemp', 'mkdir', 'flock', 'sleep', 'head', 'tail', 'cut', 'basename',
                'touch', 'chmod', 'rm', 'mv', 'wc', 'find')
    for name in commands:
        source = shutil.which(name)
        # Optional helper facilities are not prerequisites of this jq assay.
        # The actual actor must still register and reach hang, even without ps.
        if source is not None:
            (tools / name).symlink_to(source)
    if provide_jq and 'jq' in apt_packages(DOCKERFILE.read_text()):
        (tools / 'jq').symlink_to(local_jq)
    env = {**os.environ, 'HOME': str(home), 'PATH': str(tools),
           'FLOW_WAVE_REGISTRY_DIR': str(state), 'FLOW_WAVE_MAILBOX_DIR': str(state),
           'FLOW_WAVE_HOST': 'fixture', 'HOSTNAME': 'fixture', 'FLOW_WAVE_NOW': '1',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
    for argv in (['git', 'init', '-q', '-b', 'main'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  'commit', '-qm', 'scripted fixture'],
                 ['git', 'clone', '-q', '--bare', '.', str(tmp_path / 'remote.git')],
                 ['git', 'remote', 'add', 'origin', str(tmp_path / 'remote.git')]):
        subprocess.run(argv, cwd=repo, env=env, capture_output=True, check=True, timeout=5)
    actor = subprocess.Popen([sys.executable, 'wave_role_actor.py', 'worker-a', 'hang', 'start'],
                             cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
    hung = False
    try:
        _stdout, stderr = actor.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        hung = True
        os.killpg(actor.pid, signal.SIGTERM)
        _stdout, stderr = actor.communicate(timeout=5)
    finally:
        if actor.poll() is None:
            os.killpg(actor.pid, signal.SIGKILL)
            actor.wait(timeout=5)
    if provide_jq:
        assert hung, f'actor exited before hang: exit={actor.returncode}; stderr={stderr[-300:]!r}'
        assert (state / 'worker-a.mail').is_file()
    else:
        assert not hung and actor.returncode == 1
        assert b'CPP registration unavailable' in stderr
        assert b'jq is required' in (repo / 'cpp-register.stderr').read_bytes()


def test_jq_control_stage_keeps_the_other_tools_and_default_stage() -> None:
    text = DOCKERFILE.read_text()
    broken = text.split('FROM base AS no-jq\n', 1)[1].split('FROM base AS trial\n', 1)[0]
    assert 'COPY --from=uv-bin /uv /uvx /usr/local/bin/' in broken
    assert 'RUN rm /usr/bin/jq' in broken
    assert re.findall(r'^FROM .* AS (\S+)', text, re.MULTILINE)[-1] == 'trial'


def test_role_summary_keeps_bad_outcomes_and_omits_unrelated_fields(tmp_path: Path) -> None:
    from wave_role_diagnostics import write_role_summary

    roles = ('orchestrator', 'worker-a', 'worker-b')
    report = {'roles': {role: {'exit_codes': [1], 'reasons': ['exited'],
                              'stop': 'confirmed', 'absent': 'confirmed',
                              'credential': 'not-for-summary', 'error': 'not-for-summary'}
                        for role in roles}, 'large-unrelated-report': ['not-for-summary'] * 500}
    text = write_role_summary(tmp_path, report, roles)
    captured = json.loads((tmp_path / 'role-outcomes.json').read_text())
    assert set(captured) == set(roles)
    assert all(set(row) == {'exit_codes', 'reasons', 'stop', 'absent'} for row in captured.values())
    assert all(row['exit_codes'] == [1] and row['reasons'] == ['exited'] for row in captured.values())
    assert 'not-for-summary' not in text
    assert len(text) < 500
    with pytest.raises(ValueError, match='population'):
        write_role_summary(tmp_path, {'roles': {}}, roles)
