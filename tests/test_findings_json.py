"""`skillc check --json`: one machine-readable findings document (issue #27).

The human CLI is unchanged (AGENTS.md/#27: "retain the current human-readable
CLI"); `--json` is an alternative rendering of the same findings, never mixed
with the prose report, so a consumer's `json.loads(stdout)` cannot land on a
run that happened to also print a human line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import cli
from skillc.spec import Skill


def _skill(tmp_path: Path, name: str, block: str) -> Skill:
    path = tmp_path / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{block}---\nbody\n", encoding="utf-8")
    return Skill.load(path)


def _write_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing manifest scoping.\n---\nBody.\n",
        encoding="utf-8",
    )


def test_json_output_is_the_only_thing_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: states a capability only\n")
    rc = cli.main(["check", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    assert rc == 0  # trigger-shape is a WARN; a warning alone does not fail the run
    payload = json.loads(out)  # raises if anything but one JSON document is present
    assert payload["schema"] == 1


def test_a_finding_carries_stable_rule_severity_path_and_detail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: states a capability only\n")
    cli.main(["check", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    [finding] = payload["findings"]
    assert finding["rule"] == "trigger-shape"
    assert finding["severity"] == "warn"
    assert finding["path"] == "x/SKILL.md"
    assert "triggering condition" in finding["detail"]


def test_a_clean_skill_reports_an_empty_findings_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: Use when x happens.\n")
    rc = cli.main(["check", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["findings"] == []
    assert payload["errors"] == 0
    assert payload["skills_checked"] == 1


def test_field_rules_are_represented_as_data_not_prose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: Use when x happens.\n")
    cli.main(["check", str(tmp_path), "--json", "--target", "claude-code"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["field_rules"] == {"target": "claude-code", "checked": 1, "total": 1}
    assert "field_rules_reason" not in payload


def test_field_rules_not_checked_names_the_reason_in_json_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: Use when x happens.\n")
    cli.main(["check", str(tmp_path), "--json", "--rule", "name-spec"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["field_rules"] is None
    assert payload["field_rules_reason"] == "rule 'name-spec' only"


def test_a_missing_path_refuses_with_a_json_error_not_stderr_prose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["check", str(tmp_path / "does-not-exist"), "--json"])
    out, err = capsys.readouterr()
    assert rc == 2
    payload = json.loads(out)
    assert "no such path" in payload["error"]
    # The human-mode message still goes to stderr - --json does not silence it,
    # it ADDS a machine-readable document a consumer never has to fall back to.
    assert "no such path" in err


def test_an_empty_population_refuses_with_a_json_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path.mkdir(exist_ok=True)
    rc = cli.main(["check", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "nothing was checked" in payload["error"]


def _write_manifest(plugin_root: Path, skills: list[str]) -> Path:
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_text(json.dumps({"name": "fixture", "skills": skills}), encoding="utf-8")
    return manifest_path


def test_manifest_scope_is_represented_as_data_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#53's --manifest scoping and #27's --json must compose: a manifest-scoped
    run reports declared/checked/undeclared as data, not only as the human line."""
    _write_skill(tmp_path / "skills" / "declared", "declared")
    _write_skill(tmp_path / "skills" / "extra", "extra")
    manifest_path = _write_manifest(tmp_path, ["./skills/declared"])

    rc = cli.main(["check", str(tmp_path), "--manifest", str(manifest_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["manifest_scope"] == {"declared": 1, "checked": 1, "undeclared": 1}


def test_a_dangling_manifest_entry_is_a_json_finding_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _write_manifest(tmp_path, ["./skills/missing"])

    rc = cli.main(["check", str(tmp_path), "--manifest", str(manifest_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    [finding] = payload["findings"]
    assert finding["rule"] == "manifest-entry"
    assert finding["severity"] == "error"


def test_an_empty_manifest_refuses_with_a_json_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _write_manifest(tmp_path, [])

    rc = cli.main(["check", str(tmp_path), "--manifest", str(manifest_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert "declares no skills" in payload["error"]


def test_strict_mode_agrees_between_human_and_json_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _skill(tmp_path, "x", "name: x\ndescription: states a capability only\n")
    human_rc = cli.main(["check", str(tmp_path), "--strict"])
    capsys.readouterr()
    json_rc = cli.main(["check", str(tmp_path), "--strict", "--json"])
    assert human_rc == json_rc == 1
