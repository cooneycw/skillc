"""Tests for `skillc exposure` (#55, ADR 0004 rung 2): measures what a
client actually renders into its session-start input, never what the
author's files merely declare.

Uses `fixtures/exposure/fake_codex_exposure.py`, distinct from
`materialize.py`'s own fake client, because this module needs a client that
can simulate an AGENTS.md-shaped always-loaded file and a configurable
truncation boundary - CI has no real Codex either way. Several facts this
fixture encodes were verified empirically against the REAL `codex-cli
0.157.1` while building this module (see `skillc/exposure.py`'s own
docstring and `evals/subjects/exposure-synthetic/SUBJECT.md`): only
`AGENTS.md` is auto-loaded (an arbitrary declared file is not, absent
something that actually surfaces it), and a skill whose `agents/openai.yaml`
sets `policy.allow_implicit_invocation: false` is excluded from the listing
entirely.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from skillc import cli
from skillc import exposure as x
from skillc import materialize as m

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "exposure"


def _snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "snapshot"
    if not snap.exists():
        shutil.copytree(FIXTURE / "collection", snap)
    return snap


def _fake(tmp_path: Path, mode: str = "normal", **config: object) -> list[str]:
    script = tmp_path / "client" / "fake_codex_exposure.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(FIXTURE / "fake_codex_exposure.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": mode, **config}), encoding="utf-8")
    return [sys.executable, str(script)]


def _surface_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "subject_schema": 1, "exposure_schema": 1,
        "locator": "test", "revision": "v1", "surface": "codex-skills",
        "skills_root": ".", "select": ["greet", "hidden"],
        "client": {"name": "codex", "version": "1"},
    }
    data.update(overrides)
    return data


def _surface(**overrides: object) -> x.ExposureSurface:
    return x.ExposureSurface.from_dict(_surface_data(**overrides))


# ------------------------------------------------------------------ schema


def test_minimal_surface_declares_no_extra_layers() -> None:
    surface = _surface()
    assert surface.always_loaded == ()
    assert surface.index is None


def test_surface_requires_exposure_schema() -> None:
    with pytest.raises(m.Refused, match="exposure_schema"):
        _surface(exposure_schema=2)


def test_surface_parses_always_loaded() -> None:
    surface = _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": 100}])
    assert surface.always_loaded == (x.AlwaysLoadedFile("AGENTS.md", 100),)


def test_surface_always_loaded_limit_is_optional() -> None:
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}])
    assert surface.always_loaded == (x.AlwaysLoadedFile("AGENTS.md", None),)


def test_surface_refuses_an_escaping_always_loaded_path() -> None:
    with pytest.raises(m.Refused, match="escapes"):
        _surface(always_loaded=[{"path": "../outside"}])


@pytest.mark.parametrize("limit", [0, -1, "100", 1.5, True])
def test_surface_refuses_a_bad_claimed_limit(limit: object) -> None:
    with pytest.raises(m.Refused, match="claimed_limit_bytes"):
        _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": limit}])


def test_surface_parses_index() -> None:
    surface = _surface(index={"path": "docs/idx.md", "targets": ["docs/a.md"]})
    assert surface.index == x.IndexFile("docs/idx.md", ("docs/a.md",))


def test_surface_refuses_index_without_a_path() -> None:
    with pytest.raises(m.Refused):
        _surface(index={"targets": ["docs/a.md"]})


def test_surface_refuses_index_with_a_non_string_target() -> None:
    with pytest.raises(m.Refused, match="targets"):
        _surface(index={"path": "docs/idx.md", "targets": [1]})


# --------------------------------------------------------------- classification


def test_classify_marker_exposed_on_a_full_match() -> None:
    marker = x.Marker("id", "MARK-full-123", "layer", "note")
    result = x.classify_marker(marker, "prefix MARK-full-123 suffix")
    assert result["verdict"] == x.EXPOSED


def test_classify_marker_hidden_when_entirely_absent() -> None:
    marker = x.Marker("id", "MARK-absent-123", "layer", "note")
    result = x.classify_marker(marker, "nothing relevant here")
    assert result["verdict"] == x.HIDDEN


def test_classify_marker_truncated_on_a_tail_prefix_and_names_the_cut_point() -> None:
    """The acceptance's own negative control, at the classification level:
    a marker cut mid-string must report TRUNCATED with the real cut point,
    never a bare pass/fail against a prediction."""
    marker = x.Marker("id", "MARK-boundary-0123456789", "layer", "note")
    cut = len("MARK-boundary-012")
    rendered = "leading content " + marker.text[:cut]
    result = x.classify_marker(marker, rendered)
    assert result["verdict"] == x.TRUNCATED
    assert result["cut_point_bytes"] == cut


def test_marker_planted_just_beyond_a_limit_classifies_truncated_when_cut_mid_marker() -> None:
    """Regression-shaped proof for `_plant_always_loaded`'s own boundary
    construction: cutting exactly through the "outside" marker's own text
    (not before it, not after it) must classify TRUNCATED with the exact
    cut point - not merely HIDDEN, which a cut BEFORE the marker starts
    would also produce and would not exercise this path."""
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    content, (inside, outside) = x._plant_always_loaded(Path("/nonexistent"), entry)
    assert inside.text in content.decode()
    outside_start = content.index(outside.text.encode())
    half = len(outside.text) // 2
    rendered = content[: outside_start + half].decode(errors="replace")
    result = x.classify_marker(outside, rendered)
    assert result["verdict"] == x.TRUNCATED
    assert result["cut_point_bytes"] == half


def test_marker_planted_just_inside_a_limit_is_exposed_when_cut_exactly_at_the_limit() -> None:
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    content, (inside, _outside) = x._plant_always_loaded(Path("/nonexistent"), entry)
    rendered = content[:200].decode(errors="replace")
    assert x.classify_marker(inside, rendered)["verdict"] == x.EXPOSED


# ------------------------------------------------------------------ collisions


def test_check_collisions_catches_a_marker_that_matches_ambient_text() -> None:
    marker = x.Marker("id", "SKILLC-EXPOSURE-COLLIDE", "layer", "note")
    ambient = ["/some/checkout/path/contains/SKILLC-EXPOSURE-COLLIDE/here"]
    assert x.check_collisions([marker], ambient) == [marker]


def test_check_collisions_passes_when_markers_are_unique() -> None:
    marker = x.Marker("id", "SKILLC-EXPOSURE-UNIQUE-ABC123", "layer", "note")
    ambient = ["/some/unrelated/checkout/path", "an ordinary skill description"]
    assert x.check_collisions([marker], ambient) == []


def test_check_exposure_refuses_the_whole_run_on_a_marker_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: a skill whose own NAME happens to equal a planted marker
    must invalidate the run, not silently produce a misleading EXPOSED
    verdict for that marker."""
    monkeypatch.setattr(x, "_nonce", lambda: "fixed")
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}], select=["greet"])
    # The always_loaded marker with no claimed limit is
    # f"{MARKER_PREFIX}ALWAYS-fixed" - rename a skill to exactly that.
    collection = _snapshot(tmp_path)
    colliding_name = f"{x.MARKER_PREFIX}ALWAYS-fixed"
    (collection / "greet" / "SKILL.md").write_text(
        f'---\nname: "{colliding_name}"\ndescription: Colliding on purpose.\n---\nBody.\n',
        encoding="utf-8",
    )
    surface = x.ExposureSurface.from_dict(_surface_data(
        always_loaded=[{"path": "AGENTS.md"}], select=[colliding_name],
    ))
    client = _fake(tmp_path, expose_paths=["AGENTS.md"])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=collection, client=client,
        client_name="codex", timeout=10,
    )
    assert report.status == "refused"
    assert "collision" in (report.reason or "")


