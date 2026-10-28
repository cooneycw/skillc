"""Retained-export controls run the public entry points without a paid trial.

The synthetic store is deliberately derived from the committed record shapes,
with fake payloads and a tiny unrelated subject. It is never called live evidence.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from test_profile import _profile, _source

from skillc import cli, materialize, profile, trial
from skillc import fixture_live as live
from skillc import retained_export as export

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "evals/retained-exports/d3-flow-check"
CONTROL = Path(__file__).parent / "fixtures/retained-export/controls.json"


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1) + "\n")


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _put(store: Path, blob: bytes) -> str:
    digest = trial.sha256_bytes(blob)
    (store / "objects").mkdir(exist_ok=True)
    (store / "objects" / digest.removeprefix("sha256:")).write_bytes(blob)
    return digest


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, Path]:
    """No private store, network, Docker, model, or monkeypatched validator."""
    source = _source(tmp_path / "subject")
    prof = _profile(tmp_path / "profile")
    inventory = profile.validate(prof, profile.DirTree(source))
    subject_digest = materialize.tree_digest(source / prof.subject.skills_root)
    declaration = _load(ROOT / "evals/level3/flow-check-route-live/declaration-draft.json")
    declaration["subject"].update(locator=prof.subject.locator, revision=prof.subject.revision)
    declaration["approval"]["profile_inventory_digest"] = export._digest(inventory)
    declaration["approval"]["declaration_digest"] = live.parse_declaration(declaration).digest
    declaration_digest = live.parse_declaration(declaration).digest
    declaration_path = tmp_path / "declaration.json"
    _json(declaration_path, declaration)
    run = tmp_path / "run"
    store = run / "store/synthetic"
    shutil.copytree(PUBLIC / "bundle", store)
    ledger = _load(store / "ledger.json")
    ledger["experiment_id"] = "synthetic-export-control"
    files = profile.installed_home_files(inventory, profile.DirTree(source))
    installed = [{"path": p, "digest": trial.sha256_bytes(v)} for p, v in sorted(files.items())]
    payload = b"synthetic fixture payload\n"
    payload_digest = _put(store, payload)
    for position, cell in enumerate(ledger["trials"], 1):
        cell["subject"]["digest"] = subject_digest
        cell["skill_digests"] = profile.skill_digest_pins(inventory)
        cell["config"]["digest"] = _put(store, trial.canonical({"mode": "live", "approved": True,
                                                    "declaration_digest": declaration_digest,
                                                    "case": "rangekit-green", "position": position,
                                                    "repeat": 1 if cell["trial_id"].startswith("t1") else 2}))
    _json(store / "ledger.json", ledger)
    digest = _put(store, (store / "ledger.json").read_bytes())
    (store / "ledger-history.jsonl").write_text(json.dumps({"digest": digest}) + "\n")
    (store / "journal").mkdir()
    for path in store.glob("lifecycle-*.json"):
        d = _load(path)
        (store / "journal" / (d["attempt_id"] + ".jsonl")).write_text(
            "".join(json.dumps(event) + "\n" for event in d["events"]))
    for path in store.glob("receipt-*.json"):
        d = _load(path)
        d["subject"] = {"locator": prof.subject.locator, "revision": f"snapshot:{subject_digest}",
                        "digest": subject_digest}
        d["installed"] = installed
        d["readiness"]["cache_key"]["tree_digest"] = subject_digest
        _json(path, d)
    for path in store.glob("manifest-*.json"):
        d = _load(path)
        d["artifacts"] = [{"path": "repo/report.json", "type": "file", "mode": "-",
                           "size": len(payload), "digest": payload_digest}]
        for obs in d["observations"]:
            obs.update(digest=payload_digest, size=len(payload), ref="objects/" + payload_digest[7:])
        _json(path, d)
    for path in store.glob("result-*.json"):
        d = _load(path)
        d["graded_digests"] = [payload_digest]
        def replace_refs(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "trusted_observation_digest":
                        value[key] = payload_digest
                    else:
                        replace_refs(child)
            elif isinstance(value, list):
                for child in value:
                    replace_refs(child)
        replace_refs(d)
        _json(path, d)
    original = {"kind": live.REPORT_KIND, "schema": live.SCHEMA, "experiment_id": ledger["experiment_id"],
                "declaration_digest": declaration_digest, "approved": True, "rehearsal": None,
                "attempts": [{"trial_id": c["trial_id"], "attempt_id": a["attempt_id"],
                              "case": "rangekit-green", "repeat": position}
                             for position, c in enumerate(ledger["trials"], 1) for a in c["attempts"]],
                "cases": {"rangekit-green": {"honest_report": {"SATISFIED": 0, "UNKNOWN": 2}}}}
    _json(run / "live-report.json", original)
    return {"run": run, "store": store, "declaration": declaration_path,
            "profile": tmp_path / "profile/profile.json", "snapshot": source, "out": tmp_path / "published"}


def _args(i: dict[str, Path]) -> list[str]:
    return ["retained-export", *[arg for key in ("run", "declaration", "profile", "snapshot", "out")
                                 for arg in ("--" + key, str(i[key]))]]


def test_retained_export_is_available_without_a_backend(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["retained-export", "--help"])
    assert caught.value.code == 0
    assert "reproduce" in capsys.readouterr().out


def test_production_export_preserves_source_and_reproduces(inputs: dict[str, Path]) -> None:
    before = export._fingerprint(inputs["run"])
    assert cli.main(_args(inputs)) == 0
    assert export._fingerprint(inputs["run"]) == before
    report, coverage = export.reproduce(inputs["out"])
    assert report == _load(inputs["out"] / "metadata/report.json")
    assert coverage == _load(inputs["out"] / "metadata/coverage.json")
    assert report["scheduled"] == 2
    assert [a["overall_status"] for a in report["attempts"]] == ["INCONCLUSIVE"] * 2
    assert [a["primary_endpoint_status"] for a in report["attempts"]] == ["PASS"] * 2
    assert report["honesty"]["original"]["rangekit-green"]["UNKNOWN"] == 2
    assert report["honesty"]["corrected"] == {"SATISFIED": 2, "VIOLATED": 0, "UNKNOWN": 0}
    assert len(coverage["trials"]) == 2
    assert len({v["identity"]["config"]["digest"] for v in coverage["trials"]}) == 2
    assert all(len(v["coverage"]["rows"]) == 1 for v in coverage["trials"])
    for attempt in report["attempts"]:
        assert attempt["fixture_finalization"] == "UNKNOWN"
        assert attempt["skill_evidence_records"] == 0
    assert cli.main(["retained-export", "--reproduce", str(inputs["out"])]) == 0


def _mutate(i: dict[str, Path], case: dict[str, Any]) -> None:
    operation = case["operation"]
    if operation == "remove":
        next(i["store"].glob(case["glob"])).unlink()
    elif operation == "tamper-object":
        ledger = _load(i["store"] / "ledger.json")
        digest = ledger["trials"][0]["config"]["digest"]
        (i["store"] / "objects" / digest[7:]).write_bytes(b"tampered")
    elif operation == "change-source":
        path = i["snapshot"] / case["path"]
        path.write_text(path.read_text() + "\n# changed\n")
    elif operation == "declaration":
        d = _load(i["declaration"])
        node = d
        for key in case["keys"][:-1]:
            node = node[key]
        node[case["keys"][-1]] = case["value"]
        _json(i["declaration"], d)
    elif operation == "config":
        ledger_path = i["store"] / "ledger.json"
        ledger = _load(ledger_path)
        cell = ledger["trials"][1]
        config = _load(i["store"] / "objects" / cell["config"]["digest"][7:])
        config[case["key"]] = case["value"]
        cell["config"]["digest"] = _put(i["store"], trial.canonical(config))
        _json(ledger_path, ledger)
        digest = _put(i["store"], ledger_path.read_bytes())
        (i["store"] / "ledger-history.jsonl").write_text(json.dumps({"digest": digest}) + "\n")
    elif operation == "record":
        path = next(i["store"].glob(case["glob"]))
        d = _load(path)
        node = d
        for key in case["keys"][:-1]:
            node = node[key]
        node[case["keys"][-1]] = case["value"]
        _json(path, d)
    else:
        raise AssertionError(operation)


@pytest.mark.parametrize("case", _load(CONTROL), ids=lambda c: c["name"])
def test_committed_refusals_publish_nothing_and_preserve_source(inputs: dict[str, Path],
                                                               case: dict[str, Any]) -> None:
    _mutate(inputs, case)
    before = export._fingerprint(inputs["run"])
    assert cli.main(_args(inputs)) == 2
    assert not inputs["out"].exists()
    assert export._fingerprint(inputs["run"]) == before


def test_public_reproduction_rejects_changed_or_missing_record(tmp_path: Path) -> None:
    copied = tmp_path / "public"
    shutil.copytree(PUBLIC, copied)
    path = next((copied / "bundle").glob("observation-*.json"))
    d = _load(path)
    d["reason"] = "a semantically legal but unreviewed alteration"
    _json(path, d)
    with pytest.raises(export.ExportRefused, match="hashes/population"):
        export.reproduce(copied)
    path.unlink()
    with pytest.raises(export.ExportRefused):
        export.reproduce(copied)


def test_public_real_export_is_reproducible_without_the_private_store() -> None:
    report, coverage = export.reproduce(PUBLIC)
    assert report == _load(PUBLIC / "metadata/report.json")
    assert coverage == _load(PUBLIC / "metadata/coverage.json")
    assert len(coverage["trials"]) == report["scheduled"] == 2


def test_export_never_replaces_a_destination(inputs: dict[str, Path]) -> None:
    inputs["out"].mkdir()
    marker = inputs["out"] / "operator.txt"
    marker.write_text("keep")
    assert cli.main(_args(inputs)) == 2
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("field", ["client", "case", "grader", "image", "subject_digest", "skill_digests"])
def test_public_reader_refuses_mismatched_trial_identity(tmp_path: Path, field: str) -> None:
    copied = tmp_path / "public"
    shutil.copytree(PUBLIC, copied)
    path = copied / "metadata/export.json"
    d = _load(path)
    d["identities"][field] = "a different identity"
    _json(path, d)
    assert cli.main(["retained-export", "--reproduce", str(copied)]) == 2


def test_source_overlap_is_refused_without_writing(inputs: dict[str, Path]) -> None:
    inputs["out"] = inputs["run"] / "export"
    before = export._fingerprint(inputs["run"])
    assert cli.main(_args(inputs)) == 2
    assert export._fingerprint(inputs["run"]) == before


def test_unretained_grading_envelope_is_refused(inputs: dict[str, Path]) -> None:
    path = next(inputs["store"].glob("result-*.json"))
    d = _load(path)
    d["verification"]["containment"]["trusted_observation_digest"] = "sha256:" + "f" * 64
    _json(path, d)
    assert cli.main(_args(inputs)) == 2
    assert not inputs["out"].exists()


def test_changed_task_builder_is_refused(inputs: dict[str, Path], tmp_path: Path) -> None:
    copied_root = tmp_path / "task-source"
    task = "evals/level3/flow-check-route"
    shutil.copytree(ROOT / task, copied_root / task)
    builder = copied_root / task / "builder/build.py"
    builder.write_text(builder.read_text() + "\n# changed\n")
    with pytest.raises(export.ExportRefused, match="builder/base-tree"):
        export.export_retained(inputs["run"], inputs["declaration"], inputs["profile"], inputs["out"],
                               snapshot=inputs["snapshot"], root=copied_root)
    assert not inputs["out"].exists()


def test_absent_endpoint_uses_composite_status(inputs: dict[str, Path]) -> None:
    declaration = _load(inputs["declaration"])
    del declaration["primary_endpoint"]
    digest = live.parse_declaration(declaration).digest
    declaration["approval"]["declaration_digest"] = digest
    _json(inputs["declaration"], declaration)
    ledger_path = inputs["store"] / "ledger.json"
    ledger = _load(ledger_path)
    for cell in ledger["trials"]:
        config = _load(inputs["store"] / "objects" / cell["config"]["digest"][7:])
        config["declaration_digest"] = digest
        cell["config"]["digest"] = _put(inputs["store"], trial.canonical(config))
    _json(ledger_path, ledger)
    ledger_digest = _put(inputs["store"], ledger_path.read_bytes())
    (inputs["store"] / "ledger-history.jsonl").write_text(json.dumps({"digest": ledger_digest}) + "\n")
    report_path = inputs["run"] / "live-report.json"
    original = _load(report_path)
    original["declaration_digest"] = digest
    _json(report_path, original)
    assert cli.main(_args(inputs)) == 0
    report, _ = export.reproduce(inputs["out"])
    assert [a["primary_endpoint_status"] for a in report["attempts"]] == ["INCONCLUSIVE"] * 2
    assert all(not a["primary_endpoint_declared"] for a in report["attempts"])


@pytest.mark.parametrize("field,value", [("skills", []), ("profile_digest", "sha256:changed"),
                                         ("endpoint", [])])
def test_public_metadata_cannot_change_the_population(field: str, value: Any) -> None:
    meta = _load(PUBLIC / "metadata/export.json")
    meta["identities"][field] = value
    with pytest.raises(export.ExportRefused):
        export.derive(export._bundle(PUBLIC / "bundle"), meta)


def test_embedded_inventory_bytes_are_checked() -> None:
    meta = _load(PUBLIC / "metadata/export.json")
    meta["identities"]["inventory"]["skills"][0]["files"][0]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(export.ExportRefused, match="inventory digest"):
        export.derive(export._bundle(PUBLIC / "bundle"), meta)


@pytest.mark.parametrize("field", ["shim_digest", "real_digest", "path"])
def test_per_attempt_shim_identity_is_required(field: str) -> None:
    meta = _load(PUBLIC / "metadata/export.json")
    aid = next(iter(meta["treatment_deviation_by_attempt"]))
    del meta["treatment_deviation_by_attempt"][aid][0][field]
    with pytest.raises(export.ExportRefused):
        export.derive(export._bundle(PUBLIC / "bundle"), meta)


def test_published_summary_is_compared_not_merely_recomputed(tmp_path: Path) -> None:
    copied = tmp_path / "public"
    shutil.copytree(PUBLIC, copied)
    path = copied / "metadata/report.json"
    d = _load(path)
    d["scheduled"] = 900
    _json(path, d)
    with pytest.raises(export.ExportRefused, match="published report"):
        export.reproduce(copied)


def test_dotdot_output_cannot_create_a_directory_inside_source(inputs: dict[str, Path]) -> None:
    before = set(inputs["run"].rglob("*"))
    inputs["out"] = inputs["run"] / "new" / ".." / ".." / "published"
    assert cli.main(_args(inputs)) == 0
    assert set(inputs["run"].rglob("*")) == before
    assert not (inputs["run"] / "new").exists()


def test_dangling_output_symlink_is_refused(inputs: dict[str, Path], tmp_path: Path) -> None:
    target = tmp_path / "fresh-target"
    inputs["out"].symlink_to(target, target_is_directory=True)
    before = export._fingerprint(inputs["run"])
    assert cli.main(_args(inputs)) == 2
    assert inputs["out"].is_symlink()
    assert not target.exists()
    assert export._fingerprint(inputs["run"]) == before
