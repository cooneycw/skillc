"""#500: the nested-codex guard on calibration attempts, every transcript of
an attempt retained, and eligibility and tokens counted across every session.

The #287 option-1 pilot (run 20261021T003158Z-600e90) ran with no guard: one
attempt launched `codex exec --ephemeral --model gpt-6-sol`, which reached the
model, wrote no session file and left the attempt eligible; two others left a
second session file and the capture discarded both. Each red below is one of
those shapes, or the orchestrator's condition on #500.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import _docker_bin, _fake_argv, _fresh_credential, _mapped_home, _planned
from test_calibration_discrimination_run import _approved, _intact, _parse

from skillc import agent_trial as at
from skillc import attempt_guard as ag
from skillc import calibration_run as cr
from skillc import codex_guard as cg
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc import records, trial
from skillc.backend import Limits
from skillc.decide_reply_channel import ChannelRefusal

CODEX_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts" / "codex"
DIGEST = "sha256:" + "a" * 64
ZERO = {"status": "zero", "top_level": 1, "confirmed": 0, "suspected": 0, "ancestry_unknown": 0,
        "nested_policy": ag.CALIBRATION_POLICY, "channel_unavailable": False}
REFUSED_ONE = {**ZERO, "status": "observed", "confirmed": 1}


def _tool_call(command: str, kind: str = "custom_tool_call") -> dict[str, Any]:
    if kind == "custom_tool_call":
        payload = {"type": kind, "input": f"text(await tools.exec_command({{cmd:{json.dumps(command)}}}));"}
    else:
        payload = {"type": kind, "arguments": json.dumps({"cmd": command})}
    return {"type": "response_item", "payload": payload}


# ---------------------------------------------------- the transcript backstop

@pytest.mark.parametrize("command,program,guarded,model", [
    # The pilot's own shape (a-4ef6692fdccb), verbatim apart from the prompt.
    (("codex exec --skip-git-repo-check --ephemeral --sandbox read-only --model gpt-6-sol "
      "--output-last-message /tmp/r.md 'Review'"), "codex", True, "gpt-6-sol"),
    ("codex review --uncommitted", "codex", True, None),
    ("/usr/local/bin/codex exec -m o3 'x'", "/usr/local/bin/codex", False, "o3"),
    ("timeout 30 /usr/local/bin/codex exec hi", "/usr/local/bin/codex", False, None),
    ("node /usr/lib/node_modules/@openai/codex/bin/codex.js exec 'x'",
     "node /usr/lib/node_modules/@openai/codex/bin/codex.js", False, None),
    ('bash -lc "codex exec -c model=gpt-x hi"', "codex", True, "gpt-x"),
    ("x=$(codex exec hi)", "codex", True, None),
    ("make check && codex --version", "codex", True, None),
    ("/usr/local/sbin/codex exec hi", "/usr/local/sbin/codex", True, None),  # the guard itself, by path
])
def test_a_codex_launch_at_a_command_position_is_found(command: str, program: str, guarded: bool,
                                                        model: str | None) -> None:
    [hit] = ag.scan_command(command)
    assert (hit["program"], hit["guarded"], hit["model"]) == (program, guarded, model)


@pytest.mark.parametrize("command", [
    "command -v codex", "which codex", "cat /home/candidate/.codex/skills/flow-auto/reference.md",
    "ls ~/.codex/sessions", "echo codex is here", "rg -n codex README.md",
    "cat ~/.codex/config.toml && ls /usr/local/bin/codex",
])
def test_a_mention_that_launches_nothing_is_not_a_hit(command: str) -> None:
    assert ag.scan_command(command) == []


@pytest.mark.parametrize("kind", ["custom_tool_call", "function_call"])
def test_the_scan_reads_both_tool_call_shapes(kind: str) -> None:
    lines = [_tool_call("cat ISSUE.md", kind), _tool_call("/usr/local/bin/codex exec -m o3 hi", kind)]
    [hit] = ag.scan_codex_invocations(lines)
    assert hit["program"] == "/usr/local/bin/codex" and hit["model"] == "o3"


# ------------------------------------------------------------- the assessment

def test_red_an_absolute_path_codex_with_no_guard_record_stops_and_blocks() -> None:
    """Orchestrator condition 2's red: the guard counted nothing, the transcript
    shows codex launched past it."""
    hits = ag.scan_command("/usr/local/bin/codex exec --ephemeral -m gpt-6-sol 'x'")
    verdict = ag.assess(ZERO, hits, "gpt-6-astra")
    assert verdict["stop"] and "past the guard" in verdict["stop"]
    assert verdict["block"] and "past the guard" in verdict["block"]
    assert verdict["other_models"] == ["gpt-6-sol"]


def test_red_a_guarded_refused_launch_is_not_counted_twice() -> None:
    """Condition 2's other red: one bare launch the guard refused is one event."""
    hits = ag.scan_command("codex exec --ephemeral --model gpt-6-astra 'review'")
    verdict = ag.assess(REFUSED_ONE, hits, "gpt-6-astra")
    assert verdict["bypass"] == [] and verdict["stop"] is None and verdict["block"] is None


