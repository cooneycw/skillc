"""Per-trial agent bootstrap (#78): home, seed, MCP config, invocation,
prompt-delivery verification, and the skill+tool liveness canary.

Each committed case below is the red case issue #78's own "Controls"
section names: a no-op fake client, a client that answers without touching
the skill, a mismatched transcript prompt, an auto-answering or missing
seed, and a stale Dockerfile pin.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from skillc import trial_bootstrap as tb

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_SCRIPT = REPO_ROOT / "docker" / "trial" / "verify_codex_sidecar.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _load_check_pins():
    spec = importlib.util.spec_from_file_location(
        "skillc_trial_check_pins", REPO_ROOT / "docker" / "trial" / "check_pins.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_check_interpreters():
    spec = importlib.util.spec_from_file_location(
        "skillc_trial_check_interpreters", REPO_ROOT / "docker" / "trial" / "check_interpreters.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_check_helpers():
    spec = importlib.util.spec_from_file_location(
        "skillc_trial_check_helpers", REPO_ROOT / "docker" / "trial" / "check_helpers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Pinned CLI versions
# --------------------------------------------------------------------------


def test_pinned_cli_version_reads_the_real_manifest():
    assert tb.pinned_cli_version("claude_code") == "2.1.283"
    assert tb.pinned_cli_version("codex") == "0.157.1"


def test_pinned_cli_version_refuses_an_unknown_client():
    with pytest.raises(tb.PinnedVersionError):
        tb.pinned_cli_version("gemini")


def test_pinned_cli_version_refuses_a_missing_manifest(tmp_path):
    with pytest.raises(tb.PinnedVersionError):
        tb.pinned_cli_version("claude_code", manifest_path=tmp_path / "absent.json")


# --------------------------------------------------------------------------
# docker/trial/check_pins.py: the Dockerfile ARG defaults vs the manifest
# --------------------------------------------------------------------------


def test_check_pins_agrees_on_the_real_dockerfile_and_manifest():
    check_pins = _load_check_pins()
    dockerfile_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "docker" / "trial" / "pinned-versions.json").read_text(encoding="utf-8"))
    assert check_pins.check_pins(dockerfile_text, manifest) == []


def test_check_pins_reports_a_stale_dockerfile_arg():
    check_pins = _load_check_pins()
    dockerfile_text = "ARG CLAUDE_CODE_VERSION=1.0.0\nARG CODEX_VERSION=0.157.1\n"
    manifest = {
        "claude_code": {"version": "2.1.283"},
        "codex": {"version": "0.157.1"},
    }
    messages = check_pins.check_pins(dockerfile_text, manifest)
    assert any("CLAUDE_CODE_VERSION" in m for m in messages)


def test_check_pins_reports_a_missing_arg():
    check_pins = _load_check_pins()
    dockerfile_text = "ARG CODEX_VERSION=0.157.1\n"
    manifest = {
        "claude_code": {"version": "2.1.283"},
        "codex": {"version": "0.157.1"},
    }
    messages = check_pins.check_pins(dockerfile_text, manifest)
    assert any("CLAUDE_CODE_VERSION" in m for m in messages)


# --------------------------------------------------------------------------
# docker/trial/check_interpreters.py: every interpreter the demo and
# verifier invoke inside the trial container (issue #78, Refs #81, #10) must
# actually be apt-installed by the Dockerfile - found live when the real
# skillc-trial image turned out to have no python3 at all, undetected by
# every existing check because they all run against the fake `docker` CLI,
# which never looks inside an image.
# --------------------------------------------------------------------------


def test_check_interpreters_agrees_on_the_real_dockerfile():
    from skillc.verify import PROBE_INTERPRETER

    check_interpreters = _load_check_interpreters()
    dockerfile_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    assert check_interpreters.check_interpreters(dockerfile_text, {PROBE_INTERPRETER}) == []


def test_check_interpreters_reports_a_missing_interpreter():
    """Red case (issue #78/#81): remove `python3` from the Dockerfile's own
    apt-get install list and confirm the check reports it - this is the
    exact regression that shipped undetected until this module existed."""
    check_interpreters = _load_check_interpreters()
    real_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    without_python3 = real_text.replace("        python3 \\\n", "")
    assert "python3" not in check_interpreters.dockerfile_apt_packages(without_python3)
    messages = check_interpreters.check_interpreters(without_python3, {"python3"})
    assert any("python3" in m for m in messages)


def test_check_interpreters_ignores_an_unrelated_required_name():
    """A required interpreter this Dockerfile never claims to install (never
    installed at all here, e.g. `node`, which ships with the base image) is
    reported missing too - this check only knows about its OWN apt-get
    install list, never the base image's contents, and says so structurally
    rather than silently passing on a name it cannot see."""
    check_interpreters = _load_check_interpreters()
    dockerfile_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    messages = check_interpreters.check_interpreters(dockerfile_text, {"python3", "node"})
    assert any("node" in m for m in messages)
    assert not any("python3" in m for m in messages)


def test_check_interpreters_reports_an_unparseable_dockerfile():
    check_interpreters = _load_check_interpreters()
    messages = check_interpreters.check_interpreters("FROM scratch\n", {"python3"})
    assert messages and "could not find" in messages[0]


# --------------------------------------------------------------------------
# docker/trial/check_helpers.py: a required helper script must be both
# COPYed to its installed path and made executable (issue #183 PR B2).
# --------------------------------------------------------------------------


def test_check_helpers_agrees_on_the_real_dockerfile():
    check_helpers = _load_check_helpers()
    dockerfile_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    assert check_helpers.check_helpers(dockerfile_text) == []


def test_check_helpers_reports_a_missing_copy_line():
    """THE RED CASE: remove the COPY line for a required helper and
    confirm the check reports it missing, rather than silently passing
    because the chmod line (which names the same path, not the source
    file) is still present."""
    check_helpers = _load_check_helpers()
    real_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    without_copy = real_text.replace(
        "COPY skillc-disrupt-tool.py /usr/local/bin/skillc-disrupt-tool\n", "",
    )
    assert without_copy != real_text
    messages = check_helpers.check_helpers(without_copy)
    assert any("skillc-disrupt-tool.py" in m and "COPY" in m for m in messages)


def test_check_helpers_reports_a_missing_chmod():
    """A COPY with no matching chmod leaves the helper non-executable -
    refused distinctly from a missing COPY, so a reader knows which half
    is absent."""
    check_helpers = _load_check_helpers()
    real_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    without_chmod = real_text.replace(
        "RUN chmod 755 /usr/local/bin/skillc-disrupt-tool\n", "",
    )
    assert without_chmod != real_text
    messages = check_helpers.check_helpers(without_chmod)
    assert any("never made executable" in m for m in messages)


def test_check_helpers_ignores_an_unrelated_helper_not_required_here():
    """A helper this Dockerfile never claims to install (e.g. the still-
    HELD skillc-wrap.py, #78) is reported missing if asked for - this
    check only knows about its OWN required map, never the base image or
    a different helper's own install path."""
    check_helpers = _load_check_helpers()
    dockerfile_text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    messages = check_helpers.check_helpers(
        dockerfile_text, {"skillc-wrap.py": "/usr/local/bin/skillc-wrap"},
    )
    assert any("skillc-wrap.py" in m for m in messages)


# --------------------------------------------------------------------------
# docker/trial/verify_codex_sidecar.js: resolves the REAL platform package,
# never the npm wrapper's own directory (Codex code-review finding on #78:
# an earlier version searched beside bin/codex.js, which is the wrong
# directory - confirmed by extracting the real 0.157.1 tarballs).
#
# A second bug shipped past that fix and reached a real operator build
# (Dockerfile:80, "Cannot find module '@openai/codex-linux-x64/package.json'"):
# the Dockerfile COPYs this script to /tmp and runs it from there, so a bare
# require.resolve() walks up from /tmp's own ancestry - nowhere near a real
# npm global install. The FIXTURE below matches the REAL shape two ways the
# old one didn't: the script runs from a scratch directory with no relation
# to the fixture (never beside it, never above it), and CODEX_NPM_ROOT is
# the only override (never NODE_PATH, which the real Dockerfile invocation
# never sets and which resolves completely differently) - it stands in for
# what `npm root -g` prints for a real global install, and the platform
# package is nested under @openai/codex/node_modules/, exactly where npm
# puts an optional dependency of a globally-installed package, never at the
# shared global root beside it.
# --------------------------------------------------------------------------


def _fake_global_install(root: Path, *, codex_exists=True, platform_package_exists=True, native_exists=True, sidecar=("file", "executable")):
    """A fake npm global root under `root` (i.e. what `npm root -g` would
    print), laid out the way a real `npm install -g @openai/codex` actually
    nests its platform-specific optional dependency: under codex's OWN
    node_modules, never beside it. `sidecar` is `(kind, mode)`: kind is
    'file', 'dir' or 'missing'; mode is 'executable' or 'not-executable'."""
    global_root = root / "node_modules"
    if not codex_exists:
        global_root.mkdir(parents=True)
        return global_root
    codex_dir = global_root / "@openai" / "codex"
    (codex_dir / "bin").mkdir(parents=True)
    (codex_dir / "package.json").write_text('{"name": "@openai/codex", "type": "module"}', encoding="utf-8")
    if not platform_package_exists:
        return global_root
    pkg_dir = codex_dir / "node_modules" / "@openai" / "codex-linux-x64"
    vendor_bin = pkg_dir / "vendor" / "x86_64-unknown-linux-musl" / "bin"
    vendor_bin.mkdir(parents=True)
    (pkg_dir / "package.json").write_text('{"name": "@openai/codex-linux-x64"}', encoding="utf-8")
    if native_exists:
        native = vendor_bin / "codex"
        native.write_text("", encoding="utf-8")
        native.chmod(native.stat().st_mode | stat.S_IEXEC)
    kind, mode = sidecar
    sidecar_path = vendor_bin / "codex-code-mode-host"
    if kind == "file":
        sidecar_path.write_text("", encoding="utf-8")
        if mode == "executable":
            sidecar_path.chmod(sidecar_path.stat().st_mode | stat.S_IEXEC)
        else:
            sidecar_path.chmod(sidecar_path.stat().st_mode & ~stat.S_IEXEC & ~stat.S_IXGRP & ~stat.S_IXOTH)
    elif kind == "dir":
        sidecar_path.mkdir()
    # kind == "missing": create nothing
    return global_root


def _run_sidecar_check(tmp_path: Path, npm_root: Path) -> subprocess.CompletedProcess:
    """Copy the script to a scratch directory unrelated to `npm_root` and run
    it from there with no NODE_PATH - the real Dockerfile invocation shape
    (COPY to /tmp, run from /tmp), never the script's own repo location and
    never a directory above or beside the fixture. Uses the CODEX_NPM_ROOT
    test override, so it never exercises the `npm root -g` branch the real
    Docker build actually runs - see `_run_sidecar_check_via_real_npm_root`."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script_copy = scratch / SIDECAR_SCRIPT.name
    shutil.copy(SIDECAR_SCRIPT, script_copy)
    return subprocess.run(
        ["node", str(script_copy)],
        cwd=scratch,
        env={"CODEX_NPM_ROOT": str(npm_root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def _fake_npm(tmp_path: Path, root_output: Path) -> Path:
    """A fake `npm` on PATH whose `root -g` subcommand prints `root_output` -
    exercises the script's REAL (non-override) global-root discovery without
    a real npm install. Returns the directory to prepend to PATH."""
    npm_dir = tmp_path / "fake-npm-bin"
    npm_dir.mkdir()
    npm_script = npm_dir / "npm"
    npm_script.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = 'root' ] && [ \"$2\" = '-g' ]; then\n"
        f'  echo "{root_output}"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    npm_script.chmod(0o755)
    return npm_dir


def _run_sidecar_check_via_real_npm_root(tmp_path: Path, npm_root: Path) -> subprocess.CompletedProcess:
    """Same real invocation shape as `_run_sidecar_check`, but with NO
    CODEX_NPM_ROOT set - exercises `npmGlobalRoot()`'s `npm root -g`
    subprocess branch, the one every CODEX_NPM_ROOT-based test above
    bypasses and the one the real Docker build actually runs."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script_copy = scratch / SIDECAR_SCRIPT.name
    shutil.copy(SIDECAR_SCRIPT, script_copy)
    fake_npm_dir = _fake_npm(tmp_path, npm_root)
    return subprocess.run(
        ["node", str(script_copy)],
        cwd=scratch,
        env={"PATH": f"{fake_npm_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


@needs_node
def test_verify_codex_sidecar_accepts_a_valid_layout(tmp_path):
    npm_root = _fake_global_install(tmp_path)
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode == 0, result.stderr


@needs_node
def test_verify_codex_sidecar_uses_npm_root_dash_g_when_no_override_is_set(tmp_path):
    """The real invocation path (issue #78 review): no CODEX_NPM_ROOT is set
    in the Dockerfile, so `npm root -g` is asked directly. Every
    CODEX_NPM_ROOT-based test above bypasses this branch entirely."""
    npm_root = _fake_global_install(tmp_path)
    result = _run_sidecar_check_via_real_npm_root(tmp_path, npm_root)
    assert result.returncode == 0, result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_when_npm_root_dash_g_names_an_empty_directory(tmp_path):
    """Red case for the same branch: `npm root -g` succeeds but names a
    directory with no @openai/codex in it."""
    empty_root = tmp_path / "empty" / "node_modules"
    empty_root.mkdir(parents=True)
    result = _run_sidecar_check_via_real_npm_root(tmp_path, empty_root)
    assert result.returncode != 0
    assert "cannot resolve @openai/codex from the npm global root" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_when_codex_itself_is_absent(tmp_path):
    """Red case: the real operator failure (Dockerfile:80) - a bare
    require.resolve() from a script copied to /tmp can't see a real global
    install at all, however correctly npm installed it."""
    npm_root = _fake_global_install(tmp_path, codex_exists=False)
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode != 0
    assert "cannot resolve @openai/codex from the npm global root" in result.stderr


@needs_node
def test_verify_codex_sidecar_ignores_an_unrelated_codex_in_an_ancestor_directory(tmp_path):
    """Red case from a Codex code-review finding on this same fix:
    require.resolve(id, {paths}) does not confine its search to the given
    directory - it walks UP through every ancestor's own node_modules, so an
    unrelated @openai/codex two directories above the DECLARED (empty) npm
    root must not let this pass for the wrong installation."""
    ancestor_codex = tmp_path / "node_modules" / "@openai" / "codex"
    ancestor_codex.mkdir(parents=True)
    (ancestor_codex / "package.json").write_text('{"name": "@openai/codex", "type": "module"}', encoding="utf-8")
    declared_root = tmp_path / "empty-prefix" / "lib" / "node_modules"
    declared_root.mkdir(parents=True)
    result = _run_sidecar_check(tmp_path, declared_root)
    assert result.returncode != 0
    assert "cannot resolve @openai/codex from the npm global root" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_when_the_platform_package_is_absent(tmp_path):
    npm_root = _fake_global_install(tmp_path, platform_package_exists=False)
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode != 0
    assert "cannot resolve @openai/codex-linux-x64" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_missing_sidecar(tmp_path):
    """Red case: the exact issue #10 lesson A2 failure - codex installed,
    sidecar absent."""
    npm_root = _fake_global_install(tmp_path, sidecar=("missing", ""))
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode != 0
    assert "missing" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_directory_posing_as_the_sidecar(tmp_path):
    """Red case from the Codex review: a directory or non-executable file
    matching the name must not satisfy the check."""
    npm_root = _fake_global_install(tmp_path, sidecar=("dir", ""))
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode != 0
    assert "not a regular file" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_non_executable_sidecar(tmp_path):
    npm_root = _fake_global_install(tmp_path, sidecar=("file", "not-executable"))
    result = _run_sidecar_check(tmp_path, npm_root)
    assert result.returncode != 0
    assert "not executable" in result.stderr


def test_dockerfile_creates_a_fixed_candidate_user_and_matching_group():
    """Committed control for the owner ruling (2026-09-26): the image must
    create a real candidate:10001:10001 passwd/group entry, not depend on a
    bind-mounted, host-uid-matching container - the exact tradeoff the
    ruling rejected for #77's docker_backend.py."""
    text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    assert "groupadd --gid 10001 candidate" in text
    assert "useradd --uid 10001 --gid 10001" in text


def test_dockerfile_pre_creates_empty_claude_and_codex_dirs_owned_by_candidate():
    """Only the empty directories are baked in, owned by candidate - never
    seed content, which is per-trial (issue #78's own control)."""
    text = (REPO_ROOT / "docker" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    assert "mkdir -p /home/candidate/.claude /home/candidate/.codex" in text
    assert "chown -R candidate:candidate /home/candidate" in text


def test_check_pins_ignores_an_unrelated_arg():
    """Red case from the Codex review: an unrelated build arg (not shaped
    like a version pin) must not make an otherwise-agreeing check fail -
    'our thing changed' must stay distinguishable from 'a neighbour
    changed'."""
    check_pins = _load_check_pins()
    dockerfile_text = "ARG CLAUDE_CODE_VERSION=2.1.283\nARG CODEX_VERSION=0.157.1\nARG BUILD_LABEL=trial\n"
    manifest = {
        "claude_code": {"version": "2.1.283"},
        "codex": {"version": "0.157.1"},
    }
    assert check_pins.check_pins(dockerfile_text, manifest) == []


def test_check_pins_reports_a_stray_version_shaped_arg():
    check_pins = _load_check_pins()
    dockerfile_text = "ARG CLAUDE_CODE_VERSION=2.1.283\nARG CODEX_VERSION=0.157.1\nARG GEMINI_VERSION=1.0\n"
    manifest = {
        "claude_code": {"version": "2.1.283"},
        "codex": {"version": "0.157.1"},
    }
    messages = check_pins.check_pins(dockerfile_text, manifest)
    assert any("GEMINI_VERSION" in m for m in messages)


def test_check_pins_catches_a_new_manifest_pin_with_no_mapping_update():
    """Red case from the Codex review: a THIRD pin added to
    pinned-versions.json, with no matching ARG, must be caught without
    anyone having to remember to update a second, hand-maintained mapping in
    check_pins.py itself."""
    check_pins = _load_check_pins()
    dockerfile_text = "ARG CLAUDE_CODE_VERSION=2.1.283\nARG CODEX_VERSION=0.157.1\n"
    manifest = {
        "claude_code": {"version": "2.1.283"},
        "codex": {"version": "0.157.1"},
        "gemini": {"version": "1.0"},
    }
    messages = check_pins.check_pins(dockerfile_text, manifest)
    assert any("GEMINI_VERSION" in m for m in messages)


# --------------------------------------------------------------------------
# Per-trial home
# --------------------------------------------------------------------------


def test_build_trial_home_creates_a_fresh_empty_tree(tmp_path):
    home = tb.build_trial_home(tmp_path)
    assert home.home.is_dir()
    assert home.claude_home.is_dir()
    assert home.codex_home.is_dir()
    assert {p.name for p in home.home.iterdir()} == {".claude", ".codex"}


def test_build_trial_home_refuses_to_reuse_an_existing_home(tmp_path):
    tb.build_trial_home(tmp_path)
    with pytest.raises(tb.TrialHomeError):
        tb.build_trial_home(tmp_path)


# --------------------------------------------------------------------------
# Onboarding seed
# --------------------------------------------------------------------------

WORKDIR = PurePosixPath("/work")


def test_compose_claude_seed_clears_exactly_the_documented_gates():
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    assert set(seed) == tb.ALLOWED_SEED_KEYS
    assert seed["hasCompletedOnboarding"] is True
    assert seed["bypassPermissionsModeAccepted"] is True
    assert seed["projects"][str(WORKDIR)]["hasTrustDialogAccepted"] is True
    assert seed["projects"][str(WORKDIR)]["enabledMcpjsonServers"] == ["skillc-mcp"]
    assert seed["_skillc_seed_cli_version"] == "2.1.283"


def test_compose_claude_seed_refuses_an_unpinned_version():
    with pytest.raises(tb.SeedError):
        tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="")


def test_compose_claude_seed_refuses_a_relative_workdir():
    with pytest.raises(tb.SeedError):
        tb.compose_claude_seed(PurePosixPath("work"), ["skillc-mcp"], cli_version="2.1.283")


def test_validate_seed_before_launch_accepts_a_composed_seed(tmp_path):
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    seed_path = tb.write_claude_seed(claude_home, seed)
    loaded = tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")
    assert loaded == seed


def test_validate_seed_before_launch_refuses_a_missing_seed(tmp_path):
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(tmp_path / ".claude.json", WORKDIR, expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_invalid_json(tmp_path):
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_an_auto_answering_seed(tmp_path):
    """The red case for issue #78's own control: a seed carrying a key
    outside the deliberately-decided set is refused, not silently accepted -
    it stands in for a seed that would auto-answer some other prompt."""
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    seed["autoApproveEverything"] = True  # not in ALLOWED_SEED_KEYS
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_an_unaccepted_trust_dialog(tmp_path):
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    seed["projects"][str(WORKDIR)]["hasTrustDialogAccepted"] = False
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_the_wrong_workdir(tmp_path):
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, PurePosixPath("/somewhere/else"), expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_a_stale_cli_version(tmp_path):
    """Red case from the Codex review: a seed measured against one CLI
    version must not validate for launching a different, pinned version."""
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="1.0.0")
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")


def test_validate_seed_before_launch_refuses_a_second_undeclared_project(tmp_path):
    """Red case from the Codex review: a seed's OTHER project entry, not the
    one being launched into, must not be allowed to carry undeclared
    acceptance settings unnoticed - a per-trial seed has no legitimate
    reason to name a second project at all."""
    seed = tb.compose_claude_seed(WORKDIR, ["skillc-mcp"], cli_version="2.1.283")
    seed["projects"]["/somewhere/else"] = {"hasTrustDialogAccepted": True, "enabledMcpjsonServers": []}
    seed_path = tmp_path / ".claude.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    with pytest.raises(tb.SeedError):
        tb.validate_seed_before_launch(seed_path, WORKDIR, expected_cli_version="2.1.283")


# --------------------------------------------------------------------------
# Per-trial MCP config
# --------------------------------------------------------------------------


def test_compose_mcp_config_is_built_only_from_its_argument():
    servers = {"skillc-mcp": tb.MCPServerSpec(command="skillc-mcp-server", args=("--port", "0"), env={"FOO": "bar"})}
    config = tb.compose_mcp_config(servers)
    assert config == {
        "mcpServers": {
            "skillc-mcp": {"command": "skillc-mcp-server", "args": ["--port", "0"], "env": {"FOO": "bar"}}
        }
    }
    # Calling again with an empty mapping proves nothing carries over between calls.
    assert tb.compose_mcp_config({}) == {"mcpServers": {}}


def test_write_mcp_config_round_trips(tmp_path):
    config = tb.compose_mcp_config({"s": tb.MCPServerSpec(command="s")})
    path = tb.write_mcp_config(tmp_path / "mcp.json", config)
    assert json.loads(path.read_text(encoding="utf-8")) == config


# --------------------------------------------------------------------------
# Invocation
# --------------------------------------------------------------------------


def test_build_invocation_names_by_attempt_id_for_a_client_that_supports_it():
    """Claude Code's own binary documents --name; confirmed against the
    pinned 2.1.283 tarball."""
    invocation = tb.build_invocation("attempt-42", ["claude", "-p", "do the thing"], supports_name=True)
    assert invocation.argv == ("claude", "-p", "do the thing", "--name", "skillc-trial-attempt-42")
    assert invocation.env["GIT_TERMINAL_PROMPT"] == "0"


def test_build_invocation_adds_no_name_flag_for_a_client_that_lacks_it():
    """Red case from the Codex review: the pinned Codex release's `exec`
    subcommand parser accepts no --name flag - appending one unconditionally
    would fail argument parsing before the trial started."""
    invocation = tb.build_invocation("attempt-42", ["codex", "exec"], supports_name=False)
    assert invocation.argv == ("codex", "exec")
    assert invocation.env["GIT_TERMINAL_PROMPT"] == "0"


def test_build_invocation_refuses_remote_control():
    with pytest.raises(tb.InvocationError):
        tb.build_invocation("attempt-42", ["claude", "--remote-control"], supports_name=True)


def test_build_invocation_refuses_an_empty_attempt_id():
    with pytest.raises(tb.InvocationError):
        tb.build_invocation("", ["codex", "exec"], supports_name=False)


def test_build_invocation_merges_extra_env_without_overriding_git_prompt():
    invocation = tb.build_invocation("a1", ["codex"], supports_name=False, extra_env={"FOO": "bar"})
    assert invocation.env == {"GIT_TERMINAL_PROMPT": "0", "FOO": "bar"}


def test_build_invocation_refuses_an_extra_env_that_overrides_git_prompt():
    """Red case from the Codex review: extra_env silently overwriting the
    mandatory GIT_TERMINAL_PROMPT=0 must be refused, not accepted."""
    with pytest.raises(tb.InvocationError):
        tb.build_invocation("a1", ["codex"], supports_name=False, extra_env={"GIT_TERMINAL_PROMPT": "1"})


# --------------------------------------------------------------------------
# Prompt delivery, verified against the transcript
# --------------------------------------------------------------------------


def test_verify_first_user_message_accepts_a_match():
    tb.verify_first_user_message([{"role": "user", "content": "do the thing"}], "do the thing")


def test_verify_first_user_message_refuses_a_mismatch():
    """Red case: a transcript whose first user message differs from the
    prompt sent is refused (issue #78's own control)."""
    with pytest.raises(tb.PromptDeliveryError):
        tb.verify_first_user_message([{"role": "user", "content": "something else"}], "do the thing")


def test_verify_first_user_message_refuses_an_empty_transcript():
    with pytest.raises(tb.PromptDeliveryError):
        tb.verify_first_user_message([], "do the thing")


def test_verify_first_user_message_skips_non_user_events():
    events = [
        {"role": "system", "content": "setup"},
        {"role": "user", "content": "do the thing"},
    ]
    tb.verify_first_user_message(events, "do the thing")


# --------------------------------------------------------------------------
# Liveness canary: skill invocation AND a tool, tagged with a nonce
# --------------------------------------------------------------------------


def test_check_canary_accepts_a_live_transcript():
    nonce = tb.new_canary_nonce()
    events = [
        {"role": "user", "content": tb.compose_canary_instruction("tdd", nonce)},
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "tool": "Write", "input": {"content": f"touched:{nonce}"}, "output": f"touched:{nonce}"},
    ]
    tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_a_requested_but_failed_tool_call():
    """Red case from the Codex review: the nonce appearing in the tool
    call's INPUT (what was requested) must not satisfy the canary - only a
    confirmed, error-free OUTPUT proves the tool actually ran."""
    nonce = tb.new_canary_nonce()
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "tool": "Write", "input": {"content": f"touched:{nonce}"}, "error": "permission denied"},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_an_errored_tool_use_even_when_its_output_matches():
    """Adversarial red case (found by the orchestrator's own mutation
    testing on this PR): a tool_use whose OUTPUT contains the nonce marker -
    e.g. a tool that echoes its rejected request text into an error payload -
    must still be refused when the same event also carries an error. Without
    this case, `test_check_canary_refuses_a_requested_but_failed_tool_call`
    above is satisfied by the missing-output path alone, and the `error`
    check itself can be deleted with no test going red."""
    nonce = tb.new_canary_nonce()
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {
            "type": "tool_use",
            "tool": "Write",
            "error": "permission denied",
            "output": f"refused to write: touched:{nonce}",
        },
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_a_denied_tool_call_with_no_output_at_all():
    nonce = tb.new_canary_nonce()
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "tool": "Write", "input": {"content": f"touched:{nonce}"}},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_a_no_op_transcript():
    """Red case: a fake client that exits 0 having done nothing (an empty
    transcript) is refused as not-live."""
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary([], "tdd", tb.new_canary_nonce())


def test_check_canary_refuses_prose_that_never_touches_the_skill():
    """Red case: a client that answers plausibly without touching the
    installed skill is refused, whatever it says."""
    nonce = tb.new_canary_nonce()
    events = [{"role": "assistant", "content": f"Sure, I would write touched:{nonce} if you like."}]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_a_skill_invocation_with_no_tool_use():
    nonce = tb.new_canary_nonce()
    events = [{"type": "skill_invocation", "skill": "tdd"}]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_the_wrong_skill_name():
    nonce = tb.new_canary_nonce()
    events = [
        {"type": "skill_invocation", "skill": "diagnosing-bugs"},
        {"type": "tool_use", "tool": "Write", "output": f"touched:{nonce}"},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", nonce)


def test_check_canary_refuses_a_stale_nonce():
    """A tool_use event carrying a DIFFERENT attempt's nonce must not satisfy
    this attempt's canary."""
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "tool": "Write", "output": "touched:some-other-attempts-nonce"},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_canary(events, "tdd", tb.new_canary_nonce())


# --------------------------------------------------------------------------
# Sandbox decision
# --------------------------------------------------------------------------


def test_bwrap_decision_is_recorded_and_unsandboxed():
    assert tb.BWRAP_DECISION.sandboxed is False
    assert tb.BWRAP_DECISION.rationale

# --------------------------------------------------------------------------
# compose_canary_instruction's result_filename (issue #106)
# --------------------------------------------------------------------------


def test_compose_canary_instruction_default_filename_is_unchanged():
    """Omitting result_filename must produce EXACTLY the same text as
    before this parameter existed - every pre-#106 caller's prompt stays
    byte-identical."""
    nonce = tb.new_canary_nonce()
    assert tb.compose_canary_instruction("tdd", nonce) == (
        f"Before doing anything else, invoke the 'tdd' skill, then "
        f"use a tool to write the exact text 'touched:{nonce}' to a file "
        f"named 'skillc-canary-{nonce}.txt' in the working directory."
    )


def test_compose_canary_instruction_uses_the_given_result_filename():
    nonce = tb.new_canary_nonce()
    instruction = tb.compose_canary_instruction("tdd", nonce, result_filename=".skillc-canary-result")
    assert ".skillc-canary-result" in instruction
    assert f"skillc-canary-{nonce}.txt" not in instruction


# --------------------------------------------------------------------------
# check_agent_canary (issue #106)
# --------------------------------------------------------------------------


def test_check_agent_canary_accepts_a_skill_invocation_and_a_confirmed_tool_use():
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "output": "File created successfully at: /work/out.txt", "error": False},
    ]
    tb.check_agent_canary(events, "tdd")  # must not raise


