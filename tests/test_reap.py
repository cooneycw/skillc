"""Tests for `skillc/reap.py` (#79): label-scoped reaping and resource
snapshots, against the fake `docker` CLI (`tests/fixtures/docker-backend/
fake_docker.py`) - the real daemon boundary is owed to the operator's live
run (#10), exactly as `docker_backend.py` itself states.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT

from skillc import reap
from skillc.docker_backend import ATTEMPT_LABEL_KEY, OWNER_LABEL_KEY, OWNER_LABEL_VALUE

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _run(docker_state: Path, name: str, labels: dict[str, str]) -> None:
    argv = [*_docker_bin(docker_state), "run", "--rm", "-d", "--name", name]
    for key, value in labels.items():
        argv += ["--label", f"{key}={value}"]
    argv += ["--", "fake-image:1", "sleep", "infinity"]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _owned_labels(attempt_id: str) -> dict[str, str]:
    return {OWNER_LABEL_KEY: OWNER_LABEL_VALUE, ATTEMPT_LABEL_KEY: attempt_id}


def test_network_only_residue_is_removed_by_public_reap(docker_state: Path) -> None:
    argv = [*_docker_bin(docker_state), "network", "create", "--internal"]
    for key, value in _owned_labels("att-network").items():
        argv += ["--label", f"{key}={value}"]
    subprocess.run([*argv, "selected-egress"], check=True, capture_output=True)
    network = docker_state / "networks/selected-egress.json"
    assert network.is_file(), "the unhealthy population must actually exist"
    report = reap.reap(_docker_bin(docker_state), ["att-network"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert not network.exists(), "successful container-only absence must not hide network residue"
    assert report.outcome_for("att-network") == "reaped"


# --------------------------------------------------------------- snapshot()

def test_snapshot_partitions_owned_from_foreign(docker_state: Path) -> None:
    _run(docker_state, "ours", _owned_labels("att-1"))
    _run(docker_state, "foreign-lookalike", {"some.other.label": "x"})
    snap = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert snap.reachable is True
    assert snap.owned == frozenset({"ours"})
    assert snap.foreign == frozenset({"foreign-lookalike"})


def test_snapshot_is_unreachable_never_empty_when_the_daemon_is_down(docker_state: Path) -> None:
    docker_state.mkdir(parents=True)
    (docker_state / ".down").touch()
    snap = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert snap.reachable is False
    assert snap.owned == frozenset()
    assert snap.foreign == frozenset()


# ------------------------------------------------------------------ diff()

def test_diff_flags_a_leak_in_one_direction(docker_state: Path) -> None:
    before = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    _run(docker_state, "left-running", _owned_labels("att-1"))
    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    result = reap.diff(before, after)
    assert result.comparable is True
    assert result.leaked == frozenset({"left-running"})
    assert result.foreign_vanished == frozenset()


def test_diff_flags_a_foreign_disappearance_in_the_other_direction(docker_state: Path) -> None:
    _run(docker_state, "foreign-1", {"some.other.label": "x"})
    before = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    subprocess.run([*_docker_bin(docker_state), "rm", "-f", "foreign-1"], check=True, capture_output=True)
    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    result = reap.diff(before, after)
    assert result.comparable is True
    assert result.foreign_vanished == frozenset({"foreign-1"})
    assert result.leaked == frozenset()


def test_diff_is_not_comparable_across_an_unreachable_snapshot(docker_state: Path) -> None:
    before = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    result = reap.diff(before, after)
    assert result.comparable is False
    assert result.leaked == frozenset()
    assert result.foreign_vanished == frozenset()


# ------------------------------------------------------------------ reap()

def test_a_container_left_running_on_purpose_is_detected_and_reaped(docker_state: Path) -> None:
    """Control #1 (#79's own wording): a container left running is detected,
    and reaping removes it."""
    _run(docker_state, "orphan", _owned_labels("att-1"))
    before = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert "orphan" in before.owned

    report = reap.reap(_docker_bin(docker_state), ["att-1"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.daemon_reachable is True
    assert report.outcome_for("att-1") == "reaped"
    assert report.reaped == ("att-1",)

    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert "orphan" not in after.owned


def test_a_foreign_lookalike_is_never_touched(docker_state: Path) -> None:
    """Control #2: a foreign container carrying a similar name but not our
    label is never touched - proven both by the snapshot and by the fake
    CLI's own state (rm was never issued against it)."""
    _run(docker_state, "skillc-att-1", {"some.other.label": "x"})  # looks like ours, is not
    _run(docker_state, "att-1-orphan", _owned_labels("att-1"))

    report = reap.reap(_docker_bin(docker_state), ["att-1"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.outcome_for("att-1") == "reaped"

    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert "skillc-att-1" in after.foreign  # untouched: still exists
    assert "att-1-orphan" not in after.owned  # the real one is gone


def test_an_already_absent_attempt_is_idempotent_not_an_error(docker_state: Path) -> None:
    report = reap.reap(_docker_bin(docker_state), ["never-existed"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.daemon_reachable is True
    assert report.outcome_for("never-existed") == "already-absent"

    # Calling it again changes nothing.
    report2 = reap.reap(_docker_bin(docker_state), ["never-existed"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report2.outcome_for("never-existed") == "already-absent"


def test_reaping_two_attempts_only_removes_the_named_ones(docker_state: Path) -> None:
    _run(docker_state, "keep-me", _owned_labels("att-keep"))
    _run(docker_state, "reap-me", _owned_labels("att-reap"))

    report = reap.reap(_docker_bin(docker_state), ["att-reap"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.outcome_for("att-reap") == "reaped"
    assert report.outcome_for("att-keep") is None  # never asked about

    after = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert after.owned == frozenset({"keep-me"})


def test_unknown_never_reaps_when_the_daemon_is_unreachable(docker_state: Path) -> None:
    """UNKNOWN never reaps: the daemon cannot even be asked, so nothing is
    removed and the attempt is reported `unknown` - never `left-running`
    (which asserts the daemon CONFIRMS something is still there, a fact this
    call could not establish), never `already-absent`, never `reaped`."""
    _run(docker_state, "orphan", _owned_labels("att-1"))
    (docker_state / ".down").touch()

    report = reap.reap(_docker_bin(docker_state), ["att-1"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.daemon_reachable is False
    assert report.outcome_for("att-1") == "unknown"
    assert report.unknown == ("att-1",)
    assert report.reaped == ()
    assert report.left_running == ()

    (docker_state / ".down").unlink()
    still = reap.snapshot(_docker_bin(docker_state), timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert "orphan" in still.owned  # nothing was actually removed


def test_later_initial_uncertainty_prevents_mutating_earlier_attempt(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An uncertain initial inventory for a later ID prevents ALL mutations.

    The old per-attempt sweep could mutate earlier IDs before discovering that
    the batch inventory was incomplete. The selected network contract requires
    a complete preflight, while preserving UNKNOWN as distinct from known residue.
    """
    _run(docker_state, "stuck-one", _owned_labels("att-stuck"))
    (docker_state / ".stuck-stuck-one").touch()
    real_run = subprocess.run

    def _flaky_run(
        argv: list[str], *, capture_output: bool = False, env: dict[str, str] | None = None,
        check: bool = False, timeout: float | None = None, text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if any("label=skillc.attempt-id=att-unreachable" in str(a) for a in argv):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout or 0)
        return real_run(
            argv, capture_output=capture_output, env=env, check=check, timeout=timeout, text=text,
        )

    monkeypatch.setattr(reap.subprocess, "run", _flaky_run)
    report = reap.reap(_docker_bin(docker_state), ["att-stuck", "att-unreachable"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)

    assert report.outcome_for("att-stuck") == "unknown"
    assert report.outcome_for("att-unreachable") == "unknown"
    assert report.left_running == ()
    assert report.unknown == ("att-stuck", "att-unreachable")
    assert "stuck-one" in reap.snapshot(_docker_bin(docker_state)).owned


def test_a_container_that_cannot_be_confirmed_removed_is_left_running(docker_state: Path) -> None:
    """`rm -f` reporting success is not trusted alone (the same rule
    `DockerBackend.confirm_absent` already applies to a single attempt):
    the fake CLI's `.stuck-NAME` sentinel makes `rm` lie about success, and
    the follow-up list must catch that the container is still there."""
    _run(docker_state, "stuck-one", _owned_labels("att-1"))
    (docker_state / ".stuck-stuck-one").touch()

    report = reap.reap(_docker_bin(docker_state), ["att-1"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.outcome_for("att-1") == "left-running"
    assert report.reaped == ()


def test_reap_refuses_an_empty_attempt_population(docker_state: Path) -> None:
    """Codex review, MEDIUM: an empty `attempt_ids` used to report
    `daemon_reachable=True` having checked nothing at all - refused now,
    the same rule this codebase applies to an empty record population."""
    with pytest.raises(ValueError, match="empty"):
        reap.reap(_docker_bin(docker_state), [], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)


def test_reap_removes_by_container_id_never_by_name(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review, HIGH: `reap()` used to list, remove (`rm -f NAME`) and
    confirm by NAME - three separate round trips to a daemon nothing
    prevents from changing between them. A NAME can be taken by a brand-new,
    DIFFERENT container the instant the original is removed; an ID cannot,
    since it is unique to one container's lifetime. This asserts the actual
    `rm` invocation targets the container's ID, not its declared name -
    the property that makes the race impossible, not merely a scenario that
    happens not to trigger it."""
    _run(docker_state, "att-1-container", _owned_labels("att-1"))
    calls: list[list[str]] = []
    real_run = subprocess.run  # captured BEFORE patching - `subprocess` is one shared
    # module object, so `reap.subprocess` IS `subprocess` here; referring to
    # `subprocess.run` again inside `_spy` would resolve the PATCHED attribute
    # and recurse forever.

    def _spy(
        argv: list[str], *, capture_output: bool = False, env: dict[str, str] | None = None,
        check: bool = False, timeout: float | None = None, text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return real_run(
            argv, capture_output=capture_output, env=env, check=check, timeout=timeout, text=text,
        )

    monkeypatch.setattr(reap.subprocess, "run", _spy)
    report = reap.reap(_docker_bin(docker_state), ["att-1"], timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    assert report.outcome_for("att-1") == "reaped"

    rm_calls = [c for c in calls if "rm" in c]
    assert len(rm_calls) == 1
    target = rm_calls[0][-1]
    assert target != "att-1-container"  # never the declared name
    assert len(target) == 64 and all(ch in "0123456789abcdef" for ch in target)  # the fake's own id shape


# --------------------------------------------------- declared host paths

def test_an_unmodified_declared_host_path_reports_no_change(tmp_path: Path) -> None:
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    before = reap.snapshot_host_paths([watched])
    after = reap.snapshot_host_paths([watched])
    assert reap.diff_host_paths(before, after).changed == ()


def test_a_deliberately_modified_declared_host_path_is_reported(tmp_path: Path) -> None:
    """Control #3 (#79's own wording): a deliberately modified declared host
    path is reported."""
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    before = reap.snapshot_host_paths([watched])

    watched.write_text("tampered\n")
    after = reap.snapshot_host_paths([watched])

    result = reap.diff_host_paths(before, after)
    assert result.changed == (str(watched),)


def test_a_declared_path_that_appears_or_disappears_is_reported(tmp_path: Path) -> None:
    appears = tmp_path / "appears.txt"
    before = reap.snapshot_host_paths([appears])
    appears.write_text("new\n")
    after = reap.snapshot_host_paths([appears])
    assert reap.diff_host_paths(before, after).changed == (str(appears),)


def test_an_unrelated_undeclared_host_path_is_never_examined(tmp_path: Path) -> None:
    """States the limitation directly: only declared paths are ever hashed -
    a change elsewhere on the host is invisible to this check by design."""
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("original\n")

    before = reap.snapshot_host_paths([watched])
    unrelated.write_text("tampered\n")  # never declared, never checked
    after = reap.snapshot_host_paths([watched])

    assert reap.diff_host_paths(before, after).changed == ()


def test_snapshot_host_paths_refuses_an_empty_declaration() -> None:
    """Codex review, MEDIUM: an empty declaration used to report `changed=()`
    indistinguishably from "checked and confirmed unchanged"."""
    with pytest.raises(ValueError, match="empty"):
        reap.snapshot_host_paths([])


def test_an_unreadable_declared_path_is_unresolved_not_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review, MEDIUM: an `OSError` (permission denied) used to collapse
    into the same `None` as confirmed absence, so an unreadable file
    compared as "unchanged" against itself - a false claim of certainty this
    instrument does not have. It must be `unresolved`, never `changed` (we
    cannot confirm a difference) and never silently absent from both.

    Unreadability is forced by monkeypatching `Path.read_bytes`, not by
    `chmod(0o000)` (orchestrator review of PR #91, CI pipeline 138): CI's
    `python:3.12-slim` gate step runs as root, and root reads a chmod-000
    file anyway, so the permission-based version passed only for a non-root
    user - it never exercised the UNREADABLE path in CI at all. A forced
    `PermissionError` is deterministic identically as root or not.
    """
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    real_read_bytes = Path.read_bytes

    def _refuse_read(self: Path) -> bytes:
        if self == watched:
            raise PermissionError(f"forced unreadable for this test: {self}")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _refuse_read)
    before = reap.snapshot_host_paths([watched])
    after = reap.snapshot_host_paths([watched])

    assert before.digests[str(watched)] == reap.UNREADABLE
    result = reap.diff_host_paths(before, after)
    assert result.unresolved == (str(watched),)
    assert result.changed == ()


def test_a_declaration_added_between_snapshots_is_reported_not_ignored(tmp_path: Path) -> None:
    """Codex review, MEDIUM: `.get(key)` used to default a key missing from
    one snapshot's declarations to `None`, colliding with the legitimate
    "confirmed absent" `None` and making an added/removed declaration
    invisible even when the path itself never changed."""
    watched = tmp_path / "watched.txt"
    # `before` never declared this path at all (a genuinely different key
    # set, not merely a path that happened to be absent).
    before = reap.HostPathSnapshot(digests={})
    after = reap.snapshot_host_paths([watched])  # declared, and confirmed absent (None)

    result = reap.diff_host_paths(before, after)
    assert result.changed == (str(watched),)
    assert result.unresolved == ()


# #549: public recovery and bad/good protocol populations, never a real daemon.
def _network(state: Path, name: str, attempt: str, labels: dict[str, str] | None = None) -> Path:
    argv = [*_docker_bin(state), "network", "create", "--internal"]
    for k, v in (_owned_labels(attempt) if labels is None else labels).items():
        argv += ["--label", f"{k}={v}"]
    subprocess.run([*argv, name], capture_output=True, check=True)
    return state / "networks" / f"{name}.json"


def _state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def test_dual_recovery_preserves_unselected_and_partial_label_sentinels(docker_state: Path) -> None:
    _run(docker_state, "selected", _owned_labels("a"))
    _run(docker_state, "proxy", _owned_labels("a"))
    network = _network(docker_state, "ours", "a")
    for name in ("selected", "proxy"):
        subprocess.run([*_docker_bin(docker_state), "network", "connect", "ours", name], check=True)
    _run(docker_state, "second", _owned_labels("b"))
    second = _network(docker_state, "second-net", "b")
    keep = [_network(docker_state, "other", "other"),
            _network(docker_state, "owner-only", "a", {OWNER_LABEL_KEY: OWNER_LABEL_VALUE}),
            _network(docker_state, "attempt-only", "a", {ATTEMPT_LABEL_KEY: "a"})]
    _run(docker_state, "foreign", _owned_labels("live-unknown-owner"))
    keep.append(docker_state / "foreign.json")
    before = {p: p.read_bytes() for p in keep}
    report = reap.reap(_docker_bin(docker_state), ["a", "a", "b"])
    assert report.clean and len(report.outcomes) == 2 and not network.exists() and not second.exists()
    assert not (docker_state / "selected.json").exists() and not (docker_state / "proxy.json").exists()
    assert all(p.read_bytes() == b for p, b in before.items())
    assert reap.reap(_docker_bin(docker_state), ["a"]).outcome_for("a") == "already-absent"


def test_foreign_endpoint_is_preserved_without_disconnect(docker_state: Path) -> None:
    network = _network(docker_state, "ours", "a")
    _run(docker_state, "foreign", _owned_labels("unselected"))
    subprocess.run([*_docker_bin(docker_state), "network", "connect", "ours", "foreign"], check=True)
    sentinel = (docker_state / "foreign.json").read_bytes()
    report = reap.reap(_docker_bin(docker_state), ["a"])
    assert report.outcome_for("a") == "left-present" and not report.clean
    assert network.is_file() and (docker_state / "foreign.json").read_bytes() == sentinel
    assert report.outcomes[0].actions == () and report.nonclean == ("a",)


@pytest.mark.parametrize("kind", ["container", "network"])
@pytest.mark.parametrize("fault", ["nonzero", "timeout", "oserror", "garbage", "truncated", "no-newline", "duplicate"])
def test_any_initial_inventory_fault_means_zero_actions_for_all_selected(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, kind: str, fault: str,
) -> None:
    _run(docker_state, "first", _owned_labels("first"))
    _run(docker_state, "later", _owned_labels("later"))
    net = _network(docker_state, "later-net", "later")
    identity = _state(net)["id"] if kind == "network" else _state(docker_state / "later.json")["id"]
    calls: list[list[str]] = []
    real = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        listing = ("ps" in argv) if kind == "container" else ("network" in argv and "ls" in argv)
        if listing and f"label={ATTEMPT_LABEL_KEY}=later" in argv:
            if fault == "timeout":
                raise subprocess.TimeoutExpired(argv, 1)
            if fault == "oserror":
                raise OSError("controlled inventory failure")
            text = {"garbage": "garbage\n", "truncated": identity[:12] + "\n",
                    "no-newline": identity, "duplicate": identity + "\n" + identity + "\n"}.get(fault, "")
            return subprocess.CompletedProcess(argv, 1 if fault == "nonzero" else 0, text, "")
        return real(argv, **kw)

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["first", "later"])
    assert report.unknown == ("first", "later") and not report.clean
    assert not any("rm" in c or "disconnect" in c for c in calls)
    assert (docker_state / "first.json").exists() and (docker_state / "later.json").exists() and net.exists()
    assert any("ls" in c for c in calls) and any("ps" in c for c in calls)


@pytest.mark.parametrize("kind", ["container", "network"])
@pytest.mark.parametrize("fault", ["bad-json", "duplicate-key", "wrong-id", "bad-labels", "bad-endpoints", "wrong-labels"])
def test_metadata_is_independent_scope_and_completeness_evidence(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, fault: str, kind: str,
) -> None:
    if kind == "network":
        net = _network(docker_state, "ours", "a")
    else:
        _run(docker_state, "ours", _owned_labels("a"))
        net = docker_state / "ours.json"
    real = subprocess.run
    mutations: list[list[str]] = []

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if "rm" in argv:
            mutations.append(argv)
        p = real(argv, **kw)
        if "{{json .}}" in argv:
            data = json.loads(p.stdout)
            if fault == "bad-json":
                return subprocess.CompletedProcess(argv, 0, "{", "")
            if fault == "duplicate-key":
                return subprocess.CompletedProcess(argv, 0, '{"Id":"a","Id":"b"}', "")
            if fault == "wrong-id":
                data["Id"] = "0" * 64
            elif fault == "bad-labels":
                data["Labels"] = [] if kind == "network" else data.get("Labels")
                if kind == "container":
                    data["Config"]["Labels"] = []
            elif fault == "bad-endpoints":
                data["Containers"] = {"short": {}}
                if kind == "container":
                    data["Config"] = []
            elif fault == "wrong-labels":
                labels = {OWNER_LABEL_KEY: OWNER_LABEL_VALUE}  # candidate listing alone is not authority
                if kind == "network":
                    data["Labels"] = labels
                else:
                    data["Config"]["Labels"] = labels
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
        return p

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["a"])
    assert not mutations and net.exists()
    assert report.clean if fault == "wrong-labels" else report.unknown == ("a",)


@pytest.mark.parametrize("kind", ["container", "network"])
@pytest.mark.parametrize("effect", ["lie", "reply-error-after-removal", "replace", "relabel"])
def test_identity_confirmation_and_replacements_are_not_chased(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, kind: str, effect: str,
) -> None:
    if kind == "network":
        path = _network(docker_state, "target", "a")
    else:
        _run(docker_state, "target", _owned_labels("a"))
        path = docker_state / "target.json"
    original = _state(path)["id"]
    calls: list[list[str]] = []
    real = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if "rm" not in argv:
            return real(argv, **kw)
        calls.append(argv)
        assert argv[-1] == original and len(argv[-1]) == 64
        if effect == "lie":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if effect == "relabel":
            data = _state(path); data["labels"] = {}; path.write_text(json.dumps(data))
            return subprocess.CompletedProcess(argv, 0, "", "")
        p = real(argv, **kw)
        if effect == "replace":
            data = {"internal": True, "labels": _owned_labels("a"), "id": "f" * 64} if kind == "network" else {
                "status": "running", "labels": _owned_labels("a"), "id": "f" * 64}
            path.write_text(json.dumps(data))
        return subprocess.CompletedProcess(argv, 1, "", "lost reply") if effect == "reply-error-after-removal" else p

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["a"])
    assert len(calls) == 1
    if effect == "reply-error-after-removal":
        assert report.clean and not path.exists() and report.outcomes[0].errors
    else:
        assert not report.clean and path.exists()
        assert report.outcome_for("a") == ("left-present" if kind == "network" else "left-running")
        if effect == "replace":
            assert _state(path)["id"] != original


@pytest.mark.parametrize("fault", ["nonzero", "timeout", "oserror"])
def test_action_error_stops_remaining_mutations_and_retains_prior_actions(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    for name in ("one", "two", "three"):
        _run(docker_state, name, _owned_labels("a"))
    _network(docker_state, "ours", "a")
    real = subprocess.run
    calls: list[list[str]] = []

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if "rm" in argv:
            calls.append(argv)
            if len(calls) == 2:
                if fault == "timeout":
                    raise subprocess.TimeoutExpired(argv, 1)
                if fault == "oserror":
                    raise OSError("controlled action failure")
                return subprocess.CompletedProcess(argv, 1, "", "refused")
        return real(argv, **kw)

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["a"])
    row = report.outcomes[0]
    assert len(calls) == len(row.actions) == 2 and len(row.errors) == 1
    assert len(row.remaining_containers) == 2 and len(row.remaining_networks) == 1 and not report.clean
    assert len(list(docker_state.glob("*.json"))) == 2


@pytest.mark.parametrize("phase", ["selected-inventory", "target-identity"])
def test_confirmation_uncertainty_does_not_erase_successful_actions(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    net = _network(docker_state, "ours", "a")
    real = subprocess.run
    lists = 0

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        nonlocal lists
        if "network" in argv and "ls" in argv:
            lists += 1
            if lists == 2 and phase == "selected-inventory":
                raise subprocess.TimeoutExpired(argv, 1)
        if "{{.Id}}" in argv and phase == "target-identity":
            raise subprocess.TimeoutExpired(argv, 1)
        return real(argv, **kw)

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["a"])
    assert report.unknown == ("a",) and report.outcomes[0].actions and not report.clean and not net.exists()


def test_foreign_endpoint_arriving_after_preflight_refuses_removal_without_disconnect(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    net = _network(docker_state, "ours", "a")
    _run(docker_state, "foreign", _owned_labels("unselected"))
    real = subprocess.run
    calls: list[list[str]] = []

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "network" in argv and "rm" in argv:
            real([*_docker_bin(docker_state), "network", "connect", "ours", "foreign"], check=True)
        return real(argv, **kw)

    monkeypatch.setattr(reap.subprocess, "run", run)
    report = reap.reap(_docker_bin(docker_state), ["a"])
    assert report.outcome_for("a") == "left-present" and report.outcomes[0].errors
    assert net.exists() and (docker_state / "foreign.json").exists() and not report.clean
    assert not any("disconnect" in c for c in calls)