def test_a_bare_launch_beyond_the_guard_s_refusals_is_a_bypass() -> None:
    hits = ag.scan_command("codex exec a") + ag.scan_command("codex exec b")
    verdict = ag.assess(REFUSED_ONE, hits, "gpt-6-astra")
    assert "2 bare codex invocation(s) in the transcript, 1 refused" in str(verdict["stop"])


def test_a_refused_launch_on_another_model_still_names_the_model() -> None:
    hits = ag.scan_command("codex exec --model gpt-6-sol 'x'")
    assert ag.assess(REFUSED_ONE, hits, "gpt-6-astra")["other_models"] == ["gpt-6-sol"]


def test_a_clean_attempt_neither_stops_nor_blocks() -> None:
    verdict = ag.assess(ZERO, [], "gpt-6-astra")
    assert verdict == {"block": None, "stop": None, "bypass": [], "other_models": []}


@pytest.mark.parametrize("nested,invocations,reason", [
    (ZERO, None, "were not scanned"),                                   # no scan is not "none found"
    ({**ZERO, "status": "observed", "top_level": 2, "suspected": 1}, [], "suspected=1"),
    ({**ZERO, "status": "unknown", "top_level": 0}, [], "unknown"),
    ({**ZERO, "status": "observed", "ancestry_unknown": 1}, [], "ancestry-unknown=1"),
    (None, [], "no guard record"),
])
def test_every_unclean_record_stops(nested: Any, invocations: Any, reason: str) -> None:
    verdict = ag.assess(nested, invocations, "gpt-6-astra")
    assert verdict["stop"] is not None and reason in str(verdict["stop"])
    assert verdict["block"] is not None


def test_a_failed_bind_stops_and_blocks() -> None:
    verdict = ag.assess(ZERO, [], "gpt-6-astra", failure="codex guard binding failed: X")
    assert verdict["stop"] == "codex guard binding failed: X" and "binding failed" in str(verdict["block"])


@pytest.mark.parametrize("record,stops", [
    ({"disposition": "not-run"}, False),
    ({"disposition": "unavailable"}, False),
    ({"disposition": "captured"}, True),                                # dispatched with no report
    ({"disposition": "captured", "codex_guard": {"stop": None}}, False),
    ({"disposition": "inconclusive", "codex_guard": {"stop": "x"}}, True),
])
def test_the_containment_trigger(record: dict[str, Any], stops: bool) -> None:
    assert (ag.containment_trigger(record) is not None) is stops


# ------------------------------------------------------------- the guard session

def test_the_guard_route_records_and_a_refused_line_makes_the_count_unknown() -> None:
    guard = ag.AttemptGuard("a-1")
    decide = guard.watch(lambda request: guard.routes()["codex_guard"][0](request))
    decide({"op": "codex_guard", "decision": "passed-top-level", "argv_digest": DIGEST})
    decide({"op": "codex_guard", "decision": "refused-nested", "argv_digest": DIGEST})
    assert guard.record()["nested"]["confirmed"] == 1 and not guard.guard.channel_unavailable
    with pytest.raises(ChannelRefusal):
        decide({"op": "codex_guard", "decision": "passed-through", "argv_digest": DIGEST})
    assert guard.guard.channel_unavailable
    assert guard.record()["nested"]["status"] == "observed" and not cg.refusals_only(guard.record()["nested"])


