"""Declaration-bound NHL policy; no live digest has been owner-approved yet.

Synthetic sessions can qualify pure policy/attempt seams. Their permits NEVER
authorize Docker preparation. Python controller code is trusted; these objects
are provenance checks, not a sandbox against code running in this process.
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import egress, egress_bytes

NHL_HOSTS = ('api-web.nhle.com', 'api.nhle.com')
APPROVED_LIVE_DECLARATIONS: frozenset[str] = frozenset()


class PolicyRefused(ValueError):
    """No authority or incomplete policy evidence; never a task failure."""


@dataclass(frozen=True)
class Policy:
    purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, str) or self.purpose not in ('synthetic-control', 'sizing', 'live'):
            raise PolicyRefused('nhl_egress: supported policy purpose required')

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
        if not isinstance(target, str):
            raise PolicyRefused('nhl_egress: CONNECT authority must be text')
        return egress._proxy_decide()(target, frozenset(self.hosts))


def parse(data: Mapping[str, object]) -> Policy | None:
    if not isinstance(data, Mapping):
        raise PolicyRefused('nhl_egress: declaration object required')
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

    def _registered(self) -> Session:
        if (type(self._issuer) is not Session or not isinstance(self._attempt, str)
                or self._issuer._permits.get(self._attempt) is not self):
            raise PolicyRefused('nhl_egress: unregistered permit or issuer')
        return self._issuer

    @property
    def policy(self) -> Policy:
        return self._registered().policy

    @property
    def stopped(self) -> bool:
        return self._attempt in self._registered()._stopped

    def stop(self) -> None:
        self._registered()._stopped.add(self._attempt)

    def require(self, backend: object, attempt: str, *, live: bool = False) -> None:
        self._registered().require(self, backend, attempt, live=live)


class Session:
    """One immutable declaration and issuer-owned permit registrations.

    Construction only enables synthetic-control policy seams. Production
    authorization remains held; a later reviewed #639 controller must join
    require_approved, window dispatch and the owner-approved frozen registry.
    """

    def __init__(self, data: Mapping[str, object]) -> None:
        from . import calibration
        policy = parse(data)
        if policy is None:
            raise PolicyRefused('nhl_egress: policy absent')
        self._data = copy.deepcopy(dict(data))
        try:
            declaration = calibration.parse_declaration(self._data)
            calibration.approval_record_binding(declaration)  # pure provenance only
        except calibration.DeclarationRefused:
            raise PolicyRefused('nhl_egress: unverified declaration provenance') from None
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
        from .docker_backend import DockerBackend
        if (type(permit) is not Permit or permit._issuer is not self
                or not isinstance(permit._attempt, str)
                or not isinstance(backend, DockerBackend) or backend.nhl_egress_permit is not permit
                or backend.egress is not True or not isinstance(backend.egress_hosts, (tuple, list))
                or tuple(backend.egress_hosts) != self.policy.hosts):
            raise PolicyRefused('nhl_egress: registered permit and matching backend required')
        attempt = permit._attempt
        if self._permits.get(attempt) is not permit or attempt in self._backends:
            raise PolicyRefused('nhl_egress: unregistered or already bound permit')
        self._backends[attempt] = backend

    def require(self, permit: Permit, backend: object, attempt: str, *, live: bool) -> None:
        from . import calibration
        if (type(permit) is not Permit or not isinstance(attempt, str) or not attempt
                or type(live) is not bool or permit._issuer is not self
                or self._permits.get(attempt) is not permit or self._backends.get(attempt) is not backend
                or permit._attempt != attempt or parse(self._data) != self.policy
                or calibration.declaration_digest(self._data) != self._digest):
            raise PolicyRefused('nhl_egress: unregistered, changed or wrong-attempt permit')
        if live:
            # No synthetic input, forged approval JSON or caller-selected hosts
            # can populate the empty trusted registry or bypass normal approval.
            require_live_authority(self._data)
            raise PolicyRefused('nhl_egress: live permit issuance not enabled before #639 freeze')


def require_backend(backend: Any, attempt: str, *, live: bool = False) -> Policy | None:
    from .docker_backend import DockerBackend
    if not isinstance(backend, DockerBackend):
        raise PolicyRefused('nhl_egress: supported backend required')
    if (not isinstance(backend.egress_hosts, (tuple, list))
            or any(not isinstance(host, str) for host in backend.egress_hosts)):
        raise PolicyRefused('nhl_egress: explicit host sequence required')
    permit = backend.nhl_egress_permit
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


def _counts(value: object) -> Mapping[str, int]:
    if (not isinstance(value, Mapping) or any(not isinstance(k, str) or type(v) is not int or v < 0
                                             for k, v in value.items())):
        raise PolicyRefused('nhl_egress: complete nonnegative connection counters required')
    return value


def summarize_log(raw: object) -> dict[str, object]:
    """Validate NHL wire roots before the historical object-only decoder.

    Keep the legacy decoder unchanged. A non-object root or broken transport
    is unavailable input, not an empty clean connection census.
    """
    if not isinstance(raw, bytes):
        raise PolicyRefused('nhl_egress: proxy log bytes unavailable')
    policy_lines = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            raise PolicyRefused('nhl_egress: malformed proxy log line') from None
        if not isinstance(entry, dict):
            raise PolicyRefused('nhl_egress: proxy log object required')
        if entry.get('event') not in ('bytes', 'bytes-end'):
            policy_lines.append(line)
    result = egress.summarize_log('\n'.join(policy_lines).encode())
    result['bytes_observed'] = egress_bytes.summarize(raw, result['allowlist_digest'])
    return result


def violation(summary: object, policy: Policy) -> dict[str, object] | None:
    """Validate observations, then interpret a trusted declaration-bound policy.

    Callers convert PolicyRefused into an unavailable-evidence stop. Neither an
    invalid shape nor an unknown observation can become a clean empty census.
    """
    if not isinstance(policy, Policy) or policy.purpose not in ('synthetic-control', 'sizing', 'live'):
        raise PolicyRefused('nhl_egress: compiled policy required')
    required = {'status', 'allowlist_digest', 'unparsed_lines', 'allowed', 'denied'}
    optional = {'digest', 'upstream_failed', 'peer_rejected', 'controller_policy_stop', 'bytes_observed'}
    if (not isinstance(summary, Mapping) or not required <= summary.keys()
            or set(summary) - required - optional or summary['status'] != 'read'
            or summary['allowlist_digest'] != policy.digest
            or type(summary['unparsed_lines']) is not int or summary['unparsed_lines'] != 0):
        raise PolicyRefused('nhl_egress: complete bound proxy observation required')
    if ('controller_policy_stop' in summary and type(summary['controller_policy_stop']) is not bool
            or 'peer_rejected' in summary and (type(summary['peer_rejected']) is not int
                                               or summary['peer_rejected'] < 0)
            or 'digest' in summary and (not isinstance(summary['digest'], str)
                                        or re.fullmatch(r'sha256:[0-9a-f]{64}', summary['digest']) is None)):
        raise PolicyRefused('nhl_egress: invalid optional observation fields')
    result: dict[str, object] = {}
    if summary.get('controller_policy_stop') is True:
        result['nhl_controller_stop'] = True
    requested: set[str] = set()
    for name in ('allowed', 'denied', 'upstream_failed'):
        values = _counts(summary.get(name, {}))
        targets = sorted(k for k, v in values.items() if v > 0 and not policy.allowed(k))
        if name == 'allowed' and targets:
            result['off_list_allowed_targets'] = targets
        elif name != 'allowed':
            requested.update(targets)
    if requested:
        result['undeclared_requests'] = sorted(requested)
    return result or None
