"""#279 PR 1: controller-delivered turns (the Step-3 approval).

The scripted actor is `tests/fixtures/agent-trial/fake_turns_client.py`: turn 1
stops "at Step 3" with a plan; a resume carrying the approval proceeds. The
green control is an approval delivered and acted on; every red names one way a
turn must NOT be delivered, or must not be counted as clean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import _docker_bin, _fake_argv, _fresh_credential, _mapped_home, _planned

from skillc import agent_trial as at
from skillc import codex_guard as cg
from skillc import controller_turns as ct
from skillc import docker_backend as d
from skillc import egress as eg
from skillc import trial as t
from skillc.agent_trial import ServerSideChannelRefused
from skillc.backend import Limits
from skillc.fixture_attempt import AttemptFixture, FixtureSession

FAKE_TURNS = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_turns_client.py"
SESSION = "01a14f6a-cd7e-7851-8061-5cdeaaca5863"
APPROVAL = "Approved: proceed with Section C exactly as presented."
CODEX_BASE = ("codex", "exec", "--sandbox", "danger-full-access", "--skip-git-repo-check", *eg.CODEX_SERVER_SIDE_OFF)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "base"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


# ------------------------------------------------------------------ the schema


def _turns(by_case: dict[str, list[dict[str, str]]]) -> dict[str, object]:
    return {"version": 1, "by_case": by_case}


def test_turns_are_declared_per_case_and_a_case_may_declare_none() -> None:
    parsed = ct.parse_turns(_turns({"twin": [{"text": APPROVAL}], "clean": []}), ["clean", "twin"])
    assert parsed.for_case("twin").texts == (APPROVAL,)
    assert parsed.for_case("clean") == ct.NO_TURNS


@pytest.mark.parametrize("data, named", [
    ({"version": 1}, "exactly"),                                                   # no by_case
    ({"version": 2, "by_case": {"clean": [], "twin": []}}, "version"),
    ({"version": True, "by_case": {"clean": [], "twin": []}}, "version"),
    (_turns({"twin": []}), "exactly the declared cases"),                          # a case missing
    (_turns({"clean": [], "twin": [], "extra": []}), "exactly the declared cases"),
    (_turns({"clean": [], "twin": [{"text": "a"}] * (ct.MAX_TURNS + 1)}), "at most"),
    (_turns({"clean": [], "twin": [{"text": "  "}]}), "non-empty"),
    (_turns({"clean": [], "twin": [{"text": "a", "when": "always"}]}), "exactly {text}"),  # no conditions
    (_turns({"clean": [], "twin": [{"text": "a\x00b"}]}), "NUL"),
    (_turns({"clean": [], "twin": "Approved"}), "list"),
])
def test_red_case_a_malformed_turns_declaration_is_refused(data: object, named: str) -> None:
    with pytest.raises(ct.TurnsRefused, match=named):
        ct.parse_turns(data, ["clean", "twin"])


def test_red_case_an_undeclared_case_has_no_turns_to_fall_back_on() -> None:
    parsed = ct.parse_turns(_turns({"clean": [], "twin": []}), ["clean", "twin"])
    with pytest.raises(ct.TurnsRefused, match="no turns declared"):
        parsed.for_case("held-out")


# ------------------------------------------------------- the measured resume shape


def test_the_resume_argv_is_the_turn_one_argv_then_resume_id_text() -> None:
    """Measured on codex-cli 0.157.1: exec's flags BEFORE `resume`, `--sandbox`
    included, take effect; `--sandbox` after `resume` is refused."""
    argv = ct.resume_argv("codex", CODEX_BASE, SESSION, APPROVAL)
    assert argv == (*CODEX_BASE, "resume", SESSION, APPROVAL)
    assert argv.index("--sandbox") < argv.index("resume")  # never after it
    assert eg.missing_server_side_flags(argv) == []


@pytest.mark.parametrize("client, base_argv, session, named", [
    ("claude", ("claude", "-p"), SESSION, "codex"),
    ("codex", CODEX_BASE, "not-a-uuid", "not a session id"),
    ("codex", (*CODEX_BASE, "resume", SESSION), SESSION, "already holds 'resume'"),
])
def test_red_case_a_resume_argv_that_cannot_be_built_is_refused(
    client: str, base_argv: tuple[str, ...], session: str, named: str,
) -> None:
    with pytest.raises(ct.TurnsRefused, match=named):
        ct.resume_argv(client, base_argv, session, APPROVAL)


_HEADER = (f"WARNING: proceeding\nReading additional input from stdin...\nOpenAI Codex v0.157.1\n--------\n"
           f"workdir: /work\nmodel: gpt-6-astra\nsession id: {SESSION}\n--------\nuser\nhi\n")


@pytest.mark.parametrize("stderr, expected", [
    (_HEADER.encode(), SESSION),                                                         # the measured shape
    (b"", None),                                                                         # nothing captured
    (_HEADER.replace(f"session id: {SESSION}\n", "").encode(), None),                    # no id in the header
    (_HEADER.replace("--------\nuser", "user").encode(), None),                           # the header never closes
    (_HEADER.replace("model:", f"session id: {SESSION}\nmodel:").encode(), None),       # two ids: ambiguous
    (_HEADER.replace(SESSION, "not-a-uuid").encode(), None),
    # An "agent" printing a session line AFTER the header must not replace it.
    ((_HEADER + "session id: 99999999-8888-7777-6666-555555555555\n").encode(), SESSION),
    # ...nor supply one when the header has none.
    ((_HEADER.replace(f"session id: {SESSION}\n", "") + f"session id: {SESSION}\n").encode(), None),
])
def test_the_session_id_is_read_only_from_the_client_header(stderr: bytes, expected: str | None) -> None:
    assert ct.session_id_from_header(stderr) == expected


# --------------------------------------------- the guard counts each delivered turn


def _top_levels(n: int) -> list[dict[str, object]]:
    return [{"seq": i + 1, "decision": "passed-top-level", "argv_digest": "sha256:" + "0" * 64} for i in range(n)]


@pytest.mark.parametrize("delivered, top, status, suspected", [
    (0, 1, "zero", 0),       # one turn, one launch: today's clean case
    (1, 2, "zero", 0),       # 2 turns, 2 top-levels: clean (orchestrator red, green side)
    (1, 3, "observed", 1),   # 2 turns, 3 top-levels: suspected
    (0, 2, "observed", 1),   # 1 turn, 2 top-levels: suspected, as before #279
    (1, 1, "unknown", 0),    # a delivered turn the guard never saw: not clean
])
def test_red_case_the_guard_expects_one_top_level_launch_per_turn(
    delivered: int, top: int, status: str, suspected: int,
) -> None:
    nested = cg.summarize("a-1", _top_levels(top), False, expected_top_level=ct.expected_top_level(delivered))["nested"]
    assert (nested["status"], nested["suspected"]) == (status, suspected)
    assert nested["expected_top_level"] == 1 + delivered


def test_the_fixture_session_judges_its_guard_against_the_delivered_turns() -> None:
    session = FixtureSession(AttemptFixture(case="twin", declaration={}, facts={}, capture=lambda *_: {}), "a-1")
    session.guard.decisions.extend(_top_levels(2))
    assert session.guard_record()["nested"]["status"] == "observed"  # 1 expected by default
    session.expected_top_level = ct.expected_top_level(1)
    assert session.guard_record()["nested"]["status"] == "zero"


# ----------------------------------------- end to end, through run_one_attempt


def _attempt(store: Path, base: Path, docker_state: Path, tmp_path: Path, *, turns: ct.Turns | None,
             egress: bool = False, timeout: float = 20, header: str = "normal", turn1_exit: int | None = None,
             turn1_sleep: float = 0, base_flags: tuple[str, ...] = tuple(eg.CODEX_SERVER_SIDE_OFF),
             ) -> tuple[dict[str, object], list[dict[str, object]], t.Experiment, str]:
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                              daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, egress=egress)
    experiment, attempt_id = _planned(store)
    home = _mapped_home(docker_state, attempt_id)
    relpath = ".codex/sessions/2026/01/01/rollout-turns.jsonl"
    own = ["--session-id", SESSION, "--home", str(home), "--transcript-relpath", relpath, "--header", header,
           "--turn1-sleep", str(turn1_sleep)]
    if turn1_exit is not None:
        own += ["--turn1-exit", str(turn1_exit)]
    argv = [sys.executable, str(FAKE_TURNS), *own, "--",
            *_fake_argv(fmt="codex-fake", home=home, transcript_relpath=relpath)[2:], *base_flags]
    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex", base_argv=argv,
        prompt="Fix the slug helper.", skill_name="demo-skill", surface={}, limits=Limits(timeout=timeout),
        base=base, credential_explicit_path=_fresh_credential(tmp_path, "codex"), turns=turns,
    )
    log = home / "turns-log.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return record, entries, experiment, attempt_id


def _turn_events(experiment: t.Experiment, attempt_id: str) -> list[dict[str, object]]:
    return [e for e in experiment.events(attempt_id) if e.get("event") == "controller-turn"]


def test_green_control_an_approval_delivered_is_acted_on_in_the_same_session(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    record, entries, experiment, attempt_id = _attempt(store, base, docker_state, tmp_path,
                                                       turns=ct.Turns((APPROVAL,)))
    assert [e["turn"] for e in entries] == [1, "resume"]
    assert entries[1] == {"turn": "resume", "session_id": SESSION, "text": APPROVAL, "proceeded": True}
    assert record["controller_turns"] == {
        "declared": 1, "delivered": 1, "expected_top_level": 2, "session_id_source": "client-stderr-header",
        "session_id_found": True, "stopped": "every declared turn was delivered",
    }
    assert [(e.get("index"), e.get("delivered"), e.get("ended")) for e in _turn_events(experiment, attempt_id)] == [
        (2, True, None), (2, None, "exited")]
    assert record["disposition"] == "captured"


def test_red_case_an_approval_withheld_stops_the_actor_at_step_three(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """A case declared with no turns (CLEAN) never receives one, even after a
    clean exit - the orchestrator's per-case red."""
    record, entries, experiment, attempt_id = _attempt(store, base, docker_state, tmp_path, turns=ct.NO_TURNS)
    assert [e["turn"] for e in entries] == [1]
    assert entries[0]["ended_at_step"] == 3
    assert "controller_turns" not in record and _turn_events(experiment, attempt_id) == []