class _Channel:
    def __init__(self, log: object, dropped: object) -> None:
        self.log, self.dropped = log, dropped

    def trigger_log(self, handle: object) -> object:
        return self.log

    def trigger_dropped(self, handle: object) -> object:
        return self.dropped


@pytest.mark.parametrize("log,dropped,healthy", [([], 0, True), (None, 0, False), ([], 1, False), ([], None, False)])
def test_finish_reads_the_channel_s_health(log: object, dropped: object, healthy: bool) -> None:
    guard = ag.AttemptGuard("a-1")
    guard.guard.decide({"op": "codex_guard", "decision": "passed-top-level", "argv_digest": DIGEST})
    guard.finish(_Channel(log, dropped), object())
    assert (guard.record()["nested"]["status"] == "zero") is healthy
    with pytest.raises(ChannelRefusal):  # finalized: no later line is recorded
        guard.guard.decide({"op": "codex_guard", "decision": "refused-nested", "argv_digest": DIGEST})


def test_an_unknown_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="nested_policy"):
        ag.AttemptGuard("a-1", nested_policy="anything-goes")


# ------------------------------------- every live codex calibration attempt

def test_every_codex_calibration_attempt_is_guarded_and_no_other_client() -> None:
    assert cr.guard_kwargs("codex", "gpt-6-astra") == {
        "codex_guard": True, "nested_codex_policy": "refusal-expected", "declared_model": "gpt-6-astra"}
    assert cr.guard_kwargs("claude", "opus") == {}


def test_a_discrimination_attempt_is_guarded_and_a_containment_trigger_stops_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Condition 1 on the discrimination kind, and the Stop: the first attempt's
    guard report stops the schedule, and no later attempt is launched."""
    seen: list[dict[str, Any]] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        seen.append(kwargs)
        return {"disposition": "inconclusive",
                "codex_guard": {"nested": ZERO, "stop": "nested codex past the guard: /usr/local/bin/codex"}}

    monkeypatch.setattr(cc, "run_level1_agent_attempt", attempt)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _experiment, outcomes = cr.run_discrimination(
        _parse(_approved(tmp_path)), run_dir=run_dir, intact=_intact(), image_digest="sha256:" + "d" * 64,
        backends=lambda: (None, None), argv_for=lambda _s: ["codex"])  # type: ignore[arg-type,return-value]
    assert len(seen) == 1
    assert seen[0]["codex_guard"] is True and seen[0]["nested_codex_policy"] == "refusal-expected"
    assert seen[0]["declared_model"] == "gpt-6-astra"
    assert len(outcomes) == 6
    assert all("containment stop at" in str(o.record.get("reason")) for o in outcomes[1:])


def test_a_clean_guard_report_lets_every_attempt_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        calls.append(str(kwargs["attempt_id"]))
        return {"disposition": "inconclusive", "codex_guard": {"nested": REFUSED_ONE, "stop": None}}

    monkeypatch.setattr(cc, "run_level1_agent_attempt", attempt)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cr.run_discrimination(_parse(_approved(tmp_path)), run_dir=run_dir, intact=_intact(),
                          image_digest="sha256:" + "d" * 64, backends=lambda: (None, None),  # type: ignore[arg-type,return-value]
                          argv_for=lambda _s: ["codex"])
    assert len(calls) == 6


def test_an_improvement_attempt_is_guarded_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Condition 1 on the calibration-declaration (improvement) kind."""
    import test_calibration_outcome_endpoint as ep

    data = ep._data()
    ep._approve(data)
    seen: list[dict[str, Any]] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        seen.append(kwargs)
        return {"disposition": "inconclusive", "codex_guard": {"nested": ZERO, "stop": None}}

    monkeypatch.setattr(cc, "run_level1_agent_attempt", attempt)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cr.run_calibration(
        cr.calibration.parse_declaration(data), run_dir=run_dir, root=ep.ROOT,
        treatment=cr.Treatment({"skill": b"body"}, "sha256:" + "ab" * 32, None, skill_digests=ep._TEST_PINS),
        image_digest="sha256:" + "cd" * 32, backends=lambda: (object(), object()), argv_for=lambda _s: [])
    assert seen and all(call["codex_guard"] is True for call in seen)


