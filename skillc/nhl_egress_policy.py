"""Declaration-bound NHL policy; no live digest has been owner-approved yet.

Synthetic sessions can qualify pure policy/attempt seams. Their permits NEVER
authorize Docker preparation. Python controller code is trusted; these objects
are provenance checks, not a sandbox against code running in this process.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import egress

NHL_HOSTS = ('api-web.nhle.com', 'api.nhle.com')
APPROVED_LIVE_DECLARATIONS: frozenset[str] = frozenset()


class PolicyRefused(ValueError):
    """No authority or incomplete policy evidence; never a task failure."""


@dataclass(frozen=True)
class Policy:
    purpose: str

    @property
    def hosts(self) -> tuple[str, ...]:
        return (*egress.ALLOWED_HOSTS, *NHL_HOSTS)

    def document(self) -> dict[str, object]:
        return {'policy': 'nhl-declaration-egress', 'version': 1, 'issue': 638,
                'hosts': sorted(self.hosts), 'port': 443, 'stop_on_denied': True,
                'measurement': 'CONNECT authorities; HTTP requests and response codes not measured'}

    @property
    def digest(self) -> str:
        return egress.document_digest(self.document())

    def allowed(self, target: str) -> bool:
        return egress._proxy_decide()(target, frozenset(self.hosts))


def parse(data: Mapping[str, object]) -> Policy | None:
    if 'nhl_egress' not in data:
        return None
    raw = data['nhl_egress']
    if (type(raw) is not dict or set(raw) != {'version', 'purpose', 'hosts', 'port', 'stop_on_denied'}
            or type(raw['version']) is not int or raw['version'] != 1
            or raw['purpose'] not in ('synthetic-control', 'sizing', 'live')
            or raw['hosts'] != list(NHL_HOSTS)
            or type(raw['port']) is not int or raw['port'] != 443
            or raw['stop_on_denied'] is not True):
        raise PolicyRefused('nhl_egress: closed declared NHL policy required')
    return Policy(raw['purpose'])


def require_live_authority(data: Mapping[str, object]) -> None:
    policy = parse(data)
    if policy is None:
        return
    from . import calibration
    digest = calibration.declaration_digest(data)
    if policy.purpose == 'synthetic-control' or digest not in APPROVED_LIVE_DECLARATIONS:
        raise PolicyRefused('nhl_egress: no owner-approved frozen live declaration; dispatch held')


@dataclass(frozen=True, repr=False)
class Permit:
    _issuer: Session = field(repr=False)
    _attempt: str = field(repr=False)

    def __repr__(self) -> str:
        return '<NHL egress permit>'

    @property
    def policy(self) -> Policy:
        return self._issuer.policy

    @property
    def stopped(self) -> bool:
        return self._attempt in self._issuer._stopped

    def stop(self) -> None:
        if type(self._issuer) is not Session or self._issuer._permits.get(self._attempt) is not self:
            raise PolicyRefused('nhl_egress: unregistered stop input')
        self._issuer._stopped.add(self._attempt)

    def require(self, backend: object, attempt: str, *, live: bool = False) -> None:
        if type(self._issuer) is not Session:
            raise PolicyRefused('nhl_egress: unregistered issuer')
        self._issuer.require(self, backend, attempt, live=live)


class Session:
    """One immutable declaration and issuer-owned permit registrations.

    Construction only enables synthetic-control policy seams. Production
    authorization remains held; a later reviewed #639 controller must join
    require_approved, window dispatch and the owner-approved frozen registry.
    """

    def __init__(self, data: Mapping[str, object]) -> None:
        from . import calibration
        self._data = copy.deepcopy(dict(data))
        declaration = calibration.parse_declaration(self._data)
        calibration.approval_record_binding(declaration)  # pure provenance only
        policy = parse(self._data)
        if policy is None:
            raise PolicyRefused('nhl_egress: policy absent')
        self.policy = policy
        self._digest = calibration.declaration_digest(self._data)
        self._permits: dict[str, Permit] = {}
        self._backends: dict[str, object] = {}
        self._stopped: set[str] = set()

    def issue(self, attempt: str) -> Permit:
        if self.policy.purpose != 'synthetic-control':
            require_live_authority(self._data)
        if not isinstance(attempt, str) or not attempt or attempt in self._permits:
            raise PolicyRefused('nhl_egress: duplicate or empty attempt')
        permit = Permit(self, attempt)
        self._permits[attempt] = permit
        return permit

    def bind(self, permit: Permit, backend: object) -> None:
        attempt = permit._attempt
        if self._permits.get(attempt) is not permit or attempt in self._backends:
            raise PolicyRefused('nhl_egress: unregistered or already bound permit')
        self._backends[attempt] = backend

    def require(self, permit: Permit, backend: object, attempt: str, *, live: bool) -> None:
        from . import calibration
        if (self._permits.get(attempt) is not permit or self._backends.get(attempt) is not backend
                or permit._attempt != attempt or parse(self._data) != self.policy
                or calibration.declaration_digest(self._data) != self._digest):
            raise PolicyRefused('nhl_egress: unregistered, changed or wrong-attempt permit')
        if live:
            # No synthetic input, forged approval JSON or caller-selected hosts
            # can populate the empty trusted registry or bypass normal approval.
            require_live_authority(self._data)
            raise PolicyRefused('nhl_egress: live permit issuance not enabled before #639 freeze')


def require_backend(backend: Any, attempt: str, *, live: bool = False) -> Policy | None:
    permit = getattr(backend, 'nhl_egress_permit', None)
    widened = any(isinstance(host, str) and host.lower().rstrip('.') in NHL_HOSTS
                  for host in backend.egress_hosts)
    if permit is None and not widened:
        return None
    if type(permit) is not Permit:
        raise PolicyRefused('nhl_egress: registered permit required')
    permit.require(backend, attempt, live=live)
    if backend.egress is not True or tuple(backend.egress_hosts) != permit.policy.hosts:
        raise PolicyRefused('nhl_egress: backend differs from declared policy')
    return permit.policy


def violation(summary: object, policy: Policy) -> dict[str, object] | None:
    """Pure interpretation; callers supply a trusted declaration-bound policy."""
    if (not isinstance(summary, Mapping) or summary.get('status') != 'read'
            or summary.get('allowlist_digest') != policy.digest or summary.get('unparsed_lines') != 0):
        return {'nhl_policy_unavailable': True}
    result: dict[str, object] = {}
    if summary.get('controller_policy_stop') is True:
        result['nhl_controller_stop'] = True
    for name in ('allowed', 'denied'):
        values = summary.get(name)
        if (not isinstance(values, Mapping) or any(not isinstance(k, str) or type(v) is not int or v < 0
                                                   for k, v in values.items())):
            return {'nhl_policy_unavailable': True}
        targets = sorted(k for k, v in values.items() if v > 0 and not policy.allowed(k))
        if targets:
            result['off_list_allowed_targets' if name == 'allowed' else 'undeclared_requests'] = targets
    return result or None