# --------------------------------------------------------------- end to end


def test_check_exposure_happy_path_all_three_layers(tmp_path: Path) -> None:
    surface = _surface(
        always_loaded=[{"path": "AGENTS.md"}],
        index={"path": "docs/memory-index.md", "targets": ["docs/topic-a.md"]},
    )
    client = _fake(tmp_path, expose_paths=["AGENTS.md"])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    assert report.status == "ok"
    by_layer = {m["layer"]: m for m in report.markers}
    assert by_layer["always_loaded:AGENTS.md"]["verdict"] == x.EXPOSED
    # Not in expose_paths - matches real codex-cli 0.157.1, which does not
    # auto-surface an arbitrary declared file (verified empirically).
    assert by_layer["index"]["verdict"] == x.HIDDEN
    assert by_layer["index-target"]["verdict"] == x.HIDDEN

    skills = {s["skill"]: s for s in report.skills}
    assert skills["greet"]["verdict"] == x.EXPOSED
    assert skills["hidden"]["verdict"] == x.HIDDEN
    assert skills["hidden"]["cause"] and "policy" in str(skills["hidden"]["cause"])


def test_check_exposure_index_is_exposed_when_the_client_actually_loads_it(tmp_path: Path) -> None:
    surface = _surface(index={"path": "docs/memory-index.md", "targets": ["docs/topic-a.md"]})
    client = _fake(tmp_path, expose_paths=["docs/memory-index.md"])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    by_layer = {m["layer"]: m for m in report.markers}
    assert by_layer["index"]["verdict"] == x.EXPOSED
    assert by_layer["index-target"]["verdict"] == x.EXPOSED


