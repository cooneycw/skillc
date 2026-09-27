"""Machine-identity leak detection (issue #63).

skillc is public, and it will soon produce evidence bundles, ledgers and
receipts from real trial runs (#10). Nothing stops a committed file, a PR body,
or a produced bundle from carrying the operator's machine identities. This
module scans text for five classes: an absolute home-directory path, a
`uid=`/`gid=` number, a private (RFC 1918) IPv4 address, a hostname from a
locally-configured deny-list, and credential material (#98: a subscription
login copied into a trial container raises the stakes of a leak well above
a machine identity - a token is not merely embarrassing, it is usable).
Stdlib only, like the rest of `skillc/`.

CREDENTIAL MATERIAL (#98) is matched two ways, both requiring an actual
VALUE, never a bare key name alone - this module's own source, and any
prose describing a client's credential schema, legitimately mentions field
names like `"expiresAt"` or `"access_token"` without ever containing a real
secret, and must not trip its own scan:

- an OAuth-shaped `"access_token"`/`"accessToken"`/`"refresh_token"`/
  `"refreshToken"` JSON key immediately followed by a long opaque string
  value;
- a recognizable API-key prefix (`sk-`, optionally `sk-ant-`) followed by
  20+ opaque characters.

What this CANNOT see, on top of the four classes' own stated limits below:
a credential value split across lines, wrapped, or re-encoded (base64,
URL-encoding); a token shape this module does not yet recognize; or a
credential referenced only by a variable name with no literal value present
in the scanned text.

What this CANNOT see - stated plainly, because absence of a finding here is
not proof of absence:

- a hostname not in the deny-list. The deny-list is deliberately not shipped
  with real names (`load_denylist` reads an untracked file or nothing); a run
  with none configured sees no hostnames at all, only the other three classes.
- a username or machine name embedded anywhere OTHER than a `/home/<name>` or
  `/Users/<name>` path - a bare username in prose, an email local-part, a
  Windows `C:\\Users\\<name>` path, a WSL `\\\\wsl$\\...` path.
- a public IPv4 address, a loopback or link-local one (127.0.0.0/8,
  169.254.0.0/16 - neither identifies a specific machine; see `_is_private`),
  or any IPv6 address.
- a binary file, one that is not valid UTF-8, a symlink pointing outside the
  scanned tree, or a FIFO/socket/device - all skipped, not scanned, and
  `scan_path`'s `skipped` count says how many were, together.
- an identity reconstructed from fragments split across more than one line,
  or built at runtime (string concatenation, an environment variable name).
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# The directory name right after /home/ or /Users/ - not the rest of the path -
# because that name IS the local username being leaked.
HOME_PATH_RE = re.compile(r"/(?:home|Users)/([A-Za-z0-9_.-]+)")

UID_GID_RE = re.compile(r"\b(?:uid|gid)=\d+")

IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

#: An OAuth-shaped token KEY immediately followed by a long opaque VALUE
#: (#98) - requires the value, never fires on the key name alone (this
#: module's own docstring, and skillc/credential.py's, both discuss these
#: field names in prose with no value attached, and must stay silent).
OAUTH_TOKEN_RE = re.compile(
    r'"(?:access|refresh)_?[Tt]oken"\s*:\s*"([A-Za-z0-9_.\-]{20,})"'
)

#: A recognizable API-key prefix (Anthropic's `sk-ant-...`, or the generic
#: `sk-...` shape several providers share) followed by enough opaque
#: characters that a short, coincidental match is implausible.
API_KEY_RE = re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b")

#: The finding this yields for either pattern NEVER includes the matched
#: value itself (cross-model review, #98): the whole point of this class is
#: that the scanned text carries a real secret, so echoing `match.group(0)`
#: into a finding, a log line, or a review comment would create a second
#: copy of it at the exact moment of detection. See `scan_text`'s two
#: `credential-token` yields below.

#: Known-safe values a bare regex would otherwise flag - compared against the
#: EXACT matched text (a whole home-directory path, a whole `uid=`/`gid=`
#: assignment, or a bare IP), never against the containing line. Matching the
#: line would exempt any OTHER leak sharing it, and matching by substring would
#: exempt a longer, unrelated value merely containing an allowlisted one -
#: both found by cross-model review (see the tests for the exact shapes).
#: Reviewed by hand; extend only with a stated reason for why the match is not
#: a real identity, never to silence a finding that IS one.
ALLOWLIST: frozenset[str] = frozenset({
    "10.0.0.0", "172.16.0.0", "192.168.0.0",  # this module's OWN range
    # definitions (_PRIVATE_IPV4_RANGES below) - the detector's configuration,
    # not a leaked identity. Without this, skillc/leak.py fails its own scan.
    "/home/candidate",  # the evaluation-facility's OWN canonical fixed,
    # non-host identity for an execution backend (docs/specs/evaluation-
    # facility/interfaces.md, skillc/backend.py, #10/#65) - a logical
    # placeholder documented as the SAFE pattern to use, not a real one.
    "/home/some-claude-shaped-account",  # a deliberately fake, documented
    # placeholder in tests/test_lifecycle.py's own docstring ("the account
    # name here is a placeholder, not this host's"), not a real identity.
})

#: `--denylist`, then this environment variable, then nothing (#63). Real host
#: names belong in an untracked local file or this variable, never committed.
DENYLIST_ENV = "SKILLC_LEAK_DENYLIST"

#: Never scanned: version control internals and caches that are not committed
#: and can hold arbitrary third-party text a scan has no business judging.
SKIP_DIRS = frozenset({
    ".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
})


@dataclass(frozen=True)
class LeakFinding:
    path: Path
    line: int
    kind: str
    detail: str

    def render(self, root: Path) -> str:
        try:
            shown: Path | str = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        return f"{shown}:{self.line}: {self.kind}: {self.detail}"


def load_denylist(explicit: str | None = None) -> frozenset[str]:
    """Real host/machine names, kept OUT of this repository on purpose.

    An absent path, or one that does not exist, returns an empty set rather
    than refusing - a fleet with no configured deny-list still gets the other
    three classes. That silence is a real limit, not a clean result; callers
    must say so rather than imply full coverage (see the module docstring).
    """
    path = explicit or os.environ.get(DENYLIST_ENV)
    if not path:
        return frozenset()
    p = Path(path)
    if not p.is_file():
        return frozenset()
    names: set[str] = set()
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return frozenset(names)


#: RFC 1918 private ranges only. Loopback (127.0.0.0/8) and link-local
#: (169.254.0.0/16) are deliberately NOT included, even though Python's own
#: `IPv4Address.is_private` covers them too: neither identifies a specific
#: machine - 127.0.0.1 is the same address on every host that has one - so
#: flagging it is not a leak detection, it is noise. Measured directly: it
#: false-positived on `evals/subjects/cpp-codex/evidence/report.json`, a file
#: the issue itself states is already clean, over a line that only says a
#: SKILL.md mentions "127.0.0.1" as example text.
_PRIVATE_IPV4_RANGES = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def _is_private(candidate: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(candidate)
    except ipaddress.AddressValueError:
        return False
    return any(addr in network for network in _PRIVATE_IPV4_RANGES)


def scan_text(text: str, denylist: frozenset[str]) -> Iterator[tuple[int, str, str]]:
    """Yield (1-indexed line, kind, detail) for every leak class found.

    The allowlist is checked against each MATCH, not the line it is on - a
    real leak sharing a line with an allowlisted value must still fire.
    """
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in HOME_PATH_RE.finditer(line):
            if match.group(0) in ALLOWLIST:
                continue
            yield (
                lineno, "home-path",
                f"home-directory path for {match.group(1)!r}: {match.group(0)}",
            )
        for match in UID_GID_RE.finditer(line):
            if match.group(0) in ALLOWLIST:
                continue
            yield lineno, "uid-gid", match.group(0)
        for match in IPV4_RE.finditer(line):
            candidate = match.group(1)
            if candidate in ALLOWLIST:
                continue
            if _is_private(candidate):
                yield lineno, "private-ip", candidate
        for name in denylist:
            if name in line:
                yield lineno, "denylisted-hostname", name
        for match in OAUTH_TOKEN_RE.finditer(line):
            if match.group(0) in ALLOWLIST:
                continue
            yield lineno, "credential-token", "OAuth-shaped token value present (redacted)"
        for match in API_KEY_RE.finditer(line):
            if match.group(0) in ALLOWLIST:
                continue
            yield lineno, "credential-token", "API-key-shaped value present (redacted)"


def _files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


@dataclass(frozen=True)
class ScanResult:
    findings: list[LeakFinding]
    scanned: int
    skipped: int


def _excluded(rel: str, exclude: frozenset[str]) -> bool:
    return any(rel == e or rel.startswith(e.rstrip("/") + "/") for e in exclude)


def scan_path(
    root: Path, denylist: frozenset[str], exclude: frozenset[str] = frozenset()
) -> ScanResult:
    """Scan every file under `root` (or `root` itself if it is a file).

    `exclude` names path prefixes RELATIVE TO `root` (posix-style) to skip
    entirely - for a CI run over the whole repository tree, this is how the
    seeded, deliberately-fake `controls/leak-check/bad/` fixture stays out of
    its own gate's population without being blind to a real leak anywhere
    else. It is not a general allowlist: prefer `ALLOWLIST` for a specific
    known-safe line, and this only for a whole directory that exists to
    contain fake leaks on purpose.

    A file that cannot be decoded as UTF-8 is SKIPPED, counted in `skipped`,
    and never contributes a finding - it is a class this run cannot see, not
    a file that was scanned and found clean. `skipped > 0` on a real bundle is
    worth reporting alongside a clean `findings == []`.

    A symlink whose target resolves OUTSIDE `root` is skipped too, never
    followed: following it would read host state this run was never asked to
    look at, and the file's own content (and this run's verdict on it) could
    then change without the reviewed tree changing at all. A broken symlink, a
    FIFO, a socket or a device is skipped the same way - `Path.is_file()` is
    false for all of them, and none is safe to open unconditionally (a FIFO
    with no writer blocks the scan forever).
    """
    findings: list[LeakFinding] = []
    scanned = 0
    skipped = 0
    root_resolved = root.resolve()
    for path in _files(root):
        rel = path.relative_to(root).as_posix() if root.is_dir() else path.name
        if _excluded(rel, exclude):
            continue
        if not path.is_file():
            skipped += 1
            continue
        if path.is_symlink() and root.is_dir():
            target = path.resolve()
            if target != root_resolved and root_resolved not in target.parents:
                skipped += 1
                continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped += 1
            continue
        scanned += 1
        for lineno, kind, detail in scan_text(text, denylist):
            findings.append(LeakFinding(path, lineno, kind, detail))
    return ScanResult(findings=findings, scanned=scanned, skipped=skipped)
