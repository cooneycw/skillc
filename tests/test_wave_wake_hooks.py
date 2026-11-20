"""#626 P2: three keyword-only hooks on `wave_wake.drive`, inert at their
defaults (`after_bootstrap`, `before_close`, `defer_terminal_stop`).

Parent-compatible: it imports only names the parent has and checks the
signature by assertion, so on the parent every hook case fails by assertion.
The default-path golden passes on both. Each hook has a blind twin asserted to
DISAGREE with the real result."""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_wave_wake import SID, ScriptedWave, policy

from skillc import wave_wake
from skillc.backend import Confirmation, ExecuteResult

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "wave-wake-hooks" / "default.json")
                    .read_text())
HOOKS = ("after_bootstrap", "before_close", "defer_terminal_stop")


def _drive(module: Any, wave: ScriptedWave, **hooks: Any) -> dict[str, Any]:
    params = inspect.signature(module.drive).parameters
    assert set(hooks) <= set(params), f"drive lacks {sorted(set(hooks) - set(params))}"
    report: dict[str, Any] = module.drive(wave, policy(), read_revision=wave.read, **hooks)
    return report


def _facts(wave: ScriptedWave, report: dict[str, Any]) -> dict[str, Any]:
    names = {SID: "worker-a-session", SID[:-1] + "2": "worker-b-session"}
    return {"outcome": report["outcome"], "poke_count": report["poke_count"],
            "ends": {r: s["end"] for r, s in report["roles"].items()},
            "calls_after_bootstrap": [[role, "literal" if text == policy().literal else text,
                                       names.get(session or "", session)]
                                      for role, text, session in wave.calls[2:]]}


def _events(wave: ScriptedWave) -> list[dict[str, Any]]:
    path = wave.root / "wake-events.json"
    return json.loads(path.read_text()) if path.exists() else []


def _recording_stops(wave: ScriptedWave) -> list[tuple[str, bool]]:
    stops: list[tuple[str, bool]] = []
    for name, state in wave.states.items():
        state.backend = SimpleNamespace(
            end_attempt=lambda handle, name=name: stops.append((name, wave.closed)),
            confirm_stopped=lambda handle: Confirmation.NOT_CONFIRMED)
    return stops


