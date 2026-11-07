"""The merger under Kyle's main-merge lease and barrier (Kyle #2130, ADR 0011 D3).

Fake transport only: ``FakeKyle`` stands in for ``kyle-lock`` (lease, barrier
and CI evidence) and ``FakeGitHub`` for ``gh``. No network, no credentials, no
service. Every scenario's transcript is also read by the wiring gate's
:func:`ci.merge_admission.transcript_findings`, so the merger and the gate's
contract cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ci import coordinated_merge as cm
from ci import merge_admission as gate

PR = 101
HEAD = "a" * 40
SQUASH = "b" * 40


class FakeKyle:
    """kyle-lock's exit codes and JSON, with one main-merge lease and barrier."""

    def __init__(self, calls: list[dict[str, Any]], *, acquire: str = "held",
                 pr_ci: tuple[int, str] = (0, HEAD), begin: int = 0, record: int = 0,
                 renew: int = 0, main_ci: list[int] | None = None):
        self.calls = calls
        self.acquire_mode = acquire
        self.pr_ci = pr_ci
        self.begin_exit = begin
        self.record_exit = record
        self.renew_exit = renew
        self.main_ci = list(main_ci if main_ci is not None else [0])
        self.barrier: dict[str, Any] | None = None
        self.released = False
        self.cancelled: list[int] = []

    def __call__(self, argv: list[str]) -> tuple[int, Any]:
        code, answer = self._answer(argv)
        self.calls.append({"tool": "lock", "argv": list(argv), "exit": code})
        return code, answer

    def _answer(self, argv: list[str]) -> tuple[int, Any]:
        action = argv[0]
        if action == "acquire":
            return {
                "held": (0, {"state": "held", "request_id": 7, "lease_id": "lease-7", "generation": 1}),
                "queued": (10, {"state": "queued", "request_id": 7, "queue_position": 2, "retry_after": 5}),
                "frozen": (11, {"state": "frozen", "freeze": {"reason": "drain"}}),
                "unavailable": (75, {"state": "unavailable", "reason": "connection refused"}),
                "refused": (3, {"state": "refused", "code": "forbidden", "reason": "scope"}),
            }[self.acquire_mode]
        if action == "cancel":
            self.cancelled.append(int(argv[argv.index("--request-id") + 1]))
            return 0, {"state": "cancelled"}
        if action == "ci" and "--pr" in argv:
            code, sha = self.pr_ci
            return code, {"status": "success" if code == 0 else "failure", "sha": sha}
        if action == "begin-merge":
            if self.begin_exit:
                return self.begin_exit, {"state": "unavailable"}
            if self.barrier is None:
                self.barrier = {"id": 3, "state": "unknown", "pr": PR, "squash_sha": None}
            return 0, {"state": "merge_begun", "barrier": dict(self.barrier)}
        if action == "record-merge":
            assert self.barrier is not None, "record-merge before begin-merge"
            if self.record_exit:
                return self.record_exit, {"state": "unavailable"}
            sha = argv[argv.index("--squash-sha") + 1]
            self.barrier.update(state="open", squash_sha=sha)
            return 0, {"state": "merge_recorded", "barrier": dict(self.barrier)}
        if action == "renew":
            return self.renew_exit, {"state": "held" if self.renew_exit == 0 else "lost"}
        if action == "ci":
            code = self.main_ci.pop(0) if len(self.main_ci) > 1 else self.main_ci[0]
            return code, {"status": {0: "success", 1: "failure"}.get(code, "pending")}
        if action == "release":
            self.released = True
            return 0, {"state": "released"}
        raise AssertionError(f"unexpected kyle-lock call {argv}")


class FakeGitHub:
    def __init__(self, calls: list[dict[str, Any]], *, head: str = HEAD, state: str = "OPEN",
                 merge_exit: int = 0, merges: bool = True, view_after_merge: str | None = None):
        self.calls = calls
        self.head = head
        self.state = state
        self.merge_exit = merge_exit
        self.merges = merges
        self.view_after_merge = view_after_merge

    @property
    def merge_calls(self) -> int:
        return sum(1 for c in self.calls if c["tool"] == "gh" and c["argv"][:2] == ["pr", "merge"])

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        code, out = self._answer(argv)
        self.calls.append({"tool": "gh", "argv": list(argv), "exit": code})
        return code, out

    def _answer(self, argv: list[str]) -> tuple[int, str]:
        if argv[:2] == ["pr", "merge"]:
            if self.merges:
                self.state = "MERGED"
            return self.merge_exit, ""
        if argv[:2] == ["pr", "view"] and "state,mergeCommit" in argv:
            if self.view_after_merge is not None:
                return 0, self.view_after_merge
            commit = {"oid": SQUASH} if self.state == "MERGED" else None
            return 0, json.dumps({"state": self.state, "mergeCommit": commit})
        if argv[:2] == ["pr", "view"]:
            return 0, json.dumps({"state": self.state, "headRefOid": self.head, "isDraft": False})
        raise AssertionError(f"unexpected gh call {argv}")


