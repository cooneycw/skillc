"""#442: provider-only egress for live agent containers, and the server-side
channels it cannot reach.

Against the fake docker CLI (no daemon): the proxy's policy and its real
behaviour on loopback, the per-attempt network and proxy lifecycle a
`DockerBackend(egress=True)` drives, the preflight that refuses a live codex
argv with a server-side channel left open (one red per pinned flag), and the
transcript census that refuses to credit an attempt showing a server-side tool,
end to end through `run_one_attempt`, including how such an attempt still shows
in a report's accounting. What a REAL container can reach is the real-Docker
runner's job (`tests/test_agent_egress_live.py`).
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import (
    GRADER_ROOT,
    _docker_bin,
    _fake_argv,
    _fresh_credential,
    _mapped_home,
    _planned,
)

from skillc import agent_trial as at
from skillc import calibration, matched_pilot, verify
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import egress as eg
from skillc import trial as t
from skillc.backend import BackendUnavailable, Limits


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


def _decide() -> object:
    namespace: dict[str, object] = {}
    exec(compile(eg.PROXY_SOURCE, "<proxy>", "exec"), namespace)  # noqa: S102 - the shipped policy itself
    return namespace["decide"]


# ------------------------------------------------------------- the policy


@pytest.mark.parametrize("target, allowed", [
    ("chatgpt.com:443", True),
    ("auth.openai.com:443", True),
    ("CHATGPT.COM:443", True),
    ("chatgpt.com.:443", True),
    ("github.com:443", False),
    ("raw.githubusercontent.com:443", False),
    ("api.openai.com:443", False),  # ChatGPT auth only (ruling 3)
    ("ab.chatgpt.com:443", False),  # denied: measured unnecessary (ruling 1)
    ("x.oaiusercontent.com:443", False),  # not contacted with plugins off (ruling 2)
    ("chatgpt.com:80", False),
    ("evilchatgpt.com:443", False),
    ("chatgpt.com.evil.example:443", False),
    ("chatgpt.com", False),
    (":443", False),
])
def test_the_proxy_policy_allows_only_listed_hosts_on_443(target: str, allowed: bool) -> None:
    decide = _decide()
    assert decide(target, frozenset(eg.ALLOWED_HOSTS)) is allowed  # type: ignore[operator]


def test_the_allowlist_is_exactly_the_measured_provider_hosts() -> None:
    assert eg.ALLOWED_HOSTS == ("auth.openai.com", "chatgpt.com")
    doc = eg.allowlist_document()
    assert doc["hosts"] == ["auth.openai.com", "chatgpt.com"] and doc["port"] == 443
    # The digest names the allowlist: a widened list is a different digest.
    assert eg.allowlist_digest() != eg.allowlist_digest((*eg.ALLOWED_HOSTS, "github.com"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _connect(port: int, target: str) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        return s.recv(200)


def test_the_real_proxy_tunnels_an_allowed_host_refuses_the_rest_and_logs_both(tmp_path: Path) -> None:
    """The shipped proxy script, run as a process on loopback: an allowed
    CONNECT is tunnelled to its upstream byte for byte, a refused one gets 403
    and never reaches anything, and both are in the log after the start line."""
    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    up_port = int(upstream.getsockname()[1])
    received: list[bytes] = []

    def echo_once() -> None:
        conn, _ = upstream.accept()
        with conn:
            data = conn.recv(100)
            received.append(data)
            conn.sendall(b"pong:" + data)

    threading.Thread(target=echo_once, daemon=True).start()
    port, log = _free_port(), tmp_path / "proxy.log"
    # The policy is 443-only; this test serves the upstream on a free port, so
    # it runs a copy of the shipped script with ONLY that literal changed - and
    # checks the copy differs from the original in nothing else.
    source = eg.PROXY_SOURCE.replace('port != "443"', f'port != "{up_port}"')
    assert source.replace(f'port != "{up_port}"', 'port != "443"') == eg.PROXY_SOURCE
    allow = json.dumps({"hosts": ["127.0.0.1"]})
    proc = subprocess.Popen([sys.executable, "-c", source, str(port), str(log), allow, "sha256:test"])
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(f"CONNECT 127.0.0.1:{up_port} HTTP/1.1\r\n\r\n".encode())
            assert s.recv(100).startswith(b"HTTP/1.1 200")
            s.sendall(b"ping")
            assert s.recv(100) == b"pong:ping"
        assert _connect(port, "github.com:443").startswith(b"HTTP/1.1 403")
        assert _connect(port, f"127.0.0.2:{up_port}").startswith(b"HTTP/1.1 403")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        upstream.close()
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert entries[0]["event"] == "start" and entries[0]["digest"] == "sha256:test"
    summary = eg.summarize_log(log.read_bytes())
    assert summary["allowed"] == {f"127.0.0.1:{up_port}": 1}
    assert summary["denied"] == {"github.com:443": 1, f"127.0.0.2:{up_port}": 1}
    assert received == [b"ping"]


# ------------------------------------------------- the per-attempt lifecycle


def _egress_backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                           daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, egress=True)


def _state(docker_state: Path, name: str) -> dict[str, object]:
    return json.loads((docker_state / f"{name}.json").read_text())


def test_an_egress_attempt_joins_only_its_internal_network_with_no_dns_and_the_proxy_env(
    base: Path, docker_state: Path,
) -> None:
    backend = _egress_backend(base, docker_state)
    handle = backend.prepare("a-egress1")
    assert isinstance(handle, d._Handle)
    agent = _state(docker_state, handle.name)
    network, proxy = eg.network_name(handle.name), eg.proxy_name(handle.name)
    assert handle.egress_network == network and handle.egress_proxy == proxy
    assert agent["networks"] == [network], "the agent must never join bridge or any other network"
    assert agent["dns"] == [eg.AGENT_DNS]
    env = agent["env"]
    assert isinstance(env, dict)
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        assert env[key] == f"http://10.99.0.2:{eg.PROXY_PORT}"
    assert env["NO_PROXY"] == "" and env["no_proxy"] == ""
    net = json.loads((docker_state / "networks" / f"{network}.json").read_text())
    assert net["internal"] is True and net["labels"][d.ATTEMPT_LABEL_KEY] == "a-egress1"
    proxy_state = _state(docker_state, proxy)
    assert proxy_state["networks"] == ["bridge", network]
    assert proxy_state["labels"][eg.ROLE_LABEL_KEY] == eg.PROXY_ROLE  # type: ignore[index]

    log = backend.egress_log(handle)
    assert log is not None and eg.summarize_log(log)["allowlist_digest"] == eg.allowlist_digest()

    backend.destroy(handle)
    assert not (docker_state / "networks" / f"{network}.json").exists()
    assert not (docker_state / f"{proxy}.json").exists()
    assert not (docker_state / f"{handle.name}.json").exists()


def test_a_backend_without_egress_composes_exactly_the_old_argv(base: Path, docker_state: Path) -> None:
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=["docker"])
    argv = backend._keepalive_run_argv("n", "a-1")
    assert "--dns" not in argv and argv[argv.index("--network") + 1] == "none"
    assert not any(a.startswith("HTTPS_PROXY") for a in argv)


@pytest.mark.parametrize("sentinel", [".refuse-network-create", ".refuse-network-connect", ".refuse-run"])
def test_a_refused_egress_setup_leaves_no_network_or_proxy_behind(
    base: Path, docker_state: Path, sentinel: str,
) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / sentinel).write_text("")
    with pytest.raises(BackendUnavailable, match="egress setup failed"):
        _egress_backend(base, docker_state).prepare("a-refused")
    leftovers = list((docker_state / "networks").glob("*.json")) if (docker_state / "networks").is_dir() else []
    assert leftovers == []
    assert not any(p.name.endswith("-proxy.json") for p in docker_state.glob("*.json"))


def test_the_production_agent_backend_is_the_egress_backend(base: Path, docker_state: Path) -> None:
    agent, grading = cc.agent_backends(image="fake-image:1", base=base, docker_bin=["docker"], daemon_timeout=1)
    assert agent.egress and not grading.egress and grading.network == "none"
    assert cc.agent_network_label(agent) == cc.AGENT_NETWORK_POLICY


# ------------------------------------------------- server-side: preflight


def test_the_default_codex_argv_pins_every_server_side_channel_off() -> None:
    assert eg.missing_server_side_flags(cc.DEFAULT_CLIENT_ARGVS["codex"]) == []


def _without(flag_pair: tuple[str, ...]) -> list[str]:
    argv = list(cc.DEFAULT_CLIENT_ARGVS["codex"])
    for i in range(len(argv) - len(flag_pair) + 1):
        if tuple(argv[i:i + len(flag_pair)]) == flag_pair:
            return argv[:i] + argv[i + len(flag_pair):]
    raise AssertionError(f"{flag_pair} is not in the default argv")


#: Each pinned flag, removed alone (condition 2: one red per flag).
_EACH_FLAG = [("--strict-config",), ("-c", eg.CODEX_WEB_SEARCH_OFF),
              ("--disable", "apps"), ("--disable", "plugins"), ("--disable", "remote_plugin")]


def _preflight(argv: list[str], backend: d.DockerBackend, base: Path, store: Path) -> None:
    experiment, attempt_id = _planned(store)
    at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="p", skill_name=None, surface={}, limits=Limits(timeout=5), base=base,
    )


@pytest.mark.parametrize("flag_pair", _EACH_FLAG, ids=lambda f: " ".join(f))
def test_red_case_a_live_codex_argv_missing_one_server_side_flag_is_refused_before_any_container(
    base: Path, docker_state: Path, store: Path, flag_pair: tuple[str, ...],
) -> None:
    with pytest.raises(at.ServerSideChannelRefused, match="server-side channel left open"):
        _preflight(_without(flag_pair), _egress_backend(base, docker_state), base, store)
    assert not docker_state.exists() or not list(docker_state.glob("*.json")), "nothing may start"


@pytest.mark.parametrize("tail, named", [
    (["--enable", "apps"], "apps is re-enabled"),
    (["--enable=plugins"], "plugins is re-enabled"),
    (["-c", 'web_search="live"'], "web_search is set to"),
    (['-cweb_search="live"'], "web_search is set to"),  # attached short form (counter-model review)
    (['--config=web_search="cached"'], "web_search is set to"),
    (["-c", "features.remote_plugin=true"], "remote_plugin is re-enabled"),
    (["-c"], "has no value"),
])
def test_red_case_a_later_flag_that_reopens_a_channel_is_refused(tail: list[str], named: str) -> None:
    problems = eg.missing_server_side_flags([*cc.DEFAULT_CLIENT_ARGVS["codex"], *tail])
    assert any(named in p for p in problems), problems


def test_red_case_settings_are_read_in_argv_order_not_grouped_by_spelling() -> None:
    """Counter-model review: an earlier `--config=web_search="disabled"` then a
    later `-c web_search="live"` must read as live - the last setting wins,
    whatever spelling each one used."""
    argv = ["codex", "exec", "--strict-config", '--config=web_search="disabled"', "-c", 'web_search="live"',
            "--disable", "apps", "--disable", "plugins", "--disable", "remote_plugin"]
    problems = eg.missing_server_side_flags(argv)
    assert any("web_search is set to" in p for p in problems), problems
    assert eg.missing_server_side_flags([*argv[:4], *argv[6:]]) == [], "the green twin: disabled stays disabled"


def test_red_case_a_live_codex_attempt_on_an_open_network_without_egress_is_refused(
    base: Path, docker_state: Path, store: Path,
) -> None:
    opened = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                             network="bridge")
    with pytest.raises(at.ServerSideChannelRefused, match="no provider-only egress"):
        _preflight(list(cc.DEFAULT_CLIENT_ARGVS["codex"]), opened, base, store)


# --------------------------------------------- server-side: the census gate

_SHIM = '''import json, os, runpy, sys
pinned = {pinned!r}
plant = sys.argv[1]
args = sys.argv[2:]
assert args[:len(pinned)] == pinned, args
fake = args[len(pinned) + 1:]  # drop the interpreter the fake argv starts with
sys.argv = fake
code = 0
try:
    runpy.run_path(fake[0], run_name="__main__")
except SystemExit as exc:
    code = exc.code or 0
if plant != "none":
    home = fake[fake.index("--home") + 1]
    rel = fake[fake.index("--transcript-relpath") + 1]
    with open(os.path.join(home, rel), "a", encoding="utf-8") as handle:
        handle.write(plant + "\\n")
sys.exit(code)
'''

_LEAK_LINE = {"type": "response_item", "payload": {
    "type": "message", "role": "assistant", "content": [{"type": "output_text",
                                                          "text": "see /home/someone-else/notes.txt"}]}}

_PLANTS = {
    "mcp-github": {"type": "response_item", "payload": {
        "type": "mcp_tool_call", "server": "github@openai-curated-remote", "name": "get_file_contents"}},
    "remote-plugin-call": {"type": "response_item", "payload": {
        "type": "function_call", "name": "mcp__github__get_file_contents", "arguments": "{}"}},
    "web-search": {"type": "response_item", "payload": {"type": "web_search_call", "action": {"query": "skillc"}}},
}


def _shim_argv(tmp_path: Path, plant: str, fake: list[str]) -> list[str]:
    shim = tmp_path / "server_side_shim.py"
    shim.write_text(_SHIM.format(pinned=list(eg.CODEX_SERVER_SIDE_OFF)), encoding="utf-8")
    if plant == "none":
        planted = "none"
    elif plant.endswith("+leak"):
        # The plant AND a line the leak check refuses, so the transcript is
        # never retained: the census must still see the plant (counter-model).
        planted = json.dumps(_PLANTS[plant.removesuffix("+leak")]) + "\n" + json.dumps(_LEAK_LINE)
    else:
        planted = json.dumps(_PLANTS[plant])
    return [sys.executable, str(shim), planted, *eg.CODEX_SERVER_SIDE_OFF, *fake]


def _live_attempt(store: Path, base: Path, docker_state: Path, tmp_path: Path, plant: str) -> dict[str, object]:
    backend = _egress_backend(base, docker_state)
    grading = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                              daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    experiment, attempt_id = _planned(store)
    fake = _fake_argv(fmt="codex-fake", home=_mapped_home(docker_state, attempt_id),
                      transcript_relpath=".codex/sessions/2026/01/01/rollout-egress.jsonl",
                      copy_solution=GRADER_ROOT / "reference")
    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=_shim_argv(tmp_path, plant, fake), prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=10), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"),
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading,
    )
    record["_experiment_root"] = str(experiment.root)
    return record


def test_green_control_a_clean_live_attempt_is_graded_and_its_proxy_log_is_captured(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    record = _live_attempt(store, base, docker_state, tmp_path, "none")
    assert record["disposition"] == "captured"
    assert record["grading_blocked_reason"] is None
    graded = record["graded"]
    assert isinstance(graded, dict) and graded["status"] == "PASS"
    observation = record["observation"]
    assert isinstance(observation, dict)
    egress = observation["egress"]
    assert egress["status"] == "read" and egress["allowlist_digest"] == eg.allowlist_digest()
    assert egress["allowed"] == {"chatgpt.com:443": 1} and egress["denied"] == {}
    manifest = json.loads(next(Path(str(record["_experiment_root"])).glob("manifest-*.json")).read_text())
    [stream] = [o for o in manifest["observations"] if o["stream"] == eg.PROXY_LOG_STREAM]
    assert stream["origin"] == "observed" and stream["digest"] == egress["digest"]


@pytest.mark.parametrize("plant, named", [
    ("mcp-github", "response_item/mcp_tool_call"),
    ("remote-plugin-call", "mcp__github__get_file_contents"),
    ("web-search", "response_item/web_search_call"),
    ("remote-plugin-call+leak", "mcp__github__get_file_contents"),
])
def test_red_control_a_server_side_tool_in_the_transcript_is_not_credited_and_stays_accounted(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, plant: str, named: str,
) -> None:
    record = _live_attempt(store, base, docker_state, tmp_path, plant)
    assert record["disposition"] == "captured"
    reason = record["grading_blocked_reason"]
    assert isinstance(reason, str) and reason.startswith("not credited: server-side tool observed (")
    assert named in reason
    assert record["graded"] is None
    # The attempt stays in every account, with that reason (condition on (1)):
    # a study's primary endpoint reports it NOT_GRADED with the reason, and a
    # pilot report's uncertainty column names it - never a silent drop.
    endpoint = calibration.primary_endpoint(record)
    assert endpoint["status"] == calibration.NOT_GRADED and endpoint["reason"] == reason
    scheduled = matched_pilot.ScheduledAttempt(attempt_id=str(record["attempt_id"]), trial_id="t", arm="a", repeat=1)
    outcome = matched_pilot.AttemptOutcome(scheduled=scheduled, record=record, wall_seconds=1.0)
    assert f"not graded: {reason}" in matched_pilot._uncertainty(outcome)
    assert outcome.to_json()["attempt_id"] == record["attempt_id"]


def test_the_census_reads_call_names_not_only_line_types() -> None:
    """A remote plugin can surface as an ordinary `function_call` whose
    line-type count looks exactly like a local exec call; only its name says
    otherwise."""
    line = json.dumps(_PLANTS["remote-plugin-call"]).encode()
    assert at.server_side_tool_uses(None, {"response_item/function_call": 1}) == []
    assert at.server_side_tool_uses(line, {"response_item/function_call": 1}) == [
        "response_item/function_call:mcp__github__get_file_contents"]
    clean = json.dumps({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec"}}).encode()
    assert at.server_side_tool_uses(clean, {"response_item/custom_tool_call": 1}) == []


def test_a_retention_refused_transcript_is_still_inspected_by_the_census() -> None:
    """The plant's twin without the census: the leak line really does stop
    retention (so the +leak red case above tests the path it claims to)."""
    from skillc import demo
    assert demo.leak_check_text(json.dumps(_LEAK_LINE)), "the planted leak line must trip the leak check"


def test_a_declared_local_mcp_server_is_not_server_side_but_an_undeclared_one_is() -> None:
    """Counter-model review: an MCP server skillc itself configured runs in
    the container; only an undeclared one (a remote plugin) is server-side."""
    lines = b"\n".join(json.dumps(x).encode() for x in (
        {"type": "response_item", "payload": {"type": "mcp_tool_call", "server": "local", "name": "read"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "mcp__local__read_file"}},
    ))
    assert at.server_side_tool_uses(lines, None, frozenset({"local"})) == []
    assert at.server_side_tool_uses(lines, None) == [
        "response_item/function_call:mcp__local__read_file", "response_item/mcp_tool_call"]


def test_red_case_an_attempt_whose_transcript_was_never_inspected_is_not_credited(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No census result is never a clean one."""
    real = at._make_observe_before_teardown

    def without_census(**kwargs: object) -> object:
        hook = real(**kwargs)  # type: ignore[arg-type]

        def dropped(backend: object, handle: object) -> dict[str, object]:
            out = dict(hook(backend, handle))  # type: ignore[arg-type]
            out.pop("server_side_tool_uses")
            return out
        return dropped

    monkeypatch.setattr(at, "_make_observe_before_teardown", without_census)
    record = _live_attempt(store, base, docker_state, tmp_path, "none")
    assert record["grading_blocked_reason"] == "not credited: server-side tool inspection unavailable"


