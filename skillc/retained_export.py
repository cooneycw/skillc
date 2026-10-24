"""No-spend archival export of a retained fixture-live run (#556).

This preserves historical grades. It neither regrades nor certifies skill use.
Public reproduction checks the reviewed record bytes and report derivation;
private object verification happened at export time, not in that reproduction.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

from . import checks, coverage, leak, materialize, profile, records, trial, verify
from . import fixture_live as live

SCHEMA = 1
CORRECTION = {
    "issue": 534,
    "code_revision": "5ece908196fc5811293522c30fd3ab20b581a1aa",
    "source": "https://github.com/cooneycw/skillc/issues/529#issuecomment-6372334377",
    "route_correction": "https://github.com/cooneycw/skillc/issues/529#issuecomment-6371502671",
}


class ExportRefused(ValueError):
    """Publication is incomplete, inconsistent or unsafe."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise ExportRefused(reason)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    _require(isinstance(value, dict), f"{path.name}: expected an object")
    return value


def _digest(value: object) -> str:
    return trial.sha256_bytes(trial.canonical(value))


def _fingerprint(root: Path) -> dict[str, str]:
    """Refuse links rather than fingerprinting their targets outside the store."""
    out = {}
    files = 0
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), "retained source contains a symlink")
        if path.is_file():
            out[path.relative_to(root).as_posix()] = trial.sha256_bytes(path.read_bytes())
            files += 1
        else:
            _require(path.is_dir(), "retained source contains a non-regular entry")
            out[path.relative_to(root).as_posix() + "/"] = "directory"
    _require(files > 0, "retained source has no files")
    return out


def _validate(bundle: records.Bundle) -> None:
    errors = [f for r in bundle.records for f in checks.run_record(r) if f.severity == checks.ERROR]
    errors += [f for f in checks.run_bundle(bundle) if f.severity == checks.ERROR]
    _require(not errors, "bundle validation refused: " + "; ".join(f"{f.rule}: {f.detail}" for f in errors))


def _bundle(root: Path) -> records.Bundle:
    bundle = records.bundle_at(root)
    _require(bundle is not None, "exactly one retained ledger bundle is required")
    assert bundle is not None
    _validate(bundle)
    return bundle


def _body(record: records.Record) -> dict[str, Any]:
    return cast(dict[str, Any], record.data)


def _one(bundle: records.Bundle, kind: str, aid: str) -> records.Record:
    found = [r for r in bundle.of_kind(kind) if r.attempt_id == aid]
    _require(len(found) == 1, f"{aid}: expected exactly one {kind}")
    return found[0]


def _trusted_digests(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(v) for k, v in value.items() if k == "trusted_observation_digest"] + [
            d for v in value.values() for d in _trusted_digests(v)]
    if isinstance(value, list):
        return [d for v in value for d in _trusted_digests(v)]
    return []


def _outcome(criteria: list[dict[str, Any]], selected: list[str] | None) -> str:
    if selected is None:
        return records.derive_status(records.Record(Path("<composite>"), {"criteria": criteria}))
    _require(bool(selected), "a declared endpoint cannot be empty")
    by_id = {c["id"]: c["outcome"] for c in criteria}
    _require(all(name in by_id for name in selected), "declared endpoint criterion is absent")
    values = [by_id[name] for name in selected]
    return "FAIL" if "VIOLATED" in values else "PASS" if all(v == "SATISFIED" for v in values) else "INCONCLUSIVE"


def _inventory_join(expected: dict[str, Any]) -> None:
    inventory = expected["inventory"]
    _require(_digest(inventory) == expected["inventory_digest"], "inventory digest mismatch")
    _require(inventory["profile_digest"] == expected["profile_digest"], "inventory/profile identity mismatch")
    pins = profile.skill_digest_pins(inventory)
    _require(pins == expected["skill_digests"] and [p["path"] for p in pins] == expected["skills"],
             "declared skill selection differs from inventory")
    installed = {f["destination"]: f["digest"] for group in ("skills", "dependencies")
                 for entry in inventory[group] for f in entry["files"]}
    _require(installed == expected["installed"], "installed-file mapping differs from inventory")


