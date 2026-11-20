"""#817: the default trigger-socket directory is per uid, the refusal is
exactly as strict, and a refusal reaches the protocol report as a closed,
path-free reason class.

Parent-compatible on purpose: this module imports only names the parent
already has, so on the parent it fails by assertion (a shared default name,
no reason class), not by ImportError.

Honest limit: an unprivileged test cannot own a directory as a second uid.
The two-uid control therefore fakes the SECOND identity's uid for path
selection and validation, which is exactly the parent's failure (the second
identity met the first one's directory). The real second identity on a real
daemon is the runner VM's root lane."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
from test_wave_protocol_run import World, short  # noqa: F401 - short is a fixture

from skillc import docker_backend as db
from skillc import docker_wave as wave
from skillc.backend import BackendUnavailable

REAL = os.getuid()
OTHER = REAL + 4242


def _default(monkeypatch: pytest.MonkeyPatch, root: Path, uid: int) -> Path:
    """The default as an identity with `uid` would compute it. On the parent
    there is no function, so the module constant stands in (shared name)."""
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    monkeypatch.setattr(db.os, "getuid", lambda: uid)
    make = getattr(db, "default_trigger_socket_dir", None)
    return make() if make is not None else root / db.DEFAULT_TRIGGER_SOCKET_DIR.name


def _refusal(path: Path, monkeypatch: pytest.MonkeyPatch, uid: int) -> BackendUnavailable:
    monkeypatch.setattr(db.os, "getuid", lambda: uid)
    with pytest.raises(BackendUnavailable) as caught:
        db._ensure_private_trigger_dir(path)
    monkeypatch.setattr(db.os, "getuid", lambda: REAL)
    return caught.value


def test_the_default_names_this_process_uid() -> None:
    assert db.DEFAULT_TRIGGER_SOCKET_DIR.name == f"skillc-trigger-{REAL}"


def test_two_uids_each_get_a_usable_default(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    first = _default(monkeypatch, tmp_path, REAL)
    db._ensure_private_trigger_dir(first)  # the first identity creates its own
    second = _default(monkeypatch, tmp_path, OTHER)
    assert second != first
    db._ensure_private_trigger_dir(second)  # parent: meets the first's dir -> refused
    monkeypatch.setattr(db.os, "getuid", lambda: REAL)
    db._ensure_private_trigger_dir(first)  # re-entry on an existing own dir still passes
    assert (first.stat().st_mode & 0o777, second.stat().st_mode & 0o777) == (0o700, 0o700)


def test_a_foreign_owned_explicit_dir_is_still_refused(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "explicit"
    path.mkdir(mode=0o700)
    refused = _refusal(path, monkeypatch, OTHER)
    assert f"owned by uid {REAL}, not this process's own uid {OTHER}" in str(refused)
    assert getattr(refused, "reason_class", None) == "trigger-dir-foreign-owner"


@pytest.mark.parametrize("shape,reason", [("mode", "trigger-dir-mode"),
                                          ("file", "trigger-dir-not-directory")])
def test_every_refusal_carries_its_closed_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 shape: str, reason: str) -> None:
    path = tmp_path / "explicit"
    if shape == "mode":
        path.mkdir(mode=0o700)
        path.chmod(0o750)
    else:
        path.write_text("")
    assert getattr(_refusal(path, monkeypatch, REAL), "reason_class", None) == reason


def _report(tmp_path: Path, short_dir: Path, monkeypatch: pytest.MonkeyPatch,
            exc: BaseException) -> dict[str, Any]:
    world = World(tmp_path / "w", short_dir, monkeypatch)

    def fail(self: Any) -> None:
        raise exc

    monkeypatch.setattr(wave.DockerWave, "prepare", fail)
    report: dict[str, Any] = world.run.run()
    return report


def test_the_reason_reaches_the_report_without_path_or_uid(
        tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    path = tmp_path / "explicit"
    path.mkdir(mode=0o700)
    refused = _refusal(path, monkeypatch, OTHER)
    unknown = _report(tmp_path, short, monkeypatch, refused)["unknown"]
    assert f"protocol-step-unavailable:{type(refused).__name__}:trigger-dir-foreign-owner" \
        in unknown
    assert not any(str(path) in u or str(OTHER) in u for u in unknown)


def test_an_unlisted_reason_attribute_is_not_reported(
        tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Only a closed reason passes: a free-text attribute on some other
    exception is dropped, leaving the bare class as before."""
    forged = BackendUnavailable("x")
    forged.reason_class = "/private/path"  # type: ignore[attr-defined]
    unknown = _report(tmp_path, short, monkeypatch, forged)["unknown"]
    assert "protocol-step-unavailable:BackendUnavailable" in unknown
    assert not any("/private/path" in u for u in unknown)
