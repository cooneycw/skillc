"""#529: flow-check's gate witnessed through its MIRRORED copies - the
skill-bundled copy CPP #1408 makes the skill run, and the CPP checkout copy its
exit-127 fallback names (orchestrator D1). #525 witnessed a bundled gate for
flow-auto only and refused flow-check's; these are #529's reds:

1. a flow-check-shaped call through the bundled copy is witnessed
   (`via=bundled:flow-check`), through the checkout copy as
   `via=checkout:flow-check`; with no run each gate reads not-observed;
2. the real shim forwards both prescribed calls with its `via`, and refuses
   (125, reported and counted) any other argv;
3. with no installed copy, a run that names no `via` is refused;
4. the checkout mirror is proven against the verified closure (it ships no
   skill manifest), and refuses a tampered mirror, an edited sibling and a
   sibling outside the closure;
5. a gate map is witnessed only with ITS shim (a prescribed call is never a
   125 by mismatch);
6. the bare cwd-relative call never reaches a shim: 127 in a target without
   `scripts/`, and the TARGET's own script where it has one (CPP #1542).
The flow-auto 125 parity (#279) is unchanged: `test_flow_auto_gate_shim.py`
and `test_bundled_gate_witness.py` still run it.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc.backend import ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal
from skillc.gate_witness import GateWitness

SHIM = at.FLOW_CHECK_BUNDLED_GATE_SHIM_SOURCE
BUNDLED = ".codex/skills/flow-check/scripts/flow-finish-gate.sh"
CHECKOUT = "Projects/claude-power-pack/scripts/flow-finish-gate.sh"
PLAN = ["--plan", "check", "--evidence", "flow-check"]
SUMMARY = ["--check-summary"]


# ------------------------------------------------------------------ 1: the witness

class _Backend:
    """Runs nothing: records each exec's argv and answers exit 0."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, **kw: Any) -> ExecuteResult:
        self.argvs.append(list(argv))
        return ExecuteResult(reason="exited", exit_code=0, stdout=b"FLOW_FINISH_GATE: ok\n", stderr=b"")

    def resolve_realpath_in_attempt(self, handle: object, path: str) -> str | None:
        return path


def _session() -> at._WitnessSession:
    session = at._WitnessSession("a-1", Limits(timeout=60))
    at._register_mirror_variants(session, [
        {"via": "bundled:flow-check", "path": BUNDLED, "mirror": "/opt/skillc-harness/bundled/flow-check/scripts"},
        {"via": "checkout:flow-check", "path": CHECKOUT, "mirror": "/opt/skillc-harness/checkout/flow-check/scripts"},
    ])
    return session


def _witness(backend: _Backend, variants: Mapping[str, Mapping[str, Sequence[str]]] | None) -> GateWitness:
    harness = "/opt/skillc-harness/flow-finish-gate.sh"
    gates = {gate: ["bash", harness, *args] for gate, args in at.FLOW_CHECK_GATE_ARGS.items()}
    return GateWitness(gates, lambda: "sha256:" + "0" * 64, backend, object(), Limits(timeout=60),  # type: ignore[arg-type]
                       gate_exclusivity=False, exclusivity_basis="test", declared_variants=variants)


def test_each_mirrored_copy_is_a_variant_of_both_flow_check_gates_with_their_own_argv() -> None:
    variants = _session().variants
    assert variants == {
        "flow-check-plan": {
            "bundled:flow-check": ["bash", "/opt/skillc-harness/bundled/flow-check/scripts/flow-finish-gate.sh", *PLAN],
            "checkout:flow-check": ["bash", "/opt/skillc-harness/checkout/flow-check/scripts/flow-finish-gate.sh",
                                    *PLAN]},
        "flow-check-summary": {
            "bundled:flow-check": ["bash", "/opt/skillc-harness/bundled/flow-check/scripts/flow-finish-gate.sh",
                                   *SUMMARY],
            "checkout:flow-check": ["bash", "/opt/skillc-harness/checkout/flow-check/scripts/flow-finish-gate.sh",
                                    *SUMMARY]},
    }


