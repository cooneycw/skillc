"""#525: the gate witness sees a skill-BUNDLED gate copy.

From claude-power-pack #1408 on, a generated Codex skill runs its bundled
`scripts/flow-finish-gate.sh`, not the installed `~/.claude/scripts` copy the
harness witnessed, so the gate ran unwitnessed. These are the plan's reds:

1. a run through the bundled path is witnessed (`via`), and without the
   variant it reads not-observed - #525 reproduced;
2. the installed path is still witnessed, byte-identically;
3. no run at all reads not-observed;
4. the controller's run uses the mirror, so the bundled gate's own siblings;
5. refusals (a mirror that fails the skill's SHA256SUMS, a non-closure
   sibling, no SHA256SUMS, an in-place mismatch beyond the shim) and the
   positive half: the mirror verifies;
6. the deviation record names exactly the shimmed path;
plus the profile-side checks (an unwitnessed bundled gate is refused; the
checksum-consumer preflight) and the flow-check deferral. Red 7 (live) is
`--rehearse actor-bundled`, recorded on #525.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import profile as p
from skillc.backend import ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal
from skillc.gate_witness import GateWitness

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
SHIM = ROOT / "docker" / "fixture-service" / "flow-auto-gate-shim.py"

#: claude-power-pack `ca3030d` (MIT, https://github.com/cooneycw/claude-power-pack,
#: codex/skills/flow-auto/reference.md, Step 6 item 2): the shape #1408 gives
#: every generated Codex skill - the bundled gate, invoked bare.
CA3030D_STEP6 = """\
   every merge re-gate. Invoke it BARE (#581 discipline):

   ```bash
   scripts/flow-finish-gate.sh
   ```

   (Exit 127 - helper not installed: fall back to
"""


# ------------------------------------------------------------------ witness (reds 1-3)

class _Backend:
    """Runs nothing: records each exec's argv and answers exit 0."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, **kw: Any) -> ExecuteResult:
        self.argvs.append(list(argv))
        return ExecuteResult(reason="exited", exit_code=0, stdout=b"FLOW_FINISH_GATE: ok\n", stderr=b"")

    def resolve_realpath_in_attempt(self, handle: object, path: str) -> str | None:
        return path


def _witness(backend: _Backend, variants: Mapping[str, Mapping[str, Sequence[str]]] | None) -> GateWitness:
    return GateWitness({"flow-auto-finish": ["bash", "/opt/skillc-harness/flow-finish-gate.sh"]},
                       lambda: "sha256:" + "0" * 64, backend, object(), Limits(timeout=60),  # type: ignore[arg-type]
                       gate_exclusivity=False, exclusivity_basis="test", declared_variants=variants)


_MIRROR = ["bash", "/opt/skillc-harness/bundled/flow-auto/scripts/flow-finish-gate.sh"]


def test_red_1_a_bundled_run_is_witnessed_through_its_variant() -> None:
    backend = _Backend()
    w = _witness(backend, {"flow-auto-finish": {"bundled:flow-auto": _MIRROR}})
    w.decide({"op": "run_gate", "gate": "flow-auto-finish", "via": "bundled:flow-auto"})
    record = json.loads(w.finalize("a-1").to_json_bytes())
    [run] = record["gates"]["flow-auto-finish"]["runs"]
    assert run["via"] == "bundled:flow-auto" and run["exit_code"] == 0
    assert backend.argvs == [_MIRROR]  # the MIRROR ran, never the installed harness copy


def test_red_1_without_the_variant_the_bundled_run_is_refused_and_reads_not_observed() -> None:
    """#525 itself: a witness that does not declare the bundled copy records
    nothing for it - the gate is not-observed, never a pass."""
    backend = _Backend()
    w = _witness(backend, None)
    with pytest.raises(ChannelRefusal, match="not a declared variant"):
        w.decide({"op": "run_gate", "gate": "flow-auto-finish", "via": "bundled:flow-auto"})
    record = json.loads(w.finalize("a-1").to_json_bytes())
    assert record["gates"]["flow-auto-finish"]["runs"] == [] and backend.argvs == []


def test_red_2_the_installed_path_is_witnessed_byte_identically() -> None:
    backend = _Backend()
    w = _witness(backend, {"flow-auto-finish": {"bundled:flow-auto": _MIRROR}})
    w.decide({"op": "run_gate", "gate": "flow-auto-finish"})
    [run] = json.loads(w.finalize("a-1").to_json_bytes())["gates"]["flow-auto-finish"]["runs"]
    assert "via" not in run  # a record without a variant is unchanged
    assert backend.argvs == [["bash", "/opt/skillc-harness/flow-finish-gate.sh"]]


def test_red_3_no_run_reads_not_observed() -> None:
    w = _witness(_Backend(), {"flow-auto-finish": {"bundled:flow-auto": _MIRROR}})
    gate = json.loads(w.finalize("a-1").to_json_bytes())["gates"]["flow-auto-finish"]
    assert gate["runs"] == [] and gate["coverage"] == "not-observed"


def test_a_variant_of_an_undeclared_gate_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="undeclared gate"):
        _witness(_Backend(), {"other": {"bundled:x": _MIRROR}})


# ------------------------------------------------------------------ the shim

def test_the_installed_shim_request_is_unchanged_and_the_bundled_one_names_its_via() -> None:
    source = SHIM.read_bytes()
    assert source.count(at._SHIM_VIA_LINE) == 1
    bundled = at.bundled_gate_shim(source, "bundled:flow-auto")
    assert b"_VIA: str | None = 'bundled:flow-auto'\n" in bundled and bundled.count(at._SHIM_VIA_LINE) == 0
    assert bundled.replace(b"'bundled:flow-auto'", b"None") == source  # one line differs


def test_the_flow_check_shim_cannot_witness_a_bundled_gate() -> None:
    """Deferred (#525): the flow-check shim has no `_VIA` line, so a bundled gate
    through it is refused, never silently witnessed as the installed one."""
    with pytest.raises(at.HomeFileVerificationRefused, match="deferred"):
        at.bundled_gate_shim(at._FLOW_CHECK_GATE_SHIM_SOURCE.read_bytes(), "bundled:flow-check")


# ------------------------------------------------------------------ overlay (reds 4-6)

GATE = ".codex/skills/flow-auto/scripts/flow-finish-gate.sh"
REAL_GATE = b"#!/usr/bin/env bash\n. \"$(dirname \"${BASH_SOURCE[0]}\")/gate-lib.sh\"\n"
LIB = b"# the BUNDLED gate-lib\n"


def _sums(files: Mapping[str, bytes]) -> bytes:
    return b"".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n".encode() for n, d in sorted(files.items()))


def _home(lib: bytes = LIB) -> dict[str, bytes]:
    scripts = {"flow-finish-gate.sh": REAL_GATE, "gate-lib.sh": lib}
    return {f".codex/skills/flow-auto/scripts/{n}": d for n, d in {**scripts, "SHA256SUMS": _sums(scripts)}.items()}


def _verified(home: Mapping[str, bytes]) -> dict[str, str]:
    return {k: "sha256:" + hashlib.sha256(v).hexdigest() for k, v in home.items()}


class _OverlayBackend:
    """A container as files: the in-place skill and the root-owned harness.
    `sha256sum -c` is evaluated for real over whichever directory is asked."""

    def __init__(self, home: Mapping[str, bytes], corrupt_mirror: bool = False) -> None:
        self.files = {f"/home/candidate/{k}": v for k, v in home.items()}
        self.root_writes: list[str] = []
        self.corrupt_mirror = corrupt_mirror

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes, mode: int = 0o755,
                                         timeout: float | None = None) -> bool:
        self.root_writes.append(path)
        self.files[path] = content + (b"tampered" if self.corrupt_mirror and path.endswith("gate-lib.sh") else b"")
        return True

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        directory, manifest = argv[-2], argv[-1]
        listed = [line.split("  ", 1) for line in self.files[f"{directory}/{manifest}"].decode().splitlines()]
        out = [f"{n}: {'OK' if hashlib.sha256(self.files.get(f'{directory}/{n}', b'')).hexdigest() == h else 'FAILED'}"
               for h, n in listed]
        failed = any(line.endswith("FAILED") for line in out)
        if "--quiet" in argv[2]:
            return None if failed else b""
        return "\n".join(out).encode() + b"\n"


