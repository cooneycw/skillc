"""Controller CLI for private NHL reference preparation (#633).

Network actions are explicit subcommands. This module does not authorize a
season pull, a live model trial, or use of any particular machine. Consult the
declaration and evals/nhl-season/reference.md before acquisition.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import nhl_oracle as oracle
from . import nhl_snapshot as snapshot
from .nhl_snapshot import Json, ReferenceError


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _pin(root: Path, expected: str) -> None:
    if snapshot.sha256((root / "manifest.json").read_bytes()) != expected:
        raise ReferenceError("manifest differs from controller's declared digest")


def derive(root: Path, output: Path, *, manifest_sha256: str, goal: Path) -> Json:
    """Publish the completion index last; missing index means incomplete output.

    Per-game results and JSONL membership are streamed rather than retaining a
    season's tens of millions of rows in memory. The private directory must
    remain controller-owned; subject code never receives write access.
    """
    _pin(root, manifest_sha256)
    manifest, population = snapshot.load(root)
    output.mkdir(parents=True, exist_ok=False)
    (output / "reconciliation").mkdir()
    (output / "on_ice").mkdir()
    (output / "on_ice_counts").mkdir()
    summaries = []
    artifacts = []
    for game in manifest["games"]:
        identity = game["id"]
        model = oracle.GameOracle(game, population[identity])
        report = model.reconcile()
        report_path = output / "reconciliation" / f"{identity}.json"
        _write(report_path, report)
        ice_path = output / "on_ice" / f"{identity}.jsonl"
        rows = 0
        with ice_path.open("w") as stream:
            if model.on_ice_available:
                for row in model.on_ice():
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    rows += 1
        count_path = output / "on_ice_counts" / f"{identity}.jsonl"
        count_rows = 0
        with count_path.open("w") as stream:
            if model.on_ice_available:
                for count in model.on_ice_counts():
                    stream.write(json.dumps(count, sort_keys=True) + "\n")
                    count_rows += 1
        summaries.append({"game_id": identity,
                          "families": [{"family_id": f["family_id"], "status": f["status"]}
                                       for f in report["families"]]})
        artifacts.append({"game_id": identity, "reconciliation": str(report_path.relative_to(output)),
                          "reconciliation_sha256": snapshot.sha256(report_path.read_bytes()),
                          "on_ice": str(ice_path.relative_to(output)),
                          "on_ice_sha256": _file_hash(ice_path), "on_ice_rows": rows,
                          "on_ice_counts": str(count_path.relative_to(output)),
                          "on_ice_counts_sha256": _file_hash(count_path), "on_ice_count_rows": count_rows,
                          "on_ice_availability": "AVAILABLE" if model.on_ice_available else "UNAVAILABLE",
                          "periods": {str(k): {"start_second": v[0], "played_duration_seconds": v[1]}
                                      for k, v in model.periods.items()}})
    result = {"schema_version": 1, "manifest_sha256": manifest_sha256,
              "goal_sha256": snapshot.sha256(goal.read_bytes()),
              "oracle_sha256": snapshot.sha256(Path(oracle.__file__).read_bytes()),
              "snapshot_code_sha256": snapshot.sha256(Path(snapshot.__file__).read_bytes()),
              "derived_at_utc": snapshot.utc_now(), "games": artifacts,
              "census": oracle.census(summaries)}
    _pin(root, manifest_sha256)
    _write(output / "derivation.json", result)
    return result


def _file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def grade_game(root: Path, identity: int, candidate: Json, rows: Any, live: Json,
               *, manifest_sha256: str) -> Json:
    """Controller-only seam: bind freshness to this snapshot and selected game.

    The caller owns the live report and supplies candidate JSON, not executable
    code. Other deliverables (database, retrieval adaptation, viewer) belong to
    their separate graders; this seam grades reconciliation values/membership.
    """
    _pin(root, manifest_sha256)
    manifest, population = snapshot.load(root)
    game = next((g for g in manifest["games"] if g["id"] == identity), None)
    if game is None:
        raise ReferenceError("game outside reference population")
    fresh = False
    if live.get("manifest_sha256") == manifest_sha256 and identity in live.get("sample", []):
        observations = [g for g in live.get("games", []) if g.get("game_id") == identity]
        if len(observations) == 1:
            entry = observations[0]
            checks = entry.get("checks", [])
            required = {source["endpoint"]: source["payload_sha256"]
                        for source, _ in population[identity].values()}
            for sources in population.values():
                for name, (source, data) in sources.items():
                    if (name == "schedule" and data is not None
                            and any(g.get("id") == identity for day in data["gameWeek"] for g in day["games"])):
                        required[source["endpoint"]] = source["payload_sha256"]
            fresh = (entry.get("status") == "UNCHANGED" and len(checks) == len(required)
                     and len({c.get("endpoint") for c in checks}) == len(required)
                     and all(c.get("endpoint") in required and c.get("status") == "UNCHANGED"
                             and c.get("expected_sha256") == required[c["endpoint"]]
                             and c.get("observed_sha256") == required[c["endpoint"]]
                             and required[c["endpoint"]] is not None for c in checks))
    model = oracle.GameOracle(game, population[identity])
    expected = model.reconcile()
    reconciliation = oracle.compare(expected, candidate, fresh=fresh)
    on_ice = oracle.compare_on_ice(model, iter(rows), fresh=fresh)
    statuses = {reconciliation["status"], on_ice["status"]}
    status = "FAIL" if "FAIL" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "PASS"
    return {"game_id": identity, "status": status,
            "reconciliation": reconciliation, "on_ice": on_ice}


def qualify(controls: Path) -> Json:
    """Certify real comparators with committed synthetic inputs, never NHL data."""
    data = json.loads((controls / "good" / "sources.json").read_text())
    cases = json.loads((controls / "bad" / "cases.json").read_text())
    if not data.get("synthetic") or not cases:
        raise ReferenceError("qualification requires nonempty synthetic controls")
    names = [c.get("name") for c in cases]
    required = {*(f"wrong-{f}" for f in oracle.FAMILIES), *(f"source-{f}" for f in oracle.FAMILIES),
                "missing-family", "missing-check", "wrong-on-ice-player", "changed-live-bytes", "empty-season",
                "partial-reference-complete-candidate", "partial-reference-known-wrong", "fabricated-pass-unavailable"}
    if len(names) != len(required) or set(names) != required:
        raise ReferenceError("qualification control population incomplete or duplicated")
    identity = data["game"]["id"]
    responses = {snapshot.endpoint(name, identity): json.dumps(data[name]).encode()
                 for name in snapshot.SOURCE_IDS}
    responses[snapshot.endpoint("schedule", "2025-10-07")] = json.dumps(data["schedule"]).encode()

    def fetch(url: str) -> bytes:
        return responses[url]

    sources = {name: ({"source_id": name, "endpoint": snapshot.endpoint(name, identity),
                       "availability": "AVAILABLE", "retrieved_at_utc": "2026-10-30T00:00:00Z",
                       "payload_sha256": snapshot.sha256(json.dumps(data[name]).encode()), "reason": ""},
                      data[name]) for name in snapshot.SOURCE_IDS}
    model = oracle.GameOracle(data["game"], sources)
    expected = model.reconcile()
    states = {f["family_id"]: f["status"] for f in expected["families"]}
    if len(expected["families"]) != 8 or states != data["expected_family_statuses"]:
        raise ReferenceError("qualification good source failed reconciliation")
    if oracle.compare(expected, copy.deepcopy(expected), fresh=True)["status"] != "PASS":
        raise ReferenceError("qualification comparator rejected good case")
    if oracle.compare_on_ice(model, model.on_ice(), fresh=True)["status"] != "PASS":
        raise ReferenceError("qualification on-ice comparator rejected good case")
    verdicts = []
    for case in cases:
        candidate = copy.deepcopy(expected)
        mutation = case["mutation"]
        if mutation == "fabricated_unavailable":
            missing = copy.deepcopy(data)
            missing["boxscore"]["playerByGameStats"]["awayTeam"]["forwards"][0].pop("hits")
            missing_sources = {name: (sources[name][0], missing[name]) for name in snapshot.SOURCE_IDS}
            reference = oracle.GameOracle(missing["game"], missing_sources).reconcile()
            candidate = copy.deepcopy(reference)
            family = next(f for f in candidate["families"] if f["family_id"] == "F4")
            for check in family["checks"]:
                if check["status"] == "UNAVAILABLE":
                    check.update(summary_value=0, detail_value=0, status="PASS")
            family["status"] = "PASS"
            actual = oracle.compare(reference, candidate, fresh=True)["status"]
        elif mutation in ("partial_reference", "partial_reference_wrong"):
            incomplete = copy.deepcopy(data)
            incomplete["boxscore"] = {}
            partial_sources = {name: (sources[name][0], incomplete[name]) for name in snapshot.SOURCE_IDS}
            partial = oracle.GameOracle(incomplete["game"], partial_sources).reconcile()
            if mutation == "partial_reference_wrong":
                family = next(f for f in candidate["families"] if f["family_id"] == "F6")
                family["checks"][0]["detail_value"] = []
            actual = oracle.compare(partial, candidate, fresh=True)["status"]
        elif mutation == "source_mismatch":
            planted = copy.deepcopy(data)
            value = planted
            for key in case["path"][:-1]:
                value = value[key]
            value[case["path"][-1]] = case["value"]
            planted_sources = {name: (sources[name][0], planted[name]) for name in snapshot.SOURCE_IDS}
            report = oracle.GameOracle(planted["game"], planted_sources).reconcile()
            actual = next(f["status"] for f in report["families"] if f["family_id"] == case["family_id"])
        elif mutation == "increment_detail":
            family = next(f for f in candidate["families"] if f["family_id"] == case["family_id"])
            check = family["checks"][0]
            value = check["detail_value"]
            if type(value) is int:
                check["detail_value"] += 1
            elif isinstance(value, list):
                check["detail_value"] = [] if value else [999999]
            elif isinstance(value, dict):
                check["detail_value"][next(iter(value))] += 1
            else:
                check["detail_value"] = not value
            actual = oracle.compare(expected, candidate, fresh=True)["status"]
        elif mutation in ("drop_family", "drop_check"):
            if mutation == "drop_family":
                candidate["families"].pop()
            else:
                candidate["families"][0]["checks"].pop()
            actual = oracle.compare(expected, candidate, fresh=True)["status"]
        elif mutation == "change_player":
            rows = list(model.on_ice())
            rows[0]["player_id"] = 999999
            actual = oracle.compare_on_ice(model, iter(rows), fresh=True)["status"]
        elif mutation == "append_json_field":
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "reference"
                snapshot.acquire(root, "2025-10-07", "2025-10-07", fetch=fetch)
                unchanged = snapshot.recheck(root, [identity], fetch=fetch)
                if unchanged["games"][0]["status"] != "UNCHANGED":
                    raise ReferenceError("qualification good live re-check did not agree")
                url = snapshot.endpoint("boxscore", identity)
                changed = json.loads(responses[url])
                changed["planted_extra_field"] = True
                responses[url] = json.dumps(changed).encode()
                actual = snapshot.recheck(root, [identity], fetch=fetch)["games"][0]["status"]
        elif mutation == "empty_schedule":
            try:
                snapshot.completed_games([{"gameWeek": []}])
            except ReferenceError:
                actual = "REFUSED"
            else:
                actual = "PASS"
        else:
            raise ReferenceError(f"unknown qualification mutation: {mutation}")
        if actual != case["expected_verdict"]:
            raise ReferenceError(f"qualification blind/noisy: {case['name']}: {actual}")
        verdicts.append({"name": case["name"], "verdict": actual})
    return {"status": "PASS", "good": "PASS", "controls": verdicts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    acquire = commands.add_parser("snapshot", help="explicit private source acquisition")
    acquire.add_argument("--out", required=True, type=Path)
    acquire.add_argument("--start", required=True)
    acquire.add_argument("--end", required=True)
    derive_parser = commands.add_parser("derive", help="independent private expected outputs")
    derive_parser.add_argument("--reference", required=True, type=Path)
    derive_parser.add_argument("--manifest-sha256", required=True)
    derive_parser.add_argument("--goal", required=True, type=Path)
    derive_parser.add_argument("--out", required=True, type=Path)
    live = commands.add_parser("recheck", help="explicit declared live sample")
    live.add_argument("--reference", required=True, type=Path)
    live.add_argument("--manifest-sha256", required=True)
    live.add_argument("--sample", required=True, type=int, nargs="+")
    live.add_argument("--out", required=True, type=Path)
    comparison = commands.add_parser("compare", help="compare one sampled game's JSON exports")
    comparison.add_argument("--reference", required=True, type=Path)
    comparison.add_argument("--manifest-sha256", required=True)
    comparison.add_argument("--game-id", required=True, type=int)
    comparison.add_argument("--candidate-game", required=True, type=Path)
    comparison.add_argument("--candidate-on-ice", required=True, type=Path)
    comparison.add_argument("--live-report", required=True, type=Path)
    control = commands.add_parser("selftest", help="committed model-free known-good/bad controls")
    control.add_argument("--controls", type=Path, default=Path(__file__).resolve().parents[1] / "controls" / "nhl-reference")
    args = parser.parse_args(argv)
    result: Json
    try:
        if args.command == "snapshot":
            manifest = snapshot.acquire(args.out, args.start, args.end)
            result = {"status": "RETAINED", "game_count": len(manifest["games"]),
                      "manifest_sha256": snapshot.sha256((args.out / "manifest.json").read_bytes())}
        elif args.command == "derive":
            result = derive(args.reference, args.out, manifest_sha256=args.manifest_sha256, goal=args.goal)
        elif args.command == "recheck":
            _pin(args.reference, args.manifest_sha256)
            result = snapshot.recheck(args.reference, args.sample)
            result["manifest_sha256"] = args.manifest_sha256
            result["checked_at_utc"] = snapshot.utc_now()
            _write(args.out, result)
        elif args.command == "compare":
            candidate = json.loads(args.candidate_game.read_text())
            live_report = json.loads(args.live_report.read_text())
            with args.candidate_on_ice.open() as stream:
                result = grade_game(args.reference, args.game_id, candidate,
                                    (json.loads(line) for line in stream), live_report,
                                    manifest_sha256=args.manifest_sha256)
            print(json.dumps(result, sort_keys=True))
            return {"PASS": 0, "FAIL": 1, "UNKNOWN": 2}[result["status"]]
        else:
            result = qualify(args.controls)
    except (ReferenceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "UNKNOWN", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