def test_the_flow_auto_bare_map_registers_exactly_as_before() -> None:
    session = at._WitnessSession("a-1", Limits(timeout=60), gate_args={"flow-auto-finish": ()})
    at._register_mirror_variants(session, [{"via": "bundled:flow-auto", "path": "x/flow-auto/scripts/g.sh",
                                            "mirror": "/opt/m"}])
    assert session.variants == {"flow-auto-finish": {"bundled:flow-auto": ["bash", "/opt/m/g.sh"]}}


def test_red_1_a_bundled_plan_call_and_a_checkout_summary_call_are_witnessed() -> None:
    backend = _Backend()
    w = _witness(backend, _session().variants)
    w.decide({"op": "run_gate", "gate": "flow-check-plan", "via": "bundled:flow-check"})
    w.decide({"op": "run_gate", "gate": "flow-check-summary", "via": "checkout:flow-check"})
    record = json.loads(w.finalize("a-1").to_json_bytes())["gates"]
    [plan] = record["flow-check-plan"]["runs"]
    [summary] = record["flow-check-summary"]["runs"]
    assert (plan["via"], summary["via"]) == ("bundled:flow-check", "checkout:flow-check")
    assert backend.argvs == [  # the MIRRORS ran, each with its gate's own argv
        ["bash", "/opt/skillc-harness/bundled/flow-check/scripts/flow-finish-gate.sh", *PLAN],
        ["bash", "/opt/skillc-harness/checkout/flow-check/scripts/flow-finish-gate.sh", *SUMMARY]]


def test_red_1_without_the_variants_a_bundled_call_is_refused_and_reads_not_observed() -> None:
    """#525's deferral for flow-check, reproduced: a witness that does not
    declare the copy records nothing for it."""
    backend = _Backend()
    w = _witness(backend, None)
    with pytest.raises(ChannelRefusal, match="not a declared variant"):
        w.decide({"op": "run_gate", "gate": "flow-check-plan", "via": "bundled:flow-check"})
    record = json.loads(w.finalize("a-1").to_json_bytes())["gates"]
    assert record["flow-check-plan"]["runs"] == [] and backend.argvs == []


def test_red_1_no_run_reads_not_observed_for_both_gates() -> None:
    record = json.loads(_witness(_Backend(), _session().variants).finalize("a-1").to_json_bytes())["gates"]
    assert {g: (record[g]["runs"], record[g]["coverage"]) for g in at.FLOW_CHECK_GATE_ARGS} == {
        g: ([], "not-observed") for g in at.FLOW_CHECK_GATE_ARGS}


# ------------------------------------------------------------------ 3: no installed copy

def test_red_3_with_no_installed_copy_a_run_without_via_is_refused() -> None:
    backend = _Backend()
    session = _session()
    session.witness = _witness(backend, session.variants)
    session.ready = True
    session.require_via = True
    with pytest.raises(ChannelRefusal, match="names its via"):
        session.decide({"op": "run_gate", "gate": "flow-check-plan"})
    assert backend.argvs == []  # never run against the absent harness path
    session.decide({"op": "run_gate", "gate": "flow-check-plan", "via": "bundled:flow-check"})
    assert len(backend.argvs) == 1


# ------------------------------------------------------------------ 2: the real shim

class _Controller:
    def __init__(self, path: Path, reply: dict[str, Any]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply = reply
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(2)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                self.requests.append(json.loads(data))
                conn.sendall(json.dumps(self.reply).encode() + b"\n")


@pytest.fixture
def controller(tmp_path: Path) -> Iterator[tuple[_Controller, Path]]:
    sock = tmp_path / "trigger.sock"
    ctl = _Controller(sock, {"ok": True, "result": {"exit_code": 1, "stdout": "FLOW_FINISH_GATE: fail\n",
                                                    "stderr": "lint failed\n"}})
    yield ctl, sock
    ctl.server.close()


def _placed(tmp_path: Path, via: str) -> Path:
    """The shim exactly as the controller places it over a copy."""
    path = tmp_path / f"shim-{via.replace(':', '-')}.py"
    path.write_bytes(at.bundled_gate_shim(SHIM.read_bytes(), via))
    return path


def _run(shim: Path, args: list[str], sock: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(shim), *args], env={"SKILLC_TRIGGER_SOCKET": str(sock)},
                          cwd=cwd, capture_output=True, text=True, timeout=30, check=False)


