"""The operator's subscription credential, delivered into a trial container
(#98, Refs #10). skillc uses the operator's own normal Claude Code and Codex
logins for an agent run - never a pay-per-use API key, never a cloud secret
store, and never any path or mechanism belonging to another platform. The
owner's ruling, quoted verbatim (from issue #98): "Normal Claude and codex".

THREE FACTS THIS MODULE EXISTS TO KEEP TRUE, in order:

1. **skillc never searches a home directory for a credential it wasn't told
   about.** `resolve_path` tries an explicit override (an argument, or a
   named environment variable) FIRST, then exactly one documented standard
   location per client - never a scan, never a guess at "maybe it's here
   too". Nothing resolving is `CredentialRefused`, not a silent skip.
2. **The credential is read FRESH, every trial, never cached.** Both
   Claude Code's OAuth access token (~12h expiry, with a refresh token) and
   Codex's `auth.json` are rotating credentials, not long-lived keys - a
   copy taken once and reused across trials could serve an already-expired
   token, or one the operator has since rotated. Every caller of
   `read_fresh` must call it again for every trial; nothing here memoizes a
   result across calls, and there is no cache to invalidate.
3. **A trial refuses to start rather than risk needing to refresh
   mid-trial.** A refresh INSIDE the container is the real hazard: the
   provider can rotate the refresh token, which can invalidate the
   operator's own HOST copy - and nothing here writes back to the host to
   protect it. So `check_remaining_life_or_refuse` reads the access token's
   remaining life where the file exposes it and refuses (`CredentialRefused`,
   a stated reason) below `MINIMUM_REMAINING_SECONDS` - including when the
   remaining life cannot be determined at all, which is treated the same as
   "not enough time left", never as "probably fine".

A trial's RECORD may say a client used its subscription credential, but never
the credential itself - `CredentialUsage.to_record_fields()` is built from
facts a caller already holds (which client, whether delivery succeeded,
whether an in-container refresh was observed), never from the credential
bytes, so there is no field a token value could occupy.

An in-container refresh is observable, WHEN a caller compares - `refresh_observed`
compares the bytes `docker_backend.DockerBackend.deliver_home_file` sent
against what `docker_backend.DockerBackend.read_home_file` reads back before
`destroy()` discards the container (and the fact) for good. Comparing is an
extra round trip a caller must choose to make; `CredentialUsage`'s default
(`None`) means "never compared", not "no refresh".

WHAT THIS MODULE DOES NOT DO. It never writes to the credential file, on the
host or in the container. Nothing here observes or reports whether the
operator's own HOST login still works after a trial; that check is owed to
the operator's own live run, for both clients, exactly as issue #98 states
it - comparing IN-container bytes (above) says nothing about the host copy.
It also does not implement the actual delivery transport - that is
`docker_backend.DockerBackend.deliver_home_file`, which this module's
caller (a real-agent trial driver, not yet built - #11's own remaining
agent-run item) is expected to call with the bytes and destination this
module resolves.

CREDENTIAL SCHEMAS ARE BEST-EFFORT, OWED TO THE LIVE RUN. `EXPIRY_KEY_PATHS`
names the JSON key paths this module tries, per client, to find an expiry
timestamp - a documented guess at each client's real on-disk schema, not a
confirmed fact. `remaining_life_seconds` returns `None` (never a guessed
number) for any shape it does not recognize, and a caller must treat `None`
exactly like "known to be expiring soon" (see point 3 above), never like
"probably still valid". Confirming or correcting `EXPIRY_KEY_PATHS` against
a real credential file is explicitly owed to the operator's live run.

Stdlib only (AGENTS.md): `json`, `os`, `time`, `dataclasses`, `pathlib`.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class CredentialRefused(Exception):
    """No credential could be resolved, read, or trusted with enough
    remaining life - a trial must not start, with a stated reason. Never
    raised for "the file looks unusual"; only for the three named cases
    (`resolve_path`, `read_fresh`, `check_remaining_life_or_refuse`)."""


#: Standard, DOCUMENTED locations only - never a directory scan (#98: "skillc
#: never searches a home directory for it"). `CODEX_HOME` is Codex's own
#: documented override for its config directory; skillc reads it here only
#: to find the STANDARD location, exactly as the operator's own Codex CLI
#: would.
def _default_claude_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _default_codex_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "auth.json"


@dataclass(frozen=True)
class CredentialSpec:
    client: str
    #: The host-side standard location, resolved fresh on each call (never
    #: cached), so a test can monkeypatch `Path.home`/`CODEX_HOME` without
    #: this module capturing a stale value at import time.
    default_path: Callable[[], Path]
    #: The name of an environment variable that, if set, NAMES a file
    #: overriding `default_path` - not a search path, a single explicit name.
    env_override: str
    #: Where this file must land inside CONTAINER_HOME (docker_backend.py),
    #: relative to it - the directory each client already owns in the trial
    #: image (#78).
    container_relpath: str


CLIENT_SPECS: dict[str, CredentialSpec] = {
    "claude": CredentialSpec(
        client="claude",
        default_path=_default_claude_path,
        env_override="SKILLC_CLAUDE_CREDENTIAL",
        container_relpath=".claude/.credentials.json",
    ),
    "codex": CredentialSpec(
        client="codex",
        default_path=_default_codex_path,
        env_override="SKILLC_CODEX_CREDENTIAL",
        container_relpath=".codex/auth.json",
    ),
}


def resolve_path(client: str, explicit: str | Path | None = None) -> Path:
    """The ONE file this client's credential will be read from: `explicit`
    (an operator-named flag value) if given, else the client's own
    documented environment-variable override if set, else the client's
    standard location. `CredentialRefused` if the resolved candidate does
    not exist as a regular file - never a fallback to a different location,
    and never a guess at another path "just in case"."""
    if client not in CLIENT_SPECS:
        raise CredentialRefused(f"unknown client {client!r}: expected one of {sorted(CLIENT_SPECS)}")
    spec = CLIENT_SPECS[client]
    if explicit is not None:
        candidate = Path(explicit)
        source = "the explicitly given path"
    else:
        env_value = os.environ.get(spec.env_override)
        if env_value:
            candidate = Path(env_value)
            source = f"${spec.env_override}"
        else:
            candidate = spec.default_path()
            source = "the standard location"
    if candidate.is_symlink() or not candidate.is_file():
        raise CredentialRefused(
            f"no {client} credential at {candidate} ({source}) - a trial refuses rather than "
            f"guess at another location or proceed without one"
        )
    return candidate


def read_fresh(path: Path) -> bytes:
    """The credential's current bytes. Named, and documented, so a caller
    cannot mistake this for something safe to call once and reuse: call it
    again for every trial (module docstring, point 2) - there is no cache
    here to go stale, because there is no cache."""
    return path.read_bytes()


#: `claude`'s schema is a plain JSON field, verified directly against a real
#: `~/.claude/.credentials.json` on this host (#98): `claudeAiOauth.expiresAt`,
#: milliseconds since epoch. BEST-EFFORT for any shape beyond that one
#: confirmed case. `codex` has no entry here - see `_jwt_exp_seconds` below;
#: a real `~/.codex/auth.json` on this same host has no `expires_at` field
#: anywhere, at any of the paths an earlier version of this dict guessed at,
#: so a real fresh login always read as undeterminable and was always
#: refused (found by cross-model review, #98).
EXPIRY_KEY_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "claude": (
        ("claudeAiOauth", "expiresAt"),
        ("expiresAt",),
    ),
}

#: A trial should never need to refresh mid-run (issue #98). Five minutes is
#: a conservative floor for a Level 1 task's own short timeout; a longer
#: trial needs a proportionally larger value, passed explicitly rather than
#: relying on this default.
MINIMUM_REMAINING_SECONDS = 300.0


def _walk(data: object, path: tuple[str, ...]) -> object | None:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _finite_number(value: object) -> float | None:
    """`value` as a `float` only when it is a genuine, finite JSON number -
    never `True`/`False` (a JSON `bool` IS a Python `int` subclass, so
    `isinstance(value, (int, float))` alone would accept one), and never
    `NaN`/`Infinity`/`-Infinity` (Python's own `json.loads` accepts all
    three by default, so a crafted or corrupted credential file naming one
    as an expiry would otherwise silently pass every comparison below it -
    found by cross-model review, #98)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _jwt_exp_seconds(token: object) -> float | None:
    """The `exp` claim (seconds since epoch, RFC 7519) decoded from a JWT's
    payload segment. `codex`'s `tokens.access_token` is itself a JWT, and
    that claim is the only expiry this module can find anywhere in a real
    `~/.codex/auth.json` (see `EXPIRY_KEY_PATHS`'s own docstring). Never
    verifies the signature - this module only READS a credential already
    trusted by its presence on disk, never authenticates one. `None` for
    anything that is not a three-segment JWT with a finite numeric `exp`
    claim, including a token this module cannot even parse as one - the
    same "undeterminable, not assumed fine" rule as everywhere else here."""
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    return _finite_number(claims.get("exp"))


def remaining_life_seconds(client: str, data: bytes) -> float | None:
    """Seconds remaining before this credential's access token expires, or
    `None` when that cannot be determined - malformed JSON, or a shape this
    client's schema does not recognize. Never a guessed number: a caller that
    cannot tell "expires soon" from "never expires" must treat `None` as
    the FIRST one (see `check_remaining_life_or_refuse`)."""
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if client == "codex":
        exp = _jwt_exp_seconds(_walk(parsed, ("tokens", "access_token")))
        return exp - time.time() if exp is not None else None
    for path in EXPIRY_KEY_PATHS.get(client, ()):
        value = _finite_number(_walk(parsed, path))
        if value is None:
            continue
        epoch_seconds = value / 1000.0 if _is_millisecond_key(path[-1]) else value
        return epoch_seconds - time.time()
    return None


def _is_millisecond_key(last_key: str) -> bool:
    """`expiresAt` (camelCase - JS `Date.now()`-shaped, milliseconds) versus
    `expires_at` (snake_case - the common OAuth2/JSON-API convention,
    seconds). A loose substring check on the lowercased key (`"at" in
    key.lower()`) is WRONG here: "expires_at".lower() still contains the
    substring "at" (its own last two characters), so it would be
    misclassified as milliseconds and divided by 1000 - found by this
    module's own test (the codex shape returned a multi-decade-past
    timestamp). Checked against the ORIGINAL casing, exact match only, plus
    an explicit "ms" marker for any future snake_case-with-unit key."""
    return last_key == "expiresAt" or "ms" in last_key.lower()


def refresh_observed(delivered: bytes, current: bytes) -> bool:
    """Did the in-container copy change since it was delivered? A byte
    comparison, nothing more - `docker_backend.DockerBackend.read_home_file`
    supplies `current`, read back before `destroy()` discards the container
    and the fact along with it. `False` on identical bytes, `True` on any
    difference.

    NAME THE LIMIT: this is "did the bytes change", not "did a token
    refresh happen" - any process rewriting the file (reformatting,
    reordering keys, touching an unrelated field) reports `True` exactly
    like a real OAuth refresh would, because this module never parses
    WHAT changed, only WHETHER anything did. `True` is evidence worth
    recording, not proof of a rotation; a caller must not read it as a
    confirmed refresh."""
    return delivered != current


@dataclass(frozen=True)
class CredentialUsage:
    """What a record may say about this trial's credential (#98: "records
    name the client and 'subscription', never the token"). Built from facts
    a caller already holds - which client, whether delivery succeeded,
    whether an in-container refresh was observed - never from the credential
    bytes themselves. There is no field here a token value could ever occupy,
    so a caller cannot leak one through this type by mistake.

    `refresh_observed_in_container` is `None` when the caller never compared
    (the common case: comparing requires an extra `read_home_file` round
    trip before `destroy()`, which is itself owed to the live run per the
    module docstring) - `None` means "not observed", never "no refresh"."""

    client: str
    source: str = "subscription"
    delivered: bool = True
    refresh_observed_in_container: bool | None = None

    def to_record_fields(self) -> dict[str, object]:
        return {
            "credential_client": self.client,
            "credential_source": self.source,
            "credential_delivered": self.delivered,
            "credential_refresh_observed_in_container": self.refresh_observed_in_container,
        }


def check_remaining_life_or_refuse(
    client: str, data: bytes, *, minimum_seconds: float = MINIMUM_REMAINING_SECONDS,
) -> float:
    """Returns the remaining seconds when it is confidently at or above
    `minimum_seconds`; otherwise `CredentialRefused` with a stated reason -
    including when `remaining_life_seconds` returns `None`. An
    undeterminable remaining life is refused, not assumed safe (module
    docstring, point 3): guessing "probably fine" is exactly the guess this
    module exists to refuse."""
    if isinstance(minimum_seconds, bool) or not math.isfinite(minimum_seconds) or minimum_seconds < 0:
        raise ValueError(f"minimum_seconds must be a finite, non-negative number, got {minimum_seconds!r}")
    remaining = remaining_life_seconds(client, data)
    if remaining is None:
        raise CredentialRefused(
            f"{client} credential's remaining life could not be determined - refusing rather "
            f"than risk an in-trial refresh, which could invalidate the operator's own host login"
        )
    if remaining < minimum_seconds:
        raise CredentialRefused(
            f"{client} credential has {remaining:.0f}s remaining, below the required "
            f"{minimum_seconds:.0f}s - refusing rather than risk needing to refresh mid-trial"
        )
    return remaining
