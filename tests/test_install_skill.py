"""`make install-skill` and the /skill-gauntlet launcher (#763).

The installer and the launcher run as an operator runs them (plain `python3`,
plain `bash`), against a throwaway skillc-shaped git checkout and a throwaway
skills directory. Every refusal is paired with the input that succeeds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "scripts" / "install_skill.py"
LAUNCHER = ROOT / ".claude" / "skills" / "skill-gauntlet" / "scripts" / "gauntlet.sh"
FIXTURES = ROOT / "evals" / "subjects" / "gauntlet"
NAME = "skill-gauntlet"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A skillc-shaped git checkout: the installer and the skill, nothing else."""
    repo = tmp_path / "skillc"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(INSTALLER, repo / "scripts" / "install_skill.py")
    shutil.copytree(ROOT / ".claude" / "skills" / NAME, repo / ".claude" / "skills" / NAME)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return repo


def _installer(checkout: Path, skills: Path, verb: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(checkout / "scripts" / "install_skill.py"), verb], capture_output=True,
                          text=True, check=False, cwd=checkout, env={**os.environ, "SKILLC_SKILLS_DIR": str(skills)})


# ------------------------------------------------------------------- install

def test_install_links_the_skill_and_a_second_install_changes_nothing(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    first = _installer(checkout, skills, "install")
    assert first.returncode == 0 and "installed:" in first.stdout
    entry = skills / NAME
    assert entry.is_symlink() and Path(os.readlink(entry)) == checkout / ".claude" / "skills" / NAME
    assert (entry / "SKILL.md").is_file()
    second = _installer(checkout, skills, "install")
    assert second.returncode == 0 and "already installed" in second.stdout


def test_install_refuses_a_real_directory_and_leaves_it(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    (skills / NAME).mkdir(parents=True)
    (skills / NAME / "SKILL.md").write_text("someone else's skill\n")
    done = _installer(checkout, skills, "install")
    assert done.returncode == 1 and "not a link" in done.stderr
    assert (skills / NAME / "SKILL.md").read_text() == "someone else's skill\n"


def test_install_refuses_a_link_to_somewhere_else(checkout: Path, tmp_path: Path) -> None:
    skills, elsewhere = tmp_path / "skills", tmp_path / "elsewhere"
    skills.mkdir()
    elsewhere.mkdir()
    (skills / NAME).symlink_to(elsewhere, target_is_directory=True)
    done = _installer(checkout, skills, "install")
    assert done.returncode == 1 and str(elsewhere) in done.stderr
    assert Path(os.readlink(skills / NAME)) == elsewhere


def test_install_from_a_linked_worktree_links_the_main_checkout(checkout: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _git(checkout, "worktree", "add", "-q", str(worktree))
    skills = tmp_path / "skills"
    assert _installer(worktree, skills, "install").returncode == 0
    assert Path(os.readlink(skills / NAME)) == checkout / ".claude" / "skills" / NAME


def test_install_refuses_outside_a_git_checkout(tmp_path: Path) -> None:
    loose = tmp_path / "loose"
    (loose / "scripts").mkdir(parents=True)
    shutil.copy(INSTALLER, loose / "scripts" / "install_skill.py")
    done = _installer(loose, tmp_path / "skills", "install")
    assert done.returncode == 2 and "not in a git checkout" in done.stderr
    assert not (tmp_path / "skills").exists()


# ----------------------------------------------------------------- uninstall

def test_uninstall_removes_only_its_own_link(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _installer(checkout, skills, "install")
    done = _installer(checkout, skills, "uninstall")
    assert done.returncode == 0 and not (skills / NAME).exists() and not (skills / NAME).is_symlink()
    assert (checkout / ".claude" / "skills" / NAME / "SKILL.md").is_file(), "the skill itself is untouched"
    again = _installer(checkout, skills, "uninstall")
    assert again.returncode == 0 and "not installed" in again.stdout


@pytest.mark.parametrize("foreign", ["dir", "link"])
def test_uninstall_refuses_a_foreign_entry(checkout: Path, tmp_path: Path, foreign: str) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    if foreign == "dir":
        (skills / NAME).mkdir()
    else:
        (tmp_path / "other").mkdir()
        (skills / NAME).symlink_to(tmp_path / "other", target_is_directory=True)
    done = _installer(checkout, skills, "uninstall")
    assert done.returncode == 1 and (skills / NAME).exists()


# ------------------------------------------------------------------ launcher

def _collection(tmp_path: Path) -> Path:
    root = tmp_path / "coll"
    shutil.copytree(FIXTURES / "collection", root)
    return root


def test_the_launcher_runs_the_engine_from_an_unrelated_directory(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    coll = _collection(tmp_path)
    done = subprocess.run(["bash", str(LAUNCHER), str(coll), "skills/alpha", "--offline", "--issue-states",
                           str(coll / "issue-states.json"), "--repo", "example/gauntlet"],
                          capture_output=True, text=True, check=False, cwd=elsewhere)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "ROUND 1 charter: PASS" in done.stdout and "no trials ran" in done.stdout


def test_the_launcher_through_an_installed_link_finds_skillc(tmp_path: Path) -> None:
    """The launcher reached through a link, as from ~/.claude/skills, still finds
    the checkout the link points into."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / NAME).symlink_to(LAUNCHER.parent.parent, target_is_directory=True)
    coll = _collection(tmp_path)
    done = subprocess.run(["bash", str(skills / NAME / "scripts" / "gauntlet.sh"), str(coll), "skills/alpha",
                           "--offline", "--issue-states", str(coll / "issue-states.json"), "--repo", "example/gauntlet"],
                          capture_output=True, text=True, check=False, cwd=tmp_path)
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr


def test_the_launcher_with_no_skillc_reports_and_gives_no_verdict(tmp_path: Path) -> None:
    """Present but broken: the skill is installed, but no skillc stands behind it."""
    fake = tmp_path / "not-skillc" / ".claude" / "skills" / NAME / "scripts"
    fake.mkdir(parents=True)
    shutil.copy(LAUNCHER, fake / "gauntlet.sh")
    done = subprocess.run(["bash", str(fake / "gauntlet.sh"), str(tmp_path), "x"], capture_output=True, text=True,
                          check=False, cwd=tmp_path)
    assert done.returncode == 2
    assert "SKILL_GAUNTLET: cannot find a usable skillc" in done.stderr
    assert "ROUND" not in done.stdout + done.stderr


def test_a_dangling_link_lists_no_skill_and_gives_no_verdict(checkout: Path, tmp_path: Path) -> None:
    """Moved or deleted checkout (ruling 1 on #763): the link dangles, so there
    is no SKILL.md to list and no launcher to run - no verdict is possible."""
    skills = tmp_path / "skills"
    _installer(checkout, skills, "install")
    shutil.rmtree(checkout)
    entry = skills / NAME
    assert entry.is_symlink() and not (entry / "SKILL.md").exists()
    done = subprocess.run(["bash", str(entry / "scripts" / "gauntlet.sh"), str(tmp_path), "x"], capture_output=True,
                          text=True, check=False, cwd=tmp_path)
    assert done.returncode != 0 and "ROUND" not in done.stdout


def _account_paths(text: str) -> list[str]:
    return [marker for marker in ("/" + "home/", "/" + "Users/") if marker in text]


def test_no_committed_install_file_holds_an_account_path() -> None:
    for path in (INSTALLER, LAUNCHER, LAUNCHER.parent.parent / "SKILL.md", ROOT / "Makefile"):
        assert _account_paths(path.read_text()) == [], path


def test_the_account_path_scan_finds_one() -> None:
    """The scan above, on a planted path: it is not blind (Codex pass 1)."""
    assert _account_paths(LAUNCHER.read_text() + "\ncd /" + "home/someone/skillc\n") == ["/" + "home/"]


# ------------------------------------- counter-model review pass 1 (Codex), each a red

def _real_env() -> Path:
    env = os.environ.get("UV_PROJECT_ENVIRONMENT")
    return Path(env) if env else ROOT / ".venv"


def test_a_relative_project_environment_resolves_against_the_checkout(tmp_path: Path) -> None:
    if os.environ.get("UV_PROJECT_ENVIRONMENT"):
        pytest.skip("UV_PROJECT_ENVIRONMENT is set for this run; the relative case needs the in-tree .venv")
    coll = _collection(tmp_path)
    done = subprocess.run(["bash", str(LAUNCHER), str(coll), "skills/alpha", "--offline", "--issue-states",
                           str(coll / "issue-states.json"), "--repo", "example/gauntlet"], capture_output=True,
                          text=True, check=False, cwd="/", env={**os.environ, "UV_PROJECT_ENVIRONMENT": ".venv"})
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr


def test_an_environment_without_skillc_is_reported_not_run(tmp_path: Path) -> None:
    """A python that runs but cannot import this checkout's engine: the
    cannot-find line, exit 2, no ROUND line, no uv startup error."""
    fake = tmp_path / "fake-skillc"
    (fake / "skillc").mkdir(parents=True)
    (fake / "skillc" / "gauntlet.py").write_text("")
    (fake / "pyproject.toml").write_text("[project]\nname = 'skillc'\n")
    shutil.copytree(LAUNCHER.parent.parent, fake / ".claude" / "skills" / NAME)
    (fake / ".venv" / "bin").mkdir(parents=True)
    (fake / ".venv" / "bin" / "python").symlink_to(shutil.which("python3") or "/usr/bin/python3")
    done = subprocess.run(["bash", str(fake / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh"),
                           str(tmp_path), "x"], capture_output=True, text=True, check=False, cwd=tmp_path,
                          env={k: v for k, v in os.environ.items() if k != "UV_PROJECT_ENVIRONMENT"})
    assert done.returncode == 2 and "SKILL_GAUNTLET: cannot find a usable skillc" in done.stderr, done.stderr
    assert "ROUND" not in done.stdout + done.stderr


@pytest.mark.parametrize("verb", ["install", "uninstall"])
def test_the_make_targets_run_the_installer_and_carry_its_exit(checkout: Path, tmp_path: Path, verb: str) -> None:
    skills = tmp_path / "skills"
    env = {**os.environ, "SKILLC_SKILLS_DIR": str(skills)}
    if verb == "uninstall":
        _installer(checkout, skills, "install")
    ok = subprocess.run(["make", "-s", "-f", str(ROOT / "Makefile"), f"{verb}-skill"], capture_output=True, text=True,
                        check=False, cwd=checkout, env=env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    (skills / NAME).unlink(missing_ok=True)
    (skills / NAME).mkdir(parents=True, exist_ok=True)  # a foreign real entry: refused, and make says so
    refused = subprocess.run(["make", "-s", "-f", str(ROOT / "Makefile"), f"{verb}-skill"], capture_output=True,
                             text=True, check=False, cwd=checkout, env=env)
    assert refused.returncode != 0 and (skills / NAME).is_dir()
