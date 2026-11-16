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


def test_a_callers_pythonpath_never_picks_another_skillc(tmp_path: Path) -> None:
    """Codex pass 2: -P still honours PYTHONPATH, so a caller's PYTHONPATH could
    make validation and execution import different skillc packages."""
    impostor = tmp_path / "caller"
    (impostor / "skillc").mkdir(parents=True)
    (impostor / "skillc" / "__init__.py").write_text("")
    marker = tmp_path / "impostor-ran"
    (impostor / "skillc" / "cli.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    coll = _collection(tmp_path)
    done = subprocess.run(["bash", str(LAUNCHER), str(coll), "skills/alpha", "--offline", "--issue-states",
                           str(coll / "issue-states.json"), "--repo", "example/gauntlet"], capture_output=True,
                          text=True, check=False, cwd=impostor, env={**os.environ, "PYTHONPATH": "."})
    assert not marker.exists(), "the caller's skillc package was imported"
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr


# ------------------------------------- #765: exactly this checkout's modules

def _checkout_copy(tmp_path: Path) -> Path:
    """A skillc checkout to point the launcher at: its own source and skill."""
    ck = tmp_path / "ck"
    shutil.copytree(ROOT / "skillc", ck / "skillc", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", ck / "pyproject.toml")
    shutil.copytree(LAUNCHER.parent.parent, ck / ".claude" / "skills" / NAME)
    return ck


def _environment(ck: Path, import_root: Path) -> None:
    """`<ck>/.venv/bin/python`: the real interpreter (which has skillc's
    dependencies) with `import_root` first on its path. An `import_root` inside
    `.venv/.../site-packages` is a NON-editable install's layout; `ck` itself is
    an editable one. The launcher unsets PYTHONPATH, so this sets its own."""
    import sys

    bin_dir = ck / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").write_text(f'#!/bin/sh\nPYTHONPATH={str(import_root)!r} exec {sys.executable!r} "$@"\n')
    (bin_dir / "python").chmod(0o755)


def _site_packages(ck: Path) -> Path:
    return ck / ".venv" / "lib" / "python3.12" / "site-packages"


def _run_launcher(launcher: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    coll = _collection(tmp_path)
    return subprocess.run(["bash", str(launcher), str(coll), "skills/alpha", "--offline", "--issue-states",
                           str(coll / "issue-states.json"), "--repo", "example/gauntlet"], capture_output=True,
                          text=True, check=False, cwd=tmp_path,
                          env={k: v for k, v in os.environ.items() if k != "UV_PROJECT_ENVIRONMENT"})


def test_a_non_editable_skillc_inside_the_checkouts_venv_is_refused(tmp_path: Path) -> None:
    """The #765 red: a built wheel's copy under the checkout's own .venv is
    "under the checkout", but a git pull never updates it."""
    ck = _checkout_copy(tmp_path)
    shutil.copytree(ck / "skillc", _site_packages(ck) / "skillc")
    _environment(ck, _site_packages(ck))
    done = _run_launcher(ck / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh", tmp_path)
    assert done.returncode == 2 and "SKILL_GAUNTLET: cannot find a usable skillc" in done.stderr, done.stderr
    assert "skillc.gauntlet is .venv/lib/python3.12/site-packages/skillc/gauntlet.py" in done.stderr
    assert "ROUND" not in done.stdout + done.stderr and str(tmp_path) not in done.stderr


def test_a_cli_module_from_elsewhere_is_refused_even_when_the_engine_matches(tmp_path: Path) -> None:
    """Only skillc.cli is foreign: the engine file is the checkout's own (a
    symlink to it), but the command that runs it is not."""
    ck = _checkout_copy(tmp_path)
    pkg = _site_packages(ck) / "skillc"
    shutil.copytree(ck / "skillc", pkg)
    (pkg / "gauntlet.py").unlink()
    (pkg / "gauntlet.py").symlink_to(ck / "skillc" / "gauntlet.py")
    _environment(ck, _site_packages(ck))
    done = _run_launcher(ck / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh", tmp_path)
    assert done.returncode == 2 and "skillc.cli is .venv/lib/python3.12/site-packages/skillc/cli.py" in done.stderr
    assert "skillc.gauntlet is" not in done.stderr and "ROUND" not in done.stdout


def test_an_editable_skillc_in_the_checkout_runs(tmp_path: Path) -> None:
    """The negative control: the checkout's own source on the path runs."""
    ck = _checkout_copy(tmp_path)
    _environment(ck, ck)
    done = _run_launcher(ck / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh", tmp_path)
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr


def test_a_checkout_reached_through_a_symlinked_path_still_runs(tmp_path: Path) -> None:
    """realpath on both sides: the import path goes through a link to the
    checkout, the launcher derives the checkout with `pwd -P`, and they agree."""
    ck = _checkout_copy(tmp_path)
    link = tmp_path / "via-link"
    link.symlink_to(ck, target_is_directory=True)
    _environment(ck, link)
    done = _run_launcher(link / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh", tmp_path)
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr


def test_the_real_editable_install_runs_through_a_symlinked_checkout_path(tmp_path: Path) -> None:
    """Counter-model pass 1: the stand-in controls above inject a source path;
    this one is the REAL editable install (this checkout's own synced .venv)
    reached through a link to the checkout, with no stand-in at all."""
    if os.environ.get("UV_PROJECT_ENVIRONMENT"):
        pytest.skip("UV_PROJECT_ENVIRONMENT is set for this run; the case needs the in-tree editable .venv")
    if not (ROOT / ".venv" / "bin" / "python").is_file():
        pytest.skip("no in-tree .venv: this checkout's editable install is not synced here")
    link = tmp_path / "checkout-link"
    link.symlink_to(ROOT, target_is_directory=True)
    done = _run_launcher(link / ".claude" / "skills" / NAME / "scripts" / "gauntlet.sh", tmp_path)
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr
