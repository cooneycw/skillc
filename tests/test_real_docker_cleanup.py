"""Tests for `ci/real-docker/cleanup-lib.sh` (#414): run-real-docker's cleanup
removes only what its own run created.

The runner used to end every run with a HOST-WIDE `docker image prune -f`,
which deleted co-tenant campaign images that `build.py` left untagged and
receipts name only by ID. These drive the real shell functions against a
stateful fake `docker` (no daemon): the fake holds images and containers in a
JSON file, answers the listings the library makes, records every removal, and
records any `prune` so a test can prove none was issued. The real-daemon red
case is `tests/test_real_docker_cleanup_live.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "ci" / "real-docker" / "cleanup-lib.sh"

_FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_DOCKER_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
def save():
    json.dump(state, open(state_path, "w"))
def filters():
    out = []
    for i, a in enumerate(args):
        if a == "--filter":
            out.append(args[i + 1])
    return out
def label_ok(labels, f):
    key, _, value = f[len("label="):].partition("=")
    return key in labels and (not value or labels[key] == value)
if "prune" in args:
    state["log"].append(["prune", *args]); save(); sys.exit(0)
if args[0] == "images":
    if os.environ.get("FAKE_DOCKER_FAIL") == "images":
        sys.exit(1)
    selected = state["images"]
    for f in filters():
        if f == "dangling=true":
            selected = [i for i in selected if not i["tags"]]
        elif f.startswith("label="):
            selected = [i for i in selected if label_ok(i["labels"], f)]
    print("\n".join(i["id"] for i in selected))
elif args[0] == "ps":
    selected = state["containers"]
    statuses = [f[len("status="):] for f in filters() if f.startswith("status=")]
    if statuses:
        selected = [c for c in selected if c["status"] in statuses]
    for f in filters():
        if f.startswith("label="):
            selected = [c for c in selected if label_ok(c["labels"], f)]
    print("\n".join(c["id"] for c in selected))
elif args[0] == "rm":
    state["containers"] = [c for c in state["containers"] if c["id"] != args[1]]
    state["log"].append(["rm", args[1]]); save()
elif args[:2] == ["image", "rm"]:
    if "-f" in args:
        state["log"].append(["image-rm-forced", *args]); save(); sys.exit(1)
    target = args[-1]
    gone = {target}
    if "--no-prune" not in args:
        # Like the real daemon: removing an image also deletes its UNTAGGED
        # parent chain unless --no-prune is given.
        parent = next((i.get("parent") for i in state["images"] if i["id"] == target), None)
        while parent:
            p = next((i for i in state["images"] if i["id"] == parent), None)
            if p is None or p["tags"]:
                break
            gone.add(parent)
            parent = p.get("parent")
    state["images"] = [i for i in state["images"] if i["id"] not in gone]
    state["log"].append(["image-rm", target]); save()
else:
    sys.exit(2)
'''

SKILLC = {"org.skillc.image": "trial-image"}
MANAGED = {"skillc.managed": "true"}


def _image(
    name: str, *, tags: list[str] | None = None, labels: dict[str, str] | None = None, parent: str | None = None,
) -> dict[str, Any]:
    return {"id": f"sha256:{name}", "tags": tags or [], "labels": labels or {},
            "parent": f"sha256:{parent}" if parent else None}


def _container(name: str, status: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
    return {"id": name, "status": status, "labels": labels or {}}


class Host:
    """The fake daemon's state, and the two library calls run against it."""

    def __init__(self, tmp_path: Path, images: list[dict[str, Any]], containers: list[dict[str, Any]]) -> None:
        self.tmp = tmp_path
        self.state = tmp_path / "docker-state.json"
        self.state.write_text(json.dumps({"images": images, "containers": containers, "log": []}))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "python3").symlink_to(sys.executable)
        fake = bindir / "docker"
        fake.write_text(_FAKE_DOCKER)
        fake.chmod(0o755)
        self.env = {"PATH": f"{bindir}{os.pathsep}{os.defpath}", "FAKE_DOCKER_STATE": str(self.state)}
        self.snapshot = tmp_path / "snapshot"

    def call(self, function: str, *, fail: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **({"FAKE_DOCKER_FAIL": fail} if fail else {})}
        return subprocess.run(
            ["bash", "-c", f'source "$1"; {function} "$2"', "_", str(LIB), str(self.snapshot)],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )

    def add(self, *, images: list[dict[str, Any]] = (), containers: list[dict[str, Any]] = ()) -> None:  # type: ignore[assignment]
        data = json.loads(self.state.read_text())
        data["images"].extend(images)
        data["containers"].extend(containers)
        self.state.write_text(json.dumps(data))

    def image_ids(self) -> set[str]:
        return {i["id"] for i in json.loads(self.state.read_text())["images"]}

    def container_ids(self) -> set[str]:
        return {c["id"] for c in json.loads(self.state.read_text())["containers"]}

    def log(self) -> list[list[str]]:
        return json.loads(self.state.read_text())["log"]


