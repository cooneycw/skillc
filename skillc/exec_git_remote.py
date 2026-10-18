"""A `GitRemote` (#276) that runs git INSIDE a live attempt's containment
(#434 PR 2b, the hard item's "service decisions DURING the attempt").

A live flow:auto attempt pushes to a remote that lives in its own container
(`/work/.remote/widget.git`), so that remote is SUBJECT-WRITABLE. Running git
against it as the controller would run subject-chosen code as the controller
(a merge driver, a hook, a `commondir` redirection: `LocalGitRemote`'s own
contract). So this remote never runs git on the host. Every call goes through
`backend.exec_in_attempt()`:

- as the CANDIDATE identity (a bare `docker exec`, the image's own user), so a
  hostile config can only ever run code as the subject itself;
- with `cwd` the remote's git dir and `confine_root` the workspace (#338): the
  in-container wrapper opens the directory once and refuses one that is not
  under the root;
- under a FIXED environment (`env -i`): no inherited `GIT_*`, no global or
  system config, replacement objects off, and `core.hooksPath=/dev/null` /
  `core.fsmonitor=false` on the command line.

WHAT IT ANSWERS IS SUBJECT-INFLUENCED. The subject owns the remote's files and
can make git inside its own container say anything. These answers steer the
service's decisions during the attempt (merge, CAS, diff), never grading:
post-stop facts come from `git_snapshot`'s pure-Python reader over an exported
copy, which interprets raw bytes. That is the detection-only bound #436 exists
to remove.

REFUSALS, never guessed answers:
- the backend is not in `witness_io` mode: without it `exec_in_attempt()`
  writes each call's stdout back into the workspace as `observations` and its
  pid marker under `/work`, so the controller's own git calls would plant files
  the source-unmodified check then reads as the subject's;
- the attempt is not running (`attempt-not-running`): after the agent stops,
  nothing can be exec'd, and `SnapshotGitRemote` takes over;
- the confinement wrapper refused or never reported (`launch-failed`);
- a timeout, a cancel, or output that is truncated or incomplete.

Each raises `RemoteUnavailable`. The service records it as an error event and
the attempt's channel as unavailable.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .backend import ExecuteResult, Limits
from .fixture_service import SERVICE_IDENTITY

#: The fixed environment every in-containment git call runs under - the same
#: allowlist `fixture_service._git_environment` uses for the host remote, with
#: HOME pointed at a path git can read nothing from.
_ENVIRONMENT: Mapping[str, str] = {
    "PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent", "XDG_CONFIG_HOME": "/nonexistent",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    "GIT_ALLOW_PROTOCOL": "file", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ATTR_NOSYSTEM": "1",
}
_LIMITS = Limits(timeout=30.0, grace=2.0, max_captured_stdout_bytes=8 * 1024 * 1024,
                 max_captured_stderr_bytes=64 * 1024)


class RemoteUnavailable(RuntimeError):
    """The in-containment git call could not be made, or did not finish with
    complete output. Never an answer."""


class _ExecBackend(Protocol):
    @property
    def witness_io(self) -> bool: ...

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits,
                        cancel: Any = None, stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None,
                        confine_root: str | None = None) -> ExecuteResult: ...


def _plain_absolute(path: str) -> bool:
    return (path.startswith("/") and "\0" not in path and "//" not in path
            and not any(part in (".", "..") for part in path.split("/")[1:]))


class ExecGitRemote:
    """`fixture_service.GitRemote` over a bare repository inside the attempt.

    `git_dir` must be absolute, lexically plain and strictly below
    `confine_root`. That is checked here, early; the guarantee is the
    in-container confinement (`exec_in_attempt`'s #338 wrapper)."""

    def __init__(self, backend: _ExecBackend, handle: object, *, git_dir: str,
                 confine_root: str = "/work", limits: Limits = _LIMITS) -> None:
        if not _plain_absolute(git_dir) or not _plain_absolute(confine_root):
            raise ValueError(f"git_dir and confine_root must be absolute and plain: {git_dir!r}, {confine_root!r}")
        if posixpath.commonpath([git_dir, confine_root]) != confine_root or git_dir == confine_root:
            raise ValueError(f"git_dir {git_dir!r} is not strictly below confine_root {confine_root!r}")
        self.backend = backend
        self.handle = handle
        self.git_dir = git_dir
        self.confine_root = confine_root
        self.limits = limits

    def _run(self, *args: str, stdin: bytes | None = None,
             extra_env: Mapping[str, str] | None = None) -> ExecuteResult:
        if not getattr(self.backend, "witness_io", False):
            raise RemoteUnavailable("the backend is not in witness_io mode; an exec would write into the workspace")
        argv = ["git", "-c", f"user.name={SERVICE_IDENTITY[0]}", "-c", f"user.email={SERVICE_IDENTITY[1]}",
                "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                "--git-dir", ".", *args]
        env = {**_ENVIRONMENT, **(extra_env or {})}
        result = self.backend.exec_in_attempt(self.handle, argv, self.limits, stdin=stdin, cwd=self.git_dir,
                                              env=env, confine_root=self.confine_root)
        if result.reason != "exited" or result.exit_code is None:
            raise RemoteUnavailable(f"git {args[0]} did not run to completion in the attempt: "
                                    f"reason={result.reason!r}, error={result.error!r}")
        if (result.stdout is None or result.stdout_truncated or result.stdout_incomplete
                or result.stderr_incomplete):
            raise RemoteUnavailable(f"git {args[0]}: the attempt's output is missing or incomplete")
        return result

    @staticmethod
    def _answer(result: ExecuteResult, what: str) -> bool:
        """Exit 0 is yes, exit 1 is git's documented no; anything else is a
        failure to look, never an answer (`LocalGitRemote._answer`)."""
        if result.exit_code in (0, 1):
            return result.exit_code == 0
        raise RemoteUnavailable(f"git {what} failed (exit {result.exit_code}): "
                                f"{(result.stderr or b'').decode(errors='replace')}")

    def _checked(self, *args: str, stdin: bytes | None = None,
                 extra_env: Mapping[str, str] | None = None) -> str:
        result = self._run(*args, stdin=stdin, extra_env=extra_env)
        if result.exit_code != 0:
            raise RemoteUnavailable(f"git {args[0]} failed (exit {result.exit_code}): "
                                    f"{(result.stderr or b'').decode(errors='replace')}")
        assert result.stdout is not None
        return result.stdout.decode()

    def resolve(self, ref: str) -> str | None:
        result = self._run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        assert result.stdout is not None
        return (result.stdout.decode().strip() or None) if self._answer(result, "rev-parse") else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._answer(self._run("merge-base", "--is-ancestor", ancestor, descendant),
                            "merge-base --is-ancestor")

    def merge_base(self, a: str, b: str) -> str | None:
        result = self._run("merge-base", a, b)
        assert result.stdout is not None
        return (result.stdout.decode().strip() or None) if self._answer(result, "merge-base") else None

    def diff_files(self, base: str, head: str) -> list[dict[str, Any]]:
        out = self._checked("diff", "--numstat", "--no-renames", "-z", base, head)
        files = []
        for entry in filter(None, out.split("\0")):
            added, deleted, path = entry.split("\t", 2)
            files.append({"path": path, "additions": int(added) if added != "-" else 0,
                          "deletions": int(deleted) if deleted != "-" else 0})
        return files

    def commits(self, base: str, head: str) -> list[dict[str, Any]]:
        out = self._checked("log", "--reverse", "-z", "--format=%H%x1f%s%x1f%b", f"{base}..{head}")
        result = []
        for entry in filter(None, (e.lstrip("\n") for e in out.split("\0"))):
            oid, headline, body = entry.split("\x1f", 2)
            result.append({"oid": oid, "messageHeadline": headline, "messageBody": body.rstrip("\n")})
        return result

    def merge_tree(self, base: str, head: str) -> str | None:
        result = self._run("merge-tree", "--write-tree", "--no-messages", base, head)
        assert result.stdout is not None
        if result.exit_code == 0:
            return result.stdout.decode().split("\n", 1)[0].strip()
        if result.exit_code == 1:
            return None  # conflicted
        raise RemoteUnavailable(f"git merge-tree failed: {(result.stderr or b'').decode(errors='replace')}")

    def commit_tree(self, tree: str, parent: str, message: str, date: str) -> str:
        return self._checked("commit-tree", tree, "-p", parent, "-F", "-", stdin=message.encode(),
                             extra_env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}).strip()

    def update_ref(self, ref: str, new: str, old: str) -> bool:
        """`False` only when the CAS genuinely lost; any other failure raises
        (`LocalGitRemote.update_ref`)."""
        result = self._run("update-ref", ref, new, old)
        if result.exit_code == 0:
            return True
        if self.resolve(ref) != old:
            return False
        raise RemoteUnavailable(f"git update-ref failed with {ref} still at {old}: "
                                f"{(result.stderr or b'').decode(errors='replace')}")

    def delete_ref(self, ref: str, old: str) -> bool:
        return self._run("update-ref", "-d", ref, old).exit_code == 0