def test_check_exposure_reports_a_real_truncation_from_the_fake_client(tmp_path: Path) -> None:
    """The full render path, not just `classify_marker` in isolation:
    the fake client actually cuts the rendered AGENTS.md block at a
    configured byte count, and the reported verdicts must reflect it."""
    surface = _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": 60}])
    client = _fake(tmp_path, expose_paths=["AGENTS.md"], truncate={"AGENTS.md": 60})
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    markers = {m["marker_id"]: m for m in report.markers}
    assert markers["always_loaded:AGENTS.md:inside"]["verdict"] == x.EXPOSED
    assert markers["always_loaded:AGENTS.md:outside"]["verdict"] in (x.TRUNCATED, x.HIDDEN)


def test_check_exposure_blindness_reports_unmeasured_never_empty(tmp_path: Path) -> None:
    """The acceptance's blindness control: a render that fails gives
    UNMEASURED for every declared item, never an empty list (which would
    read as "nothing to check" rather than "blind")."""
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}])
    client = _fake(tmp_path, mode="crash")
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    assert report.status == "ok"
    assert report.markers
    assert all(item["verdict"] == x.UNMEASURED for item in report.markers)
    assert report.skills
    assert all(item["verdict"] == x.UNMEASURED for item in report.skills)


def test_check_exposure_absent_client_reports_unmeasured(tmp_path: Path) -> None:
    surface = _surface()
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=None,
        client_name="codex", timeout=10,
    )
    assert all(item["verdict"] == x.UNMEASURED for item in report.skills)


def test_check_exposure_claude_code_is_always_unmeasured_with_no_client_call(tmp_path: Path) -> None:
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=None,
        client_name="claude-code", timeout=10,
    )
    assert report.status == "ok"
    assert report.markers and all(item["verdict"] == x.UNMEASURED for item in report.markers)
    assert report.skills and all(item["verdict"] == x.UNMEASURED for item in report.skills)
    assert all(x.CLAUDE_CODE_UNMEASURED_REASON == item["note"] for item in report.markers)


def test_check_exposure_refuses_an_unsupported_client_name(tmp_path: Path) -> None:
    surface = _surface()
    with pytest.raises(m.Refused, match="unsupported client"):
        x.check_exposure(
            surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=None,
            client_name="something-else", timeout=10,
        )


# ------------------------------------------------------------------------- CLI


def _write_surface(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(_surface_data(**overrides)), encoding="utf-8")
    return path


def test_cli_exit_is_zero_when_every_declared_item_is_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    client = _fake(tmp_path, expose_paths=["AGENTS.md"])
    Path(client[1]).chmod(0o755)
    monkeypatch.setattr(m, "find_client", lambda _explicit: client)
    surface = _write_surface(tmp_path, always_loaded=[{"path": "AGENTS.md"}])
    out = tmp_path / "out"
    code = cli.main([
        "exposure", str(surface), "--snapshot", str(_snapshot(tmp_path)),
        "--out", str(out), "--client-bin", client[1], "--base", str(tmp_path / "base"),
    ])
    assert code == 0
    assert "measured" in capsys.readouterr().out
    assert (out / "report.json").is_file()


def test_cli_exit_is_one_when_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    client = _fake(tmp_path, mode="crash")
    Path(client[1]).chmod(0o755)
    monkeypatch.setattr(m, "find_client", lambda _explicit: client)
    surface = _write_surface(tmp_path)
    out = tmp_path / "out"
    code = cli.main([
        "exposure", str(surface), "--snapshot", str(_snapshot(tmp_path)),
        "--out", str(out), "--client-bin", client[1], "--base", str(tmp_path / "base"),
    ])
    assert code == 1
    assert "UNMEASURED" in capsys.readouterr().out


def test_cli_exit_is_two_and_refuses_to_overwrite_existing_evidence(tmp_path: Path) -> None:
    surface = _write_surface(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.json").write_text("{}", encoding="utf-8")
    code = cli.main([
        "exposure", str(surface), "--snapshot", str(_snapshot(tmp_path)),
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])
    assert code == 2


def test_cli_exit_is_two_on_a_malformed_surface(tmp_path: Path) -> None:
    surface = tmp_path / "bad.json"
    surface.write_text(json.dumps({"exposure_schema": 1}), encoding="utf-8")
    code = cli.main([
        "exposure", str(surface), "--snapshot", str(_snapshot(tmp_path)),
        "--out", str(tmp_path / "out"), "--base", str(tmp_path / "base"),
    ])
    assert code == 2
