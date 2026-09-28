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


def test_surface_refuses_a_claimed_limit_too_small_for_the_inside_marker() -> None:
    """Regression for a cross-model review finding (PR #90): a claimed limit
    smaller than the inside marker's own minimal footprint makes "expect
    EXPOSED" structurally impossible for any client, real or fake."""
    with pytest.raises(m.Refused, match="at least"):
        _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": 10}])


def test_surface_parses_index() -> None:
    surface = _surface(index={"path": "docs/idx.md", "targets": ["docs/a.md"]})
    assert surface.index == x.IndexFile("docs/idx.md", ("docs/a.md",))


def test_surface_refuses_index_without_a_path() -> None:
    with pytest.raises(m.Refused):
        _surface(index={"targets": ["docs/a.md"]})


def test_surface_refuses_index_with_a_non_string_target() -> None:
    with pytest.raises(m.Refused, match="targets"):
        _surface(index={"path": "docs/idx.md", "targets": [1]})


def test_surface_manifest_path_is_optional() -> None:
    assert _surface().manifest_path is None


def test_surface_parses_manifest_path() -> None:
    surface = _surface(manifest_path=".claude-plugin/plugin.json")
    assert surface.manifest_path == ".claude-plugin/plugin.json"


def test_surface_refuses_an_escaping_manifest_path() -> None:
    with pytest.raises(m.Refused, match="escapes"):
        _surface(manifest_path="../outside/plugin.json")


