"""Tests for the optional managed-container backend (#64): the client half
only (`skillc/managed_backend.py`), against a test-only stub
(`tests/fixtures/managed-backend/stub_server.py`) - never a real platform.
Conformance through a REAL platform-created container remains owed
(`docs/specs/evaluation-facility/support-matrix.md`); nothing here claims
otherwise.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from skillc import leak
from skillc import managed_backend as mb
from skillc.backend import BackendUnavailable, Confirmation, Limits

STUB_SERVER = Path(__file__).resolve().parent / "fixtures" / "managed-backend" / "stub_server.py"
PROTOCOL_MD = (
    Path(__file__).resolve().parent.parent / "docs" / "specs" / "evaluation-facility"
    / "managed-backend-protocol.md"
)

#: A private (RFC 1918) address `leak.scan_text`'s own `private-ip` class
#: catches - a stand-in for a platform-specific identifier leaking through
#: this backend's own output. Built from two literal fragments, never one
#: contiguous string: this repo's own whole-tree `skillc leak-check` (issue
#: #63, `make verify`) would otherwise flag THIS FILE's source text as a
#: real finding, same as it already flags `tests/test_leak.py`'s planted
#: examples - the same reason that file is excluded there. Splitting the
#: literal keeps this file in the ordinary scanned population while the
#: runtime-joined value still exercises `leak.scan_text` exactly the same.
PLANTED_IDENTIFIER = "10." + "55.66.77"

#: API-key-shaped (`leak.py`'s `API_KEY_RE`: `sk-(ant-)?` + 20+ opaque
#: chars), so both the direct substring check AND a real `skillc leak-check`
#: run treat a leak of this value as a genuine finding. Split for the same
#: reason as `PLANTED_IDENTIFIER` above.
PLANTED_CREDENTIAL = "sk-ant-" + "testcred0123456789abcdef0123456789"


@dataclasses.dataclass
class _Stub:
    socket_path: Path
    state_dir: Path

    def set_control(self, **fields: object) -> None:
        (self.state_dir / "control.json").write_text(json.dumps(fields), encoding="utf-8")

    def requests(self) -> list[dict[str, object]]:
        path = self.state_dir / "requests.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def backend(self, *, credential: str | None = None, timeout: float = 5.0) -> mb.ManagedBackend:
        return mb.ManagedBackend(socket_path=str(self.socket_path), credential=credential, timeout=timeout)


@pytest.fixture
def stub(tmp_path: Path):
    socket_path = tmp_path / "stub.sock"
    state_dir = tmp_path / "stub-state"
    proc = subprocess.Popen([sys.executable, str(STUB_SERVER), "--socket", str(socket_path), "--state", str(state_dir)])
    deadline = time.monotonic() + 5.0
    try:
        while not socket_path.exists():
            if proc.poll() is not None:
                raise RuntimeError(f"stub server exited early with code {proc.returncode}")
            if time.monotonic() > deadline:
                raise RuntimeError("stub server did not start listening in time")
            time.sleep(0.02)
        yield _Stub(socket_path=socket_path, state_dir=state_dir)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# --------------------------------------------------------------------------
# Platform absent (#64 plan item: "the static check, selftest and the
# reference path all work without it")
# --------------------------------------------------------------------------


def test_describe_never_raises_when_no_socket_is_configured() -> None:
    backend = mb.ManagedBackend(socket_path=None)
    description = backend.describe()
    assert description.version == "unreachable"
    assert description.isolation == ()


def test_prepare_refuses_rather_than_falling_back_when_no_socket_is_configured() -> None:
    backend = mb.ManagedBackend(socket_path=None)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-absent")


def test_exec_in_attempt_is_unconditionally_unsupported() -> None:
    """#269: protocol version 1 carries no `exec_in_attempt` operation, so
    this refuses without ever touching the socket - no stub server needed,
    since no request is sent at all. The gate-execution witness reads this
    `reason` as "the whole mechanism is unavailable for this attempt",
    never retrying."""
    backend = mb.ManagedBackend(socket_path=None)
    handle = mb._Handle(attempt_id="a-unsupported", token="t")
    result = backend.exec_in_attempt(handle, ["lint"], Limits(timeout=1.0))
    assert result.reason == "unsupported"
    assert result.exit_code is None


def test_module_names_no_platform_and_docker_backend_does_not_import_it() -> None:
    """Platform-neutral by construction (#64 review): nothing under
    `skillc/` may name, import or assume any particular platform. The
    protocol PAGE names one implementer as a pointer (its "Implementers"
    section); this Python module never does."""
    source = Path(mb.__file__).read_text(encoding="utf-8")
    assert "kyle" not in source.lower()
    from skillc import docker_backend

    assert "managed_backend" not in Path(docker_backend.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Full lifecycle through the stub
# --------------------------------------------------------------------------


def test_full_lifecycle_through_the_stub(stub: _Stub, tmp_path: Path) -> None:
    backend = stub.backend()
    description = backend.describe()
    assert description.name == "managed-backend-stub"

    handle = backend.prepare("a-lifecycle")
    readiness = backend.install(handle, {"SKILL.md": b"# hello\n"})
    assert readiness["declared"] == 1
    assert readiness["installed"] == 1

    result = backend.execute(handle, [sys.executable, "-c", "print('hi')"], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0

    assert backend.confirm_stopped(handle) == Confirmation.CONFIRMED

    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "observations").read_bytes().strip() == b"hi"
    assert (dest / "SKILL.md").read_bytes() == b"# hello\n"

    backend.destroy(handle)
    assert backend.confirm_absent(handle) == Confirmation.CONFIRMED


# --------------------------------------------------------------------------
# Neutral-identity leak control (#63) - red/green pair
# --------------------------------------------------------------------------


def test_a_neutral_identity_produces_no_leak_finding(stub: _Stub) -> None:
    backend = stub.backend()
    handle = backend.prepare("a-neutral")
    readiness = backend.install(handle, {})
    text = f"{handle}\n{readiness['image_digest']}\n"
    findings = list(leak.scan_text(text, leak.load_denylist(None), host_paths=leak.default_host_paths()))
    assert findings == []


def test_a_leaking_platform_identity_is_caught_by_leak_check(stub: _Stub) -> None:
    """Red case (#64 plan item 1): proves the CHECK can fail, not that any
    real platform complies - the protocol page's own "Handle rule" says
    neutrality is the platform's obligation, this backend only provides the
    instrument. Seeds a private-IP-shaped identifier into the stub's `handle`
    and `install()` response."""
    stub.set_control(leak_value=PLANTED_IDENTIFIER)
    backend = stub.backend()
    handle = backend.prepare("a-leaking")
    readiness = backend.install(handle, {})
    assert PLANTED_IDENTIFIER in str(handle)  # sanity: the plant landed
    text = f"{handle}\n{readiness['image_digest']}\n"
    findings = list(leak.scan_text(text, leak.load_denylist(None), host_paths=leak.default_host_paths()))
    kinds = {kind for _lineno, kind, _detail in findings}
    assert "private-ip" in kinds


# --------------------------------------------------------------------------
# Credential hook - red case (#64 review item 3)
# --------------------------------------------------------------------------


def test_credential_reaches_only_the_prepare_request_and_never_leaks(stub: _Stub, tmp_path: Path) -> None:
    """Red case: a planted token value must not appear in any record,
    report or exception text a full stub lifecycle produces, and a real
    `skillc leak-check` over the produced export directory must be clean."""
    stub.set_control(require_credential=PLANTED_CREDENTIAL)
    backend = mb.ManagedBackend(socket_path=str(stub.socket_path), credential=PLANTED_CREDENTIAL, timeout=5.0)

    assert PLANTED_CREDENTIAL not in repr(backend)  # dataclass field(repr=False)

    handle = backend.prepare("a-credential")
    readiness = backend.install(handle, {"SKILL.md": b"ok"})
    result = backend.execute(handle, [sys.executable, "-c", "print('hi')"], Limits(timeout=5))
    stopped = backend.confirm_stopped(handle)
    dest = tmp_path / "export"
    backend.export(handle, dest)
    backend.destroy(handle)
    absent = backend.confirm_absent(handle)

    assert stopped == Confirmation.CONFIRMED
    assert absent == Confirmation.CONFIRMED

    produced = "\n".join([
        repr(backend), str(handle), json.dumps(readiness, default=str),
        repr(result), str(stopped), str(absent),
    ])
    assert PLANTED_CREDENTIAL not in produced

    scanned = leak.scan_path(dest, leak.load_denylist(None), host_paths=leak.default_host_paths())
    assert scanned.findings == []

    from skillc import cli

    assert cli.main(["leak-check", str(dest)]) == 0

    logged = stub.requests()
    carrying = [r for r in logged if r.get("credential") == PLANTED_CREDENTIAL]
    assert len(carrying) == 1
    assert carrying[0]["op"] == "prepare"
    for entry in logged:
        if entry is not carrying[0]:
            assert "credential" not in entry


# --------------------------------------------------------------------------
# The UNKNOWN states (#64 review item 4)
# --------------------------------------------------------------------------


def test_a_dropped_connection_during_confirm_stopped_is_unknown_never_confirmed(stub: _Stub) -> None:
    backend = stub.backend()
    handle = backend.prepare("a-drop-stopped")
    backend.install(handle, {})
    stub.set_control(drop_ops=["confirm_stopped"])
    assert backend.confirm_stopped(handle) == Confirmation.UNKNOWN


def test_a_dropped_connection_during_confirm_absent_is_unknown_never_absent(stub: _Stub) -> None:
    """Red case named directly by review: the stub drops the connection
    mid-`confirm_absent`, and the result must be UNKNOWN, not a guessed
    `CONFIRMED` (which would read as "definitely gone" on a call that never
    actually got an answer)."""
    backend = stub.backend()
    handle = backend.prepare("a-drop-absent")
    backend.install(handle, {})
    stub.set_control(drop_ops=["confirm_absent"])
    assert backend.confirm_absent(handle) == Confirmation.UNKNOWN


def test_prepare_refused_by_the_platform_raises_backend_unavailable(stub: _Stub) -> None:
    stub.set_control(refuse_ops=["prepare"])
    backend = stub.backend()
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-refused")


# --------------------------------------------------------------------------
# Doc/code parity (#64 review item 2: "a test parses the page's field table
# and asserts the client's request builder emits only those keys")
# --------------------------------------------------------------------------


def _parse_field_table(markdown: str, heading: str) -> dict[str, set[tuple[str, bool]]]:
    lines = markdown.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    rows: dict[str, set[tuple[str, bool]]] = {}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        op, field_name, required_cell = cells[0], cells[1], cells[2]
        if op in ("", "Op") or set(op) <= {"-"}:
            continue
        rows.setdefault(op, set()).add((field_name, required_cell.lower() == "yes"))
    return rows


def test_client_field_tables_match_the_published_protocol_page() -> None:
    markdown = PROTOCOL_MD.read_text(encoding="utf-8")
    request_rows = _parse_field_table(markdown, "### Request fields")
    response_rows = _parse_field_table(markdown, "### Response fields")

    doc_request_fields = {op: frozenset(f for f, _r in fields) for op, fields in request_rows.items()}
    assert doc_request_fields == mb.REQUEST_FIELDS

    doc_response_fields = {op: frozenset(f for f, _r in fields) for op, fields in response_rows.items()}
    doc_response_fields.setdefault("destroy", frozenset())  # documented in prose, not the table
    assert doc_response_fields == mb.RESPONSE_RESULT_FIELDS

    doc_required = {op: frozenset(f for f, req in fields if req) for op, fields in response_rows.items()}
    doc_required.setdefault("destroy", frozenset())
    assert doc_required == mb.RESPONSE_REQUIRED_FIELDS


def test_every_request_the_client_sends_uses_only_documented_fields(stub: _Stub, tmp_path: Path) -> None:
    markdown = PROTOCOL_MD.read_text(encoding="utf-8")
    doc_request_fields = {
        op: frozenset(f for f, _r in fields) for op, fields in _parse_field_table(markdown, "### Request fields").items()
    }
    backend = stub.backend(credential=None)
    handle = backend.prepare("a-fields")
    backend.install(handle, {"SKILL.md": b"x"})
    backend.execute(handle, [sys.executable, "-c", "pass"], Limits(timeout=5), stdin=b"in")
    backend.confirm_stopped(handle)
    backend.export(handle, tmp_path / "export")
    backend.destroy(handle)
    backend.confirm_absent(handle)

    for logged in stub.requests():
        op = str(logged["op"])
        allowed = doc_request_fields[op]
        assert set(logged) <= allowed, f"{op} sent undocumented fields: {set(logged) - allowed}"