def test_the_proxy_summary_keeps_upstream_failures_apart_from_denials() -> None:
    log = b"\n".join(json.dumps(x).encode() for x in (
        {"event": "start", "digest": "sha256:x"},
        {"target": "chatgpt.com:443", "decision": "upstream-failed: TimeoutError"},
        {"target": "github.com:443", "decision": "denied"},
        {"target": "chatgpt.com:443", "decision": "allowed"},
    ))
    summary = eg.summarize_log(log)
    assert summary["denied"] == {"github.com:443": 1}
    assert summary["upstream_failed"] == {"chatgpt.com:443": 1}
    assert summary["allowed"] == {"chatgpt.com:443": 1}


def test_a_trigger_channel_failure_after_egress_leaves_nothing_behind(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(self: object, name: str, attempt_id: str) -> object:
        raise BackendUnavailable("trigger socket refused (fault injection)")

    monkeypatch.setattr(d.DockerBackend, "_start_trigger_channel", refused)
    with pytest.raises(BackendUnavailable, match="trigger socket refused"):
        _egress_backend(base, docker_state).prepare("a-trigger-fail")
    assert not list((docker_state / "networks").glob("*.json"))
    assert not any(p.name.endswith("-proxy.json") for p in docker_state.glob("*.json"))


def test_a_network_create_that_takes_effect_then_times_out_is_still_removed(base: Path, docker_state: Path) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".hang-network-create").write_text("3")
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
                              daemon_timeout=1.0, egress=True)
    with pytest.raises(BackendUnavailable, match="create internal network"):
        backend.prepare("a-net-hang")
    time.sleep(2.5)  # let the fake finish answering, as a slow daemon would
    assert not list((docker_state / "networks").glob("*.json")), "the network the timed-out create made was left"


def test_teardown_is_not_confirmed_while_the_attempt_network_remains(base: Path, docker_state: Path) -> None:
    backend = _egress_backend(base, docker_state)
    handle = backend.prepare("a-net-stuck")
    (docker_state / ".refuse-network-rm").write_text("")
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is d.Confirmation.NOT_CONFIRMED
    (docker_state / ".refuse-network-rm").unlink()
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is d.Confirmation.CONFIRMED
