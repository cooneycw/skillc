"""Per-attempt, root-owned harness overlays for a live fixture attempt (#434
PR 2b): the `gh` shim (#276) and the nested-codex guard (D3).

Both are harness apparatus, never subject dependencies, so neither belongs in a
profile (`gate_overlay`'s own lesson). Both are placed AS ROOT with
`write_root_owned_file_in_attempt()`, after the subject's surface is installed
and before the agent starts, and each is then VERIFIED rather than trusted:

1. the destination did not exist before (a pre-planted `gh` or `codex` is
   refused, never overwritten);
2. the bytes read back from the container hash to the tracked source's digest;
3. neither the file nor its directory is writable by the candidate
   (`candidate_can_write_in_attempt()`; anything but a confirmed `False`
   refuses, `gate_overlay`'s rule);
4. under the attempt's MEASURED runtime environment, as the candidate,
   `command -v <name>` resolves to the placed file. A PATH that finds another
   one first is refused before any spend.

WHY `/usr/local/sbin` FOR THE GUARD (orchestrator ruling A). npm's real
`codex` is a symlink at `/usr/local/bin/codex`, and the root write primitive
is `cat > "$1"`, which would write THROUGH that link and overwrite the real
codex.js. The image's inherited PATH searches `/usr/local/sbin` first, and
that directory is root-owned and empty, so the guard goes there and the real
link is never touched. Check 4 is what makes the PATH order a verified fact
rather than an assumption.

#518: CHECK 4 HELD ONLY FOR THE INHERITED PATH. codex runs every tool command as
`bash -lc`, and a login shell takes /etc/profile's non-root PATH, which drops
/usr/local/sbin: there a bare `codex` was the real client (sizing-2's nested
review ran unrefused while the guard read zero). A root-owned
`/etc/profile.d/00-skillc-codex-guard.sh` puts /usr/local/sbin first again,
and check 4 now runs in a login shell too.

The guard's CONFIG (the realpaths of node, the real codex.js and the vendored
native binaries) is resolved in the container now, by the controller, and
written root-owned beside the harness. The guard trusts nothing derived at run
time from what the candidate can write. Every resolved binary, and its
directory, must itself be candidate-unwritable: a codex.js the subject could
replace would make the identity match meaningless.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .backend import ExecuteResult, Limits

_FIXTURE_SERVICE_DIR = Path(__file__).resolve().parent.parent / "docker" / "fixture-service"
GH_SHIM_SOURCE = _FIXTURE_SERVICE_DIR / "skillc-gh-shim.py"
CODEX_GUARD_SOURCE = _FIXTURE_SERVICE_DIR / "skillc-codex-guard.py"

GH_PATH = "/usr/local/bin/gh"
CODEX_GUARD_PATH = "/usr/local/sbin/codex"
#: #518: a LOGIN shell (codex runs every tool command as `bash -lc`) takes
#: /etc/profile's non-root PATH, which drops /usr/local/sbin, so a bare `codex`
#: there was the real client. This root-owned entry, sourced by /etc/profile
#: after it sets PATH, puts the guard's directory first again.
LOGIN_PROFILE_PATH = "/etc/profile.d/00-skillc-codex-guard.sh"
LOGIN_PROFILE = (b"# skillc #518 (root-owned, per attempt): a login shell reaches the nested-codex guard\n"
                 b"# before npm's real codex; /etc/profile's non-root PATH drops /usr/local/sbin.\n"
                 b'PATH="/usr/local/sbin:$PATH"\nexport PATH\n')
#: Must equal `skillc-codex-guard.py`'s own `CONFIG`.
CODEX_GUARD_CONFIG = "/opt/skillc-harness/codex-guard.json"
REAL_CODEX = "/usr/local/bin/codex"
NODE = "/usr/local/bin/node"
#: The vendored native binary for each architecture codex.js supports
#: (`docker/trial/verify_codex_sidecar.js`'s own map), as npm lays it out.
NATIVE_CANDIDATES = tuple(
    f"/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/{package}/vendor/{triple}/bin/codex"
    for package, triple in (("codex-linux-x64", "x86_64-unknown-linux-musl"),
                            ("codex-linux-arm64", "aarch64-unknown-linux-musl")))

_PROBE_LIMITS = Limits(timeout=10.0, grace=2.0, max_captured_stdout_bytes=4 * 1024 * 1024,
                       max_captured_stderr_bytes=64 * 1024)


class OverlayRefused(Exception):
    """A pre-planted destination, a digest mismatch, a writable placement, a
    PATH that finds something else, or a failed write. Raised before the
    agent starts, so nothing is spent."""


@dataclass(frozen=True)
class PlacedFile:
    path: str
    digest: str


class _OverlayBackend(Protocol):
    @property
    def witness_io(self) -> bool: ...

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits,
                        cancel: Callable[[], bool] | None = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None,
                        confine_root: str | None = None) -> ExecuteResult: ...

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes,
                                         mode: int = 0o755) -> bool: ...

    def candidate_can_write_in_attempt(self, handle: object, path: str) -> bool | None: ...


def _exec(backend: _OverlayBackend, handle: object, argv: Sequence[str],
          env: Mapping[str, str] | None = None) -> ExecuteResult:
    # Without witness_io each exec writes `observations` and a pid marker into
    # /work, which the source-unmodified check would read as the subject's.
    if not getattr(backend, "witness_io", False):
        raise OverlayRefused("the backend is not in witness_io mode; a probe would write into the workspace")
    return backend.exec_in_attempt(handle, argv, _PROBE_LIMITS, env=env)


def _output(backend: _OverlayBackend, handle: object, argv: Sequence[str],
            env: Mapping[str, str] | None = None) -> bytes:
    result = _exec(backend, handle, argv, env)
    if (result.reason != "exited" or result.exit_code != 0 or result.stdout is None
            or result.stdout_truncated or result.stdout_incomplete or result.stderr_incomplete):
        raise OverlayRefused(f"the overlay probe {argv[0]!r} failed or returned incomplete output "
                             f"(reason={result.reason!r}, exit={result.exit_code!r})")
    return result.stdout


def _absent(backend: _OverlayBackend, handle: object, path: str) -> None:
    script = 'if [ -e "$1" ] || [ -L "$1" ]; then echo present; else echo absent; fi'
    out = _output(backend, handle, ["sh", "-c", script, "sh", path])
    if out != b"absent\n":
        raise OverlayRefused(f"{path!r} already exists in the attempt; a pre-planted file is never overwritten")


def _realpath(backend: _OverlayBackend, handle: object, path: str) -> str | None:
    result = _exec(backend, handle, ["realpath", "-e", "--", path])
    if result.reason == "exited" and result.exit_code == 1 and not result.stdout:
        return None  # no such file
    if (result.reason != "exited" or result.exit_code != 0 or result.stdout is None
            or result.stdout_truncated or result.stdout_incomplete):
        raise OverlayRefused(f"could not resolve {path!r} in the attempt")
    resolved = result.stdout.decode("utf-8", errors="replace")
    if not resolved.endswith("\n") or resolved.count("\n") != 1 or not resolved.startswith("/"):
        raise OverlayRefused(f"realpath of {path!r} is not one absolute path")
    return resolved[:-1]


def _unwritable(backend: _OverlayBackend, handle: object, path: str) -> None:
    for target in (path, posixpath.dirname(path)):
        writable = backend.candidate_can_write_in_attempt(handle, target)
        if writable is not False:
            raise OverlayRefused(f"{target!r} is writable by the candidate (or this could not be verified: "
                                 f"{writable!r})")


def _place(backend: _OverlayBackend, handle: object, path: str, content: bytes, mode: int) -> PlacedFile:
    _absent(backend, handle, path)
    if not backend.write_root_owned_file_in_attempt(handle, path, content, mode=mode):
        raise OverlayRefused(f"could not write the root-owned {path!r}")
    _unwritable(backend, handle, path)
    digest = hashlib.sha256(content).hexdigest()
    arrived = hashlib.sha256(_output(backend, handle, ["cat", "--", path])).hexdigest()
    if arrived != digest:
        raise OverlayRefused(f"{path!r} holds digest {arrived}, not the placed {digest}")
    return PlacedFile(path, digest)


def _resolves_to(backend: _OverlayBackend, handle: object, name: str, path: str,
                 env: Mapping[str, str]) -> None:
    out = _output(backend, handle, ["sh", "-c", 'command -v -- "$1"', "sh", name], env=env)
    if out != f"{path}\n".encode():
        raise OverlayRefused(f"under the attempt's runtime environment `{name}` resolves to "
                             f"{out.decode(errors='replace').strip()!r}, not the placed {path!r}")


def _resolves_to_in_login_shell(backend: _OverlayBackend, handle: object, name: str, path: str,
                                 env: Mapping[str, str]) -> None:
    """Check 4 again, as a LOGIN shell runs it (#518): the agent's tool calls
    are `bash -lc`, whose PATH comes from /etc/profile, not the inherited one."""
    out = _output(backend, handle, ["bash", "-lc", 'command -v -- "$1"', "bash", name], env=env)
    if out != f"{path}\n".encode():
        raise OverlayRefused(f"in a login shell `{name}` resolves to {out.decode(errors='replace').strip()!r}, "
                             f"not the placed {path!r}")


def install_gh_shim(backend: _OverlayBackend, handle: object, env: Mapping[str, str],
                    source: Path = GH_SHIM_SOURCE) -> PlacedFile:
    """Place the `gh` shim at `GH_PATH`, root-owned and verified."""
    placed = _place(backend, handle, GH_PATH, source.read_bytes(), 0o755)
    _resolves_to(backend, handle, "gh", GH_PATH, env)
    return placed


def guard_config(backend: _OverlayBackend, handle: object) -> dict[str, object]:
    """The realpaths the guard matches ancestors against, resolved now."""
    node = _realpath(backend, handle, NODE)
    codex_js = _realpath(backend, handle, REAL_CODEX)
    natives = [n for n in (_realpath(backend, handle, c) for c in NATIVE_CANDIDATES) if n is not None]
    if node is None or codex_js is None or not natives:
        raise OverlayRefused(f"the real codex could not be located (node={node!r}, codex.js={codex_js!r}, "
                             f"native={natives!r})")
    for path in (REAL_CODEX, node, codex_js, *natives):
        _unwritable(backend, handle, path)
    return {"real": REAL_CODEX, "node": node, "codex_js": codex_js, "native": natives}


def install_codex_guard(backend: _OverlayBackend, handle: object, env: Mapping[str, str],
                        source: Path = CODEX_GUARD_SOURCE) -> dict[str, object]:
    """Place the guard's config and the guard itself, root-owned and
    verified, then prove `codex` resolves to the guard. Returns what a later
    reader consults: both placements and the config."""
    config = guard_config(backend, handle)
    config_bytes = json.dumps(config, sort_keys=True).encode("utf-8") + b"\n"
    placed_config = _place(backend, handle, CODEX_GUARD_CONFIG, config_bytes, 0o644)
    placed_guard = _place(backend, handle, CODEX_GUARD_PATH, source.read_bytes(), 0o755)
    placed_profile = _place(backend, handle, LOGIN_PROFILE_PATH, LOGIN_PROFILE, 0o644)
    _resolves_to(backend, handle, "codex", CODEX_GUARD_PATH, env)
    _resolves_to_in_login_shell(backend, handle, "codex", CODEX_GUARD_PATH, env)
    return {"guard": placed_guard.__dict__, "config": placed_config.__dict__, "login_profile": placed_profile.__dict__,
            "resolved": config}
