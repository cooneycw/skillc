"""A native recipe upgrade must not reidentify scripted actors (#637, #548)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from skillc import cli, demo, trial_bootstrap
from skillc import fixture_campaign as fc
from skillc import level3_campaign as lc

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGNS = [("campaign-434", fc), ("campaign-375", lc), ("campaign-271", lc)]


@pytest.mark.parametrize("campaign,engine", CAMPAIGNS)
def test_new_native_recipe_does_not_change_scripted_campaign_identity(campaign: str, engine: Any) -> None:
    manifest = engine.load_manifest(ROOT / "evals" / "level3" / campaign / "manifest.json")
    assert manifest.data["frozen"]["client"]["argv"] == "scripted actor; no model is contacted"
    assert manifest.data["frozen"]["client"]["version"] != trial_bootstrap.pinned_cli_version("codex")
    assert engine.check_frozen(manifest, ROOT) == []


@pytest.mark.parametrize("campaign,engine", CAMPAIGNS)
@pytest.mark.parametrize("damage,reason", [("subject", "revision"), ("client", "subject pin"),
                                           ("harness", "actor")])
def test_stale_scripted_identities_still_refuse(campaign: str, engine: Any, damage: str, reason: str) -> None:
    manifest = engine.load_manifest(ROOT / "evals" / "level3" / campaign / "manifest.json")
    data = copy.deepcopy(manifest.data)
    if damage == "subject":
        data["frozen"]["subject"]["revision"] = "0" * 40
    elif damage == "client":
        data["frozen"]["client"]["version"] = "999.0.0"
    else:
        data["frozen"]["harness_digest"] = "sha256:" + "0" * 64
    problems = engine.check_frozen(engine.Manifest(data, manifest.rows), ROOT)
    assert any(reason in problem for problem in problems), problems


def test_native_declaration_still_refuses_a_recipe_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Use the real historical native declaration and the actual new recipe pin.

    No synthetic matching-pin patch: the native path must retain this refusal.
    The guard fires before Docker allocation, credentials or model invocation.
    """
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *_: pytest.fail("image allocation reached"))
    private = tmp_path / "must-not-exist"
    result = cli.main(["calibration-run", str(ROOT / "evals" / "calibration-204" / "run-manifest.json"),
                       "--private-dir", str(private)])
    assert result == 2
    assert "trial image pins" in capsys.readouterr().err
    assert not private.exists()
