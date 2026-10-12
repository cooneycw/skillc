"""Committed inputs distinguishing capture projection from a raw tree hash."""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from skillc import trial
from skillc import witness_capture as wc
from skillc.materialize import tree_digest


def _population(root: Path) -> None:
    root.mkdir(exist_ok=True)
    for name, data in {"main.py": b"print('ok')\n", "observations": b"candidate-owned",
                       ".skillc-exec-pid-candidate": b"also candidate-owned", "run": b"echo ok\n",
                       "secret.pem": b"do not capture"}.items():
        (root / name).write_bytes(data)
    (root / "run").chmod(0o700)
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("excluded")
    (root / "link").symlink_to("main.py")
    os.mkfifo(root / "pipe")


def test_projection_matches_actual_capture_and_reconstructed_grading_files(tmp_path: Path) -> None:
    from test_verify import _plan

    experiment, attempt_id = _plan(trial.open_store(tmp_path / "store", forbidden=[]))
    base = tmp_path / "base"
    base.mkdir()
    workspace = trial.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    _population(workspace)
    stop = trial.run_attempt(experiment, attempt_id, [sys.executable, "-c", "pass"],
                             cwd=workspace, timeout=5, grace=0.2)
    assert stop["confirmed"] is True
    projected = wc.capture_digest(workspace)
    manifest = trial.capture(experiment, attempt_id, workspace)
    assert not manifest["capture_failures"]
    files = [(str(a["path"]), experiment.object_path(str(a["digest"])).read_bytes(), a["mode"] == "x")
             for a in trial.frozen_artifacts(experiment, attempt_id)]
    assert {p for p, _, _ in files} == {"main.py", "observations", ".skillc-exec-pid-candidate", "run"}
    assert projected == wc.files_digest(files)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    for path, data, executable in files:
        (frozen / path).write_bytes(data)
        (frozen / path).chmod(0o755 if executable else 0o644)
    assert projected == tree_digest(frozen)
    trial.cleanup_workspace(experiment, attempt_id)


@pytest.mark.parametrize("change", ["content", "add", "delete", "mode", "observations", "pid-name"])
def test_candidate_changes_change_the_projected_identity(tmp_path: Path, change: str) -> None:
    root = tmp_path / "export"
    _population(root)
    before = wc.capture_digest(root)
    if change == "delete":
        (root / "main.py").unlink()
    elif change == "mode":
        (root / "main.py").chmod(0o700)
    else:
        path = {"content": "main.py", "add": "new-file", "observations": "observations",
                "pid-name": ".skillc-exec-pid-candidate"}[change]
        (root / path).write_text("changed")
    assert wc.capture_digest(root) != before


@pytest.mark.parametrize("limits", [trial.Limits(max_files=1), trial.Limits(max_file_bytes=1),
                                     trial.Limits(max_total_bytes=1)])
def test_partial_projection_is_refused(tmp_path: Path, limits: trial.Limits) -> None:
    _population(tmp_path)
    with pytest.raises(wc.Refused, match="incomplete"):
        wc.capture_digest(tmp_path, limits=limits)


@pytest.mark.parametrize("fault", ["read", "walk", "object-write", "cleanup"])
def test_projection_failures_refuse_and_remove_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    root = tmp_path / "export"
    _population(root)
    real_temp = wc.tempfile.TemporaryDirectory
    scratch: list[Path] = []

    @contextmanager
    def temporary(*, prefix: str) -> Iterator[str]:
        with real_temp(prefix=prefix) as directory:
            scratch.append(Path(directory))
            yield directory
        if fault == "cleanup":
            raise OSError("cleanup could not be confirmed")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("injected IO fault")

    monkeypatch.setattr(wc.tempfile, "TemporaryDirectory", temporary)
    if fault != "cleanup":
        monkeypatch.setattr(trial, {"read": "_read_bounded", "walk": "_walk", "object-write": "_put_object"}[fault], fail)
    with pytest.raises(wc.Refused):
        wc.capture_digest(root)
    assert scratch and all(not path.exists() for path in scratch)


@pytest.mark.parametrize("kind", ["empty", "excluded-only", "symlink-root", "not-directory"])
def test_empty_or_invalid_projection_refuses(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "export"
    if kind == "not-directory":
        root.write_text("file")
    elif kind == "symlink-root":
        root.symlink_to(tmp_path, target_is_directory=True)
    else:
        root.mkdir()
        if kind == "excluded-only":
            (root / "secret.pem").write_text("secret")
    with pytest.raises(wc.Refused):
        wc.capture_digest(root)


def test_scratch_dedup_and_corrupted_object_are_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    (root / "a").write_bytes(b"same")
    (root / "b").write_bytes(b"same")
    assert wc.capture_digest(root) == wc.files_digest([("a", b"same", False), ("b", b"same", False)])
    original = trial._put_object

    def corrupt(store: Path, data: bytes) -> str:
        digest = original(store, data)
        target = store / trial.OBJECTS / digest.removeprefix("sha256:")
        target.chmod(0o600)
        target.write_bytes(b"wrong bytes")
        return digest

    monkeypatch.setattr(trial, "_put_object", corrupt)
    with pytest.raises(wc.Refused):
        wc.capture_digest(root)


def test_files_digest_rejects_empty_and_duplicate_populations() -> None:
    with pytest.raises(wc.Refused, match="empty"):
        wc.files_digest([])
    with pytest.raises(wc.Refused, match="duplicate"):
        wc.files_digest([("a", b"one", False), ("a", b"two", False)])


def test_group_execute_bit_does_not_change_owner_mode(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_bytes(b"data")
    target.chmod(0o644)
    before = wc.capture_digest(tmp_path)
    target.chmod(0o654)
    assert wc.capture_digest(tmp_path) == before
    assert before == wc.files_digest([("file", b"data", False)])
