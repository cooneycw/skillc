"""#568's remote-delivery fixture, using #434's deterministic git/service seam.

Only controller-owned initial files are passed to host git. After an attempt,
SafeTree/GitDir read its export without running git or candidate code here.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
_BASE = HERE.parent / "flow-auto-necessity" / "builder" / "build.py"
_spec = importlib.util.spec_from_file_location("inventory568_necessity", _BASE)
assert _spec is not None and _spec.loader is not None
necessity = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = necessity
_spec.loader.exec_module(necessity)
CASES = ("inventory",)
GATE_OFFER_EVIDENCE = True
REPOSITORY = necessity.REPOSITORY
host_git = necessity.host_git
MAX_FILES = 1024
MAX_BYTES = 4 * 1024 * 1024


def validate_inputs(repository: Path | None = None) -> None:
    """Bind external controller/fixture dependencies to the builder identity.

    The manifest is inside task.fixture=builder and therefore approval-bound.
    Its hashes protect oracle inputs, never substitute for delivered code.
    """
    repository = HERE.parents[2] if repository is None else repository
    expected = json.loads((HERE / "builder" / "inputs.json").read_text())
    if not isinstance(expected, dict) or not expected:
        raise ValueError("inventory builder dependency population is empty")
    for relative, digest in expected.items():
        if (not isinstance(relative, str) or relative.startswith("/")
                or any(part in ("", ".", "..") for part in relative.split("/"))):
            raise ValueError("unsafe inventory dependency path")
        source = repository / relative
        if any((repository.joinpath(*relative.split("/")[:n])).is_symlink()
               for n in range(1, len(relative.split("/")) + 1)):
            raise ValueError(f"inventory dependency is redirected: {relative}")
        if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f"inventory builder dependency changed: {relative}")

    prefix = f"evals/level3/{HERE.name}/fixture/"
    actual: set[str] = set()
    for source in (repository / prefix).rglob("*"):
        if "__pycache__" in source.parts:
            continue
        if source.is_symlink() or not source.is_dir() and not source.is_file():
            raise ValueError("inventory fixture contains a non-regular entry")
        if source.is_file():
            actual.add(source.relative_to(repository).as_posix())
    if actual != {relative for relative in expected if relative.startswith(prefix)}:
        raise ValueError("inventory fixture population changed")


def build(root: Path, case: str, *, remote_url: str | None = None) -> dict[str, Any]:
    validate_inputs()
    if case not in CASES or not root.is_dir() or any(root.iterdir()):
        raise ValueError("inventory fixture needs a known case and an empty directory")
    seed, remote, repo = root / "seed", root / "remote.git", root / "repo"
    shutil.copytree(HERE / "fixture", seed, ignore=shutil.ignore_patterns("__pycache__"))
    (seed / "README.md").write_bytes((HERE / "goal.md").read_bytes())
    host_git(["init", "--template=", "--initial-branch=main", "--object-format=sha1"], seed)
    host_git(["add", "--all"], seed)
    host_git(["commit", "-q", "-m", "Initial inventory project"], seed, date="2026-10-01T09:00:00+0000")
    sha = host_git(["rev-parse", "HEAD"], seed)
    host_git(["init", "--bare", "--template=", "--initial-branch=main", str(remote)], root)
    host_git(["push", "-q", str(remote), "main:refs/heads/main"], seed)
    host_git(["clone", "-q", "--template=", str(remote), str(repo)], root)
    host_git(["remote", "set-url", "origin", remote_url or str(remote)], repo)
    facts = {"case": case, "base_commit": sha, "base_files": necessity.read_files(seed),
             "remote_refs": {"refs/heads/main": sha}}
    necessity._remove_tree(seed)
    return facts


def declaration(case: str, remote_url: str, facts: dict[str, Any]) -> dict[str, Any]:
    if case not in CASES:
        raise ValueError("unknown inventory case")
    decl = necessity.declaration("twin", remote_url, facts)
    decl["issues"][0].update(title="Add atomic CSV/JSONL inventory import",
                            body=(HERE / "goal.md").read_text(), labels=["enhancement"])
    # Equal delivery authority in every arm; not a live workflow approval receipt.
    decl["authority"] += ["pr.create", "pr.merge", "issue.close"]
    return decl


def capture_snapshot(export_root: Path, facts: dict[str, Any], *,
                     remote: str = ".remote/widget.git", **kwargs: Any) -> dict[str, Any]:
    from skillc import git_snapshot as gs

    git = gs.GitDir(gs.SafeTree(export_root), remote)
    git.check_plain()
    # A missing export/remote is unavailable; a readable remote with no main
    # is an observed non-delivery. Neither borrows a correct local workspace.
    if git.tree.kind(remote) != "dir":
        raise gs.Unreadable("the remote was not exported")
    refs = git.refs()
    main = refs.get("refs/heads/main")
    result: dict[str, Any] = {"remote_refs": refs, "base_commit": facts["base_commit"],
                              "delivery": {"status": "absent" if main is None else "read", "commit": main}}
    if main is None:
        return result
    files = git.commit_files(main)
    if len(files) > MAX_FILES or sum(len(data) for _, data in files.values()) > MAX_BYTES:
        raise gs.Unreadable("remote delivery exceeds the inventory artifact budget")
    result["delivery"]["files"] = {
        path: {"mode": mode, "data_b64": base64.b64encode(data).decode("ascii")}
        for path, (mode, data) in files.items()}
    return result


def post_capture(git: dict[str, Any], backend: Any, handle: object = None) -> dict[str, Any]:
    from skillc import inventory_oracle as oracle

    delivery = git["delivery"]
    try:
        validate_inputs()
    except (OSError, ValueError) as exc:
        delivery.pop("files", None)
        delivery["oracle"] = {"status": "unavailable", "reason": f"oracle inputs changed: {exc}"}
        return git
    if delivery["status"] == "read" and delivery.get("commit") == git.get("base_commit"):
        delivery.pop("files", None)
        delivery["oracle"] = {"status": "not-run", "reason": "initial main was never replaced"}
        return git
    if delivery["status"] == "read":
        files = delivery.pop("files")
        delivery["oracle"] = oracle.run(files, backend, handle, task_root=HERE)
    return git
