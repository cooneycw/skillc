"""Trusted collection, persistence and lifecycle boundary for #619.

Docker collectors execute only controller source in the declared namespace.
There is no agent inventory-input route and no host execution of subject code.
Controller-local capture is an explicit API for trusted fixture trees, never a
fallback for an unavailable Docker role. Every expected surface stays required.
"""
from __future__ import annotations

import base64
import hashlib
import math
import os
import secrets
import selectors
import subprocess
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from . import clutter, clutter_capture, git_snapshot
from .clutter import Policy, Snapshot, Surface, canonical, classify

MAX_OUTPUT = 4 * 1024 * 1024
CAPTURE_SECONDS = 30.0
_BATCH = 50


class RootReader(Protocol):
    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = ...) -> bytes | None: ...


def bounded_command(argv: Sequence[str], *, env: Mapping[str, str] | None, timeout: float,
                    limit: int = MAX_OUTPUT) -> bytes:
    """Bounded read-only CLI transport. Neither stderr nor environment is retained."""
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=dict(env) if env is not None else None)
    assert process.stdout is not None
    chunks: list[bytes] = []
    size = 0
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('inventory command timeout')
                for key, _ in selector.select(min(remaining, .05)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                        continue
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('inventory command output bound exceeded')
                    chunks.append(chunk)
            if process.wait(timeout=1) != 0:
                raise ValueError('inventory command failed')
        return b''.join(chunks)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()


def daemon_surfaces(docker_bin: Sequence[str], env: Mapping[str, str], *,
                    read: Callable[..., bytes] = bounded_command) -> dict[str, Surface]:
    """Whole declared daemon namespace; no untrusted label is an ownership filter.

    Every enumerated immutable ID must be inspected exactly once. A malformed,
    partial, duplicate or unavailable census is UNKNOWN, never empty/clean.
    This is a measurement, never a reaper; over-budget populations fail closed.
    """
    end = time.monotonic() + CAPTURE_SECONDS
    output: dict[str, Surface] = {}
    for family, noun in (('containers', 'container'), ('networks', 'network')):
        items: dict[str, str] = {}
        try:
            def ask(tail: list[str]) -> bytes:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise ValueError('shared daemon census deadline exceeded')
                return read([*docker_bin, *tail], env=env, timeout=min(5.0, remaining), limit=MAX_OUTPUT)
            raw = ask(['ps', '--all', '--no-trunc', '--format', '{{.ID}}'] if noun == 'container'
                      else ['network', 'ls', '--no-trunc', '--format', '{{.ID}}'])
            ids = raw.decode('ascii').splitlines()
            if (len(ids) > clutter.MAX_ITEMS or len(ids) != len(set(ids))
                    or any(len(i) != 64 or any(c not in '0123456789abcdef' for c in i) for i in ids)):
                raise ValueError('daemon census has invalid or duplicate identities')
            for offset in range(0, len(ids), _BATCH):
                batch = ids[offset:offset + _BATCH]
                rows = clutter.strict_json(ask([noun, 'inspect', *batch]))
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise ValueError('daemon inspect population incomplete')
                observed: set[str] = set()
                for row in rows:
                    if (not isinstance(row, dict) or not isinstance(row.get('Id'), str)
                            or row['Id'] not in batch or row['Id'] in observed
                            or not isinstance(row.get('Name'), str)):
                        raise ValueError('daemon inspect membership disagrees')
                    if noun == 'container' and (not isinstance(row.get('State'), dict)
                                               or not isinstance(row['State'].get('Status'), str)):
                        raise ValueError('container state unreadable')
                    observed.add(row['Id'])
                    # Store an identity plus content fingerprint, not labels,
                    # names, arbitrary commands or daemon connection strings.
                    items[row['Id']] = clutter.digest(row)
                if observed != set(batch):
                    raise ValueError('daemon inspect identity coverage incomplete')
            output[family] = Surface(items)
        except (OSError, ValueError, subprocess.SubprocessError, UnicodeError) as exc:
            output[family] = Surface(items, False, f'daemon {family} inventory unavailable: {type(exc).__name__}')
    return output


_PROBE = '''import base64,json,os,sys,types,zlib
from pathlib import Path
job=json.loads(zlib.decompress(base64.b64decode(sys.argv[1])))
package=types.ModuleType('skillc');package.__path__=[];sys.modules['skillc']=package
for name,source in job['sources']:
 module=types.ModuleType('skillc.'+name);module.__package__='skillc';sys.modules[module.__name__]=module
 setattr(package,name,module)
 exec(compile(source,'<controller-inventory:'+name+'>','exec'),module.__dict__)
policy=sys.modules['skillc.clutter'].parse_policy(job['policy'])
reader=sys.modules['skillc.clutter_capture']
rows=reader.capture_role(policy,job['role'],Path('/'),observer_pid=os.getpid())
if job['shared']: rows['shared']=reader.capture_shared(policy,Path('/'))
print(json.dumps({key:value.to_json() for key,value in rows.items()},sort_keys=True))
'''


def _decode_surfaces(data: bytes, expected: set[str]) -> dict[str, Surface]:
    raw = clutter.strict_json(data)
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError('role capture surface population disagrees')
    out: dict[str, Surface] = {}
    for name, row in raw.items():
        if (not isinstance(row, dict) or not {'items', 'complete', 'error', 'deleted_cwds'} <= set(row) <= {
                'items', 'complete', 'error', 'deleted_cwds', 'not_inspected'}
                or not isinstance(row['items'], dict) or type(row['complete']) is not bool
                or row['error'] is not None and not isinstance(row['error'], str)
                or not isinstance(row['deleted_cwds'], list)
                or not all(isinstance(k, str) for k in row['deleted_cwds'])
                or not isinstance(row.get('not_inspected', []), list)
                or not all(isinstance(k, str) for k in row.get('not_inspected', []))):
            raise ValueError('role capture protocol malformed')
        surface = Surface(row['items'], row['complete'], row['error'], tuple(row['deleted_cwds']),
                          tuple(row.get('not_inspected', [])))
        if clutter._surface_problem(surface) and surface.complete:
            raise ValueError('role capture items malformed')
        out[name] = surface
    return out


def docker_role(policy: Policy, role: str, backend: RootReader, handle: object, *,
                shared: bool = False) -> dict[str, Surface]:
    expected = {f'{role}/{kind}' for kind in clutter.ROLE_KINDS} | ({'shared'} if shared else set())
    try:
        sources = []
        for name, module in (('git_snapshot', git_snapshot), ('clutter', clutter), ('clutter_capture', clutter_capture)):
            source_path = module.__file__
            if source_path is None:
                raise ValueError('controller inventory source unavailable')
            sources.append((name, Path(source_path).read_text()))
        packet = canonical({'sources': sources, 'policy': policy.data, 'role': role, 'shared': shared})
        encoded = base64.b64encode(zlib.compress(packet)).decode('ascii')
        data = backend.root_output_in_attempt(handle, ['/usr/bin/python3', '-I', '-S', '-B', '-c', _PROBE, encoded],
                                             timeout=CAPTURE_SECONDS, max_bytes=MAX_OUTPUT)
        if data is None or len(data) > MAX_OUTPUT:
            raise ValueError('controller root capture unavailable or over bound')
        return _decode_surfaces(data, expected)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {name: Surface({}, False, f'role inventory unavailable: {type(exc).__name__}') for name in expected}


class Inventory:
    """One controller-owned, declaration-bound inventory across ALL role handles."""

    def __init__(self, policy: Policy, role_readers: Mapping[str, Callable[[], Mapping[str, Surface]]],
                 shared_reader: Callable[[], Surface], daemon_reader: Callable[[], Mapping[str, Surface]], *,
                 delivered_reader: Callable[[], Mapping[str, Any]] | None = None) -> None:
        if set(role_readers) - set(policy.roles):
            raise ValueError('controller role population exceeds declared roles')
        self.policy = policy
        self.role_readers = dict(role_readers)
        self.shared_reader = shared_reader
        self.daemon_reader = daemon_reader
        self.delivered_reader = delivered_reader
        self.scope_id = secrets.token_hex(16)

    def capture(self, phase: str) -> Snapshot:
        if phase not in ('before', 'after'):
            raise ValueError('inventory capture phase must be before or after')
        rows: dict[str, Surface] = {}
        for role in self.policy.roles:
            expected = {f'{role}/{kind}' for kind in clutter.ROLE_KINDS}
            try:
                observed = dict(self.role_readers[role]())
                if set(observed) != expected:
                    raise ValueError('role surface membership disagrees')
                rows.update(observed)
            except (KeyError, OSError, ValueError):
                rows.update({name: Surface({}, False, 'controller role capture unavailable') for name in expected})
        try:
            rows['shared'] = self.shared_reader()
        except (OSError, ValueError):
            rows['shared'] = Surface({}, False, 'controller shared-state capture unavailable')
        try:
            observed_daemon = dict(self.daemon_reader())
            if set(observed_daemon) != {'containers', 'networks'}:
                raise ValueError('daemon capture population disagrees')
            rows.update(observed_daemon)
        except (OSError, ValueError):
            rows.update({name: Surface({}, False, 'controller daemon capture unavailable')
                         for name in ('containers', 'networks')})
        frozen = {name: Surface(dict(row.items), row.complete, row.error, tuple(row.deleted_cwds), tuple(row.not_inspected))
                  if isinstance(row, Surface) and isinstance(row.items, Mapping)
                  else Surface({}, False, 'controller returned malformed surface') for name, row in rows.items()}
        if (sum(len(row.items) for row in frozen.values()) > clutter.MAX_ITEMS
                or len(canonical({name: row.to_json() for name, row in frozen.items()})) > MAX_OUTPUT):
            frozen = {name: Surface({}, False, 'aggregate snapshot budget exceeded') for name in frozen}
        return Snapshot(self.scope_id, phase, self.policy.identity, frozen)


class Session:
    """Setup, controller-witnessed completion, declared settle point, then capture.

    Callers must invoke completion from their controller lifecycle for every
    declared role, before namespace teardown. Agent-supplied snapshots or policy
    updates are not accepted. Missing/non-started roles remain UNKNOWN.
    """

    def __init__(self, inventory: Inventory, *, clock: Callable[[], float] = time.monotonic,
                 wait: Callable[[float], None] = time.sleep) -> None:
        self.inventory, self.clock, self.wait = inventory, clock, wait
        self.before: Snapshot | None = None
        self.completed: dict[str, float] = {}
        self.finished = False

    def setup(self) -> Snapshot:
        if self.before is not None:
            raise ValueError('inventory setup already captured')
        self.before = self.inventory.capture('before')
        return self.before

    def completion(self, role: str) -> None:
        if self.before is None or self.finished or role not in self.inventory.policy.roles or role in self.completed:
            raise ValueError('invalid or duplicate controller completion')
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError('controller completion clock unavailable')
        self.completed[role] = now

    def finish(self) -> dict[str, Any]:
        if self.finished or self.before is None:
            raise ValueError('inventory setup required, and finish is single-use')
        self.finished = True
        missing = set(self.inventory.policy.roles) - self.completed.keys()
        if not missing:
            now = self.clock()
            if not math.isfinite(now) or now < max(self.completed.values()):
                raise ValueError('controller settle clock unavailable')
            remaining = max(self.completed.values()) + self.inventory.policy.data['settle_seconds'] - now
            if remaining > 0:
                self.wait(remaining)
        settled_at = self.clock()
        if not math.isfinite(settled_at):
            raise ValueError('controller settle clock unavailable')
        unsettled = not missing and settled_at < max(self.completed.values()) + self.inventory.policy.data['settle_seconds']
        after = self.inventory.capture('after')
        if missing or unsettled:
            rows = dict(after.surfaces)
            for role in missing or set(self.inventory.policy.roles):
                rows[role + '/processes'] = Surface({}, False, 'controller completion or declared settle point not witnessed')
            after = Snapshot(after.scope_id, after.phase, after.policy_digest, rows)
        captured: Mapping[str, Any] = {}
        if self.inventory.policy.data.get('delivered_commit_roles'):
            try:
                if self.inventory.delivered_reader is not None:
                    captured = self.inventory.delivered_reader()
                if not isinstance(captured, Mapping) or len(canonical(captured)) > clutter.MAX_BYTES:
                    raise ValueError('delivered capture population or byte bound exceeded')
                captured = clutter.strict_json(canonical(captured))
            except (OSError, ValueError, TypeError, RecursionError):
                captured = {}
        report = classify(self.inventory.policy, self.before, after, delivered_captures=captured)
        if self.inventory.policy.data.get('delivered_commit_roles'):
            report['delivered_captures'] = captured
        report['before'] = self.before.to_json()
        report['after'] = after.to_json()
        report['capture_digest'] = 'sha256:' + hashlib.sha256(canonical([report['before'], report['after']])).hexdigest()
        return report


def docker_inventory(policy: Policy, sources: Mapping[str, tuple[RootReader, object]], *,
                     shared_role: str) -> Inventory:
    """Collect every role plus its shared mount and one held daemon namespace.

    Distinct daemon bindings cannot be silently combined into one census.
    They remain UNKNOWN; a future multi-daemon profile needs an explicit
    namespace union. Changed role bindings also deny clean coverage.
    """
    if set(sources) - set(policy.roles) or shared_role not in policy.roles:
        raise ValueError('inventory sources must match declared roles and shared-volume owner')
    shared: dict[str, Surface] = {}
    held: dict[str, tuple[RootReader, object, dict[str, str] | None, tuple[str, ...], object]] = {}
    for role, (backend, handle) in sources.items():
        captured = getattr(handle, 'env', None)
        env = dict(captured) if isinstance(captured, Mapping) else None
        held[role] = (backend, handle, env, tuple(getattr(backend, 'docker_bin', ())), getattr(handle, 'name', None))

    def read_role(role: str) -> dict[str, Surface]:
        backend, handle, env, command, name = held[role]
        has_shared = role == shared_role
        if (env is None or getattr(handle, 'env', None) != env
                or tuple(getattr(backend, 'docker_bin', ())) != command or getattr(handle, 'name', None) != name):
            observed = {f'{role}/{kind}': Surface({}, False, 'role observation binding changed or unavailable')
                        for kind in clutter.ROLE_KINDS}
            if has_shared:
                observed['shared'] = Surface({}, False, 'shared-role observation binding changed or unavailable')
        else:
            observed = docker_role(policy, role, backend, handle, shared=has_shared)
        if has_shared:
            shared['row'] = observed.pop('shared')
        return observed

    def read_daemon() -> dict[str, Surface]:
        if policy.data['daemon_scope'] != 'controller-isolated':
            return {key: Surface({}, False, 'daemon namespace observation not declared available')
                    for key in ('containers', 'networks')}
        valid = len(held) == len(policy.roles) and all(env is not None and command
                                                     for _, _, env, command, _ in held.values())
        bindings = {(command, canonical(env)) for _, _, env, command, _ in held.values()}
        if not valid or len(bindings) != 1:
            return {key: Surface({}, False, 'role daemon bindings unavailable or different')
                    for key in ('containers', 'networks')}
        _, _, env, command, _ = next(iter(held.values()))
        assert env is not None
        return daemon_surfaces(command, env)
    readers = {role: lambda role=role: read_role(role) for role in held}
    return Inventory(policy, readers,
                     lambda: shared.get('row', Surface({}, False, 'shared-volume observation missing')), read_daemon)


def single_role_session(policy: Policy, backend: RootReader, handle: object) -> Session:
    """The calibration bridge; waves use docker_inventory with ALL handles."""
    if policy.roles != ('agent',):
        raise ValueError('single-attempt clutter collection requires exactly the agent role')
    return Session(docker_inventory(policy, {'agent': (backend, handle)}, shared_role='agent'))


def unavailable(policy: Policy, reason: str) -> dict[str, Any]:
    rows = {name: Surface({}, False, reason) for name in policy.surfaces}
    scope = secrets.token_hex(16)
    return classify(policy, Snapshot(scope, 'before', policy.identity, rows),
                    Snapshot(scope, 'after', policy.identity, rows))


class AttemptInventory:
    """Latched single-attempt hooks; observer failures can never become clean."""

    def __init__(self, policy: Policy, store: Callable[[bytes], str],
                 record: Callable[..., None]) -> None:
        if policy.roles != ('agent',):
            raise ValueError('single-attempt inventory requires the agent role')
        self.policy, self.store, self.record = policy, store, record
        self.session: Session | None = None
        self.before_digest: str | None = None
        self.report = unavailable(policy, 'controller inventory was not reached')

    def setup(self, backend: RootReader, handle: object) -> None:
        try:
            self.session = single_role_session(self.policy, backend, handle)
            before = self.session.setup()
            self.before_digest = self.store(canonical(before.to_json()))
            self.record('clutter-before', policy_digest=self.policy.identity, digest=self.before_digest)
        except Exception as exc:  # noqa: BLE001 - measurement failure is latched UNKNOWN
            self.session = None
            self.report = unavailable(self.policy, f'setup capture unavailable: {type(exc).__name__}')

    def completion(self) -> None:
        if self.session is not None:
            self.session.completion('agent')

    def finish(self) -> None:
        try:
            if self.session is not None:
                self.report = self.session.finish()
            report_digest = self.store(canonical(self.report))
            self.record('clutter-after', policy_digest=self.policy.identity,
                        before_digest=self.before_digest, digest=report_digest)
            self.report = {**self.report, 'report_digest': report_digest, 'before_digest': self.before_digest}
        except Exception as exc:  # noqa: BLE001 - missing durable evidence is UNKNOWN
            self.report = unavailable(self.policy, f'final capture unavailable: {type(exc).__name__}')

    def summary(self) -> dict[str, Any]:
        return {key: value for key, value in self.report.items() if key not in ('before', 'after', 'delivered_captures')}


def report_from_events(policy: Policy, events: Sequence[Mapping[str, Any]],
                       read_object: Callable[[str], bytes]) -> dict[str, Any]:
    """Re-derive from controller journal/object bytes, never an outcomes checkpoint."""
    try:
        starts = [row for row in events if row.get('event') == 'clutter-before']
        ends = [row for row in events if row.get('event') == 'clutter-after']
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError('controller inventory journal population incomplete or duplicated')
        start, end = starts[0], ends[0]
        if list(events).index(start) >= list(events).index(end):
            raise ValueError('controller capture journal order disagrees')
        if (start.get('policy_digest') != policy.identity or end.get('policy_digest') != policy.identity
                or end.get('before_digest') != start.get('digest')):
            raise ValueError('controller inventory declaration binding disagrees')
        before_bytes = read_object(start['digest'])
        report_bytes = read_object(end['digest'])
        if ('sha256:' + hashlib.sha256(before_bytes).hexdigest() != start['digest']
                or 'sha256:' + hashlib.sha256(report_bytes).hexdigest() != end['digest']):
            raise ValueError('controller inventory content identity disagrees')
        before = clutter.snapshot_from_json(clutter.strict_json(before_bytes))
        stored = clutter.strict_json(report_bytes)
        if not isinstance(stored, dict) or stored.get('before') != clutter.strict_json(before_bytes):
            raise ValueError('controller inventory before snapshot disagrees')
        after = clutter.snapshot_from_json(stored.get('after'))
        return {**classify(policy, before, after, delivered_captures=stored.get('delivered_captures')),
                'report_digest': end['digest'], 'before_digest': start['digest']}
    except Exception:  # noqa: BLE001 - any unavailable controller evidence is UNKNOWN, never clean
        return unavailable(policy, 'controller journal or captured inventory unavailable')
