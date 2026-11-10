"""Three-role CPU/memory declaration inputs and pure owner-fact evaluation.

No host collector, reservation, resource enforcement or admission authority.
Storage bytes/inodes remain the separate nhl_headroom contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from . import wave_wake as wake
from .wave_usage import _integer, _number, _object

POLICY_FIELDS = {'version', 'sizing_report_digest', 'concurrency', 'roles', 'auxiliaries',
                 'reservations', 'max_age_seconds', 'max_collection_seconds'}


class ResourcesRefused(ValueError):
    """Missing or ambiguous resource sizing is not sufficient capacity."""


def _demand(value: object, *, role: bool) -> dict[str, Any]:
    keys = {'role', 'cpu_millicores', 'memory_bytes'} if role else {
        'name', 'cpu_millicores', 'memory_bytes', 'multiplicity'}
    row = _object(value, keys)
    name = wake._role(row['role' if role else 'name'])
    cpu = _integer(row['cpu_millicores'], 1 if role else 0)
    memory = _integer(row['memory_bytes'], 1 if role else 0)
    if cpu + memory == 0:
        raise ResourcesRefused('nonempty declared resource demand required')
    count = 1 if role else _integer(row['multiplicity'], 1)
    return {'name': name, 'cpu_millicores': _integer(cpu * count),
            'memory_bytes': _integer(memory * count), 'multiplicity': count}


def parse(value: object, *, expected_roles: tuple[str, ...], expected_sizing_digest: str) -> dict[str, Any]:
    """A plan for one simultaneous three-role wave, not a machine observation."""
    row = _object(value, POLICY_FIELDS)
    if type(row['version']) is not int or row['version'] != 1:
        raise ResourcesRefused('version-1 resource sizing required')
    wake._digest(expected_sizing_digest)
    if row['sizing_report_digest'] != expected_sizing_digest:
        raise ResourcesRefused('resource sizing identity differs')
    if type(expected_roles) is not tuple or len(expected_roles) != 3:
        raise ResourcesRefused('exact three-role resource population required')
    wake._roles(expected_roles)
    if row['concurrency'] != 'all-roles-simultaneous':
        raise ResourcesRefused('simultaneous-role resource model required')
    roles = row['roles']
    if type(roles) is not list or len(roles) != 3:
        raise ResourcesRefused('every planned role requires CPU and memory sizing')
    role_demands = [_demand(role, role=True) for role in roles]
    if tuple(role['name'] for role in role_demands) != expected_roles:
        raise ResourcesRefused('resource and accounting role populations differ')
    groups = {}
    seen = set(expected_roles)
    for kind in ('auxiliaries', 'reservations'):
        values = row[kind]
        if type(values) is not list or not (1 if kind == 'auxiliaries' else 0) <= len(values) <= 256:
            raise ResourcesRefused('explicit bounded auxiliary/reservation population required')
        groups[kind] = [_demand(item, role=False) for item in values]
        for demand in groups[kind]:
            if demand['name'] in seen:
                raise ResourcesRefused('unique resource demand identities required')
            seen.add(demand['name'])
    demands = role_demands + groups['auxiliaries'] + groups['reservations']
    return {'version': 1, 'sizing_report_digest': expected_sizing_digest,
            'roles': role_demands, **groups,
            'required_cpu_millicores': _integer(sum(row['cpu_millicores'] for row in demands), 1),
            'required_memory_bytes': _integer(sum(row['memory_bytes'] for row in demands), 1),
            'max_age_seconds': _number(row['max_age_seconds'], positive=True),
            'max_collection_seconds': _number(row['max_collection_seconds'], positive=True),
            'scope': 'declared-demand-only', 'admission_authority': False}


def validate_declaration(data: Mapping[str, object]) -> dict[str, Any] | None:
    if 'wave_resources' not in data:
        return None
    from .wave_planning import _validate

    # That parser joins the same sized role population and source digest before
    # asking parse() above to validate this optional field. No approval is issued.
    return _validate(data)['wave_resources']


@dataclass(frozen=True)
class Binding:
    collection_id: str
    window_id: str
    wave_id: str
    vm_binding_digest: str
    declaration_digest: str
    sizing_report_digest: str

    def __post_init__(self) -> None:
        for name in ('collection_id', 'window_id', 'wave_id'):
            wake._role(getattr(self, name))
        for name in ('vm_binding_digest', 'declaration_digest', 'sizing_report_digest'):
            wake._digest(getattr(self, name))


def parse_binding(value: object) -> Binding:
    return Binding(**_object(value, set(Binding.__dataclass_fields__)))


def _evaluate(plan: object, receipt: object, expected: object, now: object) -> dict[str, Any]:
    from .wave_planning import Plan

    if type(plan) is not Plan or type(expected) is not Binding:
        raise ResourcesRefused('independent bound resource context required')
    expected = parse_binding(asdict(expected))
    sizing = plan.verify()
    policy = sizing.get('wave_resources')
    if (policy is None or expected.declaration_digest != plan.approved_digest
            or expected.sizing_report_digest != policy['sizing_report_digest']):
        raise ResourcesRefused('resource observation and declaration identities differ')
    row = _object(receipt, {'version', 'binding', 'started_at', 'finished_at', 'complete',
                            'available_cpu_millicores', 'available_memory_bytes'})
    if (type(row['version']) is not int or row['version'] != 1 or row['complete'] is not True
            or parse_binding(row['binding']) != expected):
        raise ResourcesRefused('complete bound owner capacity facts required')
    start, end, current = _number(row['started_at']), _number(row['finished_at']), _number(now)
    if (not start <= end <= current or current - end > policy['max_age_seconds']
            or end - start > policy['max_collection_seconds']):
        raise ResourcesRefused('resource observations stale, future or incomplete')
    cpu = _integer(row['available_cpu_millicores'])
    memory = _integer(row['available_memory_bytes'])
    status = ('PASS' if cpu >= policy['required_cpu_millicores']
              and memory >= policy['required_memory_bytes'] else 'FAIL')
    return {'version': 1, 'status': status, 'binding': asdict(expected),
            'required_cpu_millicores': policy['required_cpu_millicores'],
            'required_memory_bytes': policy['required_memory_bytes'],
            'available_cpu_millicores': cpu, 'available_memory_bytes': memory,
            'source': 'owner-supplied-facts-no-host-observation-here',
            'scope': 'one-declared-simultaneous-wave', 'admission_authority': False}


def evaluate(plan: object, receipt: object, expected: object, now: object) -> dict[str, Any]:
    """Capacity consistency only; a fabricated receipt cannot authorize a run."""
    try:
        return _evaluate(plan, receipt, expected, now)
    except (ValueError, RecursionError):
        return {'version': 1, 'status': 'UNKNOWN', 'admission_authority': False,
                'reason': 'resource input unavailable or unverifiable'}
