#!/usr/bin/env python3
"""Install `/skill-gauntlet` for every Claude Code session (#763, #774).

`make install-skill` writes a REAL COPY of this skillc checkout's
`.claude/skills/skill-gauntlet` to `~/.claude/skills/skill-gauntlet`. It never
writes a symlink: Kyle's deploy stages every entry directly under
`~/.claude/skills` into its session image and fails the whole deploy on a
symlink, or on a directory without SKILL.md (kyle `deploy/operator_config.py`,
lines 396-408). That is why #763's link was replaced (#774).

The copy holds two files the repository never has:

- `.skillc-checkout`, the LOCATOR: the MAIN checkout's path (git
  --git-common-dir, so an install from a linked worktree does not tie sessions
  to a worktree that will be removed). Under $HOME it is written `~/...`, so the
  account name never reaches Kyle's image; only a checkout outside $HOME is
  written as an absolute path. The launcher reads it to find skillc.
- `.skillc-install`, the MARKER: kind, schema and the digest of the copied
  files. No path, no host name. It is how this installer knows a copy is its own.

A `git pull` does NOT update the copy; re-run `make install-skill`. The
launcher warns when the copy differs from the checkout's skill.

**Nothing intermediate is ever visible under the skills directory.** The new
copy is built in `${XDG_CACHE_HOME:-~/.cache}/skillc/install-tmp/`, which must
be on the same device as the skills directory (so each move is one atomic
rename; otherwise refused - never built inside ~/.claude). A replaced copy is
moved OUT to that cache first, then the new one is moved in. Between those two
renames `skill-gauntlet` is briefly ABSENT (stdlib has no atomic exchange):
a Kyle deploy landing there stages no gauntlet, which is not a failure. At no
point is there a temporary name, or a directory without SKILL.md, under skills/.

What it treats as its own: a copy with its marker; an old skillc LINK to this
checkout (#763; migrated to a copy); an UNMARKED copy byte-identical to the
checkout's skill (adopted - kyle-cli-helper's copy, orchestrator ruling). It
refuses and names anything else, and touches nothing.

    python3 scripts/install_skill.py install
    python3 scripts/install_skill.py uninstall

`SKILLC_SKILLS_DIR` overrides the skills directory (default `~/.claude/skills`).

Exit codes: 0 done, or already in the wanted state; 1 refused (named, never
touched); 2 usage (not in a git checkout, no skill, a non-regular file in the
skill, the cache on another device).

Stdlib only: it must run with plain `python3`, before any `uv sync`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "skill-gauntlet"
SKILLS_ENV = "SKILLC_SKILLS_DIR"
LOCATOR, MARKER = ".skillc-checkout", ".skillc-install"
MARKER_KIND, MARKER_SCHEMA = "skillc-skill-install", "1"
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


class Refused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _step(name: str) -> None:
    """A seam the crash controls patch to stop the install between moves."""


def main_checkout(start: Path) -> Path | None:
    done = subprocess.run(["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    common = Path(done.stdout.strip())
    return common.parent if common.name == ".git" else None


def skills_dir() -> Path:
    given = os.environ.get(SKILLS_ENV)
    return Path(given) if given else Path.home() / ".claude" / "skills"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "skillc" / "install-tmp"


def _say(code: int, message: str) -> int:
    print(f"install-skill: {message}", file=sys.stderr if code else sys.stdout)
    return code


def _source() -> tuple[Path, Path]:
    main = main_checkout(Path(__file__).resolve().parent)
    if main is None:
        raise Refused(EXIT_USAGE, "not in a git checkout of skillc; install from a source checkout")
    source = main / ".claude" / "skills" / NAME
    if not (source / "SKILL.md").is_file():
        raise Refused(EXIT_USAGE, f"no {NAME} skill in the main checkout ({source} has no SKILL.md)")
    return main, source


def payload(root: Path) -> dict[str, bytes]:
    """Every file of the skill by relative path, without the locator and the
    marker. Any symlink or special file is refused: the copy holds regular
    files only (Kyle's staging rule), so nothing else may be copied from."""
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath, name)
            mode = path.lstat().st_mode
            rel = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise Refused(EXIT_USAGE, f"{rel} in {root} is not a regular file or directory; "
                                          "the installed copy holds regular files only")
            if stat.S_ISREG(mode) and rel not in (LOCATOR, MARKER):
                files[rel] = path.read_bytes()
    return files


def digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode() + b"\0" + hashlib.sha256(files[rel]).hexdigest().encode() + b"\n")
    return h.hexdigest()


def locator_text(checkout: Path) -> str:
    home = Path.home()
    try:
        return "~/" + checkout.relative_to(home).as_posix() + "\n"
    except ValueError:
        return str(checkout) + "\n"


def _marker(path: Path) -> dict[str, str] | None:
    try:
        lines = (path / MARKER).read_text().splitlines()
    except OSError:
        return None
    fields = dict(line.split(" ", 1) for line in lines if " " in line)
    return fields if fields.get("kind") == MARKER_KIND else None


def _same_device(cache: Path, skills: Path) -> None:
    if os.stat(cache).st_dev != os.stat(skills).st_dev:
        raise Refused(EXIT_USAGE, f"the install cache {cache} is not on the same device as {skills}, so the "
                                  "copy cannot be moved in atomically; set XDG_CACHE_HOME to a directory on "
                                  "that device (it is never built inside the skills directory)")


