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
# docker/trial/verify_codex_sidecar.js: resolves the REAL platform package,
# never the npm wrapper's own directory (Codex code-review finding on #78:
# an earlier version searched beside bin/codex.js, which is the wrong
# directory - confirmed by extracting the real 0.157.1 tarballs).
# --------------------------------------------------------------------------


def _fake_platform_package(root: Path, *, native_exists=True, sidecar=("file", "executable")):
    """A minimal fake `@openai/codex-linux-x64` layout under `root`, for
    `NODE_PATH` to resolve. `sidecar` is `(kind, mode)`: kind is 'file',
    'dir' or 'missing'; mode is 'executable' or 'not-executable'."""
    pkg_dir = root / "@openai" / "codex-linux-x64"
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
    return root


def _run_sidecar_check(node_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(SIDECAR_SCRIPT)],
        env={"NODE_PATH": str(node_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


@needs_node
def test_verify_codex_sidecar_accepts_a_valid_layout(tmp_path):
    _fake_platform_package(tmp_path)
    result = _run_sidecar_check(tmp_path)
    assert result.returncode == 0, result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_missing_sidecar(tmp_path):
    """Red case: the exact issue #10 lesson A2 failure - codex installed,
    sidecar absent."""
    _fake_platform_package(tmp_path, sidecar=("missing", ""))
    result = _run_sidecar_check(tmp_path)
    assert result.returncode != 0
    assert "missing" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_directory_posing_as_the_sidecar(tmp_path):
    """Red case from the Codex review: a directory or non-executable file
    matching the name must not satisfy the check."""
    _fake_platform_package(tmp_path, sidecar=("dir", ""))
    result = _run_sidecar_check(tmp_path)
    assert result.returncode != 0
    assert "not a regular file" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_a_non_executable_sidecar(tmp_path):
    _fake_platform_package(tmp_path, sidecar=("file", "not-executable"))
    result = _run_sidecar_check(tmp_path)
    assert result.returncode != 0
    assert "not executable" in result.stderr


@needs_node
def test_verify_codex_sidecar_refuses_when_the_platform_package_is_absent(tmp_path):
    result = _run_sidecar_check(tmp_path)  # empty NODE_PATH root
    assert result.returncode != 0
    assert "cannot resolve" in result.stderr


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