@pytest.mark.parametrize("header, stopped", [
    ("absent", "no session id"),
    ("twice", "no session id"),
])
def test_red_case_no_unambiguous_session_id_means_no_further_turn(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, header: str, stopped: str,
) -> None:
    record, entries, experiment, attempt_id = _attempt(store, base, docker_state, tmp_path,
                                                       turns=ct.Turns((APPROVAL,)), header=header)
    assert [e["turn"] for e in entries] == [1]
    turns = record["controller_turns"]
    assert isinstance(turns, dict) and turns["delivered"] == 0 and stopped in str(turns["stopped"])
    assert _turn_events(experiment, attempt_id) == []


def test_red_case_a_session_line_the_agent_prints_after_the_header_is_not_used(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    _record, entries, _experiment, _attempt_id = _attempt(store, base, docker_state, tmp_path,
                                                          turns=ct.Turns((APPROVAL,)), header="late-spoof")
    assert entries[-1]["turn"] == "resume" and entries[-1]["session_id"] == SESSION


def test_red_case_a_turn_one_that_exits_non_zero_gets_no_approval(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    record, entries, experiment, attempt_id = _attempt(store, base, docker_state, tmp_path,
                                                       turns=ct.Turns((APPROVAL,)), turn1_exit=1)
    assert [e["turn"] for e in entries] == [1]
    assert _turn_events(experiment, attempt_id) == []
    turns = record["controller_turns"]
    assert isinstance(turns, dict) and turns["delivered"] == 0


def test_red_case_a_turn_one_that_times_out_gets_no_approval(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    record, entries, experiment, attempt_id = _attempt(store, base, docker_state, tmp_path,
                                                       turns=ct.Turns((APPROVAL,)), timeout=3, turn1_sleep=10)
    assert all(e["turn"] != "resume" for e in entries)
    assert _turn_events(experiment, attempt_id) == []
    stopped = [e for e in experiment.events(attempt_id) if e.get("event") == "stopped"]
    assert stopped and stopped[-1].get("reason") == "timeout"
    turns = record["controller_turns"]
    assert isinstance(turns, dict) and turns["delivered"] == 0


def test_red_case_a_resume_argv_with_a_server_side_channel_open_is_refused_before_any_container(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#442's preflight runs on every resume argv. Turn 1's argv here omits a
    pinned flag too, so the turn-1 preflight fires first; the resume check is
    pinned separately on the exact shape by the argv test above."""
    with pytest.raises(ServerSideChannelRefused):
        _attempt(store, base, docker_state, tmp_path, turns=ct.Turns((APPROVAL,)), egress=True,
                 base_flags=("--strict-config",))
    assert not any(p.suffix == ".json" for p in docker_state.glob("*.json")) if docker_state.exists() else True


def test_red_case_controller_turns_are_refused_for_a_client_with_no_measured_resume(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    experiment, attempt_id = _planned(store)
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                              daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    with pytest.raises(ct.TurnsRefused, match="codex"):
        at.run_one_attempt(backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
                           base_argv=["claude", "-p"], prompt="p", skill_name=None, surface={},
                           limits=Limits(timeout=5), base=base, turns=ct.Turns((APPROVAL,)))
