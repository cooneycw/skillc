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

import contextlib
import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

NAME = "skill-gauntlet"
SKILLS_ENV = "SKILLC_SKILLS_DIR"
LOCATOR, MARKER = ".skillc-checkout", ".skillc-install"
#: Files the installer writes into the copy; never part of the skill's payload.
INSTALL_FILES = (LOCATOR, MARKER)
MARKER_KIND, MARKER_SCHEMA = "skillc-skill-install", "1"
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
GIT_TIMEOUT = 60  # seconds for `git ls-files`: a stalled git refuses, never hangs the install
LOCK_WAIT_ENV, LOCK_WAIT = "SKILLC_INSTALL_LOCK_WAIT", 30.0


class Refused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _step(name: str) -> None:
    """A seam the crash controls patch to stop the install between moves."""


def _git_env() -> dict[str, str]:
    """The environment for every installer git call: the caller's GIT_*
    variables (GIT_DIR, GIT_INDEX_FILE, ...) never pick the checkout or its
    tracked files (#738, counter-model review)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def main_checkout(start: Path) -> Path | None:
    done = subprocess.run(["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True, check=False, env=_git_env())
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
        raise Refused(EXIT_USAGE, "not in a git checkout of skillc: installing from an export (such as `git "
                                  "archive`, with no .git) is not supported; install from a git checkout")
    source = main / ".claude" / "skills" / NAME
    if not (source / "SKILL.md").is_file():
        raise Refused(EXIT_USAGE, f"no {NAME} skill in the main checkout ({source} has no SKILL.md)")
    return main, source


def payload(root: Path) -> dict[str, bytes]:
    """Every file of the skill by relative path, without the locator and the
    marker. Any symlink or special file is refused: the copy holds regular
    files only (Kyle's staging rule), so nothing else may be copied from."""
    files: dict[str, bytes] = {}

    def unreadable(exc: OSError) -> None:
        # os.walk skips a directory it cannot list by default, which would
        # install, or adopt, an incomplete copy (counter-model review).
        raise Refused(EXIT_REFUSED, f"{exc.filename} cannot be listed ({type(exc).__name__}); refusing rather "
                                    "than copying, or comparing, an incomplete skill")

    for dirpath, dirnames, filenames in os.walk(root, onerror=unreadable):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath, name)
            mode = path.lstat().st_mode
            rel = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise Refused(EXIT_USAGE, f"{rel} in {root} is not a regular file or directory; "
                                          "the installed copy holds regular files only")
            if stat.S_ISREG(mode) and rel not in INSTALL_FILES:
                try:
                    files[rel] = path.read_bytes()
                except OSError as exc:
                    raise Refused(EXIT_REFUSED, f"{rel} in {root} cannot be read ({type(exc).__name__})") from None
    return files