def _ours(entry: Path, source: Path, files: dict[str, bytes]) -> str:
    """'absent', 'link', 'marked' or 'adopt' - or Refused, naming why."""
    if entry.is_symlink():
        current = Path(os.readlink(entry))
        if current == source:
            return "link"
        raise Refused(EXIT_REFUSED, f"refusing: {entry} is a link to {current}, not to this checkout; "
                                    "remove it yourself if it is stale")
    if not entry.exists():
        return "absent"
    if not entry.is_dir():
        raise Refused(EXIT_REFUSED, f"refusing: {entry} is not a directory; it is not ours to replace")
    if _marker(entry) is not None:
        return "marked"
    try:
        theirs = payload(entry)
    except Refused:
        theirs = None
    if theirs == files and not (entry / LOCATOR).exists():
        return "adopt"  # byte-identical to this checkout's skill: replacing it loses nothing
    raise Refused(EXIT_REFUSED, f"refusing: {entry} exists without skillc's marker and differs from this "
                                "checkout's skill; it is not ours to replace")


def _build(cache: Path, source: Path, files: dict[str, bytes], checkout: Path) -> Path:
    build = Path(tempfile.mkdtemp(prefix="new-", dir=cache)) / NAME
    for rel, data in files.items():
        (build / rel).parent.mkdir(parents=True, exist_ok=True)
        (build / rel).write_bytes(data)
        os.chmod(build / rel, (source / rel).stat().st_mode & 0o777)  # the launcher stays executable
    (build / LOCATOR).write_text(locator_text(checkout))
    (build / MARKER).write_text(f"kind {MARKER_KIND}\nschema {MARKER_SCHEMA}\ndigest {digest(files)}\n")
    return build


def _clear_leftovers(cache: Path) -> None:
    """An earlier install stopped between moves leaves its build or retired
    copy in the CACHE (never under skills/); remove those before building."""
    for stale in cache.iterdir():
        if stale.is_dir() and not stale.is_symlink() and stale.name.startswith(("new-", "old-")):
            shutil.rmtree(stale, ignore_errors=True)


def _retire(entry: Path, cache: Path) -> Path | None:
    """Move our current entry OUT of the skills directory (a link is simply
    removed). Returns where a retired copy went, for removal."""
    if entry.is_symlink():
        entry.unlink()
        return None
    if not entry.exists():
        return None
    retired = Path(tempfile.mkdtemp(prefix="old-", dir=cache)) / NAME
    os.rename(entry, retired)
    return retired.parent


def install() -> int:
    checkout, source = _source()
    files = payload(source)
    skills = skills_dir()
    entry = skills / NAME
    state = _ours(entry, source, files)
    if cache_dir().is_dir():
        _clear_leftovers(cache_dir())  # an earlier install stopped between moves
    if state == "marked":
        current = _marker(entry) or {}
        try:
            located = (entry / LOCATOR).read_text()
        except OSError:
            located = ""
        if current.get("digest") == digest(files) and located == locator_text(checkout) and payload(entry) == files:
            return _say(EXIT_OK, f"already installed: {entry} is a current copy of {source}")
    skills.mkdir(parents=True, exist_ok=True)
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    _same_device(cache, skills)
    _clear_leftovers(cache)
    build = _build(cache, source, files, checkout)
    _step("built")
    retired = _retire(entry, cache) if state != "absent" else None
    _step("retired")
    os.rename(build, entry)
    _step("moved-in")
    shutil.rmtree(build.parent, ignore_errors=True)
    if retired is not None:
        shutil.rmtree(retired, ignore_errors=True)
    verb = {"absent": "installed", "link": "migrated the old link to a copy", "adopt": "adopted the identical copy",
            "marked": "refreshed"}[state]
    return _say(EXIT_OK, f"{verb}: {entry} is a copy of {source} (a git pull does not update it; re-run "
                         "`make install-skill`, and `make uninstall-skill` removes it)")


def uninstall() -> int:
    _checkout, source = _source()
    skills = skills_dir()
    entry = skills / NAME
    if not entry.is_symlink() and not entry.exists():
        return _say(EXIT_OK, f"not installed: {entry} does not exist")
    if entry.is_symlink():
        if Path(os.readlink(entry)) != source:
            return _say(EXIT_REFUSED, f"refusing: {entry} links to {os.readlink(entry)}, not to this checkout")
        entry.unlink()
        return _say(EXIT_OK, f"uninstalled: removed the old link {entry}")
    if not entry.is_dir() or _marker(entry) is None:
        return _say(EXIT_REFUSED, f"refusing: {entry} has no skillc marker; it is not ours to remove")
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    _same_device(cache, skills)
    retired = _retire(entry, cache)
    if retired is not None:
        shutil.rmtree(retired, ignore_errors=True)
    return _say(EXIT_OK, f"uninstalled: removed skillc's copy {entry}")


def main(argv: list[str]) -> int:
    try:
        if argv[1:] == ["install"]:
            return install()
        if argv[1:] == ["uninstall"]:
            return uninstall()
    except Refused as exc:
        return _say(exc.code, str(exc))
    return _say(EXIT_USAGE, "usage: install_skill.py install|uninstall")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