@pytest.mark.parametrize("bad", ["", 1, True, ["a"]])
def test_surface_refuses_a_non_string_manifest_path(bad: object) -> None:
    with pytest.raises(m.Refused, match="manifest_path"):
        _surface(manifest_path=bad)


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
    never a bare pass/fail against a prediction. Uses a realistically-shaped
    marker (the real `MARKER_PREFIX`, a label, then a nonce) since the
    truncation floor is deliberately deep into the nonce, past the shared
    prefix (cross-model review, PR #90: a shallow floor could match the
    shared prefix inside a DIFFERENT, fully-EXPOSED marker's own text)."""
    marker = x.Marker("id", f"{x.MARKER_PREFIX}TEST-0123456789abcdef", "layer", "note")
    cut = len(marker.text) - 4  # drop only the last 4 characters of the nonce
    rendered = "leading content " + marker.text[:cut]
    result = x.classify_marker(marker, rendered)
    assert result["verdict"] == x.TRUNCATED
    assert result["cut_point_bytes"] == cut


def test_classify_marker_reports_a_true_byte_offset_for_non_ascii_text() -> None:
    """Red case for issue #55's folded-in Nit Store item 3: `cut_point_bytes`
    names itself a byte offset, but the pre-fix search cut at a `str`
    (code point) index - identical to a byte index only while every
    character is ASCII, which every marker this module plants today is, so
    the bug was dormant. 'cafe' with an accent ('e' + U+0301, or the
    precomposed 'e-acute') encodes to more UTF-8 bytes than characters, so a
    character-index cut and a byte-index cut diverge as soon as truncation
    happens anywhere past it - and this fixture asserts that divergence is
    real, not accidentally ASCII again."""
    marker = x.Marker("id", f"{x.MARKER_PREFIX}TEST-café-0123456789abcdef", "layer", "note")
    marker_bytes = marker.text.encode("utf-8")
    assert len(marker.text) != len(marker_bytes), "fixture must be genuinely non-ASCII"
    byte_cut = len(marker_bytes) - 4  # drop the last 4 BYTES, not 4 characters
    rendered = "leading content " + marker_bytes[:byte_cut].decode("utf-8")
    result = x.classify_marker(marker, rendered)
    assert result["verdict"] == x.TRUNCATED
    assert result["cut_point_bytes"] == byte_cut


def test_marker_planted_just_beyond_a_limit_classifies_truncated_when_cut_mid_marker() -> None:
    """Regression-shaped proof for `_plant_always_loaded`'s own boundary
    construction: cutting NEAR THE END of the "outside" marker's own text
    (not before it, not after it) must classify TRUNCATED with the exact
    cut point - not merely HIDDEN, which a cut BEFORE the marker starts
    would also produce and would not exercise this path. Cuts only the last
    few characters, not halfway: the truncation floor deliberately requires
    most of the marker (including its nonce) to survive before accepting a
    TRUNCATED verdict, to rule out a short accidental match (cross-model
    review, PR #90)."""
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    content, (inside, outside) = x._plant_always_loaded(Path("/nonexistent"), entry)
    assert inside.text in content.decode()
    outside_start = content.index(outside.text.encode())
    near_end = len(outside.text) - 4
    rendered = content[: outside_start + near_end].decode(errors="replace")
    result = x.classify_marker(outside, rendered)
    assert result["verdict"] == x.TRUNCATED
    assert result["cut_point_bytes"] == near_end


def test_marker_planted_just_inside_a_limit_is_exposed_when_cut_exactly_at_the_limit() -> None:
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    content, (inside, _outside) = x._plant_always_loaded(Path("/nonexistent"), entry)
    rendered = content[:200].decode(errors="replace")
    assert x.classify_marker(inside, rendered)["verdict"] == x.EXPOSED


# ---------------------------------------------------- issue #55 folded-in item 1:
# the room = limit - len(base) - len(inside) - 1 boundary, at exact real offsets.
# `inside`'s own length is deterministic (MARKER_PREFIX + "INSIDE-" + a 16-hex
# nonce = 16 + 7 + 16 = 39 bytes, always ASCII), so `room` for a given `base`
# length and `limit` is exactly computable, not merely bounded.
_INSIDE_MARKER_LEN = len(x.MARKER_PREFIX) + len("INSIDE-") + 16


def test_plant_always_loaded_with_just_enough_room_ends_exactly_at_the_limit(
    tmp_path: Path,
) -> None:
    """Green case: `room == 0` exactly - the narrowest real file that still
    leaves just enough space for the inside marker to end AT the limit, not
    past it. Must behave like the ordinary (positive-room) branch, not the
    new untestable one, and the inside marker must classify EXPOSED when the
    render is cut exactly at the limit."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    limit = 200
    base_len = limit - _INSIDE_MARKER_LEN - 1  # room == 0
    (source_dir / "AGENTS.md").write_bytes(b"x" * base_len)
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=limit)
    content, (inside, _outside) = x._plant_always_loaded(source_dir, entry)
    assert "untestable" not in inside.note
    # The inside marker's own text ends one byte short of `limit` (the `- 1`
    # in `room`'s own formula is deliberate slack, not an off-by-one here) -
    # still safely within `limit`, never past it.
    end = content.index(inside.text.encode()) + len(inside.text)
    assert end == limit - 1
    rendered = content[:limit].decode(errors="replace")
    assert x.classify_marker(inside, rendered)["verdict"] == x.EXPOSED


def test_plant_always_loaded_one_byte_too_little_is_reported_untestable(
    tmp_path: Path,
) -> None:
    """Red case for issue #55 folded-in item 1: `room == -1`, one byte less
    than `test_..._with_just_enough_room...` above. `b"." * -1` silently
    produces `b""` (never an error), so the pre-fix code planted the inside
    marker immediately after the real content anyway, ending PAST `limit`,
    while its own note still unconditionally claimed it ended AT `limit` and
    should be `EXPOSED` - a conforming client that truncates exactly at
    `limit` then reports the marker `HIDDEN`, which reads as an exposure
    failure that is actually correct client behaviour. Must now say the
    boundary is untestable rather than claim `EXPOSED`, and must not place
    the marker as if `limit` bytes were available."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    limit = 200
    base_len = limit - _INSIDE_MARKER_LEN  # room == -1: one byte too little
    (source_dir / "AGENTS.md").write_bytes(b"x" * base_len)
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=limit)
    content, (inside, outside) = x._plant_always_loaded(source_dir, entry)
    assert "untestable" in inside.note
    assert "untestable" in outside.note
    assert "expect EXPOSED" not in inside.note
    # The real offset where the inside marker actually lands - `base_len`
    # bytes of real content, then this branch's own single b"\n" separator,
    # so the marker itself ends one byte PAST `limit`, proving the pre-fix
    # silent-b"" behaviour is what is being guarded against, not merely
    # asserting the note text changed.
    start = content.index(inside.text.encode())
    assert start == base_len + 1
    end = start + len(inside.text)
    assert end == limit + 1


