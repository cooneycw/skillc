"""skill-usage records, the hook that writes them and the report that reads them (#719)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skillc import checks, cli, usage

CONTROLS = Path(__file__).resolve().parent.parent / "controls"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

GOOD = json.loads(
    (CONTROLS / "skill-usage-pairing/good/start-end.usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
)


def _log(tmp_path: Path, *lines: dict[str, object], name: str = "usage.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def _rules(path: Path) -> list[str]:
    return sorted({f.rule for f in checks.run_usage_log(usage.load_log(path))})


def _rec(**kw: object) -> dict[str, object]:
    return {**GOOD, **kw}


# ------------------------------------------------------------------ the rules


def test_the_good_control_record_is_clean_under_every_usage_rule(tmp_path: Path) -> None:
    assert _rules(_log(tmp_path, _rec(), _rec(event="end"))) == []


@pytest.mark.parametrize("prefix", ["/home/", "/" + "Us" + "ers/"])
def test_a_home_path_in_any_string_is_refused(tmp_path: Path, prefix: str) -> None:
    # Built, not literal, so the repository's own leak-check never sees an account path.
    path = _log(tmp_path, _rec(note={"nested": [f"{prefix}someone/x"]}))
    details = [f.detail for f in checks.run_usage_log(usage.load_log(path), only="skill-usage-privacy")]
    assert any("home-directory path" in d for d in details)


def test_an_email_is_refused_but_a_collection_revision_is_not_one(tmp_path: Path) -> None:
    assert list(usage.usage_privacy(usage.load_log(_log(tmp_path, _rec(x="someone@example.com")))))
    clean = usage.load_log(_log(tmp_path, _rec(collection="skillc@" + "a" * 40)))
    assert list(usage.usage_privacy(clean)) == []


def test_every_field_that_could_not_be_seen_must_say_UNKNOWN(tmp_path: Path) -> None:
    for key in ("skill_digest", "collection", "repo", "commit", "model", "invocation", "outcome"):
        record = _rec()
        del record[key]
        assert _rules(_log(tmp_path, record)) == ["skill-usage-fields"], key
        assert _rules(_log(tmp_path, _rec(**{key: ""}))) == ["skill-usage-fields"], key
        assert _rules(_log(tmp_path, _rec(**{key: "UNKNOWN"}))) == [], key


def test_skill_and_session_may_not_be_UNKNOWN(tmp_path: Path) -> None:
    assert _rules(_log(tmp_path, _rec(skill="UNKNOWN"))) == []  # a skill literally named UNKNOWN is a name
    assert _rules(_log(tmp_path, _rec(at="UNKNOWN"))) == ["skill-usage-fields"]
    assert _rules(_log(tmp_path, _rec(event="UNKNOWN"))) == ["skill-usage-fields"]


def test_a_skill_name_with_a_slash_is_refused(tmp_path: Path) -> None:
    assert _rules(_log(tmp_path, _rec(skill="../escape"))) == ["skill-usage-fields"]


def test_an_end_closes_ONE_start_first_in_first_out(tmp_path: Path) -> None:
    log = usage.load_log(_log(
        tmp_path, _rec(), _rec(at="2026-11-14T20:01:00Z"),
        _rec(event="end", outcome="stopped", origin="declared", stop_reason="approval-gate"),
    ))
    pairs, orphans = usage.pair(log)
    assert orphans == []
    assert [e.line if e else None for _, e in pairs] == [3, None]
    assert [s.line for s in usage.unended(log)] == [2]
    assert list(usage.usage_pairing(log)) == []


def test_an_unended_start_is_reported_not_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _log(tmp_path, _rec())
    rc = cli.main(["check-records", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 start(s) without an end, read as outcome UNKNOWN (reported, not refused)" in out


def test_only_usage_named_jsonl_files_are_usage_logs(tmp_path: Path) -> None:
    (tmp_path / "transcript.jsonl").write_text('{"type": "assistant"}\n', encoding="utf-8")
    _log(tmp_path, _rec(), name="a.usage.jsonl")
    assert [log.path.name for log in usage.discover_logs(tmp_path)] == ["a.usage.jsonl"]


def test_check_records_on_an_empty_usage_log_checks_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "usage.jsonl").write_text("", encoding="utf-8")
    assert cli.main(["check-records", str(tmp_path)]) == 2
    assert "nothing was checked" in capsys.readouterr().out


def test_a_usage_rule_with_no_usage_log_checked_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(CONTROLS / "result-evidence/good/record.json", tmp_path / "record.json")
    assert cli.main(["check-records", str(tmp_path), "--rule", "skill-usage-pairing"]) == 2
    assert "checked nothing" in capsys.readouterr().out


def test_check_records_refuses_a_bad_usage_log(tmp_path: Path) -> None:
    shutil.copy(CONTROLS / "skill-usage-pairing/bad/orphan-end.usage.jsonl", tmp_path / "usage.jsonl")
    assert cli.main(["check-records", str(tmp_path)]) == 1


# ------------------------------------------------------------------ the writer


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", "git@github.com:example/demo.git")
    skill = root / ".claude" / "skills" / "hello-probe" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: hello-probe\ndescription: Say hello. Use when asked to probe.\n---\nSay hello.\n",
                     encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _hook(payload: dict[str, object], home: Path) -> str:
    err = io.StringIO()
    assert usage.run_hook(io.StringIO(json.dumps(payload)), err, home=home) == 0
    return err.getvalue()


def _lines(repo: Path) -> list[dict[str, object]]:
    path = repo / ".skillc" / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _skill_call(repo: Path, name: str = "hello-probe", session: str = "s-1") -> dict[str, object]:
    return {"hook_event_name": "PreToolUse", "session_id": session, "cwd": str(repo),
            "tool_name": "Skill", "tool_input": {"skill": name}}


@needs_git
def test_a_skill_call_writes_one_start_and_session_end_closes_it(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _hook(_skill_call(repo), home)
    _hook({"hook_event_name": "SessionEnd", "session_id": "s-1", "cwd": str(repo)}, home)
    start, end = _lines(repo)
    head = _git(repo, "rev-parse", "HEAD")
    assert start["event"] == "start" and start["invocation"] == "model-selected"
    assert start["origin"] == "observed" and start["coverage"] == "partial"
    assert start["repo"] == "example/demo" and start["commit"] == head
    assert start["collection"] == f"demo@{head}"
    assert str(start["skill_digest"]).startswith("sha256:")
    assert end["event"] == "end" and end["outcome"] == "UNKNOWN" and end["skill"] == "hello-probe"
    assert (repo / ".skillc" / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert _git(repo, "status", "--porcelain") == ""
    log = repo / ".skillc" / "usage.jsonl"
    assert checks.run_usage_log(usage.load_log(log)) == []
    text = log.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "/home/" not in text


@needs_git
def test_NEGATIVE_CONTROL_no_skill_means_no_record(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _hook({"hook_event_name": "PreToolUse", "session_id": "s-1", "cwd": str(repo),
           "tool_name": "Bash", "tool_input": {"command": "echo hello-probe"}}, home)
    _hook({"hook_event_name": "UserPromptSubmit", "session_id": "s-1", "cwd": str(repo),
           "prompt": "please run hello-probe for me"}, home)
    _hook({"hook_event_name": "SessionEnd", "session_id": "s-1", "cwd": str(repo)}, home)
    assert _lines(repo) == []
    assert not (repo / ".skillc").exists()


@needs_git
def test_a_typed_slash_command_records_only_an_EXACT_installed_name(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    for prompt in ("/clear", "/hello", "/hello-probe-x now", "/tmp/hello-probe", "say /hello-probe"):
        _hook({"hook_event_name": "UserPromptSubmit", "session_id": "s-1", "cwd": str(repo), "prompt": prompt}, home)
    assert _lines(repo) == []
    _hook({"hook_event_name": "UserPromptSubmit", "session_id": "s-1", "cwd": str(repo),
           "prompt": "/hello-probe with args"}, home)
    (start,) = _lines(repo)
    assert start["invocation"] == "explicit" and start["skill"] == "hello-probe"


@needs_git
def test_a_namespaced_command_resolves_from_the_commands_directory(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    command = home / ".claude" / "commands" / "flow" / "auto.md"
    command.parent.mkdir(parents=True)
    command.write_text("---\ndescription: Full lifecycle.\n---\nDo it.\n", encoding="utf-8")
    _hook({"hook_event_name": "UserPromptSubmit", "session_id": "s-1", "cwd": str(repo),
           "prompt": "/flow:auto 719"}, home)
    (start,) = _lines(repo)
    assert start["skill"] == "flow:auto" and str(start["skill_digest"]).startswith("sha256:")
    assert start["collection"] == "UNKNOWN"  # not inside a git checkout


@needs_git
def test_an_unresolved_skill_call_is_still_recorded_with_UNKNOWN_digest(repo: Path, tmp_path: Path) -> None:
    _hook(_skill_call(repo, name="plugin:elsewhere"), tmp_path / "home")
    (start,) = _lines(repo)
    assert start["skill_digest"] == "UNKNOWN" and start["collection"] == "UNKNOWN"


@needs_git
def test_the_digest_moves_with_the_description_and_the_body(repo: Path) -> None:
    skill = repo / ".claude" / "skills" / "hello-probe" / "SKILL.md"
    before = usage.skill_digest(skill)
    skill.write_text(skill.read_text(encoding="utf-8").replace("Say hello.\n", "Say hi.\n"), encoding="utf-8")
    body_changed = usage.skill_digest(skill)
    skill.write_text(skill.read_text(encoding="utf-8").replace("Use when asked", "Use whenever"), encoding="utf-8")
    assert len({before, body_changed, usage.skill_digest(skill)}) == 3
    skill.write_text("no frontmatter\n", encoding="utf-8")
    assert usage.skill_digest(skill) == "UNKNOWN"


@needs_git
def test_a_worktree_run_lands_in_the_main_checkout(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "demo-wt"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(worktree))
    _hook(_skill_call(worktree), tmp_path / "home")
    (start,) = _lines(repo)
    assert not (worktree / ".skillc").exists()
    # The skill resolved through the worktree's own .claude/, yet the
    # collection is named for the main checkout, never for the worktree.
    assert str(start["collection"]).startswith("demo@")


@needs_git
def test_a_declared_end_closes_the_start_and_a_later_session_end_writes_nothing(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _hook(_skill_call(repo), home)
    monkeypatch.chdir(repo)
    out = io.StringIO()
    assert usage.declare_end("hello-probe", "stopped", "approval-gate", "s-1", repo, out) == 0
    assert "recorded end stopped" in out.getvalue()
    _hook({"hook_event_name": "SessionEnd", "session_id": "s-1", "cwd": str(repo)}, home)
    _start, end = _lines(repo)
    assert end["origin"] == "declared" and end["stop_reason"] == "approval-gate"
    out = io.StringIO()
    assert usage.declare_end("hello-probe", "completed", None, "s-1", repo, out) == 0
    assert "no-open-start" in out.getvalue()
    assert len(_lines(repo)) == 2


@needs_git
def test_another_sessions_stop_does_not_close_this_ones_start(repo: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _hook(_skill_call(repo, session="s-1"), home)
    _hook({"hook_event_name": "Stop", "session_id": "s-2", "cwd": str(repo)}, home)
    assert len(_lines(repo)) == 1


def test_the_hook_never_fails_its_session(tmp_path: Path) -> None:
    for raw in ("not json", "[]", json.dumps({"hook_event_name": "PreToolUse", "session_id": "bad id!"})):
        assert usage.run_hook(io.StringIO(raw), io.StringIO(), home=tmp_path) == 0


def test_outside_a_git_checkout_nothing_is_written(tmp_path: Path) -> None:
    _hook(_skill_call(tmp_path), tmp_path / "home")
    assert list(tmp_path.rglob("usage.jsonl")) == []


# ------------------------------------------------------------------ the report


def test_report_counts_three_skills_and_two_digests(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d1, d2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    lines = [
        _rec(skill="alpha", skill_digest=d1, session="a1"), _rec(skill="alpha", skill_digest=d1, session="a1",
                                                                 event="end", outcome="completed", origin="declared"),
        _rec(skill="alpha", skill_digest=d2, session="a2"),
        _rec(skill="beta", skill_digest=d1, session="b1"), _rec(skill="beta", skill_digest=d1, session="b1",
                                                                event="end", outcome="stopped", origin="declared",
                                                                stop_reason="approval-gate"),
        _rec(skill="gamma", skill_digest="UNKNOWN", session="g1", model="UNKNOWN"),
        _rec(skill="gamma", skill_digest="UNKNOWN", session="g1", event="end"),
    ]
    path = _log(tmp_path, *lines)
    assert usage.cmd_report(path) == 0
    out = capsys.readouterr().out
    report = usage.summarize(usage.load_log(path))
    assert report.starts == 4 and report.ends == 3 and report.unended == 1
    assert report.by_skill == {("alpha", d1): 1, ("alpha", d2): 1, ("beta", d1): 1, ("gamma", "UNKNOWN"): 1}
    assert report.outcomes == {"completed": 1, "stopped": 1, "UNKNOWN": 2}
    assert report.unknown["skill_digest"] == 1 and report.unknown["outcome"] == 2
    assert "outcome mix: completed=1, stopped=1, abandoned=0, UNKNOWN=2" in out
    assert "7 record(s): 4 invocation(s) (start), 3 end(s), 1 unended" in out


def test_report_on_an_empty_file_says_no_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_text("", encoding="utf-8")
    assert usage.cmd_report(path) == 2
    out = capsys.readouterr().out
    assert "no records" in out and "0 problems" not in out


def test_report_refuses_a_log_check_records_refuses(tmp_path: Path) -> None:
    shutil.copy(CONTROLS / "skill-usage-privacy/bad/email.usage.jsonl", tmp_path / "usage.jsonl")
    err = io.StringIO()
    assert usage.cmd_report(tmp_path / "usage.jsonl", io.StringIO(), err) == 1
    assert "no report drawn" in err.getvalue()


# ------------------------------------------------------- counter-model review fixes


@needs_git
def test_concurrent_closers_close_ONE_start_exactly_once(repo: Path, tmp_path: Path) -> None:
    """Read-decide-append is one locked operation: eight closers racing for
    one open start write exactly one end, and the log stays valid."""
    import threading

    _hook(_skill_call(repo), tmp_path / "home")
    barrier = threading.Barrier(8)

    def close() -> None:
        barrier.wait()
        usage.declare_end("hello-probe", "completed", None, "s-1", repo, io.StringIO())

    threads = [threading.Thread(target=close) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [line["event"] for line in _lines(repo)] == ["start", "end"]
    assert checks.run_usage_log(usage.load_log(repo / ".skillc" / "usage.jsonl")) == []


@needs_git
def test_usage_end_never_fails_its_skill(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _hook(_skill_call(repo), tmp_path / "home")
    out = io.StringIO()
    assert usage.declare_end("hello-probe", "stopped", "waiting for approval", "s-1", repo, out) == 0
    assert "refused" in out.getvalue() and len(_lines(repo)) == 1

    def disk_full(*_: object, **__: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(usage, "append", disk_full)
    out = io.StringIO()
    assert usage.declare_end("hello-probe", "stopped", None, "s-1", repo, out) == 0
    assert "not recorded (OSError: disk full)" in out.getvalue()


def test_a_semantic_rule_over_an_unreadable_log_checked_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    bad = CONTROLS / "skill-usage-envelope/bad/unreadable.usage.jsonl"
    assert cli.main(["check-records", str(bad), "--rule", "skill-usage-fields"]) == 2
    assert "checked nothing" in capsys.readouterr().out
    assert cli.main(["check-records", str(bad), "--rule", "skill-usage-envelope"]) == 1


@pytest.mark.parametrize("rule_id", [r.id for r in checks.USAGE_RULES])
def test_selftest_refuses_an_EMPTIED_good_usage_control(rule_id: str, tmp_path: Path) -> None:
    """Sabotage: truncating a rule's good control to zero bytes must stop
    certification, not leave a rule that refuses every real record green."""
    copy = tmp_path / "controls"
    shutil.copytree(CONTROLS, copy)
    for good in (copy / rule_id / "good").glob("*.jsonl"):
        good.write_text("", encoding="utf-8")
    assert cli.main(["selftest", "--controls", str(copy)]) != 0


@needs_git
def test_an_append_after_a_final_line_without_newline_keeps_the_log_readable(repo: Path, tmp_path: Path) -> None:
    state = repo / ".skillc"
    state.mkdir()
    (state / ".gitignore").write_text("*\n", encoding="utf-8")
    (state / "usage.jsonl").write_text(json.dumps(_rec(session="s-0")), encoding="utf-8")  # no trailing newline
    _hook(_skill_call(repo), tmp_path / "home")
    log = usage.load_log(state / "usage.jsonl")
    assert log.parse_error is None and len(log.entries) == 2


@needs_git
def test_an_unreadable_log_is_never_appended_to(repo: Path, tmp_path: Path) -> None:
    state = repo / ".skillc"
    state.mkdir()
    (state / "usage.jsonl").write_text("{not json\n", encoding="utf-8")
    err = _hook(_skill_call(repo), tmp_path / "home")
    assert "unreadable" in err
    assert (state / "usage.jsonl").read_text(encoding="utf-8") == "{not json\n"


@needs_git
@pytest.mark.parametrize("existing", [None, "notes.txt\n", "notes.txt"])
def test_a_preexisting_state_dir_still_ignores_the_log(repo: Path, tmp_path: Path, existing: str | None) -> None:
    state = repo / ".skillc"
    state.mkdir()
    if existing is not None:
        (state / ".gitignore").write_text(existing, encoding="utf-8")
    _hook(_skill_call(repo), tmp_path / "home")
    assert len(_lines(repo)) == 1
    # git itself is the judge: the log must not show as untracked.
    assert "usage.jsonl" not in _git(repo, "status", "--porcelain", "--untracked-files=all")


def test_an_empty_usage_log_beside_a_neighbour_record_checked_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.copy(CONTROLS / "result-evidence/good/record.json", tmp_path / "record.json")
    (tmp_path / "usage.jsonl").write_text("", encoding="utf-8")
    for rule in ("skill-usage-envelope", "skill-usage-fields"):
        assert cli.main(["check-records", str(tmp_path), "--rule", rule]) == 2, rule
        assert "checked nothing" in capsys.readouterr().out