@pytest.fixture
def admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    flag = tmp_path / "admission"
    flag.write_bytes(b"on\n")
    monkeypatch.setenv(cm.ADMISSION_FILE_ENV, str(flag))
    return flag


def merge(tmp_path: Path, kyle: FakeKyle, github: FakeGitHub, *, resume: bool = False,
          acquire_wait: float = 0.0, ci_timeout: float = 60.0) -> int:
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    settings = cm.Settings(pr=PR, head=HEAD, state_dir=tmp_path / "state", resume=resume,
                           acquire_wait=acquire_wait, ci_timeout=ci_timeout, poll=10.0)
    return cm.Merger(settings, kyle, github, sleep=sleep, clock=lambda: clock[0]).run()


def actions(calls: list[dict[str, Any]]) -> list[str]:
    return [c["argv"][0] if c["tool"] == "lock" else f"gh {c['argv'][0]} {c['argv'][1]}" for c in calls]


# -- 1. no remote merge until a held lease and a confirmed begin ------------------


def test_coordinated_merge_records_intent_before_merging_and_holds_through_main(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, main_ci=[75, 75, 0]), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_OK
    assert actions(calls) == [
        "acquire", "gh pr view", "ci", "begin-merge", "gh pr merge", "gh pr view", "record-merge",
        "renew", "ci", "renew", "ci", "renew", "ci", "release"]
    begin = next(c["argv"] for c in calls if c["argv"][0] == "begin-merge")
    assert begin[begin.index("--repo") + 1:begin.index("--repo") + 2] == ["cooneycw/skillc"]
    assert begin[begin.index("--pr") + 1] == str(PR)
    assert ["--request-id", "7", "--lease-id", "lease-7", "--generation", "1"] == begin[2:8]
    merged = next(c["argv"] for c in calls if c["argv"][:2] == ["pr", "merge"])
    assert merged[merged.index("--match-head-commit") + 1] == HEAD
    main = [c["argv"] for c in calls if c["argv"][0] == "ci" and "--sha" in c["argv"]]
    assert all(a[a.index("--sha") + 1] == SQUASH and "push" in a and "main" in a for a in main)
    assert kyle.barrier == {"id": 3, "state": "open", "pr": PR, "squash_sha": SQUASH}
    assert gate.transcript_findings(calls, PR) == []
    assert not list((tmp_path / "state").glob("*.json")), "a finished merge leaves no recovery record"


@pytest.mark.parametrize("mode, code", [
    ("queued", cm.EXIT_QUEUED), ("frozen", cm.EXIT_FROZEN),
    ("unavailable", cm.EXIT_UNAVAILABLE), ("refused", cm.EXIT_REFUSED),
])
def test_no_grant_means_zero_merge_calls(tmp_path: Path, mode: str, code: int) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, acquire=mode), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github, acquire_wait=30.0) == code
    assert github.merge_calls == 0
    assert "begin-merge" not in actions(calls)
    if mode == "queued":
        assert kyle.cancelled == [7], "a queued request left behind would be served later"


@pytest.mark.parametrize("github_kw, kyle_kw", [
    ({"head": "c" * 40}, {}),
    ({"state": "CLOSED"}, {}),
    ({}, {"pr_ci": (1, HEAD)}),
    ({}, {"pr_ci": (0, "c" * 40)}),
    ({}, {"pr_ci": (75, HEAD)}),
], ids=["moved-head", "closed", "pr-red", "ci-other-sha", "ci-unknown"])
def test_failed_exact_head_check_releases_without_intent_or_merge(
        tmp_path: Path, github_kw: dict[str, Any], kyle_kw: dict[str, Any]) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, **kyle_kw), FakeGitHub(calls, **github_kw)
    assert merge(tmp_path, kyle, github) in (cm.EXIT_REFUSED, cm.EXIT_UNAVAILABLE)
    assert github.merge_calls == 0 and kyle.barrier is None and kyle.released


def test_unconfirmed_begin_means_no_merge(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, begin=75), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNAVAILABLE
    assert github.merge_calls == 0


# -- 2. crash or lost response after merge: never a second merge ------------------