@pytest.mark.parametrize("via", ["bundled:flow-check", "checkout:flow-check"])
@pytest.mark.parametrize("args,gate", [(PLAN, "flow-check-plan"), (SUMMARY, "flow-check-summary")])
def test_red_2_both_prescribed_calls_forward_the_real_result_with_their_via(
        controller: tuple[_Controller, Path], tmp_path: Path, via: str, args: list[str], gate: str) -> None:
    ctl, sock = controller
    proc = _run(_placed(tmp_path, via), args, sock, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (1, "FLOW_FINISH_GATE: fail\n", "lint failed\n")
    assert ctl.requests == [{"op": "run_gate", "gate": gate, "cwd": str(tmp_path), "via": via}]


@pytest.mark.parametrize("args", [[], ["--plan", "check"], ["--plan", "finish"], ["--check-summary", "-v"]])
def test_red_2_any_other_argv_is_125_and_reported(controller: tuple[_Controller, Path], tmp_path: Path,
                                                   args: list[str]) -> None:
    """Including the documented pre-#1366 retry without `--evidence`: never
    run, and COUNTED (#279) with the copy's via."""
    ctl, sock = controller
    proc = _run(_placed(tmp_path, "bundled:flow-check"), args, sock, tmp_path)
    assert proc.returncode == 125 and proc.stdout == ""
    assert ctl.requests == [{"op": "gate_refused", "argv": args, "cwd": str(tmp_path), "via": "bundled:flow-check"}]


def test_an_unreachable_channel_is_125(tmp_path: Path) -> None:
    proc = _run(_placed(tmp_path, "bundled:flow-check"), PLAN, tmp_path / "no-such.sock", tmp_path)
    assert proc.returncode == 125 and "channel error" in proc.stderr


def test_the_shim_map_is_the_installed_flow_check_shims_map() -> None:
    """One flow-check contract: the mirrored-copy shim witnesses exactly what
    the unchanged installed-path shim (`docker/trial/`, #332) does."""
    def declared(path: Path) -> object:
        source = path.read_text(encoding="utf-8")
        start = source.index("_DECLARED_INVOCATIONS")
        return source[start:source.index("}", start) + 1].split("=", 1)[1]
    assert declared(SHIM) == declared(at._FLOW_CHECK_GATE_SHIM_SOURCE)
    assert {tuple(a): g for g, a in at.FLOW_CHECK_GATE_ARGS.items()} == {tuple(PLAN): "flow-check-plan",
                                                                       tuple(SUMMARY): "flow-check-summary"}


# ------------------------------------------------------------------ 4: the checkout mirror

REAL_GATE = b"#!/usr/bin/env bash\n. \"$(dirname \"${BASH_SOURCE[0]}\")/gate-lib.sh\"\n"
LIB = b"# the CHECKOUT gate-lib\n"


def _home() -> dict[str, bytes]:
    return {f"Projects/claude-power-pack/scripts/{n}": d
            for n, d in {"flow-finish-gate.sh": REAL_GATE, "gate-lib.sh": LIB, "counter-model-receipt.py": b"# r\n"}.items()}


def _verified(home: Mapping[str, bytes]) -> dict[str, str]:
    return {k: "sha256:" + hashlib.sha256(v).hexdigest() for k, v in home.items()}


class _OverlayBackend:
    """A container as files. `sha256sum -c` is evaluated for real, with the
    manifest at an absolute path or inside the checked directory."""

    def __init__(self, home: Mapping[str, bytes], corrupt_mirror: bool = False) -> None:
        self.files = {f"/home/candidate/{k}": v for k, v in home.items()}
        self.corrupt_mirror = corrupt_mirror

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes, mode: int = 0o755,
                                         timeout: float | None = None) -> bool:
        tamper = self.corrupt_mirror and path.endswith("/gate-lib.sh")
        self.files[path] = content + (b"tampered" if tamper else b"")
        return True

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        directory, manifest = argv[-2], argv[-1]
        listing = self.files[manifest if manifest.startswith("/") else f"{directory}/{manifest}"]
        out = [f"{n}: {'OK' if hashlib.sha256(self.files.get(f'{directory}/{n}', b'')).hexdigest() == h else 'FAILED'}"
               for h, n in (line.split("  ", 1) for line in listing.decode().splitlines())]
        if "--quiet" in argv[2]:
            return None if any(line.endswith("FAILED") for line in out) else b""
        return "\n".join(out).encode() + b"\n"


