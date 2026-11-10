"""Owner-run storage sizing evidence, never participant admission authority.

The owner supplies approved sizing facts, current bindings and private paths.
This module chooses no study capacities or concurrency. JSON identity/digests
prove consistency, not who measured the host. Only a future trusted owner
adapter may consume PASS for admission; this module changes no launch hold.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_VALUE = (1 << 63) - 1
MAX_ROWS = 256
MAX_INPUT = 1024 * 1024
BINDING_KEYS = {'collection_id', 'window_id', 'wave_id', 'vm_binding_digest', 'declaration_digest'}
SAMPLE_KEYS = {'device', 'inode', 'filesystem_id', 'available_bytes', 'available_inodes'}


class HeadroomRefused(ValueError):
    """Unbound or incomplete sizing/evidence; never a measured shortage."""


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise HeadroomRefused('closed headroom object required')
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value) is None:
        raise HeadroomRefused('logical headroom identity required')
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', value) is None:
        raise HeadroomRefused('sizing or binding digest required')
    return value


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_VALUE:
        raise HeadroomRefused('bounded nonnegative integer required')
    return value


def _identity(value: object) -> int:
    if type(value) is not int or not 0 < value <= (1 << 64) - 1:
        raise HeadroomRefused('complete filesystem identity required')
    return value


def _number(value: object, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise HeadroomRefused('finite headroom clock/bound required')
    assert isinstance(value, (int, float))
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise HeadroomRefused('finite headroom clock/bound required') from None
    if not math.isfinite(number) or number < 0 or positive and number == 0:
        raise HeadroomRefused('finite positive headroom bound required')
    return number


def binding(value: object) -> dict[str, Any]:
    raw = _object(value, BINDING_KEYS)
    for name in BINDING_KEYS:
        (_digest if name.endswith('_digest') else _name)(raw[name])
    return copy.deepcopy(raw)


def parse_policy(value: object) -> dict[str, Any]:
    raw = _object(value, {'version', 'sizing_report_digest', 'max_age_seconds',
                          'max_collection_seconds', 'demands', 'reservations'})
    if type(raw['version']) is not int or raw['version'] != 1:
        raise HeadroomRefused('unsupported headroom policy version')
    _digest(raw['sizing_report_digest'])
    _number(raw['max_age_seconds'], positive=True)
    _number(raw['max_collection_seconds'], positive=True)
    for kind in ('demands', 'reservations'):
        rows = raw[kind]
        if type(rows) is not list or len(rows) > MAX_ROWS or kind == 'demands' and not rows:
            raise HeadroomRefused('explicit bounded demand and reservation populations required')
        seen = set()
        for row in rows:
            _object(row, {'root', 'copy_id', 'bytes', 'inodes', 'multiplicity'})
            key = (_name(row['root']), _name(row['copy_id']))
            if key in seen:
                raise HeadroomRefused('duplicate resource row')
            seen.add(key)
            required = _integer(row['bytes']) + _integer(row['inodes'])
            if not required:
                raise HeadroomRefused('empty resource demand')
            _integer(row['multiplicity'], 1)
            _integer(row['bytes'] * row['multiplicity'])
            _integer(row['inodes'] * row['multiplicity'])
    return copy.deepcopy(raw)


def policy_digest(policy: object) -> str:
    raw = parse_policy(policy)
    data = json.dumps(raw, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _root_names(policy: dict[str, Any]) -> set[str]:
    return {row['root'] for kind in ('demands', 'reservations') for row in policy[kind]}


def _sample(path: str) -> dict[str, int]:
    # One descriptor binds stat and statvfs to the same opened directory even
    # if a path/symlink changes during collection. No mount/host action occurs.
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        info, space = os.fstat(fd), os.fstatvfs(fd)
        mode = getattr(info, 'st_mode', None)
        if type(mode) is not int or not 0 <= mode <= 0xFFFF or not stat.S_ISDIR(mode):
            raise HeadroomRefused('headroom root is not a directory')
        fragment = _integer(getattr(space, 'f_frsize', None), 1)
        return {'device': _identity(getattr(info, 'st_dev', None)),
                'inode': _identity(getattr(info, 'st_ino', None)),
                'filesystem_id': _identity(getattr(space, 'f_fsid', None)),
                'available_bytes': _integer(_integer(getattr(space, 'f_bavail', None)) * fragment),
                'available_inodes': _integer(getattr(space, 'f_favail', None))}
    finally:
        os.close(fd)


def collect(
    policy: object, bound: object, paths: object, *,
    observe: Callable[[str], object] = _sample, clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Explicit owner invocation only. Tests inject measurements and clocks."""
    compiled, identity = parse_policy(policy), binding(bound)
    if type(paths) is not dict or set(paths) != _root_names(compiled):
        raise HeadroomRefused('private root map must match the complete demand population')
    if any(not isinstance(path, str) or not Path(path).is_absolute() or '\x00' in path for path in paths.values()):
        raise HeadroomRefused('private absolute directory paths required')
    started = _number(clock())
    roots = {}
    for name, path in paths.items():
        try:
            roots[name] = observe(path)
        except (OSError, HeadroomRefused):
            roots[name] = None  # Unknown never becomes an empty/zero measurement.
    return {'version': 1, 'policy_digest': policy_digest(compiled), 'binding': identity,
            'started_at': started, 'finished_at': _number(clock()), 'roots': roots}


