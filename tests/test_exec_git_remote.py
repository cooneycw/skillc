"""`skillc.exec_git_remote.ExecGitRemote` (#434 PR 2b).

The remote a live attempt pushes to is subject-writable, so the service's
git calls run INSIDE the attempt. These tests drive it through `_HostExec`, a
test double that plays `exec_in_attempt()` on the host over a controller-owned
copy mapped at `/work`: argv, cwd confinement and `env -i` are honoured.

The EQUIVALENCE instrument builds the same fixture twice (the builder pins
dates and identity, so the two are identical) and asks `LocalGitRemote` and
`ExecGitRemote` the same questions, writes included. Its committed control is
a double that perturbs one answer, which the instrument must report.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import exec_git_remote as egr
from skillc import fixture_service as fs
from skillc.backend import ExecuteResult, Limits

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "flow-auto-necessity"
GIT_DIR = "/work/.remote/widget.git"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("flow_auto_necessity_build_egr", TASK / "builder" / "build.py")


@pytest.fixture(autouse=True)
def _umask() -> Iterator[None]:
    previous = os.umask(0o022)
    yield
    os.umask(previous)


class _HostExec:
    """`exec_in_attempt()` played on the host, `/work` mapped to `root`."""

    def __init__(self, root: Path, *, witness_io: bool = True, running: bool = True,
                 perturb: str | None = None) -> None:
        self.root = root
        self.witness_io = witness_io
        self.running = running
        self.perturb = perturb
        self.calls: list[dict[str, Any]] = []

    def _host(self, path: str) -> Path:
        assert path == "/work" or path.startswith("/work/")
        return self.root / path[len("/work/"):] if path != "/work" else self.root

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, cancel: Any = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
        self.calls.append({"argv": list(argv), "cwd": cwd, "env": dict(env or {}), "confine_root": confine_root})
        if not self.running:
            return ExecuteResult(reason="attempt-not-running", exit_code=None)
        assert cwd is not None and confine_root is not None
        real = os.path.realpath(self._host(cwd))
        if os.path.commonpath([real, os.path.realpath(self._host(confine_root))]) != os.path.realpath(
                self._host(confine_root)):
            return ExecuteResult(reason="launch-failed", exit_code=None, error="cwd-confinement-refused")
        proc = subprocess.run(list(argv), cwd=real, env=dict(env or {}), input=stdin, capture_output=True,
                              timeout=30, check=False)
        stdout = proc.stdout
        if self.perturb is not None and self.perturb in argv:
            stdout = stdout.replace(b"a", b"b", 1) or b"perturbed\n"
        return ExecuteResult(reason="exited", exit_code=proc.returncode, stdout=stdout, stderr=proc.stderr)


def _fixture(tmp_path: Path, name: str, case: str = "clean") -> tuple[Path, dict[str, Any]]:
    """The builder's fixture laid out as the attempt sees it: `<root>/repo`
    and `<root>/.remote/widget.git`."""
    root = tmp_path / name
    root.mkdir()
    facts = build.build(root, case, remote_url=GIT_DIR)
    (root / ".remote").mkdir()
    (root / "remote.git").rename(root / ".remote" / "widget.git")
    return root, facts


def _local(root: Path) -> fs.LocalGitRemote:
    return fs.LocalGitRemote(root / ".remote" / "widget.git")


def _exec(root: Path, **kwargs: Any) -> tuple[egr.ExecGitRemote, _HostExec]:
    backend = _HostExec(root, **kwargs)
    return egr.ExecGitRemote(backend, object(), git_dir=GIT_DIR), backend


def _answers(remote: Any, facts: dict[str, Any]) -> dict[str, Any]:
    """Every GitRemote question, reads and writes, in one fixed order."""
    initial, base = facts["commits"][0], facts["base_commit"]
    tree = remote.merge_tree(initial, base)
    made = remote.commit_tree(tree, base, "service merge\n\nbody line", "2026-10-17T12:00:00+0000")
    return {
        "resolve-main": remote.resolve("refs/heads/main"),
        "resolve-missing": remote.resolve("refs/heads/nope"),
        "ancestor-yes": remote.is_ancestor(initial, base),
        "ancestor-no": remote.is_ancestor(base, initial),
        "merge-base": remote.merge_base(initial, base),
        "diff": remote.diff_files(initial, base),
        "commits": remote.commits(initial, base),
        "merge-tree": tree,
        "commit-tree": made,
        "cas-lost": remote.update_ref("refs/heads/main", made, "f" * 40),  # never the ref's value
        "cas-won": remote.update_ref("refs/heads/main", made, base),
        "after": remote.resolve("refs/heads/main"),
        "delete-lost": remote.delete_ref("refs/heads/main", base),
        "delete-won": remote.delete_ref("refs/heads/main", made),
        "gone": remote.resolve("refs/heads/main"),
    }


def _equivalent(tmp_path: Path, case: str, **exec_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    host_root, host_facts = _fixture(tmp_path, f"host-{case}", case)
    exec_root, exec_facts = _fixture(tmp_path, f"exec-{case}", case)
    assert host_facts["base_commit"] == exec_facts["base_commit"]  # the two fixtures are identical
    remote, _ = _exec(exec_root, **exec_kwargs)
    return _answers(_local(host_root), host_facts), _answers(remote, exec_facts)


@pytest.mark.parametrize("case", ["clean", "twin"])
def test_exec_remote_answers_exactly_as_the_host_remote_does(tmp_path: Path, case: str) -> None:
    local, inside = _equivalent(tmp_path, case)
    assert inside == local
    # Not a vacuous agreement: the questions have real, distinct answers.
    assert local["resolve-main"] and local["resolve-missing"] is None
    assert local["cas-won"] and not local["cas-lost"] and local["gone"] is None
    if case == "clean":  # twin has one commit, so its initial IS its base
        assert local["ancestor-yes"] and not local["ancestor-no"]
        assert local["diff"] and local["commits"]


def test_equivalence_control_a_perturbed_answer_is_reported(tmp_path: Path) -> None:
    """The instrument's committed control: one perturbed answer must show."""
    local, inside = _equivalent(tmp_path, "clean", perturb="merge-base")
    assert inside != local
    assert inside["merge-base"] != local["merge-base"]


