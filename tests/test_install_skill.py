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
from typing import Any

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


def _installer(checkout: Path, skills: Path, verb: str, home: Path | None = None) -> subprocess.CompletedProcess[str]:
    """The installer as an operator runs it, with HOME and the cache in tmp:
    a test never writes under the real ~/.claude or ~/.cache (#774)."""
    home = home if home is not None else skills.parent / "home"
    env = {**os.environ, "SKILLC_SKILLS_DIR": str(skills), "HOME": str(home),
           "XDG_CACHE_HOME": str(skills.parent / "cache")}
    return subprocess.run(["python3", str(checkout / "scripts" / "install_skill.py"), verb], capture_output=True,
                          text=True, check=False, cwd=checkout, env=env)


def test_install_refuses_a_link_to_somewhere_else(checkout: Path, tmp_path: Path) -> None:
    skills, elsewhere = tmp_path / "skills", tmp_path / "elsewhere"
    skills.mkdir()
    elsewhere.mkdir()
    (skills / NAME).symlink_to(elsewhere, target_is_directory=True)
    done = _installer(checkout, skills, "install")
    assert done.returncode == 1 and str(elsewhere) in done.stderr
    assert Path(os.readlink(skills / NAME)) == elsewhere


def test_install_refuses_outside_a_git_checkout(tmp_path: Path) -> None:
    loose = tmp_path / "loose"
    (loose / "scripts").mkdir(parents=True)
    shutil.copy(INSTALLER, loose / "scripts" / "install_skill.py")
    done = _installer(loose, tmp_path / "skills", "install")
    assert done.returncode == 2 and "not in a git checkout" in done.stderr
    assert not (tmp_path / "skills").exists()


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
    env = {**os.environ, "SKILLC_SKILLS_DIR": str(skills), "HOME": str(tmp_path / "home"),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    if verb == "uninstall":
        _installer(checkout, skills, "install")
    ok = subprocess.run(["make", "-s", "-f", str(ROOT / "Makefile"), f"{verb}-skill"], capture_output=True, text=True,
                        check=False, cwd=checkout, env=env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    shutil.rmtree(skills / NAME, ignore_errors=True)
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


# ---------------------------------------------- #774: a real copy, never a link

def _tree(entry: Path) -> dict[str, str]:
    """Every entry under `entry`: its kind and, for a file, its bytes."""
    out = {}
    for path in sorted(entry.rglob("*")):
        rel = path.relative_to(entry).as_posix()
        out[rel] = "link" if path.is_symlink() else "dir" if path.is_dir() else path.read_bytes().decode()
    return out


def _kyle_stageable(skills: Path) -> None:
    """Kyle's staging rule (kyle deploy/operator_config.py:396-408): every entry
    directly under skills/ is a real directory holding SKILL.md, and no
    symlink exists anywhere in it."""
    for entry in skills.iterdir():
        assert not entry.is_symlink() and entry.is_dir() and (entry / "SKILL.md").is_file(), entry
        assert not [p for p in entry.rglob("*") if p.is_symlink()], entry


def test_install_writes_a_real_copy_with_no_symlink_anywhere(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    done = _installer(checkout, skills, "install")
    assert done.returncode == 0 and "installed:" in done.stdout, done.stderr
    entry = skills / NAME
    assert entry.is_dir() and not entry.is_symlink()
    assert not [p for p in entry.rglob("*") if p.is_symlink()], "Kyle's deploy refuses any symlink"
    _kyle_stageable(skills)
    source = checkout / ".claude" / "skills" / NAME
    assert (entry / "scripts" / "gauntlet.sh").read_bytes() == (source / "scripts" / "gauntlet.sh").read_bytes()
    assert os.access(entry / "scripts" / "gauntlet.sh", os.X_OK)
    marker = (entry / ".skillc-install").read_text()
    assert marker.startswith("kind skillc-skill-install\nschema 1\ndigest ") and str(tmp_path) not in marker
    again = _installer(checkout, skills, "install")
    assert again.returncode == 0 and "already installed" in again.stdout


def test_the_kyle_staging_check_fails_on_a_symlink() -> None:
    """The staging check above, on a planted link: it is not blind."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        skills = Path(tmp)
        (skills / "real").mkdir()
        (skills / "real" / "SKILL.md").write_text("x")
        (skills / "linked").symlink_to(skills / "real", target_is_directory=True)
        with pytest.raises(AssertionError):
            _kyle_stageable(skills)


def test_the_locator_is_home_relative_and_names_the_main_checkout(checkout: Path, tmp_path: Path) -> None:
    """The locator is copied into Kyle's session image: under $HOME it is
    written `~/...`, never the expanded path holding the account name."""
    skills = tmp_path / "skills"
    assert _installer(checkout, skills, "install", home=tmp_path).returncode == 0
    assert (skills / NAME / ".skillc-checkout").read_text() == "~/skillc\n"
    assert str(tmp_path) not in (skills / NAME / ".skillc-checkout").read_text()


def test_a_checkout_outside_home_is_located_absolutely(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    assert _installer(checkout, skills, "install", home=tmp_path / "elsewhere-home").returncode == 0
    assert (skills / NAME / ".skillc-checkout").read_text() == f"{checkout}\n"


def test_install_from_a_linked_worktree_locates_the_main_checkout(checkout: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _git(checkout, "worktree", "add", "-q", str(worktree))
    skills = tmp_path / "skills"
    assert _installer(worktree, skills, "install", home=tmp_path).returncode == 0
    assert (skills / NAME / ".skillc-checkout").read_text() == "~/skillc\n"


def test_a_source_holding_a_symlink_is_refused(checkout: Path, tmp_path: Path) -> None:
    (checkout / ".claude" / "skills" / NAME / "extra.md").symlink_to(checkout / ".claude" / "skills" / NAME / "SKILL.md")
    skills = tmp_path / "skills"
    done = _installer(checkout, skills, "install")
    assert done.returncode == 2 and "regular files only" in done.stderr and not (skills / NAME).exists()


@pytest.mark.parametrize("kind", ["differing-copy", "file"])
def test_install_refuses_a_foreign_entry_and_leaves_it(checkout: Path, tmp_path: Path, kind: str) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    if kind == "file":
        (skills / NAME).write_text("not a skill\n")
    else:
        (skills / NAME).mkdir()
        (skills / NAME / "SKILL.md").write_text("someone else's skill\n")
    before = _tree(skills)
    done = _installer(checkout, skills, "install")
    assert done.returncode == 1 and "refusing" in done.stderr and _tree(skills) == before


def test_an_unmarked_identical_copy_is_adopted(checkout: Path, tmp_path: Path) -> None:
    """kyle-cli-helper's plain copy (orchestrator ruling 1): byte-identical, so
    replacing it with a marked copy loses nothing."""
    skills = tmp_path / "skills"
    skills.mkdir()
    shutil.copytree(checkout / ".claude" / "skills" / NAME, skills / NAME)
    done = _installer(checkout, skills, "install")
    assert done.returncode == 0 and "adopted the identical copy" in done.stdout
    assert (skills / NAME / ".skillc-install").is_file() and (skills / NAME / ".skillc-checkout").is_file()


def test_an_old_skillc_link_is_migrated_to_a_copy(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / NAME).symlink_to(checkout / ".claude" / "skills" / NAME, target_is_directory=True)
    done = _installer(checkout, skills, "install")
    assert done.returncode == 0 and "migrated the old link" in done.stdout
    assert not (skills / NAME).is_symlink() and (skills / NAME / ".skillc-install").is_file()
    _kyle_stageable(skills)


def test_reinstall_replaces_the_copy_and_leaves_nothing_under_skills(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _installer(checkout, skills, "install")
    (checkout / ".claude" / "skills" / NAME / "SKILL.md").write_text("an updated skill\n")
    done = _installer(checkout, skills, "install")
    assert done.returncode == 0 and "refreshed" in done.stdout
    assert (skills / NAME / "SKILL.md").read_text() == "an updated skill\n"
    assert [p.name for p in skills.iterdir()] == [NAME]
    assert not [p for p in (tmp_path / "cache" / "skillc" / "install-tmp").iterdir()], "the cache is cleaned"


def test_uninstall_removes_only_the_marked_copy(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _installer(checkout, skills, "install")
    done = _installer(checkout, skills, "uninstall")
    assert done.returncode == 0 and not (skills / NAME).exists()
    assert (checkout / ".claude" / "skills" / NAME / "SKILL.md").is_file(), "the skill itself is untouched"
    again = _installer(checkout, skills, "uninstall")
    assert again.returncode == 0 and "not installed" in again.stdout


def test_uninstall_refuses_an_unmarked_copy_even_an_identical_one(checkout: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    shutil.copytree(checkout / ".claude" / "skills" / NAME, skills / NAME)
    done = _installer(checkout, skills, "uninstall")
    assert done.returncode == 1 and (skills / NAME / "SKILL.md").is_file()


@pytest.mark.parametrize("step", ["built", "retired", "moved-in"])
@pytest.mark.parametrize("before", ["absent", "copy"])
def test_an_install_stopped_at_any_step_leaves_only_a_stageable_entry_or_none(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, before: str,
) -> None:
    """kyle-cli-helper's condition 2: an install interrupted between its moves
    leaves, under skills/, only `skill-gauntlet/` with its SKILL.md, or no
    skill-gauntlet at all - never a temp name, never a directory without
    SKILL.md. Run in-process so the crash lands exactly at each step."""
    import importlib.util

    skills = tmp_path / "skills"
    home = tmp_path / "home"
    monkeypatch.setenv("SKILLC_SKILLS_DIR", str(skills))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    if before == "copy":
        assert _installer(checkout, skills, "install").returncode == 0
        (checkout / ".claude" / "skills" / NAME / "SKILL.md").write_text("an updated skill\n")
    spec = importlib.util.spec_from_file_location("install_skill_774", checkout / "scripts" / "install_skill.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Crash(Exception):
        pass

    def crash(name: str) -> None:
        if name == step:
            raise Crash(name)

    monkeypatch.setattr(mod, "_step", crash)
    with pytest.raises(Crash):
        mod.install()
    entries = list(skills.iterdir()) if skills.exists() else []
    assert [e.name for e in entries] in ([], [NAME]), entries
    _kyle_stageable(skills) if entries else None
    assert _installer(checkout, skills, "install").returncode == 0, "the next install recovers"
    assert (skills / NAME / "SKILL.md").read_text() == (checkout / ".claude" / "skills" / NAME / "SKILL.md").read_text()
    assert not list((tmp_path / "cache" / "skillc" / "install-tmp").iterdir())


def test_a_cache_on_another_device_is_refused(checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never built inside the skills directory as a fallback: refused, named."""
    import importlib.util

    skills = tmp_path / "skills"
    monkeypatch.setenv("SKILLC_SKILLS_DIR", str(skills))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    spec = importlib.util.spec_from_file_location("install_skill_774b", checkout / "scripts" / "install_skill.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real_stat = os.stat

    def other_device(path: Any, *args: Any, **kwargs: Any) -> Any:
        st = real_stat(path, *args, **kwargs)
        if Path(path) == mod.cache_dir():
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 1, *tuple(st)[3:]))
        return st

    monkeypatch.setattr(mod.os, "stat", other_device)
    assert mod.main(["install_skill.py", "install"]) == 2
    assert not (skills / NAME).exists() and [p.name for p in skills.iterdir()] == []


# ------------------------- #774: the launcher in an installed copy, via the locator

def _runnable_checkout(tmp_path: Path) -> Path:
    """A git checkout with the installer, the skill, skillc's source and an
    environment importing it (editable), so an installed copy can RUN."""
    repo = _checkout_copy(tmp_path)
    (repo / "scripts").mkdir()
    shutil.copy(INSTALLER, repo / "scripts" / "install_skill.py")
    _environment(repo, repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return repo


def _installed_launcher(tmp_path: Path) -> tuple[Path, Path]:
    repo = _runnable_checkout(tmp_path)
    skills = tmp_path / "skills"
    assert _installer(repo, skills, "install", home=tmp_path).returncode == 0
    return repo, skills / NAME / "scripts" / "gauntlet.sh"


def _run_installed(launcher: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    coll = _collection(tmp_path)
    return subprocess.run(["bash", str(launcher), str(coll), "skills/alpha", "--offline", "--issue-states",
                           str(coll / "issue-states.json"), "--repo", "example/gauntlet"], capture_output=True,
                          text=True, check=False, cwd=tmp_path,
                          env={**{k: v for k, v in os.environ.items() if k != "UV_PROJECT_ENVIRONMENT"},
                               "HOME": str(tmp_path)})


def test_the_installed_copy_finds_skillc_through_the_locator(tmp_path: Path) -> None:
    _repo, launcher = _installed_launcher(tmp_path)
    done = _run_installed(launcher, tmp_path)
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, done.stdout + done.stderr
    assert "warning" not in done.stderr, "a current copy is not warned about"


@pytest.mark.parametrize("locator", ["missing-checkout", "no-locator"])
def test_a_wrong_or_missing_locator_gives_cannot_find_and_no_verdict(tmp_path: Path, locator: str) -> None:
    _repo, launcher = _installed_launcher(tmp_path)
    loc = launcher.parent.parent / ".skillc-checkout"
    if locator == "missing-checkout":
        loc.write_text("~/no-such-checkout\n")
    else:
        loc.unlink()  # a copy with no locator falls back to its own path: nothing above it
    done = _run_installed(launcher, tmp_path)
    assert done.returncode == 2 and "SKILL_GAUNTLET: cannot find a usable skillc" in done.stderr, done.stderr
    assert "ROUND" not in done.stdout + done.stderr


def test_a_stale_copy_is_warned_and_still_runs_with_the_same_exit(tmp_path: Path) -> None:
    repo, launcher = _installed_launcher(tmp_path)
    (repo / ".claude" / "skills" / NAME / "SKILL.md").write_text("changed in the checkout since the install\n")
    done = _run_installed(launcher, tmp_path)
    assert "SKILL_GAUNTLET: warning: this installed copy differs" in done.stderr
    assert done.returncode == 3 and "ROUND 0 usage:" in done.stdout, "the warning never blocks or changes the exit"


def test_the_repository_skill_carries_no_locator_or_marker() -> None:
    skill = ROOT / ".claude" / "skills" / NAME
    assert not (skill / ".skillc-checkout").exists() and not (skill / ".skillc-install").exists()
