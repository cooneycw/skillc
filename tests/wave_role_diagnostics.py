"""Compact controller-owned role outcomes for the physical qualification test."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def parse_cpp_peers(stdout: str, *, exit_code: str) -> dict[str, Any]:
    """Read CPP's roster and exact LF trailer; allow one terminal LF at EOF."""
    if exit_code.strip() != '0':
        raise ValueError('CPP peer listing did not exit successfully')
    peers, end = json.JSONDecoder().raw_decode(stdout)
    if not isinstance(peers, dict) or not peers:
        raise ValueError('CPP peer listing must contain a nonempty JSON object')
    remainder = stdout[end:]
    if not remainder.startswith('\n'):
        raise ValueError('CPP peer listing is missing its line trailer')
    # jq prints one LF after the JSON. Do not normalize any trailer bytes:
    # echo emits LF, while CRLF, padding and blank detail lines are invalid.
    trailer = remainder[1:]
    trailer = trailer.removesuffix('\n')
    lines = trailer.split('\n')
    if not lines or lines[-1] != 'FLOW_WAVE: listed':
        raise ValueError('CPP peer listing must end with FLOW_WAVE: listed')
    if any(re.fullmatch(r'FLOW_WAVE_[A-Z][A-Z0-9_]*=[^\r\n]*', line) is None
           for line in lines[:-1]):
        raise ValueError('CPP peer listing has an invalid trailer detail')
    return peers


def write_role_summary(root: Path, report: Mapping[str, Any], roles: Sequence[str]) -> str:
    observed = report['roles']
    if not roles or set(observed) != set(roles):
        raise ValueError('role diagnostic population disagrees')
    fields = ('exit_codes', 'reasons', 'stop', 'absent')
    summary = {name: {field: observed[name][field] for field in fields} for name in roles}
    text = json.dumps(summary, sort_keys=True, separators=(',', ':'))
    (root / 'role-outcomes.json').write_text(text + '\n')
    return 'role outcomes: ' + text