def _deviation_join(deviations: list[dict[str, Any]], expected: dict[str, Any]) -> None:
    inventory = expected["inventory"]
    paths = set(inventory.get("bundled_gate_entrypoints", [])) | set(inventory.get("checkout_gate_entrypoints", {}))
    if inventory.get("gate_entrypoint"):
        paths.add(inventory["gate_entrypoint"])
    _require(all(isinstance(d.get("path"), str) for d in deviations), "witness deviation lacks a path")
    _require(sorted(d["path"] for d in deviations) == sorted(paths),
             "per-attempt witness deviation identities are missing or duplicated")
    for deviation in deviations:
        _require(expected["installed"].get(deviation.get("path")) == deviation.get("real_digest"),
                 "witness deviation real digest differs from declared closure")
        _require(isinstance(deviation.get("shim_digest"), str)
                 and re.fullmatch(r"sha256:[0-9a-f]{64}", deviation["shim_digest"]) is not None,
                 "witness deviation lacks a valid shim digest")


def derive(bundle: records.Bundle, meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reproduce summaries from records, retaining trial/config identity.

    The temporary ledger projection is a report view, never a new source record.
    No view combines attempts from different trials or invents skill-evidence.
    """
    _validate(bundle)
    ledger = bundle.of_kind(records.TRIAL_LEDGER)[0]
    trials = _body(ledger)["trials"]
    expected = meta["identities"]
    _inventory_join(expected)
    _require(ledger.data["experiment_id"] == meta["experiment_id"], "experiment identity changed")
    role = meta["honesty_criterion"]
    counts = dict.fromkeys(records.CRITERION_OUTCOMES, 0)
    attempts, views = [], []
    for cell in trials:
        _require(cell["subject"]["digest"] == expected["subject_digest"], "subject identity mismatch")
        _require(cell["client"] == expected["client"], "client identity mismatch")
        _require(cell["grader"] == expected["grader"], "grader identity mismatch")
        _require(cell["case"] == expected["case"], "case identity mismatch")
        _require(cell["image"] == expected["image"], "image identity mismatch")
        _require(cell.get("skill_digests") == expected["skill_digests"], "skill identity mismatch")
        aids = [a["attempt_id"] for a in cell["attempts"]]
        projected = records.Record(ledger.path, {**ledger.data, "trials": [cell]})
        members = [r for r in bundle.records if r.attempt_id in aids]
        view = records.Bundle(bundle.path, [projected, *members])
        _validate(view)
        inv = coverage.DeclaredInventory(tuple(expected["skills"]), expected["profile_digest"],
                                         expected["subject_digest"])
        report = coverage.assemble_coverage_report(view, inv).to_dict()
        identity = {key: copy.deepcopy(cell[key]) for key in ("trial_id", "case", "grader", "client", "image", "config")}
        views.append({"identity": identity, "source_ledger_digest": meta["record_digests"][ledger.path.name],
                      "source_records": {r.path.name: meta["record_digests"][r.path.name] for r in members},
                      "coverage": report})
        for aid in aids:
            result = _one(bundle, records.VERIFIED_RESULT, aid)
            _require(result.data["grader"] == cell["grader"], "result grader digest/identity mismatch")
            receipt = _one(bundle, records.INSTALLATION_RECEIPT, aid)
            receipt_body = _body(receipt)
            _require(receipt_body["image"] == expected["image"], "receipt image identity mismatch")
            subject = receipt_body["subject"]
            _require(subject["locator"] == expected["subject_locator"]
                     and subject["digest"] == expected["subject_digest"]
                     and subject["revision"] in (expected["subject_revision"],
                                                  "snapshot:" + expected["subject_digest"]),
                     "receipt subject provenance mismatch")
            cache = receipt_body["readiness"].get("cache_key")
            _require(cache is None or cache == {"image_digest": expected["image"]["digest"],
                                                "tree_digest": expected["subject_digest"]},
                     "receipt readiness cache identity mismatch")
            installed = {f["path"]: f["digest"] for f in _body(receipt)["installed"]}
            _require(installed == expected["installed"], "receipt does not match the declared closure")
            obs = _body(_one(bundle, records.AGENT_OBSERVATION, aid))
            census = (obs.get("transcript") or {}).get("census") or {}
            model = census.get("model")
            _require(model == expected["model_declared"], "client-reported model differs from declaration")
            criteria = _body(result)["criteria"]
            live.honesty_criterion(expected["task_path"], [c["id"] for c in criteria], complete=False)
            mine = [c for c in criteria if c["id"] == role]
            _require(len(mine) == 1, "historical honesty criterion is absent or duplicated")
            counts[mine[0]["outcome"]] += 1
            deviations = meta["treatment_deviation_by_attempt"].get(aid, [])
            _deviation_join(deviations, expected)
            attempts.append({"attempt_id": aid, "identity": identity,
                             "overall_status": records.derive_status(result), "criteria": criteria,
                             "primary_endpoint_status": _outcome(criteria, expected["endpoint"]),
                             "primary_endpoint_declared": expected["endpoint"] is not None,
                             "treatment_deviation": deviations,
                             "installation_readiness": receipt.data["readiness"],
                             "model_declared": expected["model_declared"], "model_client_reported": model,
                             "reasoning_effort_declared": expected["effort_declared"],
                             "reasoning_effort_independently_observed": "UNKNOWN",
                             "fixture_finalization": "UNKNOWN",
                             "skill_evidence_records": len([r for r in members if r.kind == records.SKILL_EVIDENCE]),
                             "skill_use_and_criterion_ownership": "not established without skill-evidence"})
    _require(len(attempts) == meta["scheduled"], "attempt denominator changed")
    return ({"schema": SCHEMA, "kind": "retained-historical-summary", "scheduled": len(attempts),
             "experiment_id": meta["experiment_id"], "attempts": attempts,
             "honesty": {"criterion": role, "original": meta["original_honesty"], "corrected": counts,
                         "correction": meta["correction"], "original_report_digest": meta["original_report_digest"]},
             "scope": "record-derived historical summary; not an independent regrade or skill-use certification"},
            {"schema": SCHEMA, "population": "separate trial views; never pooled", "trials": views})


def reproduce(export: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check exact published record hashes and reproduce the two summaries."""
    meta = _read(export / "metadata/export.json")
    _require(meta.get("schema") == SCHEMA, "unknown retained-export schema")
    bundle = _bundle(export / "bundle")
    actual = {p.name: trial.sha256_bytes(p.read_bytes()) for p in (export / "bundle").glob("*.json")}
    _require(actual == meta["record_digests"], "published record hashes/population differ from reviewed export")
    report, views = derive(bundle, meta)
    _require(_read(export / "metadata/report.json") == report, "published report differs from record derivation")
    _require(_read(export / "metadata/coverage.json") == views, "published coverage differs from record derivation")
    return report, views


def _pins(declaration: live.LiveDeclaration, prof: profile.Profile, tree: profile.Tree,
          scratch: Path, original: dict[str, Any], bundle: records.Bundle, root: Path) -> dict[str, Any]:
    data = declaration.data
    inventory = profile.validate(prof, tree)
    approval = declaration.approval or {}
    _require(approval.get("declaration_digest") == declaration.digest, "declaration approval digest mismatch")
    _require(approval.get("profile_inventory_digest") == _digest(inventory), "approved inventory identity mismatch")
    _require(data["subject"]["revision"] == prof.subject.revision, "profile subject revision mismatch")
    _require(data["subject"]["locator"] == prof.subject.locator, "profile subject locator mismatch")
    _require(original.get("declaration_digest") == declaration.digest, "live report declaration mismatch")
    _require(original.get("approved") is True and original.get("rehearsal") is None, "not an approved live population")
    # Recreate the acquisition's WHOLE skills-root identity, using pinned bytes.
    surface = scratch / "surface"
    surface.mkdir()
    prefix = prof.subject.skills_root.rstrip("/") + "/"
    for name in tree.under(prof.subject.skills_root):
        dest = surface / name.removeprefix(prefix)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(tree.read(name))
        dest.chmod(0o755 if tree.files()[name] == "100755" else 0o644)
    subject_digest = materialize.tree_digest(surface)
    homes = profile.installed_home_files(inventory, tree)
    grader = verify.GraderDef.load(root / declaration.task_path)
    _require(grader.id == data["task"]["grader_id"] and grader.revision == data["task"]["grader_revision"]
             and grader.digest() == data["task"]["grader_digest"], "task/grader source identity mismatch")
    _require(trial.sha256_bytes((root / declaration.task_path / "goal.md").read_bytes())
             == "sha256:" + data["task"]["goal_sha256"], "task goal identity mismatch")
    _require(trial.sha256_bytes((root / declaration.task_path / "builder/build.py").read_bytes())
             == "sha256:" + data["task"]["builder_sha256"], "task builder/base-tree identity mismatch")
    task_identity = live.task_identity(root, declaration.task_path)
    _require(all(data["task"].get(k) == v for k, v in task_identity.items()),
             "task builder/base-tree identity mismatch")
    ledger = _body(bundle.of_kind(records.TRIAL_LEDGER)[0])
    _require(original.get("experiment_id") == ledger["experiment_id"], "live report experiment mismatch")
    planned = [(t["trial_id"], a["attempt_id"]) for t in ledger["trials"] for a in t["attempts"]]
    reported = [(a["trial_id"], a["attempt_id"]) for a in original["attempts"]]
    _require(planned == reported and len(planned) == len(declaration.order), "live report/schedule population mismatch")
    return {"profile_digest": inventory["profile_digest"], "inventory_digest": _digest(inventory),
            "subject_revision": prof.subject.revision, "subject_locator": prof.subject.locator,
            "subject_digest": subject_digest, "client": data["shared"]["client"],
            "image": {"digest": data["shared"]["image"]["digest"]},
            "grader": {"id": grader.id, "revision": grader.revision, "digest": grader.digest()},
            "case": {"id": grader.id, "revision": grader.revision},
            "task_path": declaration.task_path, "task": dict(data["task"]),
            "model_declared": data["shared"]["model"], "effort_declared": data["shared"]["reasoning_effort"],
            "endpoint": list(declaration.endpoint) if declaration.endpoint is not None else None,
            "skill_digests": profile.skill_digest_pins(inventory),
            "skills": [p["path"] for p in profile.skill_digest_pins(inventory)],
            "installed": {p: trial.sha256_bytes(b) for p, b in sorted(homes.items())},
            "inventory": inventory}


def _build(run: Path, declaration_path: Path, profile_path: Path, repo: Path | None,
           snapshot: Path | None, stage: Path, scratch: Path, root: Path) -> None:
    declaration = live.load_declaration(declaration_path)
    prof = profile.Profile.load(profile_path)
    tree = profile.load_tree(prof, repo, snapshot)
    original = _read(run / "live-report.json")
    _require(original.get("kind") == live.REPORT_KIND and original.get("schema") == live.SCHEMA,
             "unknown fixture-live report kind/schema")
    stores = [p.parent for p in (run / "store").glob("*/ledger.json")]
    _require(len(stores) == 1, "expected exactly one retained experiment")
    source = stores[0]
    bundle = _bundle(source)
    record_hashes = {r.path.name: trial.sha256_bytes(r.path.read_bytes()) for r in bundle.records}
    # Recovery APIs are confined to this scratch copy, never the retained source.
    experiment = trial.Experiment.open(source)
    _require(record_hashes == {r.path.name: trial.sha256_bytes(r.path.read_bytes()) for r in bundle.records},
             "scratch recovery changed a record; historical bytes cannot be exported unchanged")
    objects = []
    for path in sorted((source / trial.OBJECTS).iterdir()):
        blob = trial.read_object(experiment, "sha256:" + path.name)
        objects.append({"digest": "sha256:" + path.name, "size": len(blob), "exported": False})
    _require(bool(objects), "no retained object bytes were checked")
    for manifest in bundle.of_kind(records.ARTIFACT_MANIFEST):
        for entry in _body(manifest)["artifacts"] + _body(manifest)["observations"]:
            if "digest" in entry:
                blob = trial.read_object(experiment, entry["digest"])
                _require(len(blob) == entry["size"], "manifest object size mismatch")
    for result in bundle.of_kind(records.VERIFIED_RESULT):
        for digest in _body(result).get("graded_digests", []) + _trusted_digests(_body(result).get("verification")):
            trial.read_object(experiment, digest)
    planned_attempts = list(experiment.attempts())
    _require(len(planned_attempts) == len(declaration.order) == len(original["attempts"]),
             "retained and declared attempt denominators differ")
    for position, (planned, attempt) in enumerate(planned_attempts, 1):
        config = json.loads(trial.read_object(experiment, cast(dict[str, Any], planned)["config"]["digest"]))
        _require(config.get("declaration_digest") == declaration.digest and config.get("mode") == "live"
                 and config.get("approved") is True, "configuration is not bound to this approved live declaration")
        _require(config.get("position") == position and config.get("case") == declaration.order[position - 1],
                 "configuration order/case differs from the declaration")
        _require(config.get("repeat") == declaration.order[:position].count(config.get("case")),
                 "configuration repeat differs from the declared schedule")
        reported = original["attempts"][position - 1]
        _require(config.get("repeat") == reported.get("repeat") and config.get("case") == reported.get("case")
                 and attempt["attempt_id"] == reported.get("attempt_id"),
                 "configuration differs from its reported attempt")
    identities = _pins(declaration, prof, tree, scratch, original, bundle, root)
    files = {r.path.name: trial.sha256_bytes(r.path.read_bytes()) for r in bundle.records}
    role = live.honesty_criterion(declaration.task_path, identities["endpoint"] or (), complete=False)
    _require(role is not None, "task has no honesty role; correction is not applicable")
    meta = {"schema": SCHEMA, "experiment_id": experiment.id, "scheduled": len(declaration.order),
            "declaration_digest": declaration.digest, "identities": identities, "record_digests": files,
            "original_report_digest": trial.sha256_bytes((run / "live-report.json").read_bytes()),
            "original_honesty": {name: value.get("honest_report") for name, value in original["cases"].items()},
            "honesty_criterion": role, "correction": CORRECTION,
            "withheld_objects": objects,
            "treatment_deviation": original.get("treatment_deviation"),
            "treatment_deviation_by_attempt": {
                a["attempt_id"]: a.get("treatment_deviation", []) for a in original["attempts"]},
            "validation": {"producer": "all record and bundle rules; all retained object byte hashes; exact identity joins",
                           "consumer": "consumer restated subset only; reviewed producer commit is the provenance boundary",
                           "public_reproduction": "record hashes and summary derivation; not private-byte checking or regrading"},
            "gaps": ["installation readiness UNKNOWN", "fixture finalization UNKNOWN",
                     "no independently certified skill use/criterion ownership without skill-evidence",
                     "raw transcripts, egress and controller envelopes withheld; no independent public regrade",
                     "single-arm green case; failed-launch/STOP and improvement unmeasured"]}
    report, views = derive(bundle, meta)
    (stage / "bundle").mkdir()
    (stage / "metadata").mkdir()
    for record in bundle.records:
        shutil.copyfile(record.path, stage / "bundle" / record.path.name)
    for name, value in (("export", meta), ("report", report), ("coverage", views)):
        (stage / "metadata" / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    _require(reproduce(stage) == (report, views), "public reproduction differs from producer summary")
    scan = leak.scan_path(stage, leak.load_denylist(), host_paths=leak.default_host_paths())
    _require(scan.scanned > 0 and not scan.skipped and not scan.findings,
             "publication leak check refused; nothing was published")


def export_retained(run: Path, declaration: Path, profile_path: Path, out: Path, *,
                    root: Path, repo: Path | None = None, snapshot: Path | None = None) -> None:
    """Publish to a fresh destination only, under a parent-directory lock."""
    # Lexically remove '..' before any mkdir, but inspect the requested leaf
    # before resolve() can dereference an existing dangling symlink.
    out = Path(os.path.abspath(out))
    _require(not out.is_symlink(), "output is a symlink; retained-export never follows it")
    run, out = run.resolve(), out.resolve()
    _require(run.is_dir(), "retained run directory is absent")
    _require(not out.resolve().is_relative_to(run) and not run.is_relative_to(out.resolve()),
             "output overlaps retained source")
    _require((repo is None) != (snapshot is None), "choose exactly one pinned repo or snapshot")
    before = _fingerprint(run)
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _require(not out.exists() and not out.is_symlink(), "output exists; retained-export never replaces it")
        with tempfile.TemporaryDirectory(prefix=".retained-export-", dir=out.parent) as temp:
            base = Path(temp)
            cloned = base / "source"
            shutil.copytree(run, cloned)
            stage = base / "publish"
            stage.mkdir()
            _build(cloned, declaration, profile_path, repo, snapshot, stage, base, root)
            _require(_fingerprint(run) == before, "source changed during export; publication refused")
            os.rename(stage, out)
    except (trial.Refused, live.LiveRefused, profile.Refused, verify.Refused, KeyError, TypeError) as exc:
        raise ExportRefused(str(exc)) from exc
    finally:
        os.close(lock)
        _require(_fingerprint(run) == before, "source changed during export")