def test_check_agent_canary_never_inspects_output_content():
    """The whole point of this function (#106): a real Write/exec result
    never echoes file content, so a confirmed tool_use with UNRELATED
    output must still satisfy it - unlike check_canary, which would refuse
    this for missing the nonce marker."""
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "output": "completely unrelated output, no nonce anywhere", "error": False},
    ]
    tb.check_agent_canary(events, "tdd")  # must not raise


def test_check_agent_canary_refuses_a_failed_tool_call():
    """Named red case (cross-model review): the file may exist (satisfying
    lifecycle's own backend content check) via a failed tool call in the
    transcript - the transcript proof must still refuse."""
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "output": "permission denied", "error": "permission denied"},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary(events, "tdd")


def test_check_agent_canary_refuses_no_skill_invocation():
    events = [{"type": "tool_use", "output": "ok", "error": False}]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary(events, "tdd")


def test_check_agent_canary_refuses_a_no_op_transcript():
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary([], "tdd")


def test_check_agent_canary_refuses_the_wrong_skill_name():
    events = [
        {"type": "skill_invocation", "skill": "diagnosing-bugs"},
        {"type": "tool_use", "output": "ok", "error": False},
    ]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary(events, "tdd")


# --------------------------------------------------------------------------
# Skill-free canary mode (issue #26 review): a SELECTION probe's own prompt
# must never name the skill it is trying to observe, or every "selected"
# result would be an artifact of the instruction, not a measurement.
# --------------------------------------------------------------------------