def tracked_payload(source: Path) -> dict[str, bytes]:
    """The SOURCE skill's files: only what git tracks, by path (#738), read
    from the working tree, so a tracked edit installs as it is on disk. An
    untracked file (the owner's GAUNTLET.json record) is never copied. When git
    cannot list the folder the install is refused: a walk instead would copy
    exactly what this exists to leave out."""
    try:
        done = subprocess.run(["git", "-C", str(source), "ls-files", "-z", "--cached", "--", "."],
                              capture_output=True, check=False, env=_git_env(), timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(EXIT_REFUSED, f"git cannot list the tracked files of {source} ({type(exc).__name__}); "
                                    "refusing rather than copying files git does not track") from None
    if done.returncode != 0:
        why = done.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no reason given"]
        raise Refused(EXIT_REFUSED, f"git cannot list the tracked files of {source} ({why[0]}); refusing rather "
                                    "than copying files git does not track")
    files: dict[str, bytes] = {}
    for raw in sorted(set(done.stdout.split(b"\0")) - {b""}):
        rel = raw.decode()
        if rel in INSTALL_FILES:
            continue
        path = source / rel
        parts = Path(rel).parts
        for depth in range(1, len(parts)):
            above = source.joinpath(*parts[:depth])
            if above.is_symlink():  # the leaf's lstat cannot see a link ABOVE it (counter-model review)
                raise Refused(EXIT_USAGE, f"{Path(*parts[:depth]).as_posix()} in {source} is a link; "
                                          "the installed copy holds regular files only")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            raise Refused(EXIT_REFUSED, f"{rel} is tracked but missing from {source}; refusing an incomplete "
                                        "skill (restore it, or commit its removal)") from None
        except OSError as exc:  # e.g. a folder above it that cannot be read
            raise Refused(EXIT_REFUSED, f"{rel} in {source} cannot be read ({type(exc).__name__}); refusing "
                                        "rather than copying an incomplete skill") from None
        if not stat.S_ISREG(mode):
            raise Refused(EXIT_USAGE, f"{rel} in {source} is not a regular file; "
                                      "the installed copy holds regular files only")
        try:
            files[rel] = path.read_bytes()
        except OSError as exc:
            raise Refused(EXIT_REFUSED, f"{rel} in {source} cannot be read ({type(exc).__name__})") from None
    if "SKILL.md" not in files:
        raise Refused(EXIT_REFUSED, f"git does not track SKILL.md in {source}; refusing to install a skill "
                                    "without it (track it, or restore it)")
    return files


def exec_bits(root: Path, files: dict[str, bytes]) -> dict[str, bool]:
    """Which payload files are executable: the launcher is run directly, so a
    copy that lost its bit is not current (counter-model review)."""
    return {rel: bool((root / rel).stat().st_mode & 0o100) for rel in files}


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


def _placed(cache: Path, skills: Path) -> None:
    """The cache must lie OUTSIDE the skills directory and outside ~/.claude
    (Kyle stages both), checked through any link, BEFORE anything is created
    there (counter-model review: XDG_CACHE_HOME=~/.claude/skills recreated the
    deploy failure)."""
    real = Path(os.path.realpath(cache))
    for guarded in (skills, Path.home() / ".claude"):
        top = Path(os.path.realpath(guarded))
        if real == top or top in real.parents:
            raise Refused(EXIT_USAGE, f"the install cache {cache} is inside {guarded}, which Kyle's deploy reads; "
                                      "set XDG_CACHE_HOME outside it")


@contextlib.contextmanager
def _locked(cache: Path) -> Iterator[None]:
    """One install or uninstall at a time: the cache is shared, and its
    leftovers are cleaned (counter-model review: an overlapping install could
    delete another's build mid-flight)."""
    cache.mkdir(parents=True, exist_ok=True)
    wait = float(os.environ.get(LOCK_WAIT_ENV, LOCK_WAIT))
    with open(cache.parent / "install.lock", "a") as handle:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Refused(EXIT_REFUSED, "another install-skill is running; try again when it finishes") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


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
    skills, cache = skills_dir(), cache_dir()
    _placed(cache, skills)
    with _locked(cache):
        return _install(skills, cache)


def _install(skills: Path, cache: Path) -> int:
    checkout, source = _source()
    files = tracked_payload(source)
    entry = skills / NAME
    state = _ours(entry, source, files)
    _clear_leftovers(cache)  # an earlier install stopped between moves
    if state == "marked":
        current = _marker(entry) or {}
        try:
            located = (entry / LOCATOR).read_text()
        except OSError:
            located = ""
        # skillc's OWN copy (its marker) is REPAIRED whatever state its files
        # are in: a copy this installer cannot even compare (a link, a FIFO, an
        # unreadable directory inside it) needs a refresh, never a refusal -
        # the launcher's drift warning tells the owner to re-run exactly this
        # (orchestrator ruling rev 47, #776 item 2). Foreign entries stay refused.
        try:
            intact = payload(entry) == files and exec_bits(entry, files) == exec_bits(source, files)
        except (Refused, OSError):
            intact = False
        if current.get("digest") == digest(files) and located == locator_text(checkout) and intact:
            return _say(EXIT_OK, f"already installed: {entry} is a current copy of {source}")
    skills.mkdir(parents=True, exist_ok=True)
    _same_device(cache, skills)
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
    skills, cache = skills_dir(), cache_dir()
    _placed(cache, skills)
    with _locked(cache):
        return _uninstall(skills, cache)


def _uninstall(skills: Path, cache: Path) -> int:
    _checkout, source = _source()
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
