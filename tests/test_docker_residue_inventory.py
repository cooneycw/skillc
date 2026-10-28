"""Read-only residue inventory controls; no test needs a Docker daemon."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ci import docker_residue_inventory as inventory

FIXTURES = Path(__file__).parent / "fixtures/docker-residue-inventory"
IMAGE = "sha256:" + "a" * 64
FOREIGN = "sha256:" + "b" * 64
CONTAINER = "1" * 64
NETWORK = "2" * 64


def case(name: str = "named-unlabelled") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Docker:
    """Only allow real inspection argv shapes; any mutation is an error."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        for kind, command in inventory.LIST_COMMANDS.items():
            if argv == command:
                return "".join(item["Id"] + "\n" for item in self.data[kind + "s"])
            if argv[:2] == [kind, "inspect"]:
                return json.dumps([item for item in self.data[kind + "s"] if item["Id"] in argv[2:]])
        raise AssertionError(f"non-inspection Docker call: {argv}")


def test_named_unlabelled_image_is_found_and_unrelated_sentinel_excluded() -> None:
    data = case()
    # The old operational label filter is blind to this committed input.
    assert [i for i in data["images"] if (i["Config"]["Labels"] or {}).get("skillc.managed")] == []
    docker = Docker(data)
    report = inventory.inventory(docker)
    assert report["inventory_status"] == "complete"
    assert report["cleanup_status"] == "unassessed"
    assert [r["id"] for r in report["resources"]["image"]] == [IMAGE]
    assert [r["id"] for r in report["proposed_removals"]["image"]] == [IMAGE]
    assert all(not r["approved"] for r in report["proposed_removals"]["image"])
    assert FOREIGN not in json.dumps(report)
    assert not any("--filter" in argv for argv in docker.calls)


def test_label_only_scanner_cannot_satisfy_the_committed_population() -> None:
    docker = Docker(case())

    def blind(argv: list[str]) -> str:
        if argv == inventory.LIST_COMMANDS["image"]:
            return ""  # the label-only filter misses the named, unlabelled image
        return docker(argv)

    report = inventory.inventory(blind)
    assert report["inventory_status"] == "unknown"
    assert report["proposed_removals"]["image"] == []
    # A test that expected the actual image population would fail, not certify zero.
    with pytest.raises(AssertionError):
        assert [r["id"] for r in report["resources"]["image"]] == [IMAGE]


def test_every_pinned_alias_protects_the_entire_id() -> None:
    report = inventory.inventory(Docker(case("pinned-aliases")))
    assert report["inventory_status"] == "complete"
    assert len(report["protected_image_ids"]) == 4
    assert report["matched_image_tag_count"] == 8
    assert report["proposed_removals"]["image"] == []
    assert all(len(r["pinned_aliases"]) == 1 for r in report["resources"]["image"])


def test_pinned_digest_alias_also_protects_an_apparent_clutter_tag() -> None:
    data = case()
    data["images"][0]["RepoDigests"] = ["registry.example.test/skillc-529-example@sha256:" + "c" * 64]
    report = inventory.inventory(Docker(data))
    assert report["protected_image_ids"] == [IMAGE]
    assert report["proposed_removals"]["image"] == []
    assert report["matched_image_tag_count"] == 1  # digest aliases are not tags


def test_empty_inventory_is_unknown_not_clean() -> None:
    report = inventory.inventory(Docker(case("empty")))
    assert report["inventory_status"] == "unknown"
    assert report["cleanup_status"] == "unassessed"
    assert "empty matching population" in report["errors"][-1]
    assert not any(report["proposed_removals"].values())


def test_an_unreadable_kind_keeps_positive_facts_but_clears_proposals() -> None:
    docker = Docker(case())

    def unreadable(argv: list[str]) -> str:
        if argv == inventory.LIST_COMMANDS["network"]:
            raise inventory.Unreadable("network inspection unavailable")
        return docker(argv)

    report = inventory.inventory(unreadable)
    assert report["inventory_status"] == "unknown"
    assert report["resources"]["image"][0]["id"] == IMAGE
    assert not any(report["proposed_removals"].values())


@pytest.mark.parametrize("fault", ["short-id", "missing", "duplicate", "malformed", "labels", "size", "digests"])
def test_malformed_or_incomplete_inspection_cannot_propose_removal(fault: str) -> None:
    data = case()
    if fault == "short-id":
        data["images"][0]["Id"] = "sha256:abc"
    elif fault == "labels":
        data["images"][0]["Config"]["Labels"] = {"skillc.managed": True}
    elif fault == "size":
        data["images"][0]["Size"] = None
    elif fault == "digests":
        data["images"][0]["RepoDigests"] = {}
    docker = Docker(data)

    def broken(argv: list[str]) -> str:
        result = docker(argv)
        if argv[:2] == ["image", "inspect"]:
            if fault == "missing":
                return "[]"
            if fault == "duplicate":
                return json.dumps([data["images"][0], data["images"][0]])
            if fault == "malformed":
                return "not JSON"
        return result

    report = inventory.inventory(broken)
    assert report["inventory_status"] == "unknown"
    assert not any(report["proposed_removals"].values())


def test_foreign_stopped_container_protects_a_matching_image() -> None:
    data = case()
    data["containers"] = [{"Id": CONTAINER, "Name": "/unrelated-sentinel", "Image": IMAGE,
                           "Config": {"Labels": {}}, "State": {"Running": False}}]
    report = inventory.inventory(Docker(data))
    assert report["inventory_status"] == "complete"
    assert report["resources"]["container"] == []
    assert report["resources"]["image"][0]["referencing_container_ids"] == [CONTAINER]
    assert report["proposed_removals"]["image"] == []


