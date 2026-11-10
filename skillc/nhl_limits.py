"""Explicit NHL model-usage mode metadata; no study values or live authority.

Operational scheduler deadlines remain finite and unchanged. Capped dispatch
is unavailable until approved sizing and actual aggregate token enforcement
are joined; a parsed number is not enforcement. Historical policy-only records
remain readable without silently acquiring a mode.
"""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from typing import Any


class LimitsRefused(ValueError):
    """A mode is absent, ambiguous or unsupported at execution."""


def parse(data: object) -> dict[str, Any] | None:
    if not isinstance(data, Mapping):
        raise LimitsRefused('nhl_limits: declaration object required')
    if 'nhl_limits' not in data:
        return None
    if 'nhl_egress' not in data:
        raise LimitsRefused('nhl_limits: declaration-bound NHL policy required')
    raw = data['nhl_limits']
    if (type(raw) is not dict or type(raw.get('version')) is not int or raw['version'] != 1
            or raw.get('mode') not in ('uncapped', 'capped')):
        raise LimitsRefused('nhl_limits: explicit supported version and mode required')
    if raw['mode'] == 'uncapped':
        if set(raw) != {'version', 'mode'}:
            raise LimitsRefused('nhl_limits: uncapped forbids capped-only or unknown values')
    else:
        if set(raw) != {'version', 'mode', 'sizing_report_digest', 'wall_seconds', 'tokens'}:
            raise LimitsRefused('nhl_limits: complete explicit capped metadata required')
        if (not isinstance(raw['sizing_report_digest'], str)
                or re.fullmatch(r'sha256:[0-9a-f]{64}', raw['sizing_report_digest']) is None
                or type(raw['tokens']) is not int or not 0 < raw['tokens'] <= (1 << 63) - 1
                or type(raw['wall_seconds']) not in (int, float)):
            raise LimitsRefused('nhl_limits: approved sizing identity and positive finite values required')
        try:
            wall = float(raw['wall_seconds'])
        except (ValueError, OverflowError):
            raise LimitsRefused('nhl_limits: finite wall value required') from None
        if not math.isfinite(wall) or wall <= 0:
            raise LimitsRefused('nhl_limits: positive finite wall value required')
    return copy.deepcopy(raw)


def require_for_planning(data: object) -> dict[str, Any] | None:
    mode = parse(data)
    assert isinstance(data, Mapping)
    if 'nhl_egress' not in data:
        return None
    if mode is None:
        raise LimitsRefused('nhl_limits: new NHL planning requires an explicit mode; neither is a default')
    return mode


def require_for_execution(data: object) -> dict[str, Any] | None:
    mode = require_for_planning(data)
    if mode is None:
        return None
    if mode['mode'] == 'capped':
        raise LimitsRefused('nhl_limits: capped dispatch requires approved sizing and evidenced token enforcement; unavailable')
    return mode
