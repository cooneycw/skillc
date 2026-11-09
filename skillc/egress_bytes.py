"""Strict CONNECT byte evidence, separate from network-policy authority (#638).

Counts are proxy read-boundary observations, including TLS overhead. They do
not establish delivery, HTTP request counts, or response codes. A shutdown trailer is
an integrity/coverage fence, not an authentication claim against the controller.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

MAX_CAPTURE = 8 * 1024 * 1024  # Technical capture bound; exceeding it is UNKNOWN.
MAX_COUNTER = (1 << 63) - 1
LIMITATION = 'HTTP request counts and response codes not measured'


class Incomplete(ValueError):
    """Missing or invalid coverage; never evidence of zero bytes."""


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_COUNTER:
        raise Incomplete('bounded nonnegative integer required')
    return value


def _object(value: object, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise Incomplete('closed telemetry object required')
    return value


def _hex(value: object, size: int) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is None:
        raise Incomplete('telemetry identity required')
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Incomplete('duplicate JSON key')
        result[key] = value
    return result


def unknown(reason: str) -> dict[str, object]:
    return {'version': 1, 'status': 'UNKNOWN', 'measurement': 'bytes observed',
            'includes_tls_overhead': True, 'limitation': LIMITATION,
            'client_to_upstream': None, 'upstream_to_client': None,
            'reason': reason}


def summarize(raw: object, digest: object) -> dict[str, object]:
    """Return COMPLETE totals or UNKNOWN with validated checkpoint lower bounds."""
    try:
        return _summarize(raw, digest)
    except (Incomplete, UnicodeError, ValueError, RecursionError) as exc:
        return unknown(str(exc))


def _summarize(raw: object, digest: object) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_CAPTURE:
        raise Incomplete('missing, oversized or truncated byte capture')
    truncated = not raw.endswith(b'\n')
    if truncated:
        raw = raw.rsplit(b'\n', 1)[0] + b'\n' if b'\n' in raw else b''
    if not isinstance(digest, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', digest) is None:
        raise Incomplete('bound policy digest required')
    lines = raw.splitlines(keepends=True)
    entries = [json.loads(line.decode('utf-8'), object_pairs_hook=_pairs) for line in lines]
    if not entries or any(type(entry) is not dict for entry in entries):
        raise Incomplete('JSON object log lines required')
    previous = '0' * 64
    rows = []
    for index, (entry, line) in enumerate(zip(entries, lines, strict=True), start=1):
        if _integer(entry.get('seq'), 1) != index or entry.get('prev') != previous:
            raise Incomplete('log chain missing, reordered or replayed record')
        previous = hashlib.sha256(line).hexdigest()
        row = {k: v for k, v in entry.items() if k not in ('seq', 'prev')}
        rows.append(row)
    entries = rows
    trailer = entries[-1] if entries[-1].get('event') == 'bytes-end' else None
    generation = _hex(entries[0].get('byte_telemetry', {}).get('generation')
                      if isinstance(entries[0].get('byte_telemetry'), dict) else None, 32)
    start = _object(entries[0], {'event', 'digest', 'allowlist', 'byte_telemetry'})
    metadata = _object(start.get('byte_telemetry'), {'version', 'generation'})
    if (type(metadata['version']) is not int or metadata['version'] != 1
            or start.get('event') != 'start' or start.get('digest') != digest
            or start.get('byte_telemetry') != {'version': 1, 'generation': generation}):
        raise Incomplete('generation start required')
    from . import egress
    if not isinstance(start['allowlist'], dict) or egress.document_digest(start['allowlist']) != digest:
        raise Incomplete('policy document and digest disagree')
    connections: dict[int, dict[str, Any]] = {}
    allowed: Counter[str] = Counter()
    for row in entries[1:-1] if trailer is not None else entries[1:]:
        if row.get('event') == 'bytes':
            row = _object(row, {'event', 'generation', 'connection', 'sequence', 'target',
                                'client_to_upstream', 'upstream_to_client', 'state'})
            cid = _integer(row['connection'], 1)
            seq = _integer(row['sequence'])
            sent = _integer(row['client_to_upstream'])
            received = _integer(row['upstream_to_client'])
            if (row['generation'] != generation or not isinstance(row['target'], str)
                    or not row['target'] or row['state'] not in ('open', 'progress', 'final', 'error')):
                raise Incomplete('connection identity or state mismatch')
            prior = connections.get(cid)
            if prior is None:
                if cid != len(connections) + 1 or seq != 0 or row['state'] != 'open' or sent or received:
                    raise Incomplete('connection opening or sequence missing')
            elif (prior['state'] in ('final', 'error') or seq != prior['sequence'] + 1
                  or row['state'] == 'open' or row['target'] != prior['target']
                  or sent < prior['client_to_upstream'] or received < prior['upstream_to_client']):
                raise Incomplete('connection sequence gap, replay or counter regression')
            connections[cid] = row
        elif row.get('event') is not None:
            raise Incomplete('unexpected telemetry event')
        elif row.get('decision') == 'allowed':
            if not isinstance(row.get('target'), str):
                raise Incomplete('allowed authority required')
            allowed[row['target']] += 1
        elif (row.get('decision') not in ('denied', 'peer-rejected')
              and not (isinstance(row.get('decision'), str)
                       and row['decision'].startswith('upstream-failed: '))):
            raise Incomplete('unparsed connection decision')
    if allowed != Counter(c['target'] for c in connections.values()):
        raise Incomplete('connection census incomplete')
    sent = sum(c['client_to_upstream'] for c in connections.values())
    received = sum(c['upstream_to_client'] for c in connections.values())
    _integer(sent)
    _integer(received)
    complete = False
    if trailer is not None:
        trailer = _object(trailer, {'event', 'final', 'records', 'last_hash', 'generation', 'finals'})
        finals = [dict(row) for row in connections.values()]
        if (trailer['final'] is not True or _integer(trailer['records']) != len(entries) - 1
                or trailer['last_hash'] != hashlib.sha256(lines[-2]).hexdigest()
                or trailer['generation'] != generation
                or json.dumps(trailer['finals'], sort_keys=True) != json.dumps(finals, sort_keys=True)):
            raise Incomplete('shutdown trailer census or chain mismatch')
        complete = not truncated and all(c['state'] == 'final' for c in connections.values())
    result = unknown('active or interrupted tunnel; checkpoint lower bounds only')
    result.update(generation=generation, connections=len(connections),
                  observed_lower_bound={'client_to_upstream': sent, 'upstream_to_client': received})
    if complete:
        result.update(status='COMPLETE', client_to_upstream=sent, upstream_to_client=received)
        result.pop('reason')
    return result


def report(value: object) -> dict[str, object]:
    """Closed validation at the persisted report-input boundary."""
    try:
        if not isinstance(value, dict):
            raise Incomplete('byte observation absent')
        base = {'version', 'status', 'measurement', 'includes_tls_overhead', 'limitation',
                'client_to_upstream', 'upstream_to_client'}
        if (type(value.get('version')) is not int or value['version'] != 1
                or value.get('measurement') != 'bytes observed'
                or value.get('includes_tls_overhead') is not True
                or value.get('limitation') != LIMITATION):
            raise Incomplete('byte observation contract mismatch')
        if value.get('status') == 'COMPLETE':
            _object(value, base | {'generation', 'connections', 'observed_lower_bound'})
            _hex(value['generation'], 32)
            _integer(value['connections'])
            lower = _object(value['observed_lower_bound'], {'client_to_upstream', 'upstream_to_client'})
            for name in lower:
                if _integer(lower[name]) != _integer(value[name]):
                    raise Incomplete('complete byte totals disagree')
        elif value.get('status') == 'UNKNOWN':
            if (not base <= value.keys() or set(value) - base - {
                    'reason', 'generation', 'connections', 'observed_lower_bound'}
                    or not isinstance(value.get('reason'), str) or not value['reason']
                    or value['client_to_upstream'] is not None or value['upstream_to_client'] is not None):
                raise Incomplete('unknown byte totals must stay unavailable')
            extras = {'generation', 'connections', 'observed_lower_bound'} & value.keys()
            if extras:
                if extras != {'generation', 'connections', 'observed_lower_bound'}:
                    raise Incomplete('partial checkpoint metadata')
                _hex(value['generation'], 32)
                _integer(value['connections'])
                lower = _object(value['observed_lower_bound'], {'client_to_upstream', 'upstream_to_client'})
                for number in lower.values():
                    _integer(number)
        else:
            raise Incomplete('byte status unavailable')
        return json.loads(json.dumps(value))  # Return independent JSON-safe data.
    except (Incomplete, ValueError, RecursionError) as exc:
        return unknown(str(exc))


_PIPE = r'''
class ByteConnection:
    def __init__(self, emit, generation, connection, target, finals):
        self.emit, self.generation = emit, generation
        self.connection, self.target, self.finals = connection, target, finals
        self.sequence, self.sent, self.received = 0, 0, 0
        self.failed = False
        self.record("open")

    def record(self, state):
        row = {"event": "bytes", "generation": self.generation,
               "connection": self.connection, "sequence": self.sequence,
               "target": self.target, "client_to_upstream": self.sent,
               "upstream_to_client": self.received, "state": state}
        self.emit(row)
        self.finals[self.connection] = row
        self.sequence += 1

    def observe(self, direction, count):
        if direction == "client":
            self.sent += count
        else:
            self.received += count

    async def checkpoint(self):
        while True:
            await asyncio.sleep(1)
            self.record("progress")

async def _pipe(reader, writer, observed=None, direction=None):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            # Observe before write/drain: this is not a delivery counter.
            observed.observe(direction, len(data))
            writer.write(data)
            await writer.drain()
    except asyncio.CancelledError:
        observed.failed = True
        raise
    except Exception:
        observed.failed = True
    finally:
        writer.close()
'''


_LOG = r'''
    log = open(log_path, "a", buffering=1)
    generation, connection_count = uuid.uuid4().hex, 0
    sequence, previous = 0, "0" * 64
    quiescing, sealed = False, False
    finals, active = {}, set()
    server = None

    def emit(row):
        nonlocal sequence, previous
        if sealed:
            return
        sequence += 1
        line = (json.dumps({**row, "seq": sequence, "prev": previous}) + "\n").encode()
        log.write(line.decode())
        previous = hashlib.sha256(line).hexdigest()

    def record(method, target, decision):
        emit({"t": round(time.time(), 3), "method": method, "target": target, "decision": decision})

    async def quiesce():
        nonlocal quiescing, sealed
        if quiescing:
            return
        quiescing = True
        server.close()
        await server.wait_closed()
        if active:
            _done, pending = await asyncio.wait(list(active), timeout=0.2)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        emit({"event": "bytes-end", "final": True, "records": sequence,
              "last_hash": previous, "generation": generation,
              "finals": [finals[key] for key in sorted(finals)]})
        sealed = True

    async def handle(cr, cw):
        if quiescing:
            cw.close()
            return
        task = asyncio.current_task()
        active.add(task)
        try:
            await handle_connection(cr, cw)
        finally:
            active.discard(task)
'''


def proxy_source() -> str:
    """Derive strict telemetry from the shipped policy; preserve legacy argv bytes.

    Exact anchor counts make a changed base script refuse generation instead of
    silently losing the telemetry hooks. No second CONNECT matcher is added.
    """
    from . import egress
    source = egress.PROXY_SOURCE

    def replace(before: str, after: str) -> None:
        nonlocal source
        if source.count(before) != 1:
            raise RuntimeError('strict proxy source anchor drift')
        source = source.replace(before, after)

    replace('import asyncio, ipaddress, json, sys, time',
            'import asyncio, hashlib, ipaddress, json, signal, sys, time, uuid')
    left = source.index('async def _pipe(')
    right = source.index('def main():', left)
    replace(source[left:right], _PIPE + '\n\n')
    left = source.index('    log = open(')
    right = source.index('    async def handle(cr, cw):', left)
    replace(source[left:right], _LOG + '\n')
    replace('    async def handle(cr, cw):\n        peer',
            '    async def handle_connection(cr, cw):\n        nonlocal connection_count\n        peer')
    replace('        record(method, target, "allowed")',
            '        record(method, target, "allowed")\n'
            '        connection_count += 1\n'
            '        observed = ByteConnection(emit, generation, connection_count, target, finals)')
    replace('        await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))', '''        checkpoint = asyncio.create_task(observed.checkpoint())
        try:
            await asyncio.gather(_pipe(cr, uw, observed, "client"), _pipe(ur, cw, observed, "upstream"))
        finally:
            checkpoint.cancel()
            await asyncio.gather(checkpoint, return_exceptions=True)
            observed.record("error" if observed.failed else "final")''')
    replace('    async def serve():\n        server =', '    async def serve():\n        nonlocal server\n        server =')
    replace('        log.write(json.dumps({"event": "start", "allowlist": allow, "digest": sys.argv[4]}) + "\\n")',
            '        emit({"event": "start", "allowlist": allow, "digest": sys.argv[4],\n'
            '              "byte_telemetry": {"version": 1, "generation": generation}})\n'
            '        asyncio.get_running_loop().add_signal_handler(\n'
            '            signal.SIGUSR1, lambda: asyncio.create_task(quiesce()))')
    replace('            await server.serve_forever()', '            await asyncio.Event().wait()')
    return source


READ_SOURCE = r'''
import sys
with open(sys.argv[1], 'rb') as source:
    raw = source.read(8 * 1024 * 1024 + 1)
if len(raw) > 8 * 1024 * 1024:
    sys.exit(2)
sys.stdout.buffer.write(raw)
'''