def test_plant_always_loaded_already_over_the_limit_reports_the_real_length(
    tmp_path: Path,
) -> None:
    """The third boundary the issue names: the real file already exceeds
    `limit` on its own. Existing branch, given its own committed control and
    real-offset assertion here (previously untested directly)."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    limit = 200
    base_len = limit + 10
    (source_dir / "AGENTS.md").write_bytes(b"x" * base_len)
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=limit)
    content, (inside, outside) = x._plant_always_loaded(source_dir, entry)
    assert f"already {base_len} bytes" in inside.note
    assert f"already {base_len} bytes" in outside.note
    assert "expect EXPOSED" not in inside.note
    start = content.index(inside.text.encode())
    assert start == base_len + 1  # base, then a single b"\n" separator


def test_plant_always_loaded_preserves_the_real_file_content(tmp_path: Path) -> None:
    """Regression for a cross-model review finding (PR #90): an earlier
    draft discarded the real declared file entirely in the claimed-limit
    branch, replacing it with synthetic filler - measuring a fabricated
    stand-in's exposure, never the author's own declared content."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "AGENTS.md").write_text("REAL AUTHOR CONTENT MARKER\n", encoding="utf-8")
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    content, _markers = x._plant_always_loaded(source_dir, entry)
    assert b"REAL AUTHOR CONTENT MARKER" in content


def test_plant_index_preserves_the_real_declared_index_content(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "memory-index.md").write_text("REAL DECLARED INDEX CONTENT\n", encoding="utf-8")
    index = x.IndexFile(path="memory-index.md", targets=("docs/a.md",))
    content, _markers = x._plant_index(source_dir, index)
    assert b"REAL DECLARED INDEX CONTENT" in content


# ------------------------------------------------------------------ collisions


def test_check_collisions_catches_a_marker_that_matches_ambient_text() -> None:
    marker = x.Marker("id", "SKILLC-EXPOSURE-COLLIDE", "layer", "note")
    ambient = ["/some/checkout/path/contains/SKILLC-EXPOSURE-COLLIDE/here"]
    assert x.check_collisions([marker], ambient) == [marker]


def test_check_collisions_passes_when_markers_are_unique() -> None:
    marker = x.Marker("id", "SKILLC-EXPOSURE-UNIQUE-ABC123", "layer", "note")
    ambient = ["/some/unrelated/checkout/path", "an ordinary skill description"]
    assert x.check_collisions([marker], ambient) == []


def test_check_collisions_does_not_flag_a_short_ambient_substring_of_the_marker() -> None:
    """Regression for a cross-model review finding (PR #90): a skill merely
    named `topic` is not a real collision risk for a target marker
    `docs/topic-a.md` just because `topic` happens to be a substring of it -
    rendering the short ambient string cannot somehow produce the longer
    marker's own text. The pre-fix code checked both directions and flagged
    this as a collision."""
    marker = x.Marker("id", "docs/topic-a.md", "index-target", "note")
    assert x.check_collisions([marker], ["topic"]) == []


def test_check_exposure_refuses_when_a_target_name_collides_with_a_skill_description(
    tmp_path: Path,
) -> None:
    """Regression for a cross-model review finding (PR #90): the module's
    own docstring claimed a skill's description was part of the ambient
    collision population, but nothing actually collected it - a hidden index
    target whose name happened to appear in a rendered skill description
    would have read as a false EXPOSED instead of refusing the run."""
    collection = _snapshot(tmp_path)
    (collection / "greet" / "SKILL.md").write_text(
        '---\nname: greet\ndescription: "Mentions docs/topic-a.md by accident."\n---\nBody.\n',
        encoding="utf-8",
    )
    surface = _surface(
        select=["greet"], index={"path": "docs/memory-index.md", "targets": ["docs/topic-a.md"]},
    )
    client = _fake(tmp_path)
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=collection, client=client,
        client_name="codex", timeout=10,
    )
    assert report.status == "refused"
    assert "collision" in (report.reason or "")


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