def _overlay(monkeypatch: pytest.MonkeyPatch, backend: _OverlayBackend, home: Mapping[str, bytes],
             verified: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    def fake_overlay(b: Any, handle: object, *, subject_root: str, harness_root: str, subject_path: str,
                     harness_path: str, expected_real_digest: str, expected_shim_digest: str,
                     shim_content: bytes) -> None:
        real = b.files[f"{subject_root}/{subject_path}"]
        assert hashlib.sha256(real).hexdigest() == expected_real_digest
        b.files[f"{harness_root}/{harness_path}"] = real
        b.files[f"{subject_root}/{subject_path}"] = shim_content
    monkeypatch.setattr(at.gate_overlay, "apply_flow_check_gate_overlay", fake_overlay)
    return at._overlay_bundled_gates(backend, object(), (), verified or _verified(home), home,  # type: ignore[arg-type]
                                     None, SHIM.read_bytes(), None, checkout={CHECKOUT: "flow-check"})


def test_red_4_the_checkout_mirror_is_proven_against_the_verified_closure(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    backend = _OverlayBackend(home)
    [deviation] = _overlay(monkeypatch, backend, home)
    mirror = "/opt/skillc-harness/checkout/flow-check/scripts"
    assert backend.files[f"{mirror}/gate-lib.sh"] == LIB and backend.files[f"{mirror}/flow-finish-gate.sh"] == REAL_GATE
    # the proof sits OUTSIDE the mirror, which holds exactly the shipped files
    proof = backend.files[f"{mirror}.sha256"].decode()
    assert proof == "".join(f"{hashlib.sha256(d).hexdigest()}  {k.rsplit('/', 1)[1]}\n"
                            for k, d in sorted(home.items(), key=lambda kv: kv[0].rsplit('/', 1)[1]))
    assert deviation["via"] == "checkout:flow-check" and deviation["path"] == CHECKOUT
    assert deviation["mirror"] == mirror and deviation["mirror_verified"] is True
    assert deviation["in_place_checksum_failures"] == ["flow-finish-gate.sh"]
    assert "verified closure digests" in str(deviation["proven_against"])


def test_red_4_a_tampered_checkout_mirror_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    with pytest.raises(at.HomeFileVerificationRefused, match="not byte-identical"):
        _overlay(monkeypatch, _OverlayBackend(home, corrupt_mirror=True), home)


def test_red_4_an_edited_checkout_sibling_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    backend = _OverlayBackend(home)
    backend.files["/home/candidate/Projects/claude-power-pack/scripts/gate-lib.sh"] = b"edited after delivery\n"
    with pytest.raises(at.HomeFileVerificationRefused, match="not on exactly the declared shim"):
        _overlay(monkeypatch, backend, home)


def test_red_4_a_checkout_sibling_outside_the_closure_is_never_mirrored(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    verified = _verified(home)
    verified["Projects/claude-power-pack/scripts/gate-lib.sh"] = "sha256:" + "f" * 64
    with pytest.raises(at.HomeFileVerificationRefused, match="not a verified closure file"):
        _overlay(monkeypatch, _OverlayBackend(home), home, verified)


def test_a_bundled_copy_still_needs_its_skill_manifest() -> None:
    """#525's proof is unchanged for a SKILL copy: no manifest, no mirror."""
    with pytest.raises(at.HomeFileVerificationRefused, match="ships no SHA256SUMS"):
        at._overlay_bundled_gates(object(), object(), (BUNDLED,), {BUNDLED: "sha256:" + "0" * 64},  # type: ignore[arg-type]
                                  {BUNDLED: b"x"}, None, SHIM.read_bytes(), "SHA256SUMS")


# ------------------------------------------------------------------ 5: a map only with its shim

FLOW_CHECK_MAP = {g: tuple(a) for g, a in at.FLOW_CHECK_GATE_ARGS.items()}
FLOW_AUTO_SHIM = at._FLOW_AUTO_GATE_SHIM_SOURCE


def _route(shim: Path, gates: Mapping[str, Sequence[str]] | None, *, fixture: object | None = object(),
           bundled: tuple[str, ...] = (BUNDLED,), checkout: Mapping[str, str] | None = None) -> None:
    at._require_bundled_route(bundled, BUNDLED, fixture, shim, gates, "SHA256SUMS",  # type: ignore[arg-type]
                              checkout if checkout is not None else {CHECKOUT: "flow-check"})


def test_red_5_the_flow_check_map_is_witnessed_with_its_own_shim() -> None:
    _route(SHIM, FLOW_CHECK_MAP)
    _route(SHIM, FLOW_CHECK_MAP, bundled=())  # a checkout copy alone needs no skill manifest


def test_red_5_a_mismatched_shim_is_refused() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="not by the shim it supplies"):
        _route(FLOW_AUTO_SHIM, FLOW_CHECK_MAP)  # every flow-check call would be a 125
    with pytest.raises(at.HomeFileVerificationRefused, match="not by the shim it supplies"):
        _route(SHIM, {"flow-auto-finish": ()})


def test_red_5_an_undeclared_map_is_refused() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="declares neither"):
        _route(SHIM, {"flow-check-plan": tuple(PLAN)})  # one of the two calls dropped


def test_red_5_still_only_on_the_fixture_live_route() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="only on the fixture-live route"):
        _route(SHIM, FLOW_CHECK_MAP, fixture=None)