def evaluate(policy: object, receipt: object, expected_binding: object, now: object) -> dict[str, Any]:
    try:
        return _evaluate(policy, receipt, expected_binding, now)
    except HeadroomRefused as exc:
        return {'status': 'UNKNOWN', 'reason': str(exc), 'admission_authority': False}


def _evaluate(policy: object, receipt: object, expected_binding: object, now: object) -> dict[str, Any]:
    policy = parse_policy(policy)
    identity = binding(expected_binding)
    receipt = _object(receipt, {'version', 'policy_digest', 'binding', 'started_at', 'finished_at', 'roots'})
    if (type(receipt['version']) is not int or receipt['version'] != 1
            or receipt['policy_digest'] != policy_digest(policy) or binding(receipt['binding']) != identity):
        raise HeadroomRefused('headroom receipt policy or run binding mismatch')
    started, finished, current = (_number(receipt['started_at']), _number(receipt['finished_at']), _number(now))
    if (finished < started or finished > current or current - started > policy['max_age_seconds']
            or finished - started > policy['max_collection_seconds']):
        raise HeadroomRefused('headroom measurement stale, future or unfinished')
    roots = receipt['roots']
    if type(roots) is not dict or set(roots) != _root_names(policy):
        raise HeadroomRefused('headroom root coverage missing or mixed')
    for row in roots.values():
        _object(row, SAMPLE_KEYS)
        for key, value in row.items():
            _integer(value) if key.startswith('available_') else _identity(value)
    device_ids: dict[int, int] = {}
    for row in roots.values():
        if row['device'] in device_ids and device_ids[row['device']] != row['filesystem_id']:
            raise HeadroomRefused('contradictory filesystem identity observations')
        device_ids[row['device']] = row['filesystem_id']
    # Device aliases and a shared statvfs fsid conservatively share ONE pool.
    groups: list[set[str]] = []
    for name, row in sorted(roots.items()):
        hits = [g for g in groups if any(roots[n]['device'] == row['device']
                                        or roots[n]['filesystem_id'] == row['filesystem_id'] for n in g)]
        merged = {name}.union(*hits)
        groups = [g for g in groups if g not in hits] + [merged]
    results = []
    for names in sorted(groups, key=lambda group: sorted(group)):
        available_bytes = min(roots[n]['available_bytes'] for n in names)
        available_inodes = min(roots[n]['available_inodes'] for n in names)
        demands: dict[tuple[object, ...], tuple[int, int, int]] = {}
        for kind in ('demands', 'reservations'):
            for row in policy[kind]:
                if row['root'] not in names:
                    continue
                observed = roots[row['root']]
                key = (kind, row['copy_id'], observed['device'], observed['inode'])
                value = (row['bytes'], row['inodes'], row['multiplicity'])
                if key in demands and demands[key] != value:
                    raise HeadroomRefused('same actual copy has conflicting sizing facts')
                demands[key] = value
        required_bytes = _integer(sum(n * copies for n, _i, copies in demands.values()))
        required_inodes = _integer(sum(n * copies for _b, n, copies in demands.values()))
        results.append({'roots': sorted(names), 'required_bytes': required_bytes,
                        'available_bytes': available_bytes, 'required_inodes': required_inodes,
                        'available_inodes': available_inodes,
                        'status': 'PASS' if required_bytes <= available_bytes and required_inodes <= available_inodes else 'FAIL'})
    return {'status': 'FAIL' if any(row['status'] == 'FAIL' for row in results) else 'PASS',
            'policy_digest': policy_digest(policy), 'binding': identity,
            'filesystems': results, 'admission_authority': False}


def _json(path: Path) -> object:
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise HeadroomRefused('headroom input exceeds technical bound')
    return json.loads(raw, object_pairs_hook=_pairs)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise HeadroomRefused('duplicate headroom JSON member')
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('collect', 'evaluate'):
        command = commands.add_parser(name)
        command.add_argument('--policy', type=Path, required=True)
        command.add_argument('--binding', type=Path, required=True)
        if name == 'collect':
            command.add_argument('--roots', type=Path, required=True)
            command.add_argument('--out', type=Path, required=True)
        else:
            command.add_argument('--receipt', type=Path, required=True)
            command.add_argument('--now', type=float, required=True)
    args = parser.parse_args(argv)
    try:
        policy, identity = _json(args.policy), _json(args.binding)
        if args.command == 'collect':
            receipt = collect(policy, identity, _json(args.roots))
            fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(receipt, stream, sort_keys=True)
                stream.write('\n')
            result = evaluate(policy, receipt, identity, receipt['finished_at'])
        else:
            result = evaluate(policy, _json(args.receipt), identity, args.now)
    except HeadroomRefused as exc:
        result = {'status': 'UNKNOWN', 'reason': str(exc), 'admission_authority': False}
    except (OSError, ValueError, RecursionError):
        result = {'status': 'UNKNOWN', 'reason': 'headroom input or collection unavailable',
                  'admission_authority': False}
    print(json.dumps(result, sort_keys=True))
    return {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