def test_policy_control_same_skill_with_and_without_the_flag(tmp_path: Path) -> None:
    """The acceptance's own policy control, literally: ONE skill, run twice
    - once with `agents/openai.yaml`'s `policy.allow_implicit_invocation:
    false` present, once without - must give `HIDDEN` and `EXPOSED`
    respectively, reproducing the #11 table (not two different skills that
    merely happen to differ, as the general happy-path test below uses)."""
    collection = _snapshot(tmp_path)
    openai_yaml = collection / "greet" / "agents" / "openai.yaml"
    surface = _surface(select=["greet"])
    client = _fake(tmp_path)

    if openai_yaml.exists():
        openai_yaml.unlink()
    without_policy = x.check_exposure(
        surface, base=tmp_path / "base-without", snapshot=collection, client=client,
        client_name="codex", timeout=10,
    )
    assert without_policy.skills == [{"skill": "greet", "verdict": x.EXPOSED, "cause": None}]

    openai_yaml.parent.mkdir(parents=True, exist_ok=True)
    openai_yaml.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
    with_policy = x.check_exposure(
        surface, base=tmp_path / "base-with", snapshot=collection, client=client,
        client_name="codex", timeout=10,
    )
    assert with_policy.skills[0]["skill"] == "greet"
    assert with_policy.skills[0]["verdict"] == x.HIDDEN
    assert "policy" in str(with_policy.skills[0]["cause"])


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
    # No manifest_path declared - None, never conflated with "checked, no gap".
    assert report.manifest_coverage is None


# -------------------------------------------- issue #55 folded-in item 2:
# the "38 declared, 25 installed" manifest-coverage specimen (issue #53).


def test_check_exposure_manifest_coverage_reports_a_declared_but_not_found_skill(
    tmp_path: Path,
) -> None:
    """Red case: a distributor's manifest DECLARES a skill ('ghost') that
    this run's own `select`/`inventory()` never found - the ADR 0004
    specimen ('38 skill directories, 25 installed', issue #53). Nothing
    previously modelled this: `subject.select`'s own validation only proves
    every SELECTED name resolves ('greet', 'hidden' here), a claim about a
    different, smaller population than what the manifest as a whole
    declares."""
    snap = _snapshot(tmp_path)
    manifest_dir = snap / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "fixture-plugin", "skills": ["./greet", "./hidden", "./ghost"]}),
        encoding="utf-8",
    )
    surface = _surface(manifest_path=".claude-plugin/plugin.json")
    client = _fake(tmp_path, expose_paths=["AGENTS.md"])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=snap, client=client,
        client_name="codex", timeout=10,
    )
    assert report.status == "ok"
    assert report.manifest_coverage is not None
    assert report.manifest_coverage["manifest"] == ".claude-plugin/plugin.json"
    assert report.manifest_coverage["declared"] == 3
    assert report.manifest_coverage["found"] == 2
    assert report.manifest_coverage["missing"] == ["ghost"]


def test_check_exposure_manifest_coverage_is_clean_when_everything_declared_is_found(
    tmp_path: Path,
) -> None:
    """Green case beside the red one: a manifest declaring exactly what was
    found reports zero missing, proving the comparison is not simply always
    flagging a gap."""
    snap = _snapshot(tmp_path)
    manifest_dir = snap / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "fixture-plugin", "skills": ["./greet", "./hidden"]}),
        encoding="utf-8",
    )
    surface = _surface(manifest_path=".claude-plugin/plugin.json")
    client = _fake(tmp_path, expose_paths=["AGENTS.md"])
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=snap, client=client,
        client_name="codex", timeout=10,
    )
    assert report.manifest_coverage is not None
    assert report.manifest_coverage["declared"] == 2
    assert report.manifest_coverage["found"] == 2
    assert report.manifest_coverage["missing"] == []


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