def test_lost_merge_response_resumes_the_same_intent_without_merging_again(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle = FakeKyle(calls)
    # The merge happened, but the read-back was lost: outcome unknown.
    github = FakeGitHub(calls, merge_exit=1, view_after_merge="not json")
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNKNOWN
    assert kyle.barrier is not None and kyle.barrier["state"] == "unknown"
    assert not kyle.released, "the fence is the only way to record this intent later"
    github.view_after_merge = None
    assert merge(tmp_path, kyle, github, resume=True) == cm.EXIT_OK
    assert github.merge_calls == 1
    assert [c["argv"][0] for c in calls].count("record-merge") == 1
    assert kyle.barrier["squash_sha"] == SQUASH
    assert gate.transcript_findings(calls, PR) == []


def test_unmerged_outcome_stays_blocked_and_is_never_retried(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls), FakeGitHub(calls, merge_exit=1, merges=False)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNKNOWN
    assert merge(tmp_path, kyle, github, resume=True) == cm.EXIT_UNKNOWN
    assert github.merge_calls == 1, "an ambiguous merge must never be re-issued"
    assert kyle.barrier is not None and kyle.barrier["state"] == "unknown", "only tier 3 resolves it"


def test_unfinished_record_refuses_a_fresh_run(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, record=75), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNKNOWN
    assert merge(tmp_path, FakeKyle(calls), github) == cm.EXIT_REFUSED
    assert github.merge_calls == 1


def test_red_main_push_is_never_success(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, main_ci=[75, 1]), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_RED
    assert kyle.released


@pytest.mark.parametrize("kyle_kw, code", [
    ({"main_ci": [75]}, cm.EXIT_UNAVAILABLE),
    ({"renew": 12}, cm.EXIT_LOST),
], ids=["pending-past-timeout", "lease-lost"])
def test_unfinished_main_evidence_never_clears(tmp_path: Path, kyle_kw: dict[str, Any], code: int) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, **kyle_kw), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github, ci_timeout=30.0) == code
    assert kyle.barrier is not None and kyle.barrier["state"] == "open", "the barrier still blocks"


# -- the switch -------------------------------------------------------------------


@pytest.mark.parametrize("content", [None, b"on", b"ON\n", b"on\n\n", b"1\n", b""])
def test_admission_is_off_unless_exactly_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            content: bytes | None) -> None:
    flag = tmp_path / "admission"
    if content is not None:
        flag.write_bytes(content)
    monkeypatch.setenv(cm.ADMISSION_FILE_ENV, str(flag))

    def untouchable(argv: list[str]) -> Any:
        raise AssertionError(f"admission off, yet called {argv}")

    assert cm.main(["--pr", str(PR), "--head", HEAD, "--state-dir", str(tmp_path / "s")],
                   lock=untouchable, gh=untouchable) == cm.EXIT_USAGE


def test_admission_on_reaches_the_coordinator(tmp_path: Path, admission: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls), FakeGitHub(calls)
    assert cm.main(["--pr", str(PR), "--head", HEAD, "--state-dir", str(tmp_path / "s"), "--poll", "0"],
                   lock=kyle, gh=github) == cm.EXIT_OK
    assert calls[0]["argv"][:2] == ["acquire", "main-merge"]