def _blind(old: str, new: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    source = Path(wave_wake.__file__).read_text()
    assert source.count(old) == 1, old
    module = types.ModuleType("skillc._blind_wave_wake")
    module.__package__ = "skillc"
    monkeypatch.setitem(sys.modules, module.__name__, module)
    code = compile(source.replace(old, new), "<blind-wave-wake>", "exec")
    exec(code, module.__dict__)  # noqa: S102
    # drive checks its inputs by exact type (`type(x) is WakeBinding`), so the
    # copy must use the REAL classes, or it refuses before it can be blind.
    for name in ("WakeBinding", "WakePolicy", "Revision", "Poke", "WakeRefused"):
        setattr(module, name, getattr(wave_wake, name))
    return module


def test_the_default_path_matches_the_recorded_golden(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / "wave", "plain-files")
    facts = _facts(wave, wave_wake.drive(wave, policy(), read_revision=wave.read))
    assert facts == {k: v for k, v in GOLDEN.items() if not k.startswith("_")}


def test_inert_hook_values_are_the_default_path(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / "wave", "plain-files")
    report = _drive(wave_wake, wave, after_bootstrap=None, before_close=None,
                    defer_terminal_stop=False)
    assert _facts(wave, report) == {k: v for k, v in GOLDEN.items() if not k.startswith("_")}


def _after_bootstrap_seen(module: Any, tmp_path: Path) -> dict[str, Any]:
    wave = ScriptedWave(tmp_path, "plain-files")
    seen: dict[str, Any] = {"calls": 0}

    def hook() -> None:
        events = _events(wave)
        seen["calls"] += 1
        seen["ended"] = sorted({e["role"] for e in events if e["event"] == "turn-ended"})
        seen["pokes"] = sum(e["event"] == "poke-attempt" for e in events)

    seen["report"] = _drive(module, wave, after_bootstrap=hook)
    return seen


GATE = "                if futures:  # no poke until every initial turn has finished"


def test_after_bootstrap_runs_once_after_every_bootstrap_and_before_any_poke(
        tmp_path: Path) -> None:
    seen = _after_bootstrap_seen(wave_wake, tmp_path / "wave")
    assert seen["calls"] == 1 and seen["pokes"] == 0
    assert seen["ended"] == ["worker-a", "worker-b"]
    assert seen["report"]["outcome"] == "STOPPED" and seen["report"]["poke_count"] == 2


def test_a_hook_that_does_not_wait_for_the_bootstraps_disagrees(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BLIND TWIN: the gate removed, so the hook runs while worker-b's
    bootstrap is still in flight (it waits for worker-a's recorded end)."""
    blind = _blind(GATE, GATE.replace("if futures:", "if False:"), monkeypatch)
    real = _after_bootstrap_seen(wave_wake, tmp_path / "real")
    twin = _after_bootstrap_seen(blind, tmp_path / "blind")
    assert real["ended"] == ["worker-a", "worker-b"], real
    assert twin["calls"] == 1, twin
    assert twin["ended"] != real["ended"], (real, twin)


def test_before_close_runs_before_close_with_every_role_still_running(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / "wave", "plain-files")
    stops = _recording_stops(wave)
    seen: dict[str, Any] = {}

    def hook() -> None:
        seen["closed"], seen["stops"] = wave.closed, list(stops)

    _drive(wave_wake, wave, before_close=hook, defer_terminal_stop=True)
    assert seen == {"closed": False, "stops": []}


def test_a_census_taken_after_the_stop_disagrees(tmp_path: Path) -> None:
    """BLIND TWIN: the same observation made after drive returns, the shape
    of a census read after shutdown. It sees a closed wave; the hook does not."""
    real_wave = ScriptedWave(tmp_path / "real", "plain-files")
    real: dict[str, Any] = {}
    _drive(wave_wake, real_wave, before_close=lambda: real.update(closed=real_wave.closed),
           defer_terminal_stop=True)
    twin_wave = ScriptedWave(tmp_path / "blind", "plain-files")
    _drive(wave_wake, twin_wave)
    twin = {"closed": twin_wave.closed}
    assert real == {"closed": False} and twin == {"closed": True}
    assert real != twin


def test_without_deferral_terminal_roles_are_stopped_in_the_loop(tmp_path: Path) -> None:
    """The counterpart that makes the deferral observable: by default a
    terminal role's attempt is ended before close."""
    wave = ScriptedWave(tmp_path / "wave", "plain-files")
    stops = _recording_stops(wave)
    _drive(wave_wake, wave, defer_terminal_stop=False)
    assert stops and all(closed is False for _, closed in stops)


class SiblingWritesLast(ScriptedWave):
    """worker-b also writes on its poked turn, after worker-a is capped."""

    def turn(self, role: str, text: str | None = None, *,
             expected_session: str | None = None) -> ExecuteResult:
        result = super().turn(role, text, expected_session=expected_session)
        if role == "worker-b" and text is not None:
            (self.shared / "message").write_bytes(b"third opaque message")
            self.revisions.append(self.current_revision())
        return result


@pytest.mark.parametrize("defer", [False, True])
def test_a_deferred_terminal_role_gets_no_further_turn_or_poke(tmp_path: Path,
                                                                defer: bool) -> None:
    """Orchestrator guard: deferring the stop must not become extra turns. A
    sibling's activity after worker-a is capped pokes worker-a zero times."""
    wave = SiblingWritesLast(tmp_path / "wave", "plain-files")
    report = _drive(wave_wake, wave, defer_terminal_stop=defer)
    a_calls = [c for c in wave.calls if c[0] == "worker-a"]
    a_pokes = [e for e in report["events"] if e["event"] == "poke-attempt"
               and e["role"] == "worker-a"]
    assert len(a_calls) == 2 and len(a_pokes) == 1
    assert report["roles"]["worker-a"]["end"] == "max-pokes"
