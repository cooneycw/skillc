"""API transition tests for `skillc/fixture_service.py` (#276).

Every test runs against a REAL bare git remote and, where a filter is
involved, REAL jq - the service's merge, ref reads and jq evaluation are the
things under test, so none of them is faked. The isolated socket path, with
the real shim, is `tests/test_fixture_service_channel.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_service as fs
from skillc.decide_reply_channel import ChannelRefusal

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
needs_jq = pytest.mark.skipif(fs.measure_jq()[0] is None, reason="jq 1.7.x is not installed")

REPO = "fixture/widget"


def _git(cwd: Path, *args: str, date: str = "2026-10-01T00:00:00+0000") -> str:
    env = {"PATH": os.defpath, "LC_ALL": "C", "HOME": str(cwd.parent), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": "file", "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", "-c", "user.name=Subject", "-c", "user.email=subject@fixture.invalid",
                           "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args], cwd=cwd,
                          env=env, capture_output=True, check=True, timeout=30).stdout.decode().strip()


class World:
    """A bare remote, a subject clone, an already-merged fix (PR #2 for
    issue #1) and a pushed `feature` branch for issue #3."""

    def __init__(self, root: Path) -> None:
        self.bare = root / "remote.git"
        self.bare.mkdir()
        _git(self.bare, "init", "--bare", "-q")
        self.work = root / "work"
        _git(root, "clone", "-q", str(self.bare), "work")
        (self.work / "README").write_text("widget\n")
        _git(self.work, "add", "README")
        _git(self.work, "commit", "-q", "-m", "initial")
        _git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        (self.work / "fix.txt").write_text("empty input handled\n")
        _git(self.work, "add", "fix.txt")
        _git(self.work, "commit", "-q", "-m", "fix: widget crash on empty input (#2)",
             date="2026-10-03T00:00:00+0000")
        _git(self.work, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.fixed = _git(self.work, "rev-parse", "HEAD")
        _git(self.work, "checkout", "-q", "-b", "feature")
        (self.work / "feature.txt").write_text("the feature\n")
        _git(self.work, "add", "feature.txt")
        _git(self.work, "commit", "-q", "-m", "feat: add the feature")
        _git(self.work, "push", "-q", "origin", "feature")
        self.remote = fs.LocalGitRemote(self.bare)

    def main(self) -> str | None:
        return self.remote.resolve("refs/heads/main")

    def declaration(self, **overrides: Any) -> dict[str, Any]:
        decl: dict[str, Any] = {
            "fixture_service_schema": 1,
            "repository": {"name_with_owner": REPO, "default_branch": "main", "remote_urls": [str(self.bare)]},
            "authority": [op for op in fs.OPS if op != "pr.merge.admin"],
            "clock": {"start": "2026-10-17T00:00:00Z", "step_seconds": 60},
            "issues": [
                {"number": 1, "title": "Widget crashes on empty input", "body": "Empty input crashes it.",
                 "state": "OPEN", "created_at": "2026-10-01T00:00:00Z"},
                {"number": 3, "title": "Add the feature", "body": "We want the feature.", "state": "OPEN",
                 "created_at": "2026-10-10T00:00:00Z", "labels": ["enhancement"]},
            ],
            "pull_requests": [
                {"number": 2, "title": "fix: widget crash on empty input", "body": "Fixes #1",
                 "state": "MERGED", "head_ref": "issue-1-fix", "merge_commit": self.fixed,
                 "created_at": "2026-10-02T00:00:00Z", "merged_at": "2026-10-03T00:00:00Z"},
            ],
        }
        decl.update(overrides)
        return decl

    def service(self, **overrides: Any) -> fs.FixtureService:
        return fs.FixtureService(self.declaration(**overrides), self.remote, "attempt-1")


@pytest.fixture(autouse=True)
def _controller_umask() -> Any:
    """A controller-owned remote is written 022 (LocalGitRemote refuses a
    group- or other-writable one); a host umask of 002 must not leak in."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def ask(service: fs.FixtureService, *argv: str, branch: str | None = "feature", origin: str | None = None,
        body_files: dict[str, str] | None = None) -> dict[str, Any]:
    context = {"origin_url": origin if origin is not None else str(next(iter(service._remote_urls))),
               "branch": branch}
    request: dict[str, Any] = {"op": "gh", "argv": list(argv), "cwd": "/work", "context": context}
    if body_files is not None:
        request["body_files"] = body_files
    return dict(service.decide(request))


def last_event(service: fs.FixtureService) -> dict[str, Any]:
    return service._events[-1]


# --- valid transitions --------------------------------------------------------

def test_create_view_merge_closes_the_referenced_issue_and_the_record_matches_the_remote(world: World) -> None:
    service = world.service()
    before = world.main()
    created = ask(service, "pr", "create", "--title", "feat: the feature", "--body", "Closes #3")
    assert created == {"exit_code": 0, "stdout": f"https://github.com/{REPO}/pull/4\n", "stderr": ""}
    merged = ask(service, "pr", "merge", "4", "--squash", "--delete-branch")
    assert merged["exit_code"] == 0
    effect = last_event(service)["effect"]
    after = world.main()
    assert effect["merge_commit"] == after and effect["base_oid"] == before
    assert world.remote.resolve(f"{after}^") == before  # a squash: one new commit on the old tip
    assert effect["closed_issues"] == [3] and effect["deleted_branch"] == "feature"
    assert world.remote.resolve("refs/heads/feature") is None
    record = service.finalize("attempt-1")
    assert record.remote_integrity == "SATISFIED" and record.divergence == ()
    assert record.final_state["issues"]["3"]["state"] == "CLOSED"
    assert record.final_state["issues"]["3"]["closed_by"] == {"kind": "pull_request", "number": 4,
                                                             "at": last_event(service)["at"]}
    assert record.final_state["prs"]["4"]["merge_commit"] == after
    assert record.coverage == "witnessed" and record.coverage_complete


@needs_jq
def test_view_after_merge_reports_the_controllers_merge_commit(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "feat", "--body", "x")
    ask(service, "pr", "merge", "4", "--squash")
    assert ask(service, "pr", "view", "4", "--json", "state", "--jq", ".state")["stdout"] == "MERGED\n"
    oid = ask(service, "pr", "view", "4", "--json", "mergeCommit", "--jq", ".mergeCommit.oid")["stdout"]
    assert oid == f"{world.main()}\n"


def test_issue_close_with_comment_records_both_effects(world: World) -> None:
    service = world.service()
    reply = ask(service, "issue", "close", "1", "--comment", "Closed via /flow:auto ELI5 review - fixed by #2.")
    assert reply["exit_code"] == 0
    event = last_event(service)
    assert event["decision"] == "applied" and event["effect"]["closed"] is True
    issue = service._state["issues"][1]
    assert issue["state"] == "CLOSED" and issue["closed_by"]["kind"] == "command"
    assert issue["comments"][0]["body"].startswith("Closed via /flow:auto")
    again = ask(service, "issue", "close", "1")
    assert again["exit_code"] == 0 and "already closed" in again["stderr"]
    assert last_event(service)["effect"] is None  # a no-op is never recorded as an effect


def test_issue_comment_from_a_body_file(world: World) -> None:
    service = world.service()
    import base64
    reply = ask(service, "issue", "comment", "1", "--body-file", "-",
                body_files={"-": base64.b64encode(b"one finding").decode()})
    assert reply["exit_code"] == 0 and reply["stdout"].endswith("#issuecomment-1\n")
    assert service._state["issues"][1]["comments"][0]["body"] == "one finding"


# --- wrong repository ------------------------------------------------------------

@pytest.mark.parametrize("argv,origin", [
    (("issue", "view", "1", "--repo", "other/widget"), None),
    (("issue", "view", "1"), "/somewhere/else.git"),
    (("api", "repos/other/widget/pulls/2/files"), None),
])
def test_wrong_repository_is_refused_and_changes_nothing(world: World, argv: tuple[str, ...],
                                                         origin: str | None) -> None:
    service = world.service()
    reply = ask(service, *argv, origin=origin)
    event = last_event(service)
    assert reply["exit_code"] == 1
    assert event["decision"] == "refused" and event["reason"] == "wrong-repository"
    assert event["state_before"] == event["state_after"]


# --- duplicate create ------------------------------------------------------------

def test_duplicate_create_is_refused_and_only_one_pr_exists(world: World) -> None:
    service = world.service()
    assert ask(service, "pr", "create", "--title", "a", "--body", "b")["exit_code"] == 0
    second = ask(service, "pr", "create", "--title", "a", "--body", "b")
    assert second["exit_code"] == 1 and "already exists" in second["stderr"]
    assert last_event(service)["reason"] == "duplicate-create"
    assert sorted(service.finalize("attempt-1").final_state["prs"]) == ["2", "4"]


# --- unauthorized and invalid transitions ---------------------------------------

def test_merge_outside_the_declared_authority_is_refused_and_the_remote_does_not_move(world: World) -> None:
    service = world.service(authority=[op for op in fs.OPS if op not in ("pr.merge", "pr.merge.admin")])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    before = world.main()
    reply = ask(service, "pr", "merge", "4", "--squash")
    assert reply["exit_code"] == 1 and last_event(service)["reason"] == "unauthorized"
    assert world.main() == before and service._state["prs"][4]["state"] == "OPEN"


def test_admin_merge_needs_its_own_authority(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    assert ask(service, "pr", "merge", "4", "--squash", "--admin")["exit_code"] == 1
    assert last_event(service)["reason"] == "unauthorized"


def test_merging_an_already_merged_pr_is_an_invalid_transition(world: World) -> None:
    service = world.service()
    before = world.main()
    reply = ask(service, "pr", "merge", "2", "--squash")
    assert reply["exit_code"] == 1 and last_event(service)["reason"] == "invalid-transition"
    assert world.main() == before


def test_merge_without_a_strategy_flag_is_refused_like_gh(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    assert "--squash required" in ask(service, "pr", "merge", "4")["stderr"]


# --- forged history ----------------------------------------------------------------

@pytest.mark.parametrize("request_", [
    {"op": "gh", "argv": ["pr", "list"], "seq": 1},
    {"op": "gh", "argv": ["pr", "list"], "result": {"exit_code": 0}},
    {"op": "gh", "argv": "pr list"},
    {"op": "gh", "argv": ["pr", "list"], "context": {"origin_url": "x", "decision": "applied"}},
    {"op": "run_gate", "argv": ["pr", "list"]},
])
def test_forged_or_malformed_requests_are_refused_and_recorded_but_never_admitted(
        world: World, request_: dict[str, Any]) -> None:
    service = world.service()
    with pytest.raises(ChannelRefusal):
        service.decide(request_)
    record = service.finalize("attempt-1")
    assert [e["decision"] for e in record.events] == ["malformed"]
    assert record.coverage == "no-controller-witness"  # junk is not a witness


def test_the_record_is_a_copy_the_caller_cannot_rewrite(world: World) -> None:
    service = world.service()
    reply = ask(service, "pr", "create", "--title", "a", "--body", "b")
    reply["stdout"] = "forged"
    first = service.finalize("attempt-1")
    returned = first.events[0]
    assert isinstance(returned, dict)
    returned["decision"] = "forged"  # mutate the returned record
    assert service._events[0]["decision"] == "applied"
    assert service._events[0]["reply"]["stdout"].startswith("https://")
    assert json.loads(first.to_json_bytes())["record_digest"].startswith("sha256:")


def test_finalize_refuses_another_attempt_and_closes_the_service(world: World) -> None:
    service = world.service()
    with pytest.raises(ValueError):
        service.finalize("attempt-2")
    service.finalize("attempt-1")
    with pytest.raises(ChannelRefusal):
        ask(service, "auth", "status")


# --- missing coverage -------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ("release", "create", "v1"),
    ("pr", "merge", "4", "--rebase"),
    ("pr", "view", "2", "--json", "reviewRequests"),
    ("api", "repos/{owner}/{repo}/collaborators"),
    ("issue", "list", "--search", "label:bug", "--json", "number"),
    ("pr", "view", "2", "--json", "state", "--jq", ".state | ascii_downcase"),
])
def test_out_of_grammar_requests_are_unsupported_and_mark_coverage_incomplete(world: World,
                                                                              argv: tuple[str, ...]) -> None:
    service = world.service()
    reply = ask(service, *argv)
    assert reply["exit_code"] == 1 and "unsupported" in reply["stderr"]
    record = service.finalize("attempt-1")
    assert record.events[-1]["decision"] == "unsupported"
    assert record.coverage_complete is False and record.unsupported_events == (1,)


def test_jq_unavailable_is_unsupported_never_approximated(world: World, tmp_path: Path) -> None:
    fake = tmp_path / "jq"
    fake.write_text("#!/bin/sh\necho jq-1.6\n")
    fake.chmod(0o755)
    service = fs.FixtureService(world.declaration(), world.remote, "attempt-1", jq_path=str(fake))
    reply = ask(service, "pr", "view", "2", "--json", "state", "--jq", ".state")
    assert reply["exit_code"] == 1 and "jq is unavailable" in reply["stderr"]
    record = service.finalize("attempt-1")
    assert record.jq["version"] is None and "1.6" in record.jq["unavailable_reason"]
    assert record.coverage_complete is False


@needs_jq
def test_real_jq_version_is_recorded(world: World) -> None:
    record = world.service().finalize("attempt-1")
    assert record.jq["version"].startswith("jq-1.7")


# --- bypass and remote integrity ------------------------------------------------

def test_a_subject_that_never_calls_is_no_controller_witness(world: World) -> None:
    record = world.service().finalize("attempt-1")
    assert record.coverage == "no-controller-witness" and record.events == ()
    assert record.remote_integrity == "SATISFIED"


def test_a_direct_push_to_main_is_a_violated_divergence(world: World) -> None:
    service = world.service()
    _git(world.work, "push", "-q", "origin", "feature:refs/heads/main")  # bypass the service entirely
    record = service.finalize("attempt-1")
    assert record.remote_integrity == "VIOLATED"
    assert [d["kind"] for d in record.divergence] == ["default-branch-moved-outside-service"]


def test_a_force_push_that_rewrites_a_recorded_merge_is_a_violated_divergence(world: World) -> None:
    service = world.service()
    initial = world.remote.resolve(f"{world.fixed}^")
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    ask(service, "pr", "merge", "4", "--squash")
    merged = world.main()
    _git(world.work, "push", "-q", "--force", "origin", f"{initial}:refs/heads/main")
    record = service.finalize("attempt-1")
    kinds = sorted(d["kind"] for d in record.divergence)
    assert record.remote_integrity == "VIOLATED"
    assert kinds == ["default-branch-moved-outside-service", "recorded-merge-not-reachable",
                     "recorded-merge-not-reachable"]
    assert {d.get("commit") for d in record.divergence} >= {merged, world.fixed}


def test_main_moved_before_a_merge_is_recorded_at_merge_time_and_kept(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    _git(world.work, "checkout", "-q", "-b", "sneak", "main")
    (world.work / "sneak.txt").write_text("x\n")
    _git(world.work, "add", "sneak.txt")
    _git(world.work, "commit", "-q", "-m", "sneak")
    _git(world.work, "push", "-q", "origin", "sneak:refs/heads/main")
    assert ask(service, "pr", "merge", "4", "--squash")["exit_code"] == 0
    record = service.finalize("attempt-1")
    # Never reconciled: the merge landed on the moved tip, and the move stays on the record.
    assert record.remote_integrity == "VIOLATED"
    assert record.divergence[0]["kind"] == "default-branch-moved-outside-service"


def test_a_declared_merge_that_is_not_on_main_is_refused(world: World) -> None:
    feature = world.remote.resolve("refs/heads/feature")
    decl = world.declaration()
    decl["pull_requests"][0]["merge_commit"] = feature
    with pytest.raises(fs.DeclarationRefused, match="declared-merge-not-in-remote"):
        fs.FixtureService(decl, world.remote, "attempt-1")


# --- search, as #434's necessity check uses it -----------------------------------

def test_merged_since_search_finds_the_resolving_pr(world: World) -> None:
    service = world.service()
    found = ask(service, "pr", "list", "--state", "merged", "--search", "merged:>=2026-10-01",
                "--json", "number,title,mergedAt")
    assert [p["number"] for p in json.loads(found["stdout"])] == [2]
    later = ask(service, "pr", "list", "--state", "merged", "--search", "merged:>=2026-10-04", "--json", "number")
    assert json.loads(later["stdout"]) == []


def test_issue_search_matches_terms_and_title_scope(world: World) -> None:
    service = world.service()
    hits = ask(service, "issue", "list", "--state", "all", "--search", "widget crashes", "--json", "number")
    assert json.loads(hits["stdout"]) == [{"number": 1}]
    title_only = ask(service, "issue", "list", "--search", 'in:title "want the feature"', "--json", "number")
    assert json.loads(title_only["stdout"]) == []  # the phrase is in #3's body, not its title


def test_files_api_matches_the_merge(world: World) -> None:
    service = world.service()
    files = ask(service, "api", "repos/{owner}/{repo}/pulls/2/files", "--paginate")
    assert [f["filename"] for f in json.loads(files["stdout"])] == ["fix.txt"]


def test_unprotected_branch_answers_like_github_without_applying_jq(world: World) -> None:
    service = world.service()
    reply = ask(service, "api", "repos/{owner}/{repo}/branches/main/protection/required_status_checks",
                "--jq", ".contexts[]")
    assert reply["exit_code"] == 1 and "Branch not protected" in reply["stdout"]
    assert last_event(service)["reason"] == "simulated-absent"


# --- faults --------------------------------------------------------------------------

def test_lost_response_commits_the_merge_but_answers_with_a_transport_error(world: World) -> None:
    service = world.service(faults=[{"kind": "lost-response", "op": "pr.merge"}])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    reply = ask(service, "pr", "merge", "4", "--squash")
    assert reply["exit_code"] == 1 and "error connecting" in reply["stderr"]
    event = last_event(service)
    assert event["fault"] == "lost-response" and event["decision"] == "applied"
    assert event["effect"]["merge_commit"] == world.main()  # the action DID commit
    assert event["suppressed_reply"]["exit_code"] == 0
    assert service._state["prs"][4]["state"] == "MERGED"
    record = service.finalize("attempt-1")
    assert record.faults[0]["fired"] and record.faults[0]["fired_at_seq"] == event["seq"]


def test_a_junk_flood_cannot_move_the_fault_point(world: World) -> None:
    service = world.service(faults=[{"kind": "lost-response", "op": "pr.merge"}])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    for _ in range(3):
        with pytest.raises(ChannelRefusal):
            service.decide({"op": "gh", "argv": ["pr", "merge", "4", "--squash"], "seq": 99})
        ask(service, "pr", "merge", "4", "--rebase")  # unsupported
        ask(service, "pr", "merge", "2", "--squash")  # refused: already merged
    assert not service._faults[0]["fired"]
    reply = ask(service, "pr", "merge", "4", "--squash")
    assert "error connecting" in reply["stderr"] and service._faults[0]["fired"]


def test_stale_read_answers_one_read_from_before_the_merge(world: World) -> None:
    service = world.service(faults=[{"kind": "stale-read", "after": "pr.merge", "read": "pr.view"}])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    ask(service, "pr", "merge", "4", "--squash")
    stale = json.loads(ask(service, "pr", "view", "4", "--json", "state")["stdout"])
    fresh = json.loads(ask(service, "pr", "view", "4", "--json", "state")["stdout"])
    assert stale == {"state": "OPEN"} and fresh == {"state": "MERGED"}
    record = service.finalize("attempt-1")
    assert record.events[-2]["fault"] == "stale-read" and record.events[-1]["fault"] is None
    assert record.faults[0]["fired"]


def test_a_declared_fault_that_never_fires_reads_unknown(world: World) -> None:
    service = world.service(faults=[{"kind": "lost-response", "op": "pr.merge"}])
    record = service.finalize("attempt-1")
    assert record.faults[0]["coverage"] == "UNKNOWN"


def test_deterministic_record_for_identical_runs(tmp_path: Path) -> None:
    digests = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        world = World(root)
        decl = world.declaration()
        decl["repository"]["remote_urls"] = ["/srv/remote.git"]
        service = fs.FixtureService(decl, world.remote, "attempt-1")
        ask(service, "pr", "create", "--title", "a", "--body", "Closes #3", origin="/srv/remote.git")
        ask(service, "pr", "merge", "4", "--squash", origin="/srv/remote.git")
        digests.append(json.loads(service.finalize("attempt-1").to_json_bytes())["record_digest"])
    assert digests[0] == digests[1]


# --- counter-model review regressions (each red on the pre-fix code) -------------

def test_a_hook_in_the_subject_writable_remote_never_runs_under_the_controller(world: World,
                                                                              tmp_path: Path) -> None:
    marker = tmp_path / "hook-ran"
    hook = world.bare / "hooks" / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    assert ask(service, "pr", "merge", "4", "--squash")["exit_code"] == 0
    assert not marker.exists()


@pytest.mark.parametrize("key,value", [("merge.evil.driver", "touch /tmp/x"), ("core.hooksPath", "/tmp/h"),
                                       ("include.path", "/tmp/c")])
def test_a_remote_config_outside_the_allowlist_is_refused_and_integrity_unknown(world: World, key: str,
                                                                               value: str) -> None:
    service = world.service()
    _git(world.bare, "config", key, value)
    reply = ask(service, "pr", "create", "--title", "a", "--body", "b")
    event = last_event(service)
    assert reply["exit_code"] == 1 and event["decision"] == "error" and "RemoteUntrusted" in event["reason"]
    record = service.finalize("attempt-1")
    assert record.remote_integrity == "UNKNOWN" and record.coverage_complete is False


def test_a_huge_closing_reference_cannot_commit_an_unrecorded_merge(world: World) -> None:
    service = world.service(faults=[{"kind": "lost-response", "op": "pr.merge"}])
    ask(service, "pr", "create", "--title", "a", "--body", "Closes #" + "9" * 4500)
    reply = ask(service, "pr", "merge", "4", "--squash")
    event = last_event(service)
    assert event["op"] == "pr.merge" and event["decision"] == "applied" and event["fault"] == "lost-response"
    assert event["effect"]["merge_commit"] == world.main() and "error connecting" in reply["stderr"]
    assert service.finalize("attempt-1").remote_integrity == "SATISFIED"


def test_two_stale_faults_each_keep_their_own_snapshot(world: World) -> None:
    service = world.service(faults=[{"kind": "stale-read", "after": "issue.close", "read": "issue.view"},
                                    {"kind": "stale-read", "after": "issue.comment", "read": "issue.list"}])
    ask(service, "issue", "close", "1")
    ask(service, "issue", "comment", "3", "--body", "note")
    listed = json.loads(ask(service, "issue", "list", "--state", "all", "--json", "number,comments")["stdout"])
    assert {i["number"]: len(i["comments"]) for i in listed}[3] == 0  # the list fault, from before the comment
    viewed = json.loads(ask(service, "issue", "view", "1", "--json", "state")["stdout"])
    assert viewed == {"state": "OPEN"}  # the view fault still fires, from before the close
    record = service.finalize("attempt-1")
    assert [f["fired_at_seq"] for f in record.faults] == [4, 3]


def test_a_stale_pr_view_reproduces_the_old_remote_derived_payload(world: World) -> None:
    service = world.service(faults=[{"kind": "stale-read", "after": "pr.merge", "read": "pr.view"}])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    before = json.loads(ask(service, "pr", "view", "4", "--json", "state,changedFiles,commits")["stdout"])
    ask(service, "pr", "merge", "4", "--squash", "--delete-branch")
    stale = json.loads(ask(service, "pr", "view", "4", "--json", "state,changedFiles,commits")["stdout"])
    assert stale == before and stale["changedFiles"] == 1


def test_a_failed_branch_deletion_is_recorded_as_failed(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    (world.bare / "refs" / "heads" / "feature.lock").write_text("")
    assert ask(service, "pr", "merge", "4", "--squash", "--delete-branch")["exit_code"] == 0
    effect = last_event(service)["effect"]
    assert effect["deleted_branch"] is None and effect["branch_delete_failed"] == "feature"
    assert world.remote.resolve("refs/heads/feature") is not None


def test_invalid_base64_body_file_is_a_recorded_malformed_request(world: World) -> None:
    service = world.service()
    with pytest.raises(ChannelRefusal):
        ask(service, "issue", "comment", "1", "--body-file", "-", body_files={"-": "A"})
    assert [e["decision"] for e in service._events] == ["malformed"]


def test_a_git_failure_reads_unknown_never_violated(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    service = world.service()
    original = fs.LocalGitRemote._git

    def broken(self: fs.LocalGitRemote, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(list(args), 128, b"", b"fatal: bad object")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(fs.LocalGitRemote, "_git", broken)
    record = service.finalize("attempt-1")
    assert record.remote_integrity == "UNKNOWN"


# --- counter-model review pass 2 regressions --------------------------------------

def test_a_commondir_redirection_is_refused(world: World, tmp_path: Path) -> None:
    # A real common dir: git reads config, objects and refs from it, so the
    # checked local config can stay harmless while this one is not.
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(world.bare, elsewhere)
    _git(elsewhere, "config", "merge.evil.driver", "touch /tmp/x")
    (world.bare / "commondir").write_text(str(elsewhere) + "\n")
    with pytest.raises(fs.RemoteUntrusted, match="commondir"):
        world.service()


def test_a_lone_surrogate_cannot_make_the_record_unserializable(world: World) -> None:
    service = world.service()
    with pytest.raises(ChannelRefusal):
        service.decide(json.loads('{"op": "gh", "argv": ["issue", "close", "1"], '
                                  '"context": {"origin_url": "x", "branch": "\\ud800"}}'))
    assert service._state["issues"][1]["state"] == "OPEN"
    record = service.finalize("attempt-1")
    assert [e["decision"] for e in record.events] == ["malformed"]
    assert json.loads(record.to_json_bytes())["record_digest"].startswith("sha256:")


def test_a_stale_not_found_is_the_stale_answer_and_consumes_the_fault(world: World) -> None:
    service = world.service(faults=[{"kind": "stale-read", "after": "pr.create", "read": "pr.view"}])
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    stale = ask(service, "pr", "view", "4", "--json", "state")
    fresh = ask(service, "pr", "view", "4", "--json", "state")
    assert stale["exit_code"] == 1 and "Could not resolve" in stale["stderr"]
    assert json.loads(fresh["stdout"]) == {"state": "OPEN"}
    record = service.finalize("attempt-1")
    assert record.faults[0]["fired"] and record.events[1]["fault"] == "stale-read"


def test_an_update_ref_failure_on_an_unmoved_base_is_an_error_not_base_moved(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    before = world.main()
    original = fs.LocalGitRemote._git

    def locked(self: fs.LocalGitRemote, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args[:1] == ("update-ref",) and len(args) == 4:
            return subprocess.CompletedProcess(list(args), 128, b"", b"fatal: Unable to create lock: Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(fs.LocalGitRemote, "_git", locked)
    ask(service, "pr", "merge", "4", "--squash")
    event = last_event(service)
    assert event["decision"] == "error" and world.main() == before
    assert service.finalize("attempt-1").coverage_complete is False


# --- ruling on pass 2: the LocalGitRemote contract, enforced fail-closed ----------

@pytest.mark.parametrize("target,mode", [("config", 0o664), ("config", 0o646), (".", 0o775), ("objects", 0o777),
                                         ("hooks", 0o757)])
def test_a_remote_writable_by_another_uid_is_refused_before_any_git_runs(
        world: World, monkeypatch: pytest.MonkeyPatch, target: str, mode: int) -> None:
    (world.bare / target).chmod(mode)
    ran: list[tuple[str, ...]] = []
    real_run = subprocess.run

    def spy(argv: Any, *args: Any, **kwargs: Any) -> Any:
        ran.append(tuple(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(fs.subprocess, "run", spy)
    with pytest.raises(fs.RemoteUntrusted, match="writable by another uid"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")
    assert not [a for a in ran if a and a[0] == "git"]


def test_a_remote_file_owned_by_another_uid_is_refused(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # A file the subject's uid owns, inside an otherwise controller-owned tree
    # (only lstat is altered: chown needs root).
    real_lstat = os.lstat
    config = os.path.abspath(world.bare / "config")

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        info = real_lstat(path, *args, **kwargs)
        if os.path.abspath(path) == config:
            fields = list(info)
            fields[4] = info.st_uid + 1  # st_uid
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(fs.os, "lstat", lstat)
    with pytest.raises(fs.RemoteUntrusted, match="config is owned by uid"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")


def test_a_remote_under_an_ancestor_owned_by_another_uid_is_refused(world: World, tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulated with lstat, not getuid: CI runs as root, where every real
    # ancestor is root-owned and therefore (correctly) accepted.
    real_lstat = os.lstat
    ancestor = os.path.abspath(tmp_path)

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        info = real_lstat(path, *args, **kwargs)
        if os.path.abspath(path) == ancestor:
            fields = list(info)
            fields[4] = os.getuid() + 1 if os.getuid() != 0 else 4242  # st_uid: neither us nor root
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(fs.os, "lstat", lstat)
    with pytest.raises(fs.RemoteUntrusted, match="ancestor directory of the remote is a link or not owned"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")



def test_a_symlink_inside_the_remote_is_refused(world: World, tmp_path: Path) -> None:
    (tmp_path / "outside").write_text("x")
    (world.bare / "info" / "linked").symlink_to(tmp_path / "outside")
    with pytest.raises(fs.RemoteUntrusted, match="not a plain file"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")


def test_an_ancestor_writable_by_another_uid_is_refused(world: World, tmp_path: Path) -> None:
    tmp_path.chmod(0o777)  # not sticky: anyone could rename the remote away
    try:
        with pytest.raises(fs.RemoteUntrusted, match="ancestor"):
            fs.LocalGitRemote(world.bare).resolve("refs/heads/main")
    finally:
        tmp_path.chmod(0o700)


def test_the_service_refuses_a_subject_writable_remote_as_an_error_event(world: World) -> None:
    service = world.service()
    (world.bare / "config").chmod(0o666)
    ask(service, "pr", "create", "--title", "a", "--body", "b")
    event = last_event(service)
    assert event["decision"] == "error" and "RemoteUntrusted" in event["reason"]
    assert service.finalize("attempt-1").remote_integrity == "UNKNOWN"


# --- counter-model review pass 3 regressions ---------------------------------------

def _unlistable(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make `target` unlistable for os.walk. Simulated, not chmod: root (CI)
    lists any directory whatever its mode."""
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> Any:
        if not isinstance(path, int) and os.path.abspath(path) == os.path.abspath(target):
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)


def test_an_unlistable_remote_root_is_refused_not_read_as_empty(world: World,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    _unlistable(monkeypatch, world.bare)  # os.walk alone would yield nothing
    with pytest.raises(fs.RemoteUntrusted, match="could not be fully inspected"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")


def test_an_inspection_that_examined_nothing_is_refused(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs.os, "walk", lambda *a, **k: iter(()))
    with pytest.raises(fs.RemoteUntrusted, match="examined nothing"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")



def test_a_missing_remote_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(fs.RemoteUntrusted, match="cannot be inspected"):
        fs.LocalGitRemote(tmp_path / "absent.git").resolve("refs/heads/main")


def test_a_symlink_plus_dotdot_path_cannot_check_one_dir_and_run_git_in_another(world: World,
                                                                              tmp_path: Path) -> None:
    (tmp_path / "inner").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "inner")
    with pytest.raises(fs.RemoteUntrusted, match="no '.' or '..'"):
        fs.LocalGitRemote(tmp_path / "link" / ".." / "remote.git")


def test_a_usage_error_does_not_consume_a_stale_fault(world: World) -> None:
    service = world.service(faults=[{"kind": "stale-read", "after": "issue.close", "read": "issue.view"}])
    ask(service, "issue", "close", "1")
    usage = ask(service, "issue", "view", "1", "--jq", ".state")  # --jq without --json
    assert usage["exit_code"] == 1 and "without specifying `--json`" in usage["stderr"]
    assert not service._faults[0]["fired"]
    stale = json.loads(ask(service, "issue", "view", "1", "--json", "state")["stdout"])
    assert stale == {"state": "OPEN"} and service._faults[0]["fired"]


def test_an_unlistable_subdirectory_is_refused_not_skipped(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    _unlistable(monkeypatch, world.bare / "objects")  # it must not just be skipped
    with pytest.raises(fs.RemoteUntrusted, match="could not be fully inspected"):
        fs.LocalGitRemote(world.bare).resolve("refs/heads/main")
@pytest.mark.parametrize("text,closes", [
    ("Closes #10", (10,)), ("closes #10", (10,)), ("CLOSES #10", (10,)), ("Closes: #10", (10,)),
    ("CLOSES: #10", (10,)), ("fix #3", (3,)), ("fixes #3", (3,)), ("Fixed #3", (3,)),
    ("resolve #4", (4,)), ("Resolves #4", (4,)), ("resolved: #4", (4,)), ("close #1", (1,)), ("closed #1", (1,)),
    ("Closes fixture/widget#7", (7,)), ("Closes #1, closes #2", (1, 2)),
])
def test_every_documented_form_closes(text: str, closes: tuple[int, ...]) -> None:
    assert fs.closing_references(text, REPO).closes == closes


def test_the_documented_multiple_issue_rule_needs_a_keyword_per_issue() -> None:
    assert fs.closing_references("Closes #1, #2", REPO).closes == (1,)


def test_a_negated_or_incidental_form_closes_as_github_does() -> None:
    assert fs.closing_references("This does not fix #3 yet", REPO).closes == (3,)
    assert fs.closing_references("prefixes #3 and suffixes #4", REPO).closes == ()  # no keyword boundary


def test_another_repository_is_foreign_and_closes_nothing_here() -> None:
    refs = fs.closing_references("Fixes other/repo#9", REPO)
    assert refs.closes == () and refs.foreign == ("other/repo#9",)


@pytest.mark.parametrize("text", ["Fixes:#42", "Fixes#42", "closes:fixture/widget#5"])
def test_forms_the_doc_does_not_settle_are_ambiguous_and_close_nothing(text: str) -> None:
    refs = fs.closing_references(text, REPO)
    assert refs.closes == () and refs.ambiguous == (text,)


def test_merge_records_foreign_and_ambiguous_references(world: World) -> None:
    service = world.service()
    ask(service, "pr", "create", "--title", "a", "--body", "Fixes:#3 and Fixes other/repo#9")
    ask(service, "pr", "merge", "4", "--squash")
    effect = last_event(service)["effect"]
    assert effect["closed_issues"] == [] and effect["ambiguous_closing_refs"] == ["Fixes:#3"]
    assert effect["foreign_closing_refs"] == ["other/repo#9"]
    assert service._state["issues"][3]["state"] == "OPEN"


# -------------------------------------- #279 PR-2a: the controller-owned order

def test_every_event_carries_the_controllers_order_only_when_given_one(world: World) -> None:
    from skillc.ordering import Order
    order = Order()
    service = fs.FixtureService(world.declaration(), world.remote, "attempt-1", order=order)
    ask(service, "issue", "view", "1")
    order.next()  # a gate run between two requests took the next number
    with pytest.raises(ChannelRefusal):
        # A malformed request still gets the controller's stamp, and a
        # request-supplied `order` never sets it.
        service.decide({"op": "gh", "argv": ["issue", "view", "1"], "order": 1})
    ask(service, "pr", "list")
    events = service.finalize("attempt-1").to_json()["events"]
    assert [e["order"] for e in events] == [1, 3, 4]
    plain = world.service()
    ask(plain, "issue", "view", "1")
    assert all("order" not in e for e in plain.finalize("attempt-1").to_json()["events"])  # byte-identical control
