"""Trusted fixed command actor; run only inside the bounded cold container."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from test_profile_flow_auto_87ecb097_cold import Budget, need, observed_command

from skillc import fixture_service as fs
from skillc import profile
from skillc.decide_reply_channel import DecideReplyChannel


def actor(case: str) -> dict[str, Any]:
    root = Path('/opt/controller')
    need(root.is_dir() and os.environ.get('SKILLC_PROJECT_WAVE_ACTOR') == '1', 'container actor only')
    cases = json.loads((root / 'controls/profile-project-wave/cold-cases.json').read_text())
    need(case in cases and case != 'forbidden-bind', 'closed command case')
    source = root / 'tests/fixtures/profile-cpp-codex-project-wave-auto-87ecb097'
    declaration = root / 'evals/subjects/cpp-codex-project-wave-auto-87ecb097/profile.json'
    inv = profile.validate(profile.Profile.load(declaration), profile.DirTree(source))
    home = Path('/home/proof')
    home.mkdir(exist_ok=True)
    # Install and all probes occur here, never on the host. Import availability
    # and live/native workflow readiness are not inferred from file installation.
    profile.install(inv, profile.DirTree(source), home)
    verified = profile.verify_installed(inv, home)
    need(len(verified['files']) == 320 and all(r['status'] == 'satisfied' for r in verified['files']),
         'actual installed closure')
    logs = Path('/work/commands')
    logs.mkdir()
    budget = Budget(logs, 80)
    rows: list[Any] = [{'installed_files': 320}]
    tools = Path('/work/tools')
    tools.mkdir()
    (tools / 'gh').write_text('#!/bin/sh\nexec /usr/local/bin/python /opt/controller/gh-shim.py "$@"\n')
    (tools / 'gh').chmod(0o755)
    env = {'HOME': str(home), 'PATH': str(tools) + ':/usr/local/bin:/usr/bin:/bin',
           'PYTHONPATH': str(root), 'LC_ALL': 'C', 'UV_OFFLINE': '1',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(home / '.gitconfig'),
           'GIT_ALLOW_PROTOCOL': 'file', 'GIT_AUTHOR_NAME': 'Fixture',
           'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
           'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'XDG_RUNTIME_DIR': '/work/runtime',
           'FLOW_WAVE_MAILBOX_DIR': '/work/waves', 'FLOW_WAVE_REGISTRY_DIR': '/work/waves',
           'SKILLC_TRIGGER_SOCKET': '/work/gh.sock', 'UV_CACHE_DIR': '/work/scaffold-cache'}
    Path('/work/runtime').mkdir()
    if case != 'offline-cache-unavailable':
        shutil.copytree('/opt/scaffold-cache', env['UV_CACHE_DIR'])

    def call(argv: list[str], cwd: Path, local: dict[str, str] | None = None) -> tuple[int, str]:
        return observed_command(budget, rows, argv, cwd, local or env)

    project = home / 'Projects/widget'
    engine = home / 'Projects/claude-power-pack/scripts/project-init.py'
    rc, output = call([sys.executable, str(engine), '--project-name', 'widget', '--framework', 'python',
                       '--target-dir', str(project)], home)
    if case == 'offline-cache-unavailable':
        need(rc != 0 and ('cache' in output.lower() or 'offline' in output.lower())
             and not (project / '.git').exists(), 'actual uncached engine must refuse before Git initialization')
        return {'case': case, 'observations': rows, 'scope': 'offline cache refusal; no project/service readiness'}
    need(rc == 0 and (project / 'pyproject.toml').is_file() and (project / '.git').is_dir(),
         'actual project engine scaffold: ' + output[-300:])
    need(hashlib.sha256((project / 'uv.lock').read_bytes()).digest()
         == hashlib.sha256(Path('/opt/scaffold-warm/uv.lock').read_bytes()).digest(),
         'actual scaffold resolution differs from baked dependency cache')
    bare = Path('/work/remote.git')
    need(call(['git', 'init', '--bare', '-q', str(bare)], home)[0] == 0, 'fixture remote initialization')
    service = fs.FixtureService({
        'fixture_service_schema': 1,
        'repository': {'name_with_owner': 'fixture/widget', 'default_branch': 'main',
                       'remote_urls': [str(bare)], 'exists': False, 'creation_transport_url': str(bare)},
        'authority': list(fs.OPS), 'clock': {'start': '2026-10-17T00:00:00Z'},
    }, fs.LocalGitRemote(bare), 'cold-project-wave')
    channel = DecideReplyChannel(Path(env['SKILLC_TRIGGER_SOCKET']),
                                 fs.dispatch({'gh': (service.decide, fs.REQUEST_KEYS)}), 'cold-project-wave')
    channel.start()
    channel_active = True
    try:
        rc, output = call(['gh', 'repo', 'create', 'widget', '--private', '--source=.', '--push'], project)
        need(rc == 0 and service._remote.resolve('refs/heads/main') is not None, 'fixture repo create/push')
        spec = project / '.specify/specs/cold'
        spec.mkdir(parents=True, exist_ok=True)
        (spec / 'spec.md').write_text('# Cold project\n\n## Requirements\n- Deliver an offline fixture.\n')
        (spec / 'tasks.md').write_text('# Tasks\n\n- [ ] **T001** [US1] Add the fixture result\n')
        helpers = home / '.claude/scripts'
        converter = helpers / 'speckit-tasks-to-issues.sh'
        data = home / 'Projects/claude-power-pack/templates/cicd.yml.example'
        if case == 'missing-context-helper':
            (helpers / 'speckit-context.py').unlink()
        elif case == 'missing-project-data':
            data.unlink()
            rc, _ = call(['cp', str(data), str(project / 'cicd.yml')], project)
            need(rc != 0 and not (project / 'cicd.yml').exists(), 'actual missing template refuses copy')
        elif case == 'missing-jq':
            jq = shutil.which('jq', path=env['PATH'])
            need(jq is not None, 'jq positive tool population')
            # An actual missing PATH executable, without modifying the
            # read-only image or replacing jq with a fake success program.
            restricted = Path('/work/without-jq')
            restricted.mkdir()
            for directory in (tools, Path('/usr/local/bin'), Path('/usr/bin'), Path('/bin')):
                for binary in directory.iterdir():
                    target = restricted / binary.name
                    if binary.name != 'jq' and binary.is_file() and os.access(binary, os.X_OK) and not target.is_symlink():
                        target.symlink_to(binary)
            env = {**env, 'PATH': str(restricted)}
        elif case == 'service-unavailable':
            channel.stop_and_finalize()
            channel_active = False
            rc, _ = call(['gh', 'issue', 'list', '--json', 'number,title,body'], project)
            need(rc == 125, 'actual disconnected service is not an empty issue population')
        rc, output = call(['bash', str(converter), '--tasks', str(spec / 'tasks.md')], project)
        if case in ('missing-context-helper', 'missing-jq', 'service-unavailable'):
            expected = {'missing-context-helper': 7, 'missing-jq': 1, 'service-unavailable': 4}[case]
            need(rc == expected, 'actual converter refusal must identify the injected failure')
            need(not service.finalize('cold-project-wave').final_state['issues'], 'broken path filed an issue')
        else:
            need(rc == 0, 'installed issue converter: ' + output[-500:])
            state = service.finalize('cold-project-wave').final_state
            need(len(state['issues']) == 1, 'actual issue filing population')
            issue = next(iter(state['issues'].values()))
            need('T001' in issue['title'] and '<!-- speckit-context:v1' in issue['body'], 'real context helper consumed')
            rc, listing = call(['gh', 'issue', 'list', '--state', 'all', '--json', 'number,title,body,state',
                                '--limit', '200'], project)
            need(rc == 0 and len(json.loads(listing)) == 1, 'fixture issue listing')
            issues = Path('/work/issues.json')
            issues.write_text(listing)
            rc, plan = call([sys.executable, str(helpers / 'flow-wave-plan.py'), str(issues),
                             '--in-flight', ''], project)
            need(rc == 0 and 'FLOW_WAVE_PLAN_EXIT=0' in plan, 'installed planner consumed filed issue')
            registry = helpers / 'flow-wave-registry.sh'
            rc, _ = call(['bash', str(registry), 'policy', 'set', '--wave', 'cold',
                           '--authority', 'implement', '--driver', 'codex'], project)
            need(rc == 0, 'installed registry policy writer')
            rc, shown = call(['bash', str(registry), 'policy', 'show', '--wave', 'cold', '--json'], project)
            need(rc == 0 and 'implement' in shown, 'installed registry consumed stored policy')
            mailbox = helpers / 'flow-wave-mailbox.sh'
            rc, _ = call(['bash', str(mailbox), 'send', '--wave', 'cold', '--from', 'orchestrator',
                           '--to', 'worker-a', '--body', 'Complete the offline fixture.'], project)
            need(rc == 0, 'installed mailbox writer')
            rc, message = call(['bash', str(mailbox), 'read', '--wave', 'cold', '--role', 'worker-a', '--all'], project)
            need(rc == 0 and 'Complete the offline fixture.' in message, 'installed mailbox consumption')
            if case == 'missing-wave-helper':
                (helpers / 'flow-wave-plan.py').unlink()
                rc, _ = call([sys.executable, str(helpers / 'flow-wave-plan.py'), str(issues)], project)
                need(rc != 0, 'missing actual planner command must fail')
            elif case == 'installed-drift':
                target = helpers / 'flow-wave-registry.sh'
                target.write_bytes(target.read_bytes() + b'\n# planted drift\n')
        if case in ('missing-context-helper', 'missing-project-data', 'missing-wave-helper', 'installed-drift'):
            need(any(r['status'] == 'violated' for r in profile.verify_installed(inv, home)['files']),
                 'installed verification missed injected source/helper/data drift')
        record = service.finalize('cold-project-wave')
        rows.append({'fixture_operations': [e['op'] for e in record.events],
                     'fixture_remote_integrity': record.remote_integrity})
    finally:
        if channel_active:
            channel.stop_and_finalize()
    return {'case': case, 'observations': rows,
            'scope': 'container-local installation and fixed commands; native workflow remains unproven'}


if __name__ == '__main__':
    need(len(sys.argv) == 2, 'one fixed case required')
    print(json.dumps(actor(sys.argv[1])))