# --------------------------------------- the report: every session counted

def _entry(record: dict[str, Any], obs: dict[str, Any]) -> dict[str, object]:
    return cr.guard_entry(record, obs, "gpt-6-astra")


def test_a_nested_session_on_another_model_widens_other_models_and_tokens_sum() -> None:
    obs = {"transcript_sessions": [
        {"model": "gpt-6-astra", "token_usage": {"total_tokens": 100}},
        {"model": "gpt-6-sol", "token_usage": {"total_tokens": 30}}]}
    out = _entry({}, obs)
    assert out["models_all_sessions"] == ["gpt-6-astra", "gpt-6-sol"] and out["tokens_all_sessions"] == 130
    assert out["nested_codex"] == {"other_models": ["gpt-6-sol"]}


def test_a_bypass_makes_the_token_total_unknown() -> None:
    record = {"codex_guard": {"nested": ZERO, "bypass": ["codex by path"], "other_models": []}}
    obs = {"run_metadata": {"model": "gpt-6-astra", "token_usage": {"total_tokens": 100}}}
    assert _entry(record, obs)["tokens_all_sessions"] == cr.UNKNOWN


def test_an_unguarded_single_session_entry_is_unchanged() -> None:
    assert _entry({}, {"run_metadata": {"model": "gpt-6-astra"}}) == {}


# ------------------------------- two transcripts: both kept, both counted

