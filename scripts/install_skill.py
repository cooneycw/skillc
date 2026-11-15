#!/usr/bin/env python3
"""Install `/skill-gauntlet` for every Claude Code session (#763).

`make install-skill` links `~/.claude/skills/skill-gauntlet` to this skillc
checkout's `.claude/skills/skill-gauntlet`. It is a link, so a `git pull`
updates the skill, and `make uninstall-skill` removes the link and nothing
else. The link always points at the MAIN checkout (git --git-common-dir), so
running it from a linked worktree does not tie every session to a worktree that
will be removed.

    python3 scripts/install_skill.py install
    python3 scripts/install_skill.py uninstall

`SKILLC_SKILLS_DIR` overrides the skills directory (default `~/.claude/skills`).

Exit codes: 0 done, or already in the wanted state; 1 refused (the entry is a
real file or directory, or a link pointing somewhere else - named, never
touched); 2 usage (not in a git checkout, no skill in the checkout).

Stdlib only: it must run with plain `python3`, before any `uv sync`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

NAME = "skill-gauntlet"
SKILLS_ENV = "SKILLC_SKILLS_DIR"
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


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


def _target() -> Path:
    main = main_checkout(Path(__file__).resolve().parent)
    if main is None:
        raise SystemExit(_say(EXIT_USAGE, "not in a git checkout of skillc; install from a source checkout"))
    target = main / ".claude" / "skills" / NAME
    if not (target / "SKILL.md").is_file():
        raise SystemExit(_say(EXIT_USAGE, f"no {NAME} skill in the main checkout ({target} has no SKILL.md)"))
    return target


def _say(code: int, message: str) -> int:
    print(f"install-skill: {message}", file=sys.stderr if code else sys.stdout)
    return code


def install() -> int:
    target, entry = _target(), skills_dir() / NAME
    if entry.is_symlink():
        current = Path(os.readlink(entry))
        if current == target:
            return _say(EXIT_OK, f"already installed: {entry} -> {target}")
        return _say(EXIT_REFUSED, f"refusing: {entry} is a link to {current}, not to this checkout; "
                                  "remove it yourself if it is stale")
    if entry.exists():
        return _say(EXIT_REFUSED, f"refusing: {entry} exists and is not a link; it is not ours to replace")
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.symlink_to(target, target_is_directory=True)
    return _say(EXIT_OK, f"installed: {entry} -> {target} (a git pull updates it; "
                         "`make uninstall-skill` removes it)")


def uninstall() -> int:
    target, entry = _target(), skills_dir() / NAME
    if not entry.is_symlink() and not entry.exists():
        return _say(EXIT_OK, f"not installed: {entry} does not exist")
    if not entry.is_symlink():
        return _say(EXIT_REFUSED, f"refusing: {entry} is not a link; it is not ours to remove")
    current = Path(os.readlink(entry))
    if current != target:
        return _say(EXIT_REFUSED, f"refusing: {entry} links to {current}, not to this checkout")
    entry.unlink()
    return _say(EXIT_OK, f"uninstalled: removed the link {entry}")


def main(argv: list[str]) -> int:
    if argv[1:] == ["install"]:
        return install()
    if argv[1:] == ["uninstall"]:
        return uninstall()
    return _say(EXIT_USAGE, "usage: install_skill.py install|uninstall")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