def _overlay(monkeypatch: pytest.MonkeyPatch, backend: _OverlayBackend, home: Mapping[str, bytes],
             verified: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    def fake_overlay(b: Any, handle: object, *, subject_root: str, harness_root: str, subject_path: str,
                     harness_path: str, expected_real_digest: str, expected_shim_digest: str,
                     shim_content: bytes) -> None:
        real = b.files[f"{subject_root}/{subject_path}"]
        assert hashlib.sha256(real).hexdigest() == expected_real_digest
        b.files[f"{harness_root}/{harness_path}"] = real  # the real gate moves into the mirror
        b.files[f"{subject_root}/{subject_path}"] = shim_content
    monkeypatch.setattr(at.gate_overlay, "apply_flow_check_gate_overlay", fake_overlay)
    return at._overlay_bundled_gates(backend, object(), [GATE], verified or _verified(home), home,  # type: ignore[arg-type]
                                     None, SHIM.read_bytes(), "SHA256SUMS")


def test_red_4_5_6_the_mirror_is_the_shipped_skill_and_the_deviation_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    backend = _OverlayBackend(home)
    [deviation] = _overlay(monkeypatch, backend, home)
    mirror = "/opt/skillc-harness/bundled/flow-auto/scripts"
    # 4: the controller's copy keeps the BUNDLED siblings beside it.
    assert backend.files[f"{mirror}/gate-lib.sh"] == LIB and backend.files[f"{mirror}/flow-finish-gate.sh"] == REAL_GATE
    # 6: exactly the shimmed path, and the in-place skill fails only there.
    assert deviation["path"] == GATE and deviation["via"] == "bundled:flow-auto" and deviation["mirror"] == mirror
    assert deviation["mirror_verified"] is True and deviation["in_place_checksum_failures"] == ["flow-finish-gate.sh"]
    assert deviation["shim_digest"] == "sha256:" + hashlib.sha256(
        at.bundled_gate_shim(SHIM.read_bytes(), "bundled:flow-auto")).hexdigest()


def test_red_5_a_mirror_that_fails_the_skills_own_sums_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    with pytest.raises(at.HomeFileVerificationRefused, match="not byte-identical to the shipped skill"):
        _overlay(monkeypatch, _OverlayBackend(home, corrupt_mirror=True), home)


def test_red_5_a_sibling_outside_the_verified_closure_is_never_mirrored(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    verified = _verified(home)
    verified[".codex/skills/flow-auto/scripts/gate-lib.sh"] = "sha256:" + "f" * 64
    with pytest.raises(at.HomeFileVerificationRefused, match="not a verified closure file"):
        _overlay(monkeypatch, _OverlayBackend(home), home, verified)


def test_red_5_a_skill_without_sums_cannot_be_proven_and_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    home = {k: v for k, v in _home().items() if not k.endswith("SHA256SUMS")}
    with pytest.raises(at.HomeFileVerificationRefused, match="ships no SHA256SUMS"):
        _overlay(monkeypatch, _OverlayBackend(home), home)


def test_red_5_an_in_place_mismatch_beyond_the_shim_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    home = _home()
    backend = _OverlayBackend(home)
    backend.files["/home/candidate/.codex/skills/flow-auto/scripts/gate-lib.sh"] = b"edited after delivery\n"
    with pytest.raises(at.HomeFileVerificationRefused, match="not on exactly the declared shim"):
        _overlay(monkeypatch, backend, home)


def test_a_bundled_path_outside_a_skills_scripts_dir_is_refused() -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="no <skill>/<dir>/<gate> shape"):
        at._bundled_via("scripts/flow-finish-gate.sh")
    assert at._bundled_via(GATE) == "bundled:flow-auto"


# ------------------------------------------------------------------ profile side

def test_a_bare_bundled_call_is_detected_and_prose_or_the_installed_path_is_not() -> None:
    gate = "scripts/flow-finish-gate.sh"  # relative to the skill directory
    assert p._bare_bundled_gate_calls(CA3030D_STEP6, gate)
    assert p._bare_bundled_gate_calls("```bash\nbash scripts/flow-finish-gate.sh --plan check\n```\n", gate)
    assert not p._bare_bundled_gate_calls("```bash\n~/.claude/scripts/flow-finish-gate.sh\n```\n", gate)
    assert not p._bare_bundled_gate_calls("the logic lives in `scripts/flow-finish-gate.sh`.\n", gate)
    assert not p._bare_bundled_gate_calls("scripts/flow-finish-gate.sh\n", gate)  # outside a fence


def test_the_86641e8_skill_does_not_invoke_its_bundled_gate() -> None:
    """The negative half on a real pin: 86641e8's flow-auto reference invokes
    the INSTALLED gate, so its profiles need no bundled witness."""
    text = (SNAPSHOT / "codex" / "skills" / "flow-auto" / "reference.md").read_text(encoding="utf-8")
    assert not p._bare_bundled_gate_calls(text, "scripts/flow-finish-gate.sh")


class _Tree:
    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = dict(files)

    def read(self, path: str) -> bytes:
        return self._files[path]


def _installed(files: Mapping[str, bytes]) -> dict[str, dict[str, object]]:
    return {dest: {"origin": "pinned", "source": dest} for dest in files}


def _gate_profile(bundled: tuple[str, ...] = (), consumers: Mapping[str, str] | None = None) -> p.Profile:
    prof = p.Profile.__new__(p.Profile)
    object.__setattr__(prof, "gate_entrypoint", ".claude/scripts/flow-finish-gate.sh")
    object.__setattr__(prof, "bundled_gate_entrypoints", bundled)
    object.__setattr__(prof, "checksum_consumers", dict(consumers or {}))
    object.__setattr__(prof, "bundled_checksum_manifest", "SHA256SUMS" if bundled else None)
    return prof


def _check(prof: p.Profile, files: Mapping[str, bytes]) -> None:
    walk = type("W", (), {"problems": None})()
    p._check_bundled_gates(walk, prof, _Tree(files), _installed(files))  # type: ignore[arg-type]


_SKILL = {".codex/skills/flow-auto/reference.md": CA3030D_STEP6.encode(),
          GATE: b"#!/usr/bin/env bash\n", ".claude/scripts/flow-finish-gate.sh": b"#!/usr/bin/env bash\n"}


def test_red_an_unwitnessed_bundled_gate_refuses_the_profile() -> None:
    """The check the orchestrator required: a profile at a pin whose skill runs
    its bundled gate, without the bundled witness, is refused (this is what
    keeps a flow-check re-pin past #1408 gated on #525's follow-up)."""
    with pytest.raises(p.Refused, match="does not witness"):
        _check(_gate_profile(), _SKILL)
    _check(_gate_profile(bundled=(GATE,)), _SKILL)  # declared: passes (no checksum signature here)


def test_red_an_undeclared_checksum_consumer_refuses_and_a_declared_one_passes() -> None:
    files = {**_SKILL, ".codex/skills/flow-auto/scripts/tool.py": b"subprocess.run(['sha256sum', '-c', ...])\n"}
    files[".codex/skills/flow-auto/scripts/tool.py"] = b"run('sha256sum -c SHA256SUMS')\n"
    with pytest.raises(p.Refused, match="not a declared checksum_consumer"):
        _check(_gate_profile(bundled=(GATE,)), files)
    _check(_gate_profile(bundled=(GATE,), consumers={".codex/skills/flow-auto/scripts/tool.py": "measured"}), files)


def test_the_preflight_runs_only_with_a_bundled_gate_declared() -> None:
    """Without a shim there is no deviation, so nothing to re-measure."""
    files = {".claude/scripts/flow-finish-gate.sh": b"x\n", ".claude/scripts/t.py": b"sha256sum -c SHA256SUMS\n"}
    _check(_gate_profile(), files)


def test_the_committed_rehearsal_profile_validates_against_the_snapshot() -> None:
    prof = p.Profile.load(ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8-bundled" / "profile.json")
    inv = p.validate(prof, p.DirTree(SNAPSHOT))
    assert inv["bundled_gate_entrypoints"] == [GATE]
    assert {c["path"] for c in inv["checksum_consumers"]} == {
        ".claude/scripts/flow-plan-record.py", ".codex/skills/flow-auto/reference.md",
        ".codex/skills/flow-auto/scripts/codex-skill-sync.py", ".codex/skills/flow-auto/scripts/flow-plan-record.py",
        # delivered neighbours outside the closure (counter-model review): measured, declared
        ".codex/skills/flow-doctor/scripts/flow-helpers-install.sh",
        ".codex/skills/flow-repair/scripts/flow-helpers-install.sh", ".codex/skills/flow-finish/scripts/codex-skill-sync.py"}


# ------------------------------------------------------------------ counter-model review (#525)

def test_review_the_treatment_check_sees_a_delivered_neighbour_the_profile_closure_does_not() -> None:
    """Finding 1: a subject selecting more skills installs them all, so the
    bundled checks run over the WHOLE delivered home - a neighbour invoking its
    own bundled gate, or verifying checksums undeclared, is refused there."""
    home = {**_SKILL, GATE: b"#!/usr/bin/env bash\n",
            ".codex/skills/flow-check/reference.md": CA3030D_STEP6.encode(),
            ".codex/skills/flow-check/scripts/flow-finish-gate.sh": b"#!/usr/bin/env bash\n"}
    problems = p.bundled_gate_problems(home, ".claude/scripts/flow-finish-gate.sh", (GATE,), {},
                                       manifest_name="SHA256SUMS", require_consumers_installed=True)
    assert [c for c, _m, _p in problems] == ["bundled-gate-unwitnessed"]
    assert problems[0][2] == ".codex/skills/flow-check/scripts/flow-finish-gate.sh"
    neighbour = {**_SKILL, ".codex/skills/flow-doctor/scripts/install.sh": b"sha256sum -c SHA256SUMS\n"}
    assert [c for c, _m, _p in p.bundled_gate_problems(neighbour, ".claude/scripts/flow-finish-gate.sh", (GATE,), {},
                                                        manifest_name="SHA256SUMS", require_consumers_installed=True)] == [
        "checksum-consumer-undeclared"]


def test_review_a_stale_consumer_declaration_is_refused_where_the_population_exists() -> None:
    problems = p.bundled_gate_problems(_SKILL, ".claude/scripts/flow-finish-gate.sh", (GATE,),
                                       {".codex/skills/gone/scripts/x.sh": "measured"}, manifest_name="SHA256SUMS",
                                       require_consumers_installed=True)
    assert [c for c, _m, _p in problems] == ["checksum-consumer-not-installed"]


def test_review_a_synthetic_checksum_consumer_is_scanned_not_skipped() -> None:
    """Finding 2: a profile-authored (synthetic) file is installed bytes too."""
    files = dict(_SKILL)
    installed = _installed(files)
    installed[".claude/scripts/verify.sh"] = {"origin": "synthetic", "source": None,
                                              "content": "sha256sum -c SHA256SUMS\n"}
    walk = type("W", (), {"problems": None})()
    with pytest.raises(p.Refused, match="not a declared checksum_consumer"):
        p._check_bundled_gates(walk, _gate_profile(bundled=(GATE,)), _Tree(files), installed)  # type: ignore[arg-type]


def test_review_a_bundled_gate_off_the_fixture_live_route_is_refused() -> None:
    """Finding 3: only the fixture-live report declares the deviation, so a
    calibration or discrimination attempt with a bundled gate is refused."""
    gates = {"flow-auto-finish": ()}
    with pytest.raises(at.HomeFileVerificationRefused, match="only on the fixture-live route"):
        at._require_bundled_route((GATE,), ".claude/scripts/flow-finish-gate.sh", None, SHIM, gates, "SHA256SUMS")
    at._require_bundled_route((GATE,), ".claude/scripts/flow-finish-gate.sh", object(), SHIM, gates,  # type: ignore[arg-type]
                              "SHA256SUMS")
    with pytest.raises(at.HomeFileVerificationRefused, match="deferred"):
        at._require_bundled_route((GATE,), ".claude/scripts/flow-finish-gate.sh", object(),  # type: ignore[arg-type]
                                  at._FLOW_CHECK_GATE_SHIM_SOURCE, gates, "SHA256SUMS")


def test_a_bundled_gate_without_a_checksum_manifest_is_refused() -> None:
    """The mirror is proven against the subject's own manifest; none, no proof."""
    with pytest.raises(at.HomeFileVerificationRefused, match="checksum manifest"):
        at._require_bundled_route((GATE,), ".claude/scripts/flow-finish-gate.sh", object(), SHIM,  # type: ignore[arg-type]
                                  {"flow-auto-finish": ()}, None)
