"""Tests for `skillc/configuration_compare.py` (issue #13, PR2): the
matched-configuration comparison, against synthetic fixture records only -
this module makes no agent or docker call of its own, and real runs are
operator-owed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import cli
from skillc import configuration_compare as ccmp
from skillc.trial import Refused


def _dims(functional: str = "PASS") -> dict[str, object]:
    return {
        "functional": {"verdict": functional, "criteria": []},
        "constraint": {"verdict": "not-applicable", "criteria": []},
        "integration": {"verdict": "not-applicable", "criteria": []},
        "unclassified": {"verdict": "not-applicable", "criteria": []},
    }


def _base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "task_id": "slug-constrained", "grader_revision": "1",
        "image_digest": "sha256:" + "ab" * 32, "client": "codex", "model": "gpt-6-astra",
        "timeout_seconds": 30, "collection": "subject-a", "outcome_dimensions": _dims(),
    }
    record.update(overrides)
    return record


def _write(tmp_path: Path, name: str, record: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _sub(d: dict[str, object], key: str) -> dict[str, object]:
    value = d[key]
    assert isinstance(value, dict)
    return value


def _recorded(*exclude: str) -> dict[str, str]:
    """A provenance block marking every `IDENTITY_FIELDS` entry `recorded`
    except the ones named - i.e. "earned" recorded status, the only way
    `load_record`'s `asserted` default is overridden."""
    return {field: "recorded" for field in ccmp.IDENTITY_FIELDS if field not in exclude}


# --------------------------------------------------------------- load_record


def test_a_well_formed_record_loads(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.json", _base_record())
    record = ccmp.load_record(path)
    assert record.task_id == "slug-constrained"
    assert record.collection == "subject-a"
    assert record.outcome_dimensions == _dims()


@pytest.mark.parametrize("missing_field", list(ccmp.IDENTITY_FIELDS))
def test_a_record_missing_any_identity_field_is_refused(tmp_path: Path, missing_field: str) -> None:
    """Review ruling: "a missing identity field on either side is a
    refusal, not a match: absent is not equal." Committed for every field,
    not just one."""
    record = _base_record()
    del record[missing_field]
    path = _write(tmp_path, "a.json", record)
    with pytest.raises(Refused, match=missing_field):
        ccmp.load_record(path)


def test_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(Refused, match="not JSON"):
        ccmp.load_record(path)


def test_a_non_object_top_level_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.json", [])  # type: ignore[arg-type]
    with pytest.raises(Refused, match="not an object"):
        ccmp.load_record(path)


def test_a_wrong_typed_identity_field_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.json", _base_record(client=123))
    with pytest.raises(Refused, match="client"):
        ccmp.load_record(path)


def test_a_non_number_timeout_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.json", _base_record(timeout_seconds="30"))
    with pytest.raises(Refused, match="timeout_seconds"):
        ccmp.load_record(path)


def test_missing_outcome_dimensions_is_refused(tmp_path: Path) -> None:
    record = _base_record()
    del record["outcome_dimensions"]
    path = _write(tmp_path, "a.json", record)
    with pytest.raises(Refused, match="outcome_dimensions"):
        ccmp.load_record(path)


def test_an_unreadable_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="cannot read"):
        ccmp.load_record(tmp_path / "does-not-exist.json")


def test_an_absent_provenance_defaults_every_field_to_asserted(tmp_path: Path) -> None:
    """Review ruling: the default must be the WEAKER claim. A generic
    record with no `provenance` block at all must not silently claim every
    identity field was recorded - JSON alone cannot support that."""
    record = ccmp.load_record(_write(tmp_path, "a.json", _base_record()))
    assert record.provenance == {field: ccmp.ASSERTED for field in ccmp.IDENTITY_FIELDS}


def test_a_partial_provenance_defaults_only_the_unmentioned_fields(tmp_path: Path) -> None:
    data = _base_record(provenance={"image_digest": "recorded"})
    record = ccmp.load_record(_write(tmp_path, "a.json", data))
    assert record.provenance["image_digest"] == ccmp.RECORDED
    assert record.provenance["timeout_seconds"] == ccmp.ASSERTED