def test_compose_canary_instruction_skill_free_names_no_skill():
    """Red case (issue #26): the composed instruction must contain no skill
    name at all. Confirmed red by planting one into the skill-free branch
    before this test was added - see the mutation check below in the
    module's own review notes; a skill name appearing here would silently
    turn a selection probe's own instruction into the answer key."""
    nonce = tb.new_canary_nonce()
    instruction = tb.compose_canary_instruction(None, nonce)
    assert "invoke" not in instruction.lower()
    assert " skill" not in instruction.lower()  # the 'skillc-canary-...' default filename legitimately contains "skill"
    assert instruction == (
        f"Before doing anything else, use a tool to write the exact text "
        f"'touched:{nonce}' to a file named 'skillc-canary-{nonce}.txt' in the working directory."
    )


def test_compose_canary_instruction_named_mode_is_unchanged_alongside_skill_free():
    """Regression: adding the skill-free branch must not touch the existing
    named-skill text in any way."""
    nonce = tb.new_canary_nonce()
    assert tb.compose_canary_instruction("tdd", nonce) == (
        f"Before doing anything else, invoke the 'tdd' skill, then "
        f"use a tool to write the exact text 'touched:{nonce}' to a file "
        f"named 'skillc-canary-{nonce}.txt' in the working directory."
    )


def test_check_agent_canary_skill_free_accepts_a_confirmed_tool_use_alone():
    events = [{"type": "tool_use", "output": "anything", "error": False}]
    tb.check_agent_canary(events, None)  # must not raise - no skill clause to satisfy


def test_check_agent_canary_skill_free_ignores_any_skill_invocation_present():
    """A skill invocation happening to be present in skill-free mode is
    exactly the MEASUREMENT this mode exists to observe elsewhere
    (`TranscriptObservation.skill_invocations`) - the canary itself must
    neither require nor reject it."""
    events = [
        {"type": "skill_invocation", "skill": "tdd"},
        {"type": "tool_use", "output": "anything", "error": False},
    ]
    tb.check_agent_canary(events, None)  # must not raise


def test_check_agent_canary_skill_free_still_refuses_a_failed_tool_call():
    """Red case (issue #26's own acceptance: "a failed tool call is still
    not live"): skill-free mode drops the skill requirement, never the tool
    requirement."""
    events = [{"type": "tool_use", "output": "permission denied", "error": "permission denied"}]
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary(events, None)


def test_check_agent_canary_skill_free_refuses_a_no_op_transcript():
    with pytest.raises(tb.CanaryNotSatisfied):
        tb.check_agent_canary([], None)