def test_red_5_a_checkout_copy_alone_still_triggers_the_route_check() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="only on the fixture-live route"):
        _route(SHIM, FLOW_CHECK_MAP, fixture=None, bundled=())


# ------------------------------------------------------------------ 6: the bare call (CPP #1542)

def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _bare(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", "scripts/flow-finish-gate.sh --check-summary"], cwd=cwd,
                          capture_output=True, text=True, timeout=30, check=False)


def test_red_6_the_bare_call_from_a_target_without_scripts_is_127(tmp_path: Path) -> None:
    """The prescribed call resolves against the TARGET, never the skill: no
    shim is reached, so the witness records nothing (not-observed, red 1)."""
    assert _bare(_git_repo(tmp_path / "target")).returncode == 127


def test_red_6_where_the_target_has_its_own_script_the_bare_call_runs_that(tmp_path: Path) -> None:
    """CPP #1542's hazard, and why a bare call is never read as the gate."""
    repo = _git_repo(tmp_path / "target")
    (repo / "scripts").mkdir()
    own = repo / "scripts" / "flow-finish-gate.sh"
    own.write_text("#!/usr/bin/env bash\necho THE-TARGETS-OWN-SCRIPT\n")
    own.chmod(0o755)
    proc = _bare(repo)
    assert (proc.returncode, proc.stdout) == (0, "THE-TARGETS-OWN-SCRIPT\n")


# ------------------------------------------------------------------ counter-model review reds

@pytest.mark.parametrize("skill", ["../../../../home/candidate/redirect", "..", "a/b"])
def test_review_the_controller_refuses_an_unsafe_mirror_name(monkeypatch: pytest.MonkeyPatch, skill: str) -> None:
    """HIGH, defence in depth: whatever a profile says, no privileged write
    lands outside the harness root."""
    home = _home()
    backend = _OverlayBackend(home)
    with pytest.raises(at.HomeFileVerificationRefused, match="unsafe"):
        at._overlay_bundled_gates(backend, object(), (), _verified(home), home,  # type: ignore[arg-type]
                                  None, SHIM.read_bytes(), None, checkout={CHECKOUT: skill})
    assert not [k for k in backend.files if not k.startswith("/home/candidate/Projects/")]  # nothing written


def test_review_two_copies_on_one_route_are_refused_before_any_write() -> None:
    """MEDIUM: a route and a mirror name exactly one copy."""
    home = {**_home(), "Projects/other/scripts/flow-finish-gate.sh": REAL_GATE}
    backend = _OverlayBackend(home)
    with pytest.raises(at.HomeFileVerificationRefused, match="one route"):
        at._overlay_bundled_gates(backend, object(), (), _verified(home), home,  # type: ignore[arg-type]
                                  None, SHIM.read_bytes(), None,
                                  checkout={CHECKOUT: "flow-check", "Projects/other/scripts/flow-finish-gate.sh":
                                            "flow-check"})
    assert set(backend.files) == {f"/home/candidate/{k}" for k in home}