def test_an_unknown_provenance_field_name_is_refused(tmp_path: Path) -> None:
    data = _base_record(provenance={"not_a_real_field": "asserted"})
    with pytest.raises(Refused, match="not_a_real_field"):
        ccmp.load_record(_write(tmp_path, "a.json", data))


def test_an_unknown_provenance_value_is_refused(tmp_path: Path) -> None:
    data = _base_record(provenance={"image_digest": "guessed"})
    with pytest.raises(Refused, match="guessed"):
        ccmp.load_record(_write(tmp_path, "a.json", data))


# ------------------------------------------------------------------- compare


def test_matched_configurations_compare_cleanly(tmp_path: Path) -> None:
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record(collection="subject-a")))
    b = ccmp.load_record(_write(tmp_path, "b.json", _base_record(collection="subject-b", outcome_dimensions=_dims("FAIL"))))
    result = ccmp.compare(a, b, "collection")
    assert result["vary"] == "collection"
    assert result["matched_fields"] == [f for f in ccmp.IDENTITY_FIELDS if f != "collection"]
    assert _sub(result, "per_dimension")["functional"] == {"a": "PASS", "b": "FAIL"}
    assert "descriptive only" in str(result["scope"])
    assert "n=1 each" in str(result["scope"])


def test_an_unmatched_configuration_is_refused_naming_every_mismatch(tmp_path: Path) -> None:
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record(collection="subject-a", client="codex")))
    b = ccmp.load_record(_write(
        tmp_path, "b.json", _base_record(collection="subject-b", client="claude-code", model="other-model"),
    ))
    with pytest.raises(Refused) as excinfo:
        ccmp.compare(a, b, "collection")
    message = str(excinfo.value)
    assert "client" in message and "codex" in message and "claude-code" in message
    assert "model" in message and "gpt-6-astra" in message and "other-model" in message
    assert "compatibility/product comparison" in message


def test_varying_field_itself_is_never_reported_as_a_mismatch(tmp_path: Path) -> None:
    """The whole point of --vary: the ONE field it names is exempt from the
    equality check, even though it legitimately differs."""
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record(model="model-a")))
    b = ccmp.load_record(_write(tmp_path, "b.json", _base_record(model="model-b")))
    result = ccmp.compare(a, b, "model")  # must not raise
    assert _sub(result, "a")["model"] == "model-a"
    assert _sub(result, "b")["model"] == "model-b"


def test_an_unknown_vary_field_is_refused(tmp_path: Path) -> None:
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record()))
    b = ccmp.load_record(_write(tmp_path, "b.json", _base_record()))
    with pytest.raises(Refused, match="not one of"):
        ccmp.compare(a, b, "not-a-real-field")


def test_missing_dimension_on_one_side_reports_none_not_a_crash(tmp_path: Path) -> None:
    a_dims = _dims()
    del a_dims["integration"]
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record(collection="subject-a", outcome_dimensions=a_dims)))
    b = ccmp.load_record(_write(tmp_path, "b.json", _base_record(collection="subject-b")))
    result = ccmp.compare(a, b, "collection")
    assert _sub(result, "per_dimension")["integration"] == {"a": None, "b": "not-applicable"}


def test_a_generic_record_with_no_provenance_flags_every_matched_field(tmp_path: Path) -> None:
    """Review-required red case for the inverted default: a plain,
    hand-written record (the generic input path this module documents -
    no `provenance` block at all) must not let a comparison read as if
    every identity field had been proven equal by a real record. Every
    MATCHED field - the full set except `vary` - lands in
    `unverified_matched_fields`, because nothing here earned `recorded`."""
    a = ccmp.load_record(_write(tmp_path, "a.json", _base_record(collection="subject-a")))
    b = ccmp.load_record(_write(tmp_path, "b.json", _base_record(collection="subject-b")))
    result = ccmp.compare(a, b, "collection")
    unverified_matched_fields = result["unverified_matched_fields"]
    assert isinstance(unverified_matched_fields, list)
    assert sorted(unverified_matched_fields) == sorted(f for f in ccmp.IDENTITY_FIELDS if f != "collection")
    assert "unverified_matched_fields_note" in result