def test_every_call_runs_inside_the_attempt_under_the_fixed_environment(tmp_path: Path) -> None:
    root, facts = _fixture(tmp_path, "env")
    remote, backend = _exec(root)
    remote.resolve("refs/heads/main")
    remote.commit_tree(facts["base_tree"], facts["base_commit"], "m", "2026-10-17T12:00:00+0000")
    for call in backend.calls:
        assert call["cwd"] == GIT_DIR and call["confine_root"] == "/work"
        assert call["argv"][0] == "git" and "core.hooksPath=/dev/null" in call["argv"]
        assert call["argv"][call["argv"].index("--git-dir") + 1] == "."
        assert {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1"}.items() <= call["env"].items()
        assert not any(k.startswith("GIT_DIR") or k == "GIT_CONFIG_PARAMETERS" for k in call["env"])
    assert backend.calls[-1]["env"]["GIT_AUTHOR_DATE"] == "2026-10-17T12:00:00+0000"


def test_no_host_git_process_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A planted hook and a hostile config in the remote cannot reach the
    host: ExecGitRemote itself never starts a process. Every call goes to the
    backend, which here only records it."""
    root, _ = _fixture(tmp_path, "spy")
    git_dir = root / ".remote" / "widget.git"
    (git_dir / "hooks").mkdir(exist_ok=True)
    (git_dir / "hooks" / "reference-transaction").write_text("#!/bin/sh\ntouch /tmp/owned\n")
    with open(git_dir / "config", "a") as handle:
        handle.write("[core]\n\tfsmonitor = /bin/false\n")

    class _Recording(_HostExec):
        def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits,  # type: ignore[override]
                            cancel: Any = None, stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None,
                            confine_root: str | None = None) -> ExecuteResult:
            self.calls.append({"argv": list(argv)})
            return ExecuteResult(reason="exited", exit_code=0, stdout=b"0" * 40 + b"\n", stderr=b"")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"a host process was started: {args!r}")

    backend = _Recording(root)
    remote = egr.ExecGitRemote(backend, object(), git_dir=GIT_DIR)
    for name in ("run", "Popen", "check_output", "call"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    assert remote.resolve("refs/heads/main") == "0" * 40
    assert remote.update_ref("refs/heads/main", "1" * 40, "0" * 40) is True
    assert len(backend.calls) == 2


def test_a_stopped_attempt_is_refused(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path, "stopped")
    remote, _ = _exec(root, running=False)
    with pytest.raises(egr.RemoteUnavailable, match="attempt-not-running"):
        remote.resolve("refs/heads/main")


def test_a_backend_without_witness_io_is_refused_before_any_exec(tmp_path: Path) -> None:
    """Without witness_io, each exec writes `observations` and a pid marker
    into /work, which the source-unmodified check would read as the subject's."""
    root, _ = _fixture(tmp_path, "no-witness-io")
    remote, backend = _exec(root, witness_io=False)
    with pytest.raises(egr.RemoteUnavailable, match="witness_io"):
        remote.resolve("refs/heads/main")
    assert backend.calls == []


def test_a_git_dir_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    for bad in ("/etc/widget.git", "/work", "/work/../etc", "relative/widget.git", "/work//x", "/workx/a"):
        with pytest.raises(ValueError):
            egr.ExecGitRemote(_HostExec(tmp_path), object(), git_dir=bad)


def test_a_confinement_refusal_in_the_container_is_never_an_answer(tmp_path: Path) -> None:
    """The early lexical check passes, but inside the attempt the git dir is a
    symlink out of the workspace: the confined exec refuses, and so does this."""
    root, _ = _fixture(tmp_path, "symlinked")
    outside = tmp_path / "outside.git"
    (root / ".remote" / "widget.git").rename(outside)
    (root / ".remote" / "widget.git").symlink_to(outside)
    remote, _ = _exec(root)
    with pytest.raises(egr.RemoteUnavailable, match="launch-failed"):
        remote.resolve("refs/heads/main")


@pytest.mark.parametrize("result", [
    ExecuteResult(reason="timeout", exit_code=None),
    ExecuteResult(reason="exited", exit_code=0, stdout=None),
    ExecuteResult(reason="exited", exit_code=0, stdout=b"x", stdout_truncated=True),
    ExecuteResult(reason="exited", exit_code=0, stdout=b"x", stdout_incomplete=True),
    ExecuteResult(reason="exited", exit_code=0, stdout=b"x", stderr_incomplete=True),
])
def test_incomplete_output_is_refused(tmp_path: Path, result: ExecuteResult) -> None:
    class _Fixed(_HostExec):
        def exec_in_attempt(self, *args: Any, **kwargs: Any) -> ExecuteResult:  # type: ignore[override]
            return result

    remote = egr.ExecGitRemote(_Fixed(tmp_path), object(), git_dir=GIT_DIR)
    with pytest.raises(egr.RemoteUnavailable):
        remote.resolve("refs/heads/main")


def test_a_git_failure_is_never_a_no(tmp_path: Path) -> None:
    """Exit 1 is git's documented no; exit 128 is a failure to look."""
    class _Exit(_HostExec):
        def exec_in_attempt(self, *args: Any, **kwargs: Any) -> ExecuteResult:  # type: ignore[override]
            return ExecuteResult(reason="exited", exit_code=128, stdout=b"", stderr=b"fatal: bad object")

    remote = egr.ExecGitRemote(_Exit(tmp_path), object(), git_dir=GIT_DIR)
    with pytest.raises(egr.RemoteUnavailable, match="exit 128"):
        remote.is_ancestor("a" * 40, "b" * 40)
    with pytest.raises(egr.RemoteUnavailable):
        remote.merge_tree("a" * 40, "b" * 40)