def test_names_and_network_suffix_cross_check_ownership_labels() -> None:
    data = case()
    data["containers"] = [{"Id": CONTAINER, "Name": "/skillc-attempt-example", "Image": IMAGE,
                           "Config": {"Labels": None}, "State": {"Running": True}}]
    data["networks"] = [{"Id": NETWORK, "Name": "attempt-example-egress", "Labels": None,
                         "Containers": {CONTAINER: {}}}]
    report = inventory.inventory(Docker(data))
    assert report["matched_counts"] == {"image": 1, "container": 1, "network": 1}
    assert not any(report["proposed_removals"].values())
    assert report["resources"]["container"][0]["ownership"] == "unknown"


def test_labelled_resources_with_other_names_are_still_inventoried() -> None:
    data = case()
    data["containers"] = [{"Id": CONTAINER, "Name": "/opaque-name", "Image": IMAGE,
                           "Config": {"Labels": {"skillc.managed": "true"}}, "State": {"Running": True}}]
    data["networks"] = [{"Id": NETWORK, "Name": "opaque-network", "Labels": {"skillc.managed": "true"},
                         "Containers": {CONTAINER: {}}}]
    assert inventory.inventory(Docker(data))["matched_counts"] == {"image": 1, "container": 1, "network": 1}


def test_population_change_invalidates_proposals_without_chasing_arrivals() -> None:
    docker = Docker(case())
    calls = 0

    def changing(argv: list[str]) -> str:
        nonlocal calls
        result = docker(argv)
        if argv == inventory.LIST_COMMANDS["image"]:
            calls += 1
            if calls == 2:
                return result + "sha256:" + "f" * 64 + "\n"
        return result

    report = inventory.inventory(changing)
    assert calls == 2
    assert report["inventory_status"] == "unknown"
    assert not any(report["proposed_removals"].values())


def test_inventory_batches_more_than_sixty_four_images_without_losing_ids() -> None:
    data = case("empty")
    data["images"] = [{"Id": "sha256:" + f"{i:064x}", "RepoTags": [f"skillc-example:image-{i}"],
                       "Config": {"Labels": None}, "Size": 512} for i in range(65)]
    docker = Docker(data)
    report = inventory.inventory(docker)
    assert report["inventory_status"] == "complete"
    assert report["listed_counts"]["image"] == report["inspected_counts"]["image"] == 65
    assert len(report["proposed_removals"]["image"]) == 65
    assert [len(argv) - 2 for argv in docker.calls if argv[:2] == ["image", "inspect"]] == [64, 1]


def test_second_listing_failure_invalidates_an_otherwise_complete_observation() -> None:
    docker = Docker(case())
    calls = 0

    def failed_confirmation(argv: list[str]) -> str:
        nonlocal calls
        if argv == inventory.LIST_COMMANDS["image"]:
            calls += 1
            if calls == 2:
                raise inventory.Unreadable("confirmation unavailable")
        return docker(argv)

    report = inventory.inventory(failed_confirmation)
    assert report["inspected_counts"]["image"] == 2
    assert report["inventory_status"] == "unknown"
    assert not any(report["proposed_removals"].values())


@pytest.mark.parametrize("case_name,expected_code", [("named-unlabelled", 0), ("empty", 2), ("pinned-aliases", 0)])
def test_cli_is_inspection_only_and_uses_exit_two_for_unknown(
        tmp_path: Path, case_name: str, expected_code: int,
) -> None:
    script = tmp_path / "docker"
    # Drive the actual CLI process, not a second implementation of the planner.
    source = FIXTURES / f"{case_name}.json"
    script.write_text(f"#!{sys.executable}\nimport json,sys\ndata=json.load(open({str(source)!r}))\n"
                      "args=sys.argv[1:]\n"
                      "kind='container' if args[0]=='ps' else args[0]\n"
                      "assert args[:2] in ([kind,'ls'],[kind,'inspect']) or args[0]=='ps'\n"
                      "items=data[kind+'s']\n"
                      "print(json.dumps([i for i in items if i['Id'] in args[2:]]) if args[1]=='inspect' "
                      "else '\\n'.join(i['Id'] for i in items),end='')\n")
    script.chmod(0o755)
    tool = Path(inventory.__file__)
    output = tmp_path / "inventory.json"
    result = subprocess.run([sys.executable, str(tool), "--docker", str(script), "--out", str(output)],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == expected_code, result.stderr
    report = json.loads(output.read_text())
    assert report["read_only"]
    if case_name == "named-unlabelled":
        assert report["proposed_removals"]["image"][0]["id"] == IMAGE
    else:
        assert not any(report["proposed_removals"].values())
    refused = subprocess.run([sys.executable, str(tool), "--docker", str(script), "--out", str(output)],
                             capture_output=True, text=True, timeout=10, check=False)
    assert refused.returncode == 2
    assert json.loads(output.read_text()) == report
    unavailable = subprocess.run([sys.executable, str(tool), "--docker", str(tmp_path / "absent")],
                                 capture_output=True, text=True, timeout=10, check=False)
    assert unavailable.returncode == 2
    assert json.loads(unavailable.stdout)["inventory_status"] == "unknown"