def test_an_asserted_matched_field_is_labeled_unverified_not_proven(tmp_path: Path) -> None:
    """Review requirement (#13 PR2, citing #188): `image_digest`/
    `timeout_seconds` are caller-asserted rather than captured by
    `collection-run` today, so a comparison must not read as if a real
    record had proved they matched. Every OTHER matched field is marked
    `recorded` here so only `image_digest` is under test - it must appear
    in `unverified_matched_fields` with an explanatory note, even though
    both sides genuinely agree on its value."""
    a = ccmp.load_record(_write(
        tmp_path, "a.json",
        _base_record(collection="subject-a", provenance=_recorded("image_digest")),
    ))
    b = ccmp.load_record(_write(
        tmp_path, "b.json",
        _base_record(collection="subject-b", provenance=_recorded("image_digest")),
    ))
    result = ccmp.compare(a, b, "collection")
    assert result["unverified_matched_fields"] == ["image_digest"]
    assert "image_digest" in str(result["unverified_matched_fields_note"])
    assert "asserted" in str(_sub(result, "a")["provenance"])


def test_a_fully_recorded_comparison_omits_the_unverified_key_entirely(tmp_path: Path) -> None:
    """Negative control for the label above: when both sides EARNED
    `recorded` on every matched field, `unverified_matched_fields` must
    not appear at all - not as an empty list, so a reader cannot mistake
    "never checked" for "checked and found none asserted"."""
    a = ccmp.load_record(_write(
        tmp_path, "a.json", _base_record(collection="subject-a", provenance=_recorded()),
    ))
    b = ccmp.load_record(_write(
        tmp_path, "b.json", _base_record(collection="subject-b", provenance=_recorded()),
    ))
    result = ccmp.compare(a, b, "collection")
    assert "unverified_matched_fields" not in result
    assert "unverified_matched_fields_note" not in result


def test_an_asserted_but_varied_field_is_not_labeled_unverified(tmp_path: Path) -> None:
    """`--vary` exempts a field from the matched-fields check entirely, so
    an asserted provenance on the VARYING field must not appear in
    `unverified_matched_fields` - that list is about fields the comparison
    is claiming matched, and the varying field is never claimed to match.
    Every other field is marked `recorded` so only the varying field's
    (default) `asserted` status is under test."""
    a = ccmp.load_record(_write(
        tmp_path, "a.json", _base_record(model="model-a", provenance=_recorded("model")),
    ))
    b = ccmp.load_record(_write(
        tmp_path, "b.json", _base_record(model="model-b", provenance=_recorded("model")),
    ))
    result = ccmp.compare(a, b, "model")
    assert "unverified_matched_fields" not in result


# ------------------------------------------------------------------- the CLI


def test_cli_prints_the_comparison_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a_path = _write(tmp_path, "a.json", _base_record(collection="subject-a"))
    b_path = _write(tmp_path, "b.json", _base_record(collection="subject-b", outcome_dimensions=_dims("FAIL")))
    rc = cli.main(["configuration-compare", "--a", str(a_path), "--b", str(b_path), "--vary", "collection"])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["vary"] == "collection"
    assert printed["per_dimension"]["functional"] == {"a": "PASS", "b": "FAIL"}


def test_cli_refuses_an_unmatched_pair_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a_path = _write(tmp_path, "a.json", _base_record(collection="subject-a", client="codex"))
    b_path = _write(tmp_path, "b.json", _base_record(collection="subject-b", client="claude-code"))
    rc = cli.main(["configuration-compare", "--a", str(a_path), "--b", str(b_path), "--vary", "collection"])
    assert rc == 2
    assert "compatibility/product comparison" in capsys.readouterr().err
