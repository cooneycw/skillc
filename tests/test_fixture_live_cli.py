"""No-launch real opt-in controls. These never run a client or a container."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration_run as cr
from skillc import cli, credential, demo, lifecycle, trial
from skillc import collection_conformance as cc
from skillc import fixture_live as fl

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "evals/level3/campaign-434-live/campaign-declaration.json"
CASES = json.loads((ROOT / "tests/fixtures/fixture-preflight/cases.json").read_text())


def _forbidden(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("preflight attempted a launch/approval/image/private-store side effect")


@pytest.mark.parametrize("case", CASES["launch_environment"], ids=lambda c: c["name"])
def test_cli_launch_environment(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    if case["value"] is None:
        monkeypatch.delenv(lifecycle.ALLOW_REAL_AGENT_ENV, raising=False)
    else:
        monkeypatch.setenv(lifecycle.ALLOW_REAL_AGENT_ENV, case["value"])
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(fl, "require_approved", _forbidden)
    monkeypatch.setattr(cr, "private_root", _forbidden)
    monkeypatch.setattr(demo, "resolve_image_digest", _forbidden)
    monkeypatch.setattr(cc, "acquire_collection", _forbidden)
    monkeypatch.setattr(cc, "agent_backends", _forbidden)
    monkeypatch.setattr(credential, "resolve_path", _forbidden)
    monkeypatch.setattr(credential, "read_fresh", _forbidden)
    monkeypatch.setattr(fl, "run_live", _forbidden)
    monkeypatch.setattr(trial, "open_store", _forbidden)
    private = tmp_path / "must-not-exist"
    result = cli.main(["level3-live", str(DECLARATION), "--preflight-launch-env",
                       "--private-dir", str(private), "--credential", str(private / "unused")])
    assert not private.exists()
    assert result == case["exit"]
    output = capsys.readouterr()
    if result == 0:
        assert "current environment" in output.err and "opt-in" in output.err
        assert "readiness" not in output.err
    else:
        assert "SKILLC_ALLOW_REAL_AGENT=1" in output.err


@pytest.mark.parametrize("extra", [["--rehearse", "dry"], ["--rehearse", "actor"],
                                    ["--judge-replay", "unused"]])
def test_preflight_rejects_other_modes(extra: list[str], monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv(lifecycle.ALLOW_REAL_AGENT_ENV, "1")
    monkeypatch.setattr(fl, "load_declaration", _forbidden)
    assert cli.main(["level3-live", str(DECLARATION), "--preflight-launch-env", *extra]) == 2
    assert "cannot combine" in capsys.readouterr().err


def test_preflight_checks_the_same_pinned_argv_and_runtime_rechecks(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declaration = fl.load_declaration(DECLARATION)
    base = cc.DEFAULT_CLIENT_ARGVS[fl.CLIENT]
    monkeypatch.setenv(lifecycle.ALLOW_REAL_AGENT_ENV, "1")
    checked: list[list[str]] = []
    guard = lifecycle._refuse_real_agent

    def observe(argv: Any) -> None:
        checked.append(list(argv))
        guard(argv)

    monkeypatch.setattr(lifecycle, "_refuse_real_agent", observe)
    fl.preflight_launch_env(declaration, base)
    assert checked == [fl.live_client_argv(declaration, base)]
    assert checked[0] == [*base, "-m", str(declaration.shared["model"]),
                          "-c", f'model_reasoning_effort="{declaration.shared["reasoning_effort"]}"']
    monkeypatch.delenv(lifecycle.ALLOW_REAL_AGENT_ENV)
    # The real lifecycle driver must refuse before dereferencing even a backend,
    # experiment or limits. This is a later call, not a cached preflight verdict.
    with pytest.raises(lifecycle.RealAgentBlocked):
        lifecycle.run_through_backend(None, None, "unused", checked[0], {}, None, tmp_path)  # type: ignore[arg-type]


@pytest.mark.parametrize("measured", ["0.0.1", None])
def test_548_live_refuses_an_image_whose_client_is_not_the_declared_one(
        measured: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        tmp_path: Path) -> None:
    """#548: tag, ID and receipt bind (C3) and the checkout pin agrees, but the
    codex binary inside the image answers another version, or none: refused
    before any run store exists."""
    from skillc import trial_bootstrap

    declaration = fl.load_declaration(DECLARATION)
    shared = declaration.shared
    real_run = subprocess.run

    def clean_git(argv: list[str], *args: Any, **kwargs: Any) -> Any:
        if argv[:1] == ["git"]:
            return subprocess.CompletedProcess(argv, 0, "" if "status" in argv else "0" * 40 + "\n", "")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", clean_git)
    monkeypatch.setattr(fl, "require_approved", lambda *a, **k: None)
    monkeypatch.setattr(trial_bootstrap, "pinned_cli_version", lambda _: str(shared["client"]["version"]))
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a: str(shared["image"]["digest"]))
    monkeypatch.setattr(cr, "require_image_binding", lambda *a, **k: b"receipt")
    probes: list[str] = []

    def probe(_docker: object, image_id: str, client: str, **_k: object) -> trial_bootstrap.ClientProbe:
        probes.append(f"{client}@{image_id}")
        return trial_bootstrap.ClientProbe(measured, "measured" if measured else "`codex --version` exited 125")

    monkeypatch.setattr(trial_bootstrap, "probe_image_cli_version", probe)
    monkeypatch.setattr(cr, "private_root", _forbidden)
    monkeypatch.setattr(cc, "acquire_collection", _forbidden)
    assert cli.main(["level3-live", str(DECLARATION), "--rehearse", "actor",
                     "--private-dir", str(tmp_path / "private")]) == 2
    assert probes == [f"{fl.CLIENT}@{shared['image']['digest']}"]
    err = capsys.readouterr().err
    assert ("reports 0.0.1" if measured else "could not measure the codex client") in err
