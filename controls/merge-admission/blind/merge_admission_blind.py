"""FROZEN blind anchor for ci/merge_admission.py (Kyle #2130). Do not update.

The gate's pipeline check with script-following removed. It must MISS
controls/merge-admission/bad/ci.yml, whose only route to main-merge is a script
the step runs. If it ever catches that case, the bad case no longer exercises
script-following and the control has gone blind.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml

RESOURCE = "main-merge"
#: kyle-lock actions that take, or act under, a main-merge lease.
LEASE_ACTIONS = frozenset({"acquire", "run", "renew", "begin-merge", "record-merge"})
#: Any of these in a CI step hands it a coordination principal.
CREDENTIALS = ("KYLE_LOCK_TOKEN", "KYLE_LOCK_TOKEN_FILE")
SERVICE_ROUTES = ("coordination_acquire", "coordination_begin_merge",
                  f"/api/coordination/{RESOURCE}/")


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True)
    except ValueError:
        # Unbalanced quoting: fall back to whitespace, still without comments.
        return line.split("#", 1)[0].split()


def _line_findings(line: str, where: str) -> list[str]:
    tokens = _tokens(line)
    found: list[str] = []
    for i, token in enumerate(tokens):
        if Path(token).name == "kyle-lock":
            rest = tokens[i + 1:]
            if RESOURCE in rest and LEASE_ACTIONS.intersection(rest):
                found.append(f"{where}: kyle-lock {' '.join(rest)} - CI must never take {RESOURCE}")
        if any(route in token for route in SERVICE_ROUTES):
            found.append(f"{where}: {token} - CI must never take {RESOURCE}")
        if any(token == name or token.startswith(f"{name}=") or f"${name}" in token
               or f"${{{name}}}" in token for name in CREDENTIALS):
            found.append(f"{where}: {token} - CI must not hold a coordination credential")
    return found


def pipeline_findings(ci_yml: str) -> list[str]:
    steps = (yaml.safe_load(ci_yml) or {}).get("steps") or []
    found: list[str] = []
    for step in steps:
        for number, line in enumerate(step.get("commands") or [], 1):
            found += _line_findings(str(line), f"step {step.get('name', '?')}:{number}")
    return found