def test_red_a_two_transcript_attempt_keeps_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pilot discarded both files of a two-session attempt (#500). Now each
    is retained as its own stream, digest-listed, and each session's model and
    tokens are read; the attempt is still never graded."""
    store = trial.open_store(tmp_path / "store", forbidden=[])
    base, state = tmp_path / "work", tmp_path / "docker-state"
    base.mkdir()
    experiment, attempt_id = _planned(store)
    home = _mapped_home(state, attempt_id)
    second = (CODEX_FIXTURES / "run-metadata.jsonl").read_bytes()  # model fake-model-b, 330 tokens

    class _TwoSessions(d.DockerBackend):
        planted = False

        def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
            super().deliver_home_file(handle, container_relpath, data, mode=mode)
            if not self.planted:
                type(self).planted = True
                super().deliver_home_file(handle, ".codex/sessions/2026/01/01/rollout-nested.jsonl", second)

    backend = _TwoSessions(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                           daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=_fake_argv(fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-main.jsonl"),
        prompt="Fix the slug helper.", skill_name=None, surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"))
    obs = record["observation"]
    assert isinstance(obs, dict) and obs["transcript_files_found"] == 2 and obs["multiple_transcripts"] is True
    sessions = obs["transcript_sessions"]
    assert [s["retained"] for s in sessions] == [True, True]
    assert {s["model"] for s in sessions} >= {"fake-model-b"}
    manifest = json.loads((experiment.root / f"manifest-{attempt_id}.json").read_text())
    kept = {o["stream"]: o for o in manifest["observations"]}
    for index in (1, 2):
        entry = kept[f"{records.CLIENT_TRANSCRIPT}-session-{index}"]
        assert entry["coverage"] == "complete" and entry["digest"].startswith("sha256:")
        assert trial.sha256_bytes((experiment.root / entry["ref"]).read_bytes()) == entry["digest"]
    # The single-transcript stream still says, with its reason, that none was graded.
    assert kept[records.CLIENT_TRANSCRIPT]["coverage"] == "missing"
    assert record["graded"] is None


def test_red_on_main_a_two_transcript_attempt_kept_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same attempt with the session list switched off - the behaviour on
    main before #500 - keeps no transcript at all: this is what the fix changed."""
    real = at._make_observe_before_teardown

    def without_sessions(**kwargs: Any) -> Any:
        kwargs.pop("sessions", None)
        return real(**kwargs)

    monkeypatch.setattr(at, "_make_observe_before_teardown", without_sessions)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    base, state = tmp_path / "work", tmp_path / "docker-state"
    base.mkdir()
    experiment, attempt_id = _planned(store)
    home = _mapped_home(state, attempt_id)

    class _TwoSessions(d.DockerBackend):
        planted = False

        def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
            super().deliver_home_file(handle, container_relpath, data, mode=mode)
            if not self.planted:
                type(self).planted = True
                super().deliver_home_file(handle, ".codex/sessions/2026/01/01/rollout-nested.jsonl",
                                          (CODEX_FIXTURES / "run-metadata.jsonl").read_bytes())

    backend = _TwoSessions(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                           daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=_fake_argv(fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-main.jsonl"),
        prompt="Fix the slug helper.", skill_name=None, surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"))
    manifest = json.loads((experiment.root / f"manifest-{attempt_id}.json").read_text())
    assert not any(str(o["stream"]).startswith(f"{records.CLIENT_TRANSCRIPT}-session-")
                   for o in manifest["observations"])


def test_the_guard_overlay_is_the_fixture_path_s_own() -> None:
    """One overlay, not a second copy that could drift (#500)."""
    assert ag.fo.install_codex_guard is fo.install_codex_guard
    assert ag.GUARDED_PATHS == {fo.CODEX_GUARD_PATH}


def test_a_guarded_attempt_needs_a_docker_backend() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="Docker backend"):
        at.run_one_attempt(backend=object(), experiment=None, attempt_id="a", client="codex",  # type: ignore[arg-type]
                           base_argv=[], prompt="p", skill_name=None, surface={}, limits=Limits(timeout=1),
                           base=Path("."), codex_guard=True)


def test_the_pilot_shape_would_have_stopped_the_schedule() -> None:
    """a-4ef6692fdccb's tool call, as the transcript recorded it: with no guard
    record at all, the backstop alone blocks it and stops the schedule."""
    line = _tool_call("codex exec --skip-git-repo-check --ephemeral --sandbox read-only --model gpt-6-sol "
                      "--output-last-message /tmp/rangekit-review.md 'Review the change.'")
    hits = ag.scan_codex_invocations([line])
    verdict = ag.assess({**ZERO}, hits, "gpt-6-astra")
    assert verdict["stop"] and verdict["block"] and verdict["other_models"] == ["gpt-6-sol"]


# --------------------------------------------- counter-model review, pass 1

def test_red_a_quoted_command_key_is_read() -> None:
    line = {"type": "response_item", "payload": {"type": "custom_tool_call", "input":
            'await tools.exec_command({"cmd": "/usr/local/bin/codex exec --ephemeral --model other hi"})'}}
    [hit] = ag.scan_codex_invocations([line])
    assert hit["program"] == "/usr/local/bin/codex" and hit["guarded"] is False and hit["model"] == "other"


def test_red_a_command_the_scan_cannot_read_fails_closed() -> None:
    line = {"type": "response_item", "payload": {"type": "custom_tool_call", "input": "await tools.exec_command(cmd)"}}
    hits = ag.scan_codex_invocations([line])
    assert [h.get("unreadable") for h in hits] == [True]
    verdict = ag.assess(ZERO, hits, "gpt-6-astra")
    assert "could not read" in str(verdict["stop"]) and verdict["block"]


def test_a_tool_call_that_runs_no_command_is_not_unreadable() -> None:
    line = {"type": "response_item", "payload": {"type": "custom_tool_call", "input": "text('hello')"}}
    assert ag.scan_codex_invocations([line]) == []


@pytest.mark.parametrize("command,programs", [
    ("FOO=1 /usr/local/bin/codex exec --ephemeral --model other hi", ["/usr/local/bin/codex"]),
    ("A=1 B=2 codex exec hi", ["codex"]),
    # The outer, guarded launch must not swallow the inner one by path.
    ('codex exec "Review $(/usr/local/bin/codex exec --ephemeral hi)"', ["codex", "/usr/local/bin/codex"]),
    ("cat <<EOF\nx $(codex exec hi)\nEOF", ["codex"]),
    ("sh -c 'codex exec hi'", ["codex"]),
])
def test_red_shell_syntax_does_not_hide_a_launch(command: str, programs: list[str]) -> None:
    assert [h["program"] for h in ag.scan_command(command)] == programs


@pytest.mark.parametrize("command", [
    "echo 'example; codex exec --model other hi'",
    "cat <<'EOF'\ncodex exec --model other hi\nEOF",
    "git commit -m 'codex exec run'",
    'printf "%s\\n" "codex exec --model other"',
])
def test_red_quoted_literal_text_is_not_a_launch(command: str) -> None:
    assert ag.scan_command(command) == []


def test_a_model_flag_inside_the_prompt_is_not_the_launch_s_model() -> None:
    [hit] = ag.scan_command("codex exec --ephemeral --model 'gpt-6-sol' 'Review --model fake'")
    assert hit["model"] == "gpt-6-sol"


def test_red_an_extra_transcript_session_stops_the_schedule() -> None:
    verdict = ag.assess(ZERO, [], "gpt-6-astra", sessions=2)
    assert "2 transcript sessions" in str(verdict["stop"]) and verdict["block"]
    assert ag.assess(ZERO, [], "gpt-6-astra", sessions=1)["stop"] is None


def test_red_a_same_model_bypass_is_ineligible_and_its_tokens_unknown() -> None:
    record = {"codex_guard": {"nested": ZERO, "bypass": ["codex by path"], "other_models": [],
                              "stop": "nested codex past the guard", "block": "not credited"}}
    obs = {"run_metadata": {"model": "gpt-6-astra", "token_usage": {"total_tokens": 100}}}
    out = cr.guard_entry(record, obs, "gpt-6-astra")
    assert out["tokens_all_sessions"] == cr.UNKNOWN and out["tokens_measured_sessions"] == 100


def test_red_a_suspected_launch_leaves_the_token_total_unknown() -> None:
    suspected = {**ZERO, "status": "observed", "top_level": 2, "suspected": 1}
    verdict = ag.assess(suspected, [], "gpt-6-astra")
    record = {"codex_guard": {"nested": suspected, **verdict}}
    obs = {"run_metadata": {"model": "gpt-6-astra", "token_usage": {"total_tokens": 100}}}
    assert cr.guard_entry(record, obs, "gpt-6-astra")["tokens_all_sessions"] == cr.UNKNOWN


def test_red_a_stopped_attempt_is_never_model_eligible(tmp_path: Path) -> None:
    """The report revokes eligibility on any unclean containment, not only on
    another model's name (counter-model review, pass 1)."""
    import test_calibration_outcome_endpoint as ep

    experiment, schedule = ep._planned(tmp_path)
    outcomes = ep._outcomes(schedule)
    for outcome in outcomes:
        outcome.record["observation"] = {"run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high",
                                                          "token_usage": {"total_tokens": 10}}}
    outcomes[0].record["codex_guard"] = {"nested": ZERO, "bypass": ["codex by path"], "other_models": [],
                                         "stop": "nested codex past the guard", "block": "not credited"}
    outcomes[1].record["codex_guard"] = {"nested": REFUSED_ONE, "bypass": [], "other_models": [],
                                         "stop": None, "block": None}
    report = ep._report(experiment, outcomes)
    rows = {row["attempt_id"]: row for row in report["attempts"]}
    assert rows[outcomes[0].scheduled.attempt_id]["model_eligible"] is False
    assert rows[outcomes[1].scheduled.attempt_id]["model_eligible"] is True
    assert report["containment_stop"]["at_attempt"] == outcomes[0].scheduled.attempt_id
