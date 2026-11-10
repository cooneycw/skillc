"""Explicit multi-session sizing projections, never dispatch or token enforcement.

The whole declaration is bound to a digest independently held by the caller.
Other declaration/approval/live contracts remain that caller's responsibility.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import cost_estimate, nhl_limits, wave_wake
from .wave_usage import _hash, _integer, _json, _number, _object

ROLE_FIELDS = {'role', 'initial_input_tokens', 'initial_output_tokens', 'resume_input_tokens',
               'resume_output_tokens', 'resumed_turns', 'initial_seconds', 'resume_seconds'}
PLAN_FIELDS = {'version', 'sizing_report_digest', 'roles', 'critical_path_seconds',
               'setup_seconds', 'capture_seconds', 'cleanup_seconds'}


class PlanningRefused(ValueError):
    """Missing or ambiguous sizing is not zero-cost work."""


def _role_plan(value: object) -> dict[str, Any]:
    row = _object(value, ROLE_FIELDS)
    wave_wake._role(row['role'])
    resumes = _integer(row['resumed_turns'], 0, 64)
    for name in ('initial_input_tokens', 'initial_output_tokens'):
        _integer(row[name], 1)
    for name in ('resume_input_tokens', 'resume_output_tokens'):
        _integer(row[name], 1 if resumes else 0)
    initial = _number(row['initial_seconds'], positive=True)
    resumed = _number(row['resume_seconds'], positive=bool(resumes))
    tokens_in = _integer(row['initial_input_tokens'] + resumes * row['resume_input_tokens'], 1)
    tokens_out = _integer(row['initial_output_tokens'] + resumes * row['resume_output_tokens'], 1)
    return {'role': row['role'], 'turns': resumes + 1, 'input_tokens': tokens_in,
            'output_tokens': tokens_out, 'active_seconds': _number(initial + resumes * resumed, positive=True)}


def _validate(declaration: object) -> dict[str, Any]:
    if type(declaration) is not dict:
        raise PlanningRefused('whole sizing declaration required')
    limits = nhl_limits.require_for_planning(declaration)
    if limits is None:
        raise PlanningRefused('explicit NHL model-usage mode required')
    raw = _object(declaration.get('wave_accounting'), PLAN_FIELDS)
    if type(raw['version']) is not int or raw['version'] != 1:
        raise PlanningRefused('version-1 wave sizing required')
    wave_wake._digest(raw['sizing_report_digest'])
    if limits['mode'] == 'capped' and limits['sizing_report_digest'] != raw['sizing_report_digest']:
        raise PlanningRefused('capped and wave sizing identities differ')
    roles = raw['roles']
    if type(roles) is not list or not 1 <= len(roles) <= 64:
        raise PlanningRefused('bounded nonempty role sizing required')
    planned = [_role_plan(role) for role in roles]
    wave_wake._roles(tuple(role['role'] for role in planned))
    path = _number(raw['critical_path_seconds'], positive=True)
    if path < max(role['active_seconds'] for role in planned):
        raise PlanningRefused('critical path cannot cover a role allowance')
    overhead = sum(_number(raw[key]) for key in ('setup_seconds', 'capture_seconds', 'cleanup_seconds'))
    wave_seconds = _number(path + overhead, positive=True)
    return {'mode': limits['mode'], 'declared_limits': limits, 'roles': planned, 'wave_seconds': wave_seconds,
            'input_tokens': _integer(sum(role['input_tokens'] for role in planned), 1),
            'output_tokens': _integer(sum(role['output_tokens'] for role in planned), 1),
            'sizing_report_digest': raw['sizing_report_digest']}


@dataclass(frozen=True)
class Plan:
    declaration: bytes
    approved_digest: str

    def verify(self) -> dict[str, Any]:
        wave_wake._digest(self.approved_digest)
        if type(self.declaration) is not bytes or not 0 < len(self.declaration) <= wave_wake.MAX_DECLARATION:
            raise PlanningRefused('bounded sizing declaration required')
        if _hash(self.declaration) != self.approved_digest:
            raise PlanningRefused('sizing declaration differs from caller approval')
        try:
            declaration = json.loads(self.declaration, object_pairs_hook=wave_wake._pairs)
        except (ValueError, RecursionError):
            raise PlanningRefused('sizing declaration unavailable') from None
        if _json(declaration) != self.declaration:
            raise PlanningRefused('canonical whole sizing declaration required')
        return _validate(declaration)


def bind_plan(declaration: object, approved_digest: object) -> Plan:
    """Consistency only: no new approval issuer or actual sizing observation."""
    plan = Plan(_json(declaration), wave_wake._digest(approved_digest))
    plan.verify()
    return plan


def parse_plan(value: object) -> Plan:
    plan = Plan(**_object(value, {'declaration', 'approved_digest'}))
    plan.verify()
    return plan


def _verified(plan: object) -> dict[str, Any]:
    if type(plan) is not Plan:
        raise PlanningRefused('bound multi-session plan required')
    return plan.verify()


def _schedule(plan: object, waves: object) -> dict[str, Any]:
    sizing = _verified(plan)
    count = _integer(waves, 1)
    required = _number(count * sizing['wave_seconds'], positive=True)
    return {'version': 1, 'unit': 'wave', 'waves': count, 'roles': sizing['roles'],
            'mode': sizing['mode'], 'wave_seconds': sizing['wave_seconds'], 'required_seconds': required,
            'sufficiency': 'owner-sizing-assumption-not-physical-qualification',
            'token_enforcement': 'unavailable', 'admission_authority': False}


def schedule(plan: object, *, waves: object, total_seconds: object) -> dict[str, Any]:
    result = _schedule(plan, waves)
    total = _number(total_seconds, positive=True)
    if total < result['required_seconds']:
        raise PlanningRefused('schedule cannot cover all sized waves')
    return {**result, 'total_seconds': total}


@dataclass(frozen=True)
class CostEstimate:
    """Per-role projections plus the unchanged per-wave judge/spend semantics."""

    mode: str
    roles: tuple[dict[str, Any], ...]
    cost: cost_estimate.RunCostEstimate
    wave_seconds: float
    sizing_report_digest: str


def estimate(plan: object, *, trials: int, waves_per_trial: int, price: cost_estimate.ModelPrice,
             judge_tiers_enabled: int = 0, judge_price: cost_estimate.ModelPrice | None = None,
             judge_input_tokens: int = 0, judge_output_tokens: int = 0) -> CostEstimate:
    sizing = _verified(plan)
    _integer(trials, 1)
    _integer(waves_per_trial, 1)
    _integer(trials * waves_per_trial, 1)
    _integer(sizing['input_tokens'] * trials * waves_per_trial, 1)
    _integer(sizing['output_tokens'] * trials * waves_per_trial, 1)
    _integer(judge_tiers_enabled, 0, 2)
    _integer(judge_input_tokens)
    _integer(judge_output_tokens)
    if (type(price) is not cost_estimate.ModelPrice or judge_price is not None
            and type(judge_price) is not cost_estimate.ModelPrice):
        raise PlanningRefused('declared model prices required')
    projected = cost_estimate.estimate(trials, waves_per_trial, sizing['input_tokens'], sizing['output_tokens'],
        price, assumptions={'attempt_unit': 'wave', 'roles': str(len(sizing['roles'])),
                            'authority': 'projection-only-not-measured-or-enforced'},
        judge_tiers_enabled=judge_tiers_enabled, judge_price=judge_price,
        estimated_judge_input_tokens_per_call=judge_input_tokens,
        estimated_judge_output_tokens_per_call=judge_output_tokens)
    _number(projected.estimated_usd)
    _number(projected.judge_estimated_usd)
    return CostEstimate(sizing['mode'], tuple(sizing['roles']), projected,
                        sizing['wave_seconds'], sizing['sizing_report_digest'])


def report(plan: object) -> dict[str, Any]:
    sizing = _verified(plan)
    return {'version': 1, **sizing, 'token_enforcement': 'unavailable', 'admission_authority': False,
            'scope': 'planning-only-no-live-dispatch'}
