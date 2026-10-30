"""Synthetic-only oracle controls; no downloaded NHL response is committed."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import nhl_oracle as oracle
from skillc import nhl_snapshot as snapshot

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "controls" / "nhl-reference"


def fixture() -> dict[str, Any]:
    return json.loads((CONTROLS / "good" / "sources.json").read_text())


def make_game(data: dict[str, Any] | None = None) -> oracle.GameOracle:
    data = fixture() if data is None else data
    sources = {name: ({"source_id": name, "endpoint": snapshot.endpoint(name, data["game"]["id"]),
                       "retrieved_at_utc": "2026-10-30T00:00:00Z", "availability": "AVAILABLE",
                       "payload_sha256": snapshot.sha256(json.dumps(data[name]).encode()), "reason": ""},
                      data[name]) for name in snapshot.SOURCE_IDS}
    return oracle.GameOracle(data["game"], sources)


def fake_fetch(data: dict[str, Any]) -> snapshot.Fetch:
    responses = {snapshot.endpoint(name, data["game"]["id"]): json.dumps(data[name]).encode()
                 for name in snapshot.SOURCE_IDS}
    responses[snapshot.endpoint("schedule", "2025-10-07")] = json.dumps(data["schedule"]).encode()

    def fetch(url: str) -> bytes:
        if url not in responses:
            raise OSError("synthetic source absent")
        return responses[url]

    return fetch


def checks(report: dict[str, Any], family: str) -> list[dict[str, Any]]:
    return next(f["checks"] for f in report["families"] if f["family_id"] == family)


def test_good_case_all_families_and_sparse_stream() -> None:
    game = make_game()
    report = game.reconcile()
    assert len(report["families"]) == 8
    assert all(f["status"] == "PASS" for f in report["families"])
    assert len({c["check_id"] for f in report["families"] for c in f["checks"]}) == sum(len(f["checks"]) for f in report["families"])
    rows = list(game.on_ice())
    assert len(rows) == 14400
    assert rows[0] == {"game_id": 2025020999, "game_elapsed_second": 0, "team_id": 10, "player_id": 101, "role": "skater"}
    assert rows[-1]["game_elapsed_second"] == 3599
    assert oracle.compare(report, copy.deepcopy(report), fresh=True)["status"] == "PASS"
    assert oracle.compare_on_ice(game, iter(rows), fresh=True)["status"] == "PASS"


BAD_CASES = json.loads((CONTROLS / "bad" / "cases.json").read_text())


@pytest.mark.parametrize("case", BAD_CASES, ids=[c["name"] for c in BAD_CASES])
def test_committed_negative_controls(case: dict[str, Any], tmp_path: Path) -> None:
    game = make_game()
    expected = game.reconcile()
    candidate = copy.deepcopy(expected)
    mutation = case["mutation"]
    if mutation == "fabricated_unavailable":
        data = fixture()
        data["boxscore"]["playerByGameStats"]["awayTeam"]["forwards"][0].pop("hits")
        partial = make_game(data).reconcile()
        candidate = copy.deepcopy(partial)
        family = next(f for f in candidate["families"] if f["family_id"] == "F4")
        check = next(c for c in family["checks"] if c["summary_value"] is None)
        check.update(summary_value=0, detail_value=0, status="PASS")
        family["status"] = "PASS"
        result = oracle.compare(partial, candidate, fresh=True)
    elif mutation in ("partial_reference", "partial_reference_wrong"):
        data = fixture()
        data["boxscore"] = {}
        partial = make_game(data).reconcile()
        if mutation == "partial_reference_wrong":
            checks(candidate, "F6")[0]["detail_value"] = []
        result = oracle.compare(partial, candidate, fresh=True)
    elif mutation == "source_mismatch":
        data = fixture()
        value = data
        for key in case["path"][:-1]:
            value = value[key]
        value[case["path"][-1]] = case["value"]
        report = make_game(data).reconcile()
        result = next(f for f in report["families"] if f["family_id"] == case["family_id"])
    elif mutation == "increment_detail":
        check = checks(candidate, case["family_id"])[0]
        value = check["detail_value"]
        if type(value) is int:
            check["detail_value"] += 1
        elif isinstance(value, list):
            check["detail_value"] = [] if value else [999999]
        elif isinstance(value, dict):
            check["detail_value"][next(iter(value))] += 1
        else:
            check["detail_value"] = not value
        # Keep forged PASS statuses: the oracle must compare the values.
        result = oracle.compare(expected, candidate, fresh=True)
    elif mutation in ("drop_family", "drop_check"):
        if mutation == "drop_family":
            candidate["families"].pop()
        else:
            candidate["families"][0]["checks"].pop()
        result = oracle.compare(expected, candidate, fresh=True)
    elif mutation == "change_player":
        rows = list(game.on_ice())
        rows[0]["player_id"] = 999999
        result = oracle.compare_on_ice(game, iter(rows), fresh=True)
    elif mutation == "append_json_field":
        data = fixture()
        path = tmp_path / "snapshot"
        fetch = fake_fetch(data)
        snapshot.acquire(path, "2025-10-07", "2025-10-07", fetch=fetch)
        url = snapshot.endpoint("boxscore", data["game"]["id"])

        def changed(endpoint: str) -> bytes:
            return fetch(endpoint) + b" " if endpoint == url else fetch(endpoint)

        result = snapshot.recheck(path, [data["game"]["id"]], fetch=changed)["games"][0]
        assert oracle.compare(expected, candidate, fresh=False)["status"] == "UNKNOWN"
        assert oracle.compare_on_ice(game, iter([]), fresh=False)["status"] == "UNKNOWN"
    else:
        assert mutation == "empty_schedule"
        with pytest.raises(snapshot.ReferenceError, match="empty"):
            snapshot.completed_games([{"gameWeek": []}])
        result = {"status": "REFUSED"}
    assert result["status"] == case["expected_verdict"]


def test_snapshot_round_trip_raw_added_fields_drift_and_local_tamper(tmp_path: Path) -> None:
    data = fixture()
    data["boxscore"]["new_object"] = {"unknown": [1, {"extra": True}]}
    path = tmp_path / "reference"
    manifest = snapshot.acquire(path, "2025-10-07", "2025-10-07", fetch=fake_fetch(data))
    assert len(manifest["sources"]) == 5
    loaded, population = snapshot.load(path)
    assert loaded == manifest
    assert population[data["game"]["id"]]["boxscore"][1] == data["boxscore"]
    assert snapshot.recheck(path, [data["game"]["id"]], fetch=fake_fetch(data))["games"][0]["status"] == "UNCHANGED"
    source = path / "sources" / f"boxscore-{data['game']['id']}.json"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(snapshot.ReferenceError, match="checksum"):
        snapshot.load(path)


def test_missing_fetch_is_unavailable_not_empty_or_pass(tmp_path: Path) -> None:
    data = fixture()
    original = fake_fetch(data)

    def fetch(url: str) -> bytes:
        if "/boxscore" in url:
            raise OSError("unavailable")
        return original(url)

    path = tmp_path / "reference"
    snapshot.acquire(path, "2025-10-07", "2025-10-07", fetch=fetch)
    manifest, population = snapshot.load(path)
    game = oracle.GameOracle(manifest["games"][0], population[data["game"]["id"]])
    assert checks(game.reconcile(), "F1")[0]["status"] == "UNAVAILABLE"
    assert snapshot.recheck(path, [data["game"]["id"]], fetch=original)["games"][0]["status"] == "UNKNOWN"


def test_incomplete_schedule_refuses_manifest_publication(tmp_path: Path) -> None:
    data = fixture()
    with pytest.raises(snapshot.ReferenceError, match="coverage"):
        snapshot.acquire(tmp_path / "reference", "2025-10-07", "2025-10-08", fetch=fake_fetch(data))
    assert not (tmp_path / "reference" / "manifest.json").exists()


def test_shift_boundary_overlap_and_period_end_event() -> None:
    data = fixture()
    records = data["shifts"]["data"]
    original = records[0]
    original.update(endTime="00:10", duration="00:10")
    records.append(original | {"id": 99, "startTime": "00:10", "endTime": "20:00", "duration": "19:50"})
    game = make_game(data)
    assert (10, 101) in game.lineup(9)
    assert (10, 101) in game.lineup(10)
    assert sum(row["player_id"] == 101 for row in game.on_ice()) == 3600
    event = {"periodDescriptor": {"number": 1, "periodType": "REG"}, "timeInPeriod": "20:00"}
    assert game.event_second(event) == 1199
    event["timeInPeriod"] = "20:01"
    assert game.event_second(event) is None
    records.append(original | {"id": 100})
    game = make_game(data)
    report = game.reconcile()
    assert any(a["code"] == "overlapping-shifts" for a in report["anomalies"])
    assert sum(row["player_id"] == 101 for row in game.on_ice()) == 3600


def test_overtime_ends_at_winning_goal_and_shootout_has_no_seconds() -> None:
    data = fixture()
    data["play_by_play"]["periodDescriptor"] = {"number": 4, "periodType": "OT"}
    data["play_by_play"]["plays"].append({"eventId": 99, "typeDescKey": "goal", "timeInPeriod": "01:05",
                                          "periodDescriptor": {"number": 4, "periodType": "OT"}, "details": {"eventOwnerTeamId": 10}})
    game = make_game(data)
    assert game.periods[4] == (3600, 65)
    assert game.event_second(data["play_by_play"]["plays"][-1]) == 3664
    data["play_by_play"]["periodDescriptor"] = {"number": 5, "periodType": "SO"}
    data["boxscore"]["gameOutcome"]["lastPeriodType"] = "SO"
    data["boxscore"]["awayTeam"]["score"] = 2
    data["play_by_play"]["plays"].pop()
    game = make_game(data)
    assert game.periods[4] == (3600, 300)
    assert checks(game.reconcile(), "F1")[0]["status"] == "PASS"


def test_empty_net_bench_pim_and_unused_backup() -> None:
    data = fixture()
    data["play_by_play"]["plays"][0]["details"].pop("goalieInNetId")
    data["play_by_play"]["plays"][0]["situationCode"] = "1110"
    data["boxscore"]["playerByGameStats"]["homeTeam"]["goalies"][0]["shotsAgainst"] = 1
    penalty = copy.deepcopy(data["play_by_play"]["plays"][-1])
    penalty["eventId"] = 99
    penalty["details"].pop("committedByPlayerId")
    penalty["details"]["descKey"] = "bench-minor"
    data["play_by_play"]["plays"].append(penalty)
    backup = {"playerId": 999, "position": "G", "toi": "00:00", "shotsAgainst": 0, "pim": 0}
    data["boxscore"]["playerByGameStats"]["homeTeam"]["goalies"].append(backup)
    data["play_by_play"]["rosterSpots"].append({"teamId": 20, "playerId": 999, "positionCode": "G"})
    report = make_game(data).reconcile()
    assert all(c["status"] == "PASS" for c in checks(report, "F2"))
    assert all(c["status"] == "PASS" for c in checks(report, "F3"))
    assert all(c["status"] == "PASS" for c in checks(report, "F8"))
    assert any(a["code"] == "bench-penalty" for a in report["anomalies"])


def test_unknown_source_fields_and_invalid_role_never_make_zero_pass() -> None:
    data = fixture()
    data["play_by_play"]["plays"][0]["details"].pop("eventOwnerTeamId")
    report = make_game(data).reconcile()
    assert all(c["status"] == "UNAVAILABLE" for c in checks(report, "F1"))
    data = fixture()
    data["play_by_play"]["rosterSpots"][0]["positionCode"] = "G"
    game = make_game(data)
    assert not game.on_ice_available
    assert all(c["status"] == "UNAVAILABLE" for c in checks(game.reconcile(), "F7"))


def test_census_zero_discrepancies_requires_plants_and_empty_refuses() -> None:
    report = make_game().reconcile()
    result = oracle.census([report])
    assert result["game_count"] == 1
    assert all(f["planted_cases_required"] for f in result["families"].values())
    changed = copy.deepcopy(report)
    changed["families"][0]["status"] = "DISCREPANCY"
    assert not oracle.census([changed])["families"]["F1"]["planted_cases_required"]
    with pytest.raises(snapshot.ReferenceError, match="empty"):
        oracle.census([])
    report["families"][-1] = report["families"][0]
    with pytest.raises(snapshot.ReferenceError, match="family"):
        oracle.census([report])


def test_qualifier_rejects_deliberately_blind_comparators(monkeypatch: pytest.MonkeyPatch) -> None:
    from skillc.nhl_reference import qualify

    assert qualify(CONTROLS)["status"] == "PASS"
    with monkeypatch.context() as patch:
        patch.setattr(oracle, "compare", lambda *args, **kwargs: {"status": "PASS"})
        with pytest.raises(snapshot.ReferenceError, match="blind/noisy: wrong-F1"):
            qualify(CONTROLS)
    with monkeypatch.context() as patch:
        patch.setattr(oracle, "compare_on_ice", lambda *args, **kwargs: {"status": "PASS"})
        with pytest.raises(snapshot.ReferenceError, match="blind/noisy: wrong-on-ice-player"):
            qualify(CONTROLS)


def test_derive_completion_index_pins_manifest_goal_and_row_count(tmp_path: Path) -> None:
    from skillc.nhl_reference import derive

    data = fixture()
    root = tmp_path / "reference"
    snapshot.acquire(root, "2025-10-07", "2025-10-07", fetch=fake_fetch(data))
    digest = snapshot.sha256((root / "manifest.json").read_bytes())
    goal = ROOT / "evals/nhl-season/goal.md"
    result = derive(root, tmp_path / "derived", manifest_sha256=digest, goal=goal)
    assert result["census"]["game_count"] == 1
    assert result["goal_sha256"] == snapshot.sha256(goal.read_bytes())
    assert result["games"][0]["on_ice_rows"] == 14400
    assert result["games"][0]["on_ice_availability"] == "AVAILABLE"
    assert (tmp_path / "derived/derivation.json").exists()
    with pytest.raises(snapshot.ReferenceError, match="manifest"):
        derive(root, tmp_path / "wrong", manifest_sha256="0" * 64, goal=goal)
    assert not (tmp_path / "wrong").exists()


def test_grade_seam_binds_live_game_and_sources_and_drift_vetoes_wrong_output(tmp_path: Path) -> None:
    from skillc.nhl_reference import grade_game

    data = fixture()
    root = tmp_path / "reference"
    fetch = fake_fetch(data)
    snapshot.acquire(root, "2025-10-07", "2025-10-07", fetch=fetch)
    digest = snapshot.sha256((root / "manifest.json").read_bytes())
    live = snapshot.recheck(root, [data["game"]["id"]], fetch=fetch)
    live["manifest_sha256"] = digest
    game = make_game()
    report = game.reconcile()
    result = grade_game(root, game.identity, report, game.on_ice(), live, manifest_sha256=digest)
    assert result["status"] == "PASS"
    wrong = copy.deepcopy(report)
    checks(wrong, "F1")[0]["detail_value"] = 999
    assert grade_game(root, game.identity, wrong, game.on_ice(), live, manifest_sha256=digest)["status"] == "FAIL"
    for mutation in ("manifest", "sample", "missing", "duplicate", "digest", "status"):
        changed = copy.deepcopy(live)
        if mutation == "manifest":
            changed["manifest_sha256"] = "0" * 64
        elif mutation == "sample":
            changed["sample"] = []
        elif mutation == "missing":
            changed["games"][0]["checks"].pop()
        elif mutation == "duplicate":
            changed["games"][0]["checks"][-1] = changed["games"][0]["checks"][0]
        elif mutation == "digest":
            changed["games"][0]["checks"][0]["observed_sha256"] = "0" * 64
        else:
            changed["games"][0]["status"] = "UNKNOWN"
        assert grade_game(root, game.identity, wrong, iter([]), changed,
                          manifest_sha256=digest)["status"] == "UNKNOWN"


def test_transport_refuses_unapproved_host_and_redirect_without_network() -> None:
    for url in ("http://api.nhle.com/example", "https://other.invalid/", "https://api.nhle.com:8443/",
                "https://user@api.nhle.com/"):
        with pytest.raises(snapshot.ReferenceError, match="approved"):
            snapshot.fetch_public(url)
    with pytest.raises(snapshot.ReferenceError, match="redirect"):
        snapshot._NoRedirect().redirect_request(None, None, 302, "redirect", None, "https://other.invalid/")


def test_reference_missing_data_rejects_unsupported_complete_candidate() -> None:
    data = fixture()
    data["boxscore"] = {}
    partial = make_game(data).reconcile()
    complete = make_game().reconcile()
    assert oracle.compare(partial, complete, fresh=True)["status"] == "FAIL"
    assert oracle.compare(partial, copy.deepcopy(partial), fresh=True)["status"] == "PASS"


def test_fabricating_zero_pass_over_unavailable_input_is_a_failure() -> None:
    data = fixture()
    data["boxscore"]["playerByGameStats"]["awayTeam"]["forwards"][0].pop("hits")
    expected = make_game(data).reconcile()
    candidate = copy.deepcopy(expected)
    unavailable = next(c for c in checks(candidate, "F4") if c["summary_value"] is None)
    unavailable.update(summary_value=0, detail_value=0, status="PASS")
    next(f for f in candidate["families"] if f["family_id"] == "F4")["status"] = "PASS"
    assert oracle.compare(expected, candidate, fresh=True)["status"] == "FAIL"


def test_unreadable_penalty_and_event_attribution_name_raw_records() -> None:
    data = fixture()
    data["play_by_play"]["plays"][-1]["details"]["duration"] = "unknown"
    data["play_by_play"]["plays"][2]["details"].pop("hittingPlayerId")
    report = make_game(data).reconcile()
    for code, identity, pointer in (("penalty-duration", 7, "/plays/6"), ("event-attribution", 3, "/plays/2")):
        anomaly = next(a for a in report["anomalies"] if a["code"] == code)
        assert anomaly["scope"]["event_id"] == identity
        assert anomaly["sources"][0]["record_pointer"] == pointer
