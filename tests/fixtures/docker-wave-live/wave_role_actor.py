"""Model-free container actor for #621's physical transport qualification."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

role, mode, *turn = sys.argv[1:]
session = turn[1] if turn[0] == 'resume' else str(uuid.uuid4())
sys.stderr.write('OpenAI Codex v0.157.1\n--------\nsession id: ' + session + '\n--------\n')
sys.stderr.flush()
transcript = Path.home() / '.codex/sessions' / (role + '.jsonl')
transcript.parent.mkdir(parents=True, exist_ok=True)
with transcript.open('a') as stream:
    stream.write(json.dumps({'session_id': session, 'turn': turn[0]}) + '\n')
if turn[0] == 'resume':
    Path('resumed.json').write_text(json.dumps({'session': session}))
    raise SystemExit(0)

state = Path(os.environ['FLOW_WAVE_MAILBOX_DIR'])
assert str(state) == os.environ['FLOW_WAVE_REGISTRY_DIR']
registry_env = dict(os.environ, CLAUDE_PID=str(os.getpid()), CLAUDE_CODE_SESSION_ID=session)
registered = subprocess.run(['bash', 'flow-wave-registry.sh', 'register', role, '--wave', 'qualification'],
                            env=registry_env, capture_output=True, check=False, timeout=20)
Path('cpp-register.stdout').write_bytes(registered.stdout)
Path('cpp-register.stderr').write_bytes(registered.stderr)
assert registered.returncode == 0, 'CPP registration unavailable'
if mode != 'omit-mail':
    (state / (role + '.mail')).write_text(json.dumps({'sender': role, 'session': session}))

# Every role pushes only its own branch; there is no shared checkout or branch race.
subprocess.run(['git', 'config', 'user.name', 'Fixture'], check=True)
subprocess.run(['git', 'config', 'user.email', 'fixture@example.invalid'], check=True)
Path(role + '.txt').write_text(role)
subprocess.run(['git', 'add', role + '.txt'], check=True)
subprocess.run(['git', 'commit', '-m', 'scripted role artifact'], check=True, capture_output=True)
subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/' + role], check=True, capture_output=True, timeout=15)
if mode == 'hang':
    while True:
        time.sleep(1)

end = time.monotonic() + 15
while not all((state / (name + '.mail')).is_file() for name in ('orchestrator', 'worker-a', 'worker-b')):
    if time.monotonic() >= end:
        Path('delivery.json').write_text(json.dumps({'status': 'missing-mail'}))
        raise SystemExit(7)
    time.sleep(.03)
Path('delivery.json').write_text(json.dumps({'status': 'delivered', 'messages': {
    name: json.loads((state / (name + '.mail')).read_text())
    for name in ('orchestrator', 'worker-a', 'worker-b')}}))
# Capture CPP's OWN liveness reading without overriding its PID/socket probes.
listed = subprocess.run(['bash', 'flow-wave-registry.sh', 'list', '--wave', 'qualification', '--json'],
                        env=registry_env, capture_output=True, check=False, timeout=20)
Path('cpp-peers.stdout').write_bytes(listed.stdout)
Path('cpp-peers.stderr').write_bytes(listed.stderr)
Path('cpp-peers.exit').write_text(str(listed.returncode))
for name in ('orchestrator', 'worker-a', 'worker-b'):
    subprocess.run(['git', 'fetch', 'origin', name], check=True, capture_output=True, timeout=15)
    found = subprocess.check_output(['git', 'show', 'FETCH_HEAD:' + name + '.txt'])
    assert found.decode() == name
Path('git-delivery.json').write_text(json.dumps({'status': 'delivered'}))