def test_check_exposure_detects_truncation_mid_marker_despite_wrapper_and_trailing_content(
    tmp_path: Path,
) -> None:
    """Regression for a cross-model review finding (PR #90): `classify_marker`
    used to search only the very END of the whole rendered blob for a
    truncated marker's prefix, but a real render wraps planted content in
    closing tags (`</INSTRUCTIONS>`) and appends further messages afterward -
    so a marker cut mid-string almost never ends up at the literal tail.
    Drives the FULL render path (the fake client's own AGENTS.md wrapper and
    trailing prompt message included) with the cut landing exactly mid-way
    through the outside marker, and requires TRUNCATED, not HIDDEN - which a
    cut this far into the marker's own text should never produce."""
    entry = x.AlwaysLoadedFile(path="AGENTS.md", claimed_limit_bytes=200)
    snapshot = _snapshot(tmp_path)
    # Peeking at the layout: nonce VALUES differ between this call and the
    # one check_exposure makes internally, but byte OFFSETS depend only on
    # fixed lengths (a 16-hex-char nonce is always 16 characters), so the
    # computed cut point is positionally valid for the real run below.
    planted_content, (_inside, outside) = x._plant_always_loaded(snapshot, entry)
    outside_start = planted_content.index(outside.text.encode())
    cut_at = outside_start + len(outside.text) - 4  # cut only the last 4 characters

    surface = _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": 200}])
    client = _fake(tmp_path, expose_paths=["AGENTS.md"], truncate={"AGENTS.md": cut_at})
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=snapshot, client=client,
        client_name="codex", timeout=10,
    )
    markers = {m["marker_id"]: m for m in report.markers}
    assert markers["always_loaded:AGENTS.md:outside"]["verdict"] == x.TRUNCATED


def test_check_exposure_reports_a_real_truncation_from_the_fake_client(tmp_path: Path) -> None:
    """The full render path, not just `classify_marker` in isolation:
    the fake client actually cuts the rendered AGENTS.md block at a
    configured byte count, and the reported verdicts must reflect it."""
    surface = _surface(always_loaded=[{"path": "AGENTS.md", "claimed_limit_bytes": 200}])
    client = _fake(tmp_path, expose_paths=["AGENTS.md"], truncate={"AGENTS.md": 200})
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


def test_check_exposure_empty_output_reports_unmeasured_not_hidden(tmp_path: Path) -> None:
    """Regression for a real gap this PR's own review caught: exit 0 with
    empty stdout used to fall through to `status="ok"` with an empty
    `raw_text`, which classified every marker HIDDEN (a real, wrong verdict)
    rather than UNMEASURED (no render exists to judge). The acceptance
    names this exact case: "a render that fails, or returns empty output,
    gives UNMEASURED"."""
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}])
    client = _fake(tmp_path, mode="empty")
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    assert all(item["verdict"] == x.UNMEASURED for item in report.markers)
    assert all(item["verdict"] == x.UNMEASURED for item in report.skills)


def test_check_exposure_textless_response_reports_unmeasured_not_hidden(tmp_path: Path) -> None:
    """Regression for a cross-model review finding (PR #90): exit 0 with a
    well-formed but entirely textless JSON response (`[{"content": []}]`) is
    a DIFFERENT blind case from empty stdout - distinguishing them was the
    exact gap this test closes. Fails on the pre-fix code, which fell
    through to `status="ok"` with an empty `raw_text` and classified every
    marker/skill HIDDEN instead of UNMEASURED."""
    surface = _surface(always_loaded=[{"path": "AGENTS.md"}])
    client = _fake(tmp_path, mode="textless")
    report = x.check_exposure(
        surface, base=tmp_path / "base", snapshot=_snapshot(tmp_path), client=client,
        client_name="codex", timeout=10,
    )
    assert all(item["verdict"] == x.UNMEASURED for item in report.markers)
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