def test_a_run_removes_only_its_own_dangling_skillc_images(tmp_path: Path) -> None:
    host = Host(tmp_path, images=[
        _image("cotenant-campaign", labels=SKILLC),          # untagged build.py output from before this run
        _image("tagged-campaign", tags=["skillc-profile-runtime:x"], labels=SKILLC),
    ], containers=[])
    assert host.call("snapshot_runner_artifacts").returncode == 0
    host.add(images=[
        _image("runner-leftover", labels=SKILLC),             # this run's dangling skillc image
        _image("unlabelled-leftover"),                        # dangling, but not a skillc image
        _image("runner-tagged", tags=["skillc-trial-test:1"], labels=SKILLC),
    ])
    assert host.call("remove_runner_artifacts").returncode == 0
    assert host.image_ids() == {
        "sha256:cotenant-campaign", "sha256:tagged-campaign", "sha256:unlabelled-leftover", "sha256:runner-tagged",
    }
    assert ["image-rm", "sha256:runner-leftover"] in host.log()  # control: the runner's own IS cleaned


def test_removing_a_runs_image_never_takes_a_pre_existing_untagged_parent(tmp_path: Path) -> None:
    """#414 review: `docker image rm` deletes an image's untagged parents
    unless told `--no-prune`. A pre-existing untagged parent of this run's
    child image is in the snapshot, so it is not this run's to remove."""
    host = Host(tmp_path, images=[_image("cotenant-parent", labels=SKILLC)], containers=[])
    host.call("snapshot_runner_artifacts")
    host.add(images=[_image("runner-child", labels=SKILLC, parent="cotenant-parent")])
    host.call("remove_runner_artifacts")
    assert host.image_ids() == {"sha256:cotenant-parent"}


def test_a_run_removes_only_its_own_stopped_managed_containers(tmp_path: Path) -> None:
    host = Host(tmp_path, images=[], containers=[_container("cotenant-stopped", "exited", MANAGED)])
    host.call("snapshot_runner_artifacts")
    host.add(containers=[
        _container("runner-exited", "exited", MANAGED),
        _container("runner-dead", "dead", MANAGED),
        _container("runner-running", "running", MANAGED),
        _container("unlabelled-exited", "exited"),
    ])
    host.call("remove_runner_artifacts")
    assert host.container_ids() == {"cotenant-stopped", "runner-running", "unlabelled-exited"}


def test_no_host_wide_prune_and_no_forced_removal_is_ever_issued(tmp_path: Path) -> None:
    host = Host(tmp_path, images=[_image("old", labels=SKILLC)], containers=[_container("old-c", "exited", MANAGED)])
    host.call("snapshot_runner_artifacts")
    host.add(images=[_image("new", labels=SKILLC)], containers=[_container("new-c", "exited", MANAGED)])
    host.call("remove_runner_artifacts")
    assert not [entry for entry in host.log() if entry[0] in ("prune", "image-rm-forced")]


def test_an_incomplete_snapshot_removes_nothing(tmp_path: Path) -> None:
    """A failed listing must not leave a snapshot that makes everything look
    new: the removal refuses outright and says so."""
    host = Host(tmp_path, images=[_image("cotenant", labels=SKILLC)], containers=[])
    snap = host.call("snapshot_runner_artifacts", fail="images")
    assert "will remove nothing" in snap.stderr
    host.add(images=[_image("runner-leftover", labels=SKILLC)])
    removed = host.call("remove_runner_artifacts")
    assert "cleanup skipped" in removed.stderr
    assert host.image_ids() == {"sha256:cotenant", "sha256:runner-leftover"}
    assert host.log() == []


def test_a_missing_snapshot_file_removes_nothing(tmp_path: Path) -> None:
    host = Host(tmp_path, images=[_image("cotenant", labels=SKILLC)], containers=[])
    assert host.call("remove_runner_artifacts").returncode == 0
    assert host.log() == []


def test_run_real_docker_no_longer_prunes_host_wide() -> None:
    script = (ROOT / "ci" / "real-docker" / "run-real-docker").read_text()
    code = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "prune" in line]
    assert any("snapshot_runner_artifacts" in line for line in code)
    assert any("remove_runner_artifacts" in line for line in code)


def test_run_real_docker_tells_its_pytest_that_it_holds_run_lock() -> None:
    """The live cleanup tests run only when this marker is set (they would
    otherwise risk a neighbour's artifacts on a shared daemon), so the runner -
    which holds run.lock - must pass it to the pytest it launches."""
    script = (ROOT / "ci" / "real-docker" / "run-real-docker").read_text()
    pytest_block = script[script.index("env SKILLC_LIVE_TEST_BREAK="):script.index("uv run --no-sync pytest -m real_docker")]
    assert "SKILLC_REAL_DOCKER_RUN_LOCK_HELD=1" in pytest_block


def test_the_closure_live_test_releases_its_build_only_under_run_lock() -> None:
    """#414 third review pass: `release_build` is sound only with exclusion
    from inventory through release. The closure live test runs in any gate
    with a reachable daemon, so outside run-real-docker it must KEEP its build
    (tagged, never dangling) rather than release it over a neighbour's."""
    source = (ROOT / "tests" / "test_profile_closure_preflight_live.py").read_text()
    helper = source[source.index("def _build_trial_image("):source.index("_REFUSAL_SYMPTOMS")]
    gate = helper.index('os.environ.get("SKILLC_REAL_DOCKER_RUN_LOCK_HELD") != "1"')
    keep = helper.index("return supply, lambda: None")
    release = helper.index("builder.release_build(receipt, before)")
    assert gate < keep < release, "the unlocked path must return before any release"
