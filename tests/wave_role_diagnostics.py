"""Compact controller-owned role outcomes for the physical qualification test."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def write_role_summary(root: Path, report: Mapping[str, Any], roles: Sequence[str]) -> str:
    observed = report['roles']
    if not roles or set(observed) != set(roles):
        raise ValueError('role diagnostic population disagrees')
    fields = ('exit_codes', 'reasons', 'stop', 'absent')
    summary = {name: {field: observed[name][field] for field in fields} for name in roles}
    text = json.dumps(summary, sort_keys=True, separators=(',', ':'))
    (root / 'role-outcomes.json').write_text(text + '\n')
    return 'role outcomes: ' + text