def test_default_flag_is_the_shared_cpp_switch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(cm.ADMISSION_FILE_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cm.admission_file() == tmp_path / "claude-power-pack" / "coordination" / "admission"


def test_client_must_be_named_explicitly(tmp_path: Path, admission: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cm.CLIENT_ENV, raising=False)
    assert cm.main(["--pr", str(PR), "--head", HEAD, "--state-dir", str(tmp_path)]) == cm.EXIT_USAGE


# -- 3. D3: the pipeline the merger waits on never takes main-merge ---------------

CONTROLS = gate.ROOT / "controls" / "merge-admission"
FAKE_CLIENT = """#!/usr/bin/env bash
# Records every call. main-merge is held by the merger, so CI's acquire queues.
printf '%s\\n' "$*" >> "$KYLE_LOCK_CALL_LOG"
if [ "$1" = acquire ] && [ "$2" = main-merge ]; then
  echo '{"state": "queued", "queue_position": 1}'; exit 10
fi
echo '{"state": "held"}'
"""


class PipelineKyle(FakeKyle):
    """The main push read runs the control pipeline's steps, as CI would."""

    def __init__(self, calls: list[dict[str, Any]], case: str, bin_dir: Path, log: Path):
        super().__init__(calls)
        self.case, self.bin_dir, self.log = case, bin_dir, log
        self.held_during_pipeline: list[bool] = []

    def _answer(self, argv: list[str]) -> tuple[int, Any]:
        if argv[0] == "ci" and "--sha" in argv:
            self.held_during_pipeline.append(not self.released)
            return self._run_pipeline(), {}
        return super()._answer(argv)

    def _run_pipeline(self) -> int:
        import os
        import subprocess

        import yaml

        root = CONTROLS / self.case
        env = {**os.environ, "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
               "KYLE_LOCK_CALL_LOG": str(self.log)}
        for step in yaml.safe_load((root / "ci.yml").read_text(encoding="utf-8"))["steps"]:
            script = "set -euo pipefail\n" + "\n".join(step["commands"])
            done = subprocess.run(["bash", "-c", script], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=30, check=False)
            if done.returncode:
                return cm.EXIT_RED
        return cm.EXIT_OK


def _pipeline_run(tmp_path: Path, case: str) -> tuple[int, PipelineKyle, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "kyle-lock").write_text(FAKE_CLIENT, encoding="utf-8")
    (bin_dir / "kyle-lock").chmod(0o755)
    log = tmp_path / "ci-lock-calls.log"
    log.touch()
    calls: list[dict[str, Any]] = []
    kyle = PipelineKyle(calls, case, bin_dir, log)
    code = merge(tmp_path, kyle, FakeGitHub(calls))
    return code, kyle, log.read_text(encoding="utf-8").splitlines()


def test_a_good_pipeline_progresses_with_zero_ci_main_merge_acquires(tmp_path: Path) -> None:
    code, kyle, ci_calls = _pipeline_run(tmp_path, "good")
    assert kyle.held_during_pipeline == [True], "the merger holds main-merge while CI runs"
    assert ci_calls == []
    assert code == cm.EXIT_OK


def test_a_planted_inner_acquire_is_the_deadlock_and_the_gate_names_it(tmp_path: Path) -> None:
    code, kyle, ci_calls = _pipeline_run(tmp_path, "bad")
    assert kyle.held_during_pipeline == [True]
    # Against the real service this acquire would queue behind the merger forever.
    assert [c for c in ci_calls if c.startswith("acquire main-merge")], ci_calls
    assert code == cm.EXIT_RED, "a pipeline waiting on its own merger is never green"
    assert gate.pipeline_findings((CONTROLS / "bad" / "ci.yml").read_text(encoding="utf-8"),
                                  CONTROLS / "bad")


# -- review hardening: concurrency, durability, lost begin, timeout ---------------


def test_a_concurrent_run_on_the_same_record_is_refused(tmp_path: Path) -> None:
    import fcntl

    calls: list[dict[str, Any]] = []
    state = tmp_path / "state"
    state.mkdir()
    lock = (state / f"{cm.REPO.replace('/', '__')}-pr{PR}.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        github = FakeGitHub(calls)
        assert merge(tmp_path, FakeKyle(calls), github) == cm.EXIT_REFUSED
        assert calls == [], "a second process must not even acquire"
    finally:
        lock.close()


def test_an_unpersistable_merge_marker_means_no_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls), FakeGitHub(calls)
    real_fsync = cm.os.fsync
    saves = {"n": 0}

    def failing_fsync(fd: int) -> None:
        # held, begin_pending and begun persist; the merge_sent marker does not.
        saves["n"] += 1
        if saves["n"] > 6:
            raise OSError(5, "I/O error")
        real_fsync(fd)

    monkeypatch.setattr(cm.os, "fsync", failing_fsync)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNAVAILABLE
    assert github.merge_calls == 0


class LostBeginKyle(FakeKyle):
    """Kyle records the intent, but the first begin response never arrives."""

    lost = True

    def _answer(self, argv: list[str]) -> tuple[int, Any]:
        code, answer = super()._answer(argv)
        if argv[0] == "begin-merge" and self.lost:
            self.lost = False
            return cm.EXIT_UNAVAILABLE, None
        return code, answer


def test_a_lost_begin_response_keeps_the_record_when_the_head_moved(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = LostBeginKyle(calls), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNAVAILABLE
    assert kyle.barrier is not None and kyle.barrier["state"] == "unknown"
    github.head = "c" * 40
    assert merge(tmp_path, kyle, github, resume=True) == cm.EXIT_UNKNOWN
    assert github.merge_calls == 0
    assert any((tmp_path / "state").glob("*.json")), "the only record of the intent was deleted"


def test_a_lost_begin_response_resumes_through_the_same_intent(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = LostBeginKyle(calls), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github) == cm.EXIT_UNAVAILABLE
    assert merge(tmp_path, kyle, github, resume=True) == cm.EXIT_OK
    assert github.merge_calls == 1
    assert actions(calls).count("acquire") == 1, "resume keeps the original fence"


def test_a_timed_out_wait_keeps_the_lease_and_resumes(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    kyle, github = FakeKyle(calls, main_ci=[75]), FakeGitHub(calls)
    assert merge(tmp_path, kyle, github, ci_timeout=30.0) == cm.EXIT_UNAVAILABLE
    assert not kyle.released
    kyle.main_ci = [0]
    assert merge(tmp_path, kyle, github, resume=True) == cm.EXIT_OK
    assert kyle.released and github.merge_calls == 1
