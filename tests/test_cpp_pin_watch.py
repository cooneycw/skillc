"""Committed drift inputs distinguish the public report from a blind reading."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_profile import PROFILE, SUBJECT, _profile, _source, _write

from skillc import cpp_pin_watch as watch
from skillc import profile

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / "controls/cpp-pin-watch/cases.json").read_text())


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Fixture tree")
    return _git(repo, "rev-parse", "HEAD")


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = _source(tmp_path / "source")
    for name in ("runner", "steps", "manifest"):
        _write(repo / f"lib/cicd/{name}.py", "SILENT_SUCCESS = False\n")
    _write(repo / "tools/counter-model-receipt.py", "SCHEMA = 4\n")
    _write(repo / "pack/skills/gate-check/reference.md", "Pinned reference.\n")
    _git(repo, "init", "-q")
    pin = _commit(repo)
    subject = {**SUBJECT, "locator": watch.CPP_LOCATOR, "revision": pin}
    data: dict[str, Any] = copy.deepcopy(PROFILE)
    data["dependencies"][2]["paths"].append("lib/cicd")
    data["dependencies"].append({"id": "receipt", "kind": "helper", "scope": "treatment",
        "source_root": "tools", "paths": ["counter-model-receipt.py"], "destination": ".helpers",
        "unreferenced_reason": "receipt contract control"})
    decl = _profile(tmp_path / "profile", subject=subject, **{k: v for k, v in data.items() if k != "subject"},
                    gate_entrypoint=".helpers/run-gate.sh")
    inventory = profile.validate(decl, profile.GitTree(repo, pin))
    evidence = tmp_path / "profile/evidence"
    evidence.mkdir()
    (evidence / "inventory.json").write_text(json.dumps(inventory))
    return repo, tmp_path / "profile", pin


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_committed_changes_classify_with_exact_evidence(tmp_path: Path, case: dict[str, Any]) -> None:
    repo, directory, pin = _fixture(tmp_path)
    changed = case.get("edit") or case.get("add") or case.get("remove")
    assert changed is None or isinstance(changed, str)
    if case.get("remove"):
        assert changed is not None
        (repo / changed).unlink()
    elif changed:
        _write(repo / changed, case.get("content", "Changed contract or library.\n"))
    target = _commit(repo) if changed else pin
    report = watch.classify(repo, directory, target)
    assert report["classification"] == case["classification"]
    assert report["flags"] == case["flags"]
    assert report["pin"] == pin and report["target"] == target
    assert report["unique_sources"] > 0
    evidence = report["changed"] + report["removed"] + report["added"]
    assert (changed in [e["path"] for e in evidence]) if changed else not evidence


@pytest.mark.parametrize("field", ["git_blob", "digest", "mode", "profile_digest", "population"])
def test_unreadable_or_unverified_inventory_is_unknown(tmp_path: Path, field: str) -> None:
    repo, directory, pin = _fixture(tmp_path)
    path = directory / "evidence/inventory.json"
    data = json.loads(path.read_text())
    if field == "profile_digest":
        data[field] = "sha256:" + "0" * 64
    elif field == "population":
        data["skills"][0]["files"].pop()
    else:
        data["skills"][0]["files"][0][field] = "100755" if field == "mode" else "0" * 40
    path.write_text(json.dumps(data))
    report = watch.classify(repo, directory, pin)
    assert report["classification"] == "unknown" and report["error"]


def test_missing_evidence_is_explicitly_derived_but_corrupt_evidence_is_not(tmp_path: Path) -> None:
    repo, directory, pin = _fixture(tmp_path)
    path = directory / "evidence/inventory.json"
    path.unlink()
    assert watch.classify(repo, directory, pin)["classification"] == "unknown"
    report = watch.classify(repo, directory, pin, allow_derived=True)
    assert report["classification"] == "none" and report["inventory_source"] == "derived"
    path.write_text("{")
    assert watch.classify(repo, directory, pin)["classification"] == "unknown"


def test_a_missing_git_object_or_inventory_file_cannot_report_none(tmp_path: Path) -> None:
    repo, directory, _ = _fixture(tmp_path)
    assert watch.classify(repo, directory, "0" * 40)["classification"] == "unknown"
    (directory / "profile.json").unlink()
    assert watch.classify(repo, directory, "0" * 40)["classification"] == "unknown"


def test_a_new_file_outside_selected_roots_is_outside_the_addition_census(tmp_path: Path) -> None:
    repo, directory, _ = _fixture(tmp_path)
    _write(repo / "lib/new-unselected.py", "Future dependency, not a closure claim.\n")
    report = watch.classify(repo, directory, _commit(repo))
    assert report["classification"] == "none" and report["added"] == []


def test_the_public_consumer_detects_a_blind_classifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, directory, _ = _fixture(tmp_path)
    _write(repo / "pack/skills/gate-check/reference.md", "Changed.\n")
    target = _commit(repo)
    correct = watch.classify(repo, directory, target)
    assert correct["classification"] == "contract"
    monkeypatch.setattr(watch, "classify", lambda *a: {**correct, "classification": "none", "flags": []})
    assert watch.reading([(directory, "fixture")], repo, target)["profiles"][0]["classification"] != "contract"
    # The same public assertion used by the committed reference case now fails.
    with pytest.raises(AssertionError):
        assert watch.reading([(directory, "fixture")], repo, target)["profiles"][0]["classification"] == "contract"


def _report(tmp_path: Path) -> dict[str, Any]:
    repo, directory, pin = _fixture(tmp_path)
    return watch.reading([(directory, "base:gate-check")], repo, pin)


def _comment(report: dict[str, Any]) -> dict[str, Any]:
    return {"user": {"login": "cooneycw"}, "body": watch.notice(report)}


def test_opt_in_poster_deduplicates_remote_classifications_not_commit_churn(tmp_path: Path) -> None:
    from ci import cpp_pin_watch as adapter

    report = _report(tmp_path)
    posted: list[dict[str, Any]] = []

    def write(body: str) -> dict[str, Any]:
        posted.append({"user": {"login": "cooneycw"}, "body": body})
        return {"id": len(posted)}

    assert adapter.publish(report, lambda: posted, write)["posted"]
    assert not adapter.publish(report, lambda: posted, write)["posted"]
    later = {**report, "target": "a" * 40}
    assert not adapter.publish(later, lambda: posted, write)["posted"]
    changed = copy.deepcopy(later)
    changed["profiles"][0].update(classification="contract", flags=["contract"])
    assert adapter.publish(changed, lambda: posted, write)["posted"]
    changed["profiles"][0]["flags"].append("structural")
    assert adapter.publish(changed, lambda: posted, write)["posted"]
    assert len(posted) == 3


def test_remote_marker_recheck_handles_lost_post_acknowledgement(tmp_path: Path) -> None:
    from ci import cpp_pin_watch as adapter

    report = _report(tmp_path)
    remote = []

    def uncertain(body: str) -> dict[str, Any]:
        remote.append({"user": {"login": "cooneycw"}, "body": body})
        raise OSError("lost acknowledgement after durable write")

    with pytest.raises(OSError):
        adapter.publish(report, lambda: remote, uncertain)
    assert not adapter.publish(report, lambda: remote, uncertain)["posted"]
    assert len(remote) == 1


@pytest.mark.parametrize("seed", [
    "-".join(("sc", "orch")), "mas" + "ter", ".".join(("192", "168", "20", "8")),  # noqa: FLY002
])
def test_generated_notice_refuses_seeded_identity_before_posting(tmp_path: Path, seed: str) -> None:
    from ci import cpp_pin_watch as adapter

    report = _report(tmp_path)
    report["profiles"][0]["changed"] = [{"path": f"scripts/{seed}.py"}]
    with pytest.raises(watch.WatchRefused, match="identity"):
        adapter.publish(report, lambda: pytest.fail("privacy failure read remote state"),
                        lambda _: pytest.fail("privacy failure posted"))


def test_malformed_own_marker_refuses_but_other_authors_cannot_set_state(tmp_path: Path) -> None:
    report = _report(tmp_path)
    other = _comment(report)
    other["user"]["login"] = "someone-else"
    assert watch.last_reading([other]) is None
    assert watch.transition_key(watch.last_reading([_comment(report)])) == watch.transition_key(report)  # type: ignore[arg-type]
    with pytest.raises(watch.WatchRefused):
        watch.last_reading([{"user": {"login": "cooneycw"}, "body": watch.MARKER + "{"}])


def test_unknown_transition_is_distinct_from_none_and_does_not_erase_history(tmp_path: Path) -> None:
    from ci import cpp_pin_watch as adapter

    known = _report(tmp_path)
    unknown = copy.deepcopy(known)
    unknown.update(ok=False)
    unknown["profiles"][0].update(classification="unknown", flags=[], error="fetch failed")
    remote = [_comment(known)]

    def write(body: str) -> dict[str, Any]:
        remote.append({"user": {"login": "cooneycw"}, "body": body})
        return {"id": len(remote)}

    assert adapter.publish(unknown, lambda: remote, write)["posted"]
    assert not adapter.publish(unknown, lambda: remote, write)["posted"]
    assert adapter.publish(known, lambda: remote, write)["posted"]
    assert len(remote) == 3


def test_default_command_is_read_only_and_fetch_failure_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from ci import cpp_pin_watch as adapter

    repo, directory, pin = _fixture(tmp_path)
    monkeypatch.setattr(adapter, "inputs", lambda *_: [(directory, "base:gate-check")])
    monkeypatch.setattr(adapter, "fetch_target", lambda _: pin)
    monkeypatch.setattr(adapter, "comments", list)
    monkeypatch.setattr(adapter, "create_comment", lambda _: pytest.fail("default command posted"))
    assert adapter.main(["--cpp-repo", str(repo)]) == 0
    assert '"would_post": true' in capsys.readouterr().out

    def fail(_: Path) -> str:
        raise watch.WatchRefused("fetch failed")

    monkeypatch.setattr(adapter, "fetch_target", fail)
    assert adapter.main(["--cpp-repo", str(repo)]) == 2
    text = capsys.readouterr().out
    assert '"classification": "unknown"' in text and '"classification": "none"' not in text


def test_post_requires_opt_in_and_cannot_publish_an_offline_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import cpp_pin_watch as adapter

    repo, directory, pin = _fixture(tmp_path)
    monkeypatch.setattr(adapter, "inputs", lambda *_: [(directory, "base:gate-check")])
    monkeypatch.setattr(adapter, "fetch_target", lambda _: pin)
    monkeypatch.setattr(adapter, "comments", list)
    posted: list[str] = []

    def write(body: str) -> dict[str, Any]:
        posted.append(body)
        return {"id": 1}

    monkeypatch.setattr(adapter, "create_comment", write)
    assert adapter.main(["--cpp-repo", str(repo), "--post", "--lock", str(tmp_path / "post.lock")]) == 0
    assert len(posted) == 1
    with pytest.raises(SystemExit):
        adapter.main(["--cpp-repo", str(repo), "--target", pin, "--post"])


@pytest.mark.parametrize("mutation", ["flags", "duplicate", "status"])
def test_malformed_machine_population_cannot_suppress_a_transition(tmp_path: Path, mutation: str) -> None:
    report = _report(tmp_path)
    if mutation == "flags":
        report["profiles"][0]["flags"] = ["contract"]
    elif mutation == "duplicate":
        report["profiles"].append(copy.deepcopy(report["profiles"][0]))
    else:
        report["ok"] = False
    body = watch.MARKER + json.dumps(report) + "\n-->"
    with pytest.raises(watch.WatchRefused):
        watch.last_reading([{"user": {"login": "cooneycw"}, "body": body}])


def test_local_post_lock_refuses_a_second_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    from ci import cpp_pin_watch as adapter

    repo, directory, pin = _fixture(tmp_path)
    monkeypatch.setattr(adapter, "inputs", lambda *_: [(directory, "base:gate-check")])
    monkeypatch.setattr(adapter, "fetch_target", lambda _: pin)
    monkeypatch.setattr(adapter, "comments", lambda: pytest.fail("locked writer read remote state"))
    path = tmp_path / "post.lock"
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert adapter.main(["--cpp-repo", str(repo), "--post", "--lock", str(path)]) == 2


def test_fetch_must_succeed_and_resolve_before_using_any_cached_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import cpp_pin_watch as adapter

    commands = []

    def fail_fetch(argv: list[str], **kwargs: Any) -> str:
        commands.append(argv)
        if "get-url" in argv:
            return adapter.REPOSITORY
        raise watch.WatchRefused("fetch refused")

    monkeypatch.setattr(adapter, "_run", fail_fetch)
    with pytest.raises(watch.WatchRefused):
        adapter.fetch_target(tmp_path)
    assert not any("rev-parse" in argv for argv in commands)


def test_post_requires_a_durable_matching_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import cpp_pin_watch as adapter

    monkeypatch.setattr(adapter, "_run", lambda argv, **kw: "cooneycw" if "user" in argv
                        else json.dumps({"id": 1, "body": "wrong"}))
    with pytest.raises(watch.WatchRefused, match="receipt"):
        adapter.create_comment("expected")
    monkeypatch.setattr(adapter, "_run", lambda argv, **kw: "cooneycw" if "user" in argv
                        else json.dumps({"id": 1, "body": "expected"}))
    assert adapter.create_comment("expected")["id"] == 1



def test_a_different_posting_author_is_refused_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from ci import cpp_pin_watch as adapter

    def wrong_author(argv: list[str], **kwargs: Any) -> str:
        assert "user" in argv, "POST must not run under an unread author"
        return "another-author"

    monkeypatch.setattr(adapter, "_run", wrong_author)
    with pytest.raises(watch.WatchRefused, match="identity"):
        adapter.create_comment("safe body")


def test_runtime_id_selects_a_profile_without_requiring_its_legacy_display_name(
    tmp_path: Path,
) -> None:
    import shutil

    from ci import cpp_pin_watch as adapter

    _, directory, pin = _fixture(tmp_path)
    root = tmp_path / "selection"
    shutil.copytree(directory, root / "evals/subjects/legacy-runtime")
    (root / "skillc").mkdir()
    policy = {"runtime_id": "legacy-runtime", "subject_locator": watch.CPP_LOCATOR,
              "subject_revision": pin, "gate_entrypoint": ".helpers/run-gate.sh"}
    (root / "skillc/runtime-policy.json").write_text(json.dumps(policy))
    (root / "skillc/runtime-policy-extra.json").write_text(json.dumps({"profile_runtimes": []}))
    selected = adapter.inputs(root, [])
    assert selected == [(root / "evals/subjects/legacy-runtime", "base:gate-check")]
    policy["gate_entrypoint"] = ".helpers/another-gate.sh"
    (root / "skillc/runtime-policy.json").write_text(json.dumps(policy))
    with pytest.raises(watch.WatchRefused):
        adapter.inputs(root, [])


def test_the_historical_control_rejects_a_blind_classifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, directory, _ = _fixture(tmp_path)
    _write(repo / "pack/skills/gate-check/reference.md", "Changed.\n")
    target = _commit(repo)
    correct = watch.classify(repo, directory, target)
    expected = {"profile": "profile", **{k: correct[k] for k in
                ("pin", "target", "classification", "flags", "unique_sources")},
                **{k: [e["path"] for e in correct[k]] for k in ("changed", "removed", "added")}}
    assert watch.historical_control(repo, tmp_path, expected)["classification"] == "contract"
    monkeypatch.setattr(watch, "classify", lambda *a: {**correct, "classification": "none", "flags": []})
    with pytest.raises(watch.WatchRefused, match="historical control"):
        watch.historical_control(repo, tmp_path, expected)


def test_changed_file_type_and_executable_mode_remain_visible(tmp_path: Path) -> None:
    repo, directory, _ = _fixture(tmp_path)
    path = repo / "lib/core/deep.py"
    path.chmod(0o755)
    report = watch.classify(repo, directory, _commit(repo))
    assert report["classification"] == "library-only"
    assert report["changed"][0]["after"]["mode"] == "100755"
    path.unlink()
    path.symlink_to("missing.py")
    assert watch.classify(repo, directory, _commit(repo))["classification"] == "structural"
