"""Merge-admission wiring gate (Kyle #2130, ADR 0011 D3).

The committed cases are ``controls/merge-admission/``. ``bad/ci.yml`` reaches
``main-merge`` only through a script it runs; the frozen blind anchor (the
same check without script-following) must miss it, so the case exercises the
feature that catches it. ``good/ci.yml`` names the acquire only in comments, so
a grep would call it bad and this gate must not.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from ci import merge_admission as gate

CONTROLS = gate.ROOT / "controls" / "merge-admission"


def _blind() -> ModuleType:
    path = CONTROLS / "blind" / "merge_admission_blind.py"
    spec = importlib.util.spec_from_file_location("merge_admission_blind", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pipeline(case: str) -> str:
    return (CONTROLS / case / "ci.yml").read_text(encoding="utf-8")


def _transcript(case: str) -> tuple[list[dict[str, object]], int]:
    data = json.loads((CONTROLS / case / "transcript.json").read_text(encoding="utf-8"))
    return data["calls"], data["pr"]


def test_the_real_pipeline_never_takes_main_merge() -> None:
    followed: set[Path] = set()
    assert gate.pipeline_findings((gate.ROOT / ".woodpecker" / "ci.yml").read_text(encoding="utf-8"),
                                  followed=followed) == []
    # A zero from a scan that read nothing would look the same: prove it read the scripts.
    assert gate.ROOT / "ci" / "negative-control.sh" in followed
    assert len(followed) >= 10


def test_the_bad_pipeline_is_caught_through_the_script_it_runs() -> None:
    found = gate.pipeline_findings(_pipeline("bad"), CONTROLS / "bad")
    assert len(found) == 1 and found[0].startswith("scripts/merge-lock.sh:4:")


def test_the_good_pipeline_with_only_comment_mentions_passes() -> None:
    text = _pipeline("good")
    assert "kyle-lock acquire main-merge" in text, "the good case must keep its comment mention"
    assert gate.pipeline_findings(text, CONTROLS / "good") == []


def test_the_frozen_blind_anchor_misses_the_bad_case() -> None:
    blind = _blind()
    assert blind.pipeline_findings(_pipeline("bad")) == [], (
        "the blind anchor caught bad/ci.yml: the bad case no longer needs script-following")
    assert blind.pipeline_findings(_pipeline("good")) == []


@pytest.mark.parametrize("command", [
    "kyle-lock acquire main-merge --request-key ci",
    "/opt/kyle/scripts/kyle-lock run main-merge -- make test",
    "python3 scripts/kyle-lock begin-merge main-merge --request-id 1 --lease-id x --generation 1",
    "curl -X POST $URL/api/coordination/main-merge/acquire/",
    "export KYLE_LOCK_TOKEN_FILE=/run/secret",
])
def test_inline_routes_to_main_merge_are_findings(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": ["echo ok", command]}]}
    assert gate.pipeline_findings(json.dumps(ci)), command


@pytest.mark.parametrize("command", [
    "kyle-lock acquire full-suite --request-key ci",
    "kyle-lock ci --repo cooneycw/skillc --pr 3",
    "echo 'kyle-lock acquire main-merge'",
    "true  # kyle-lock acquire main-merge",
])
def test_non_merge_lock_use_and_quoted_mentions_are_not(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)) == [], command


@pytest.mark.parametrize("step", [
    {"name": "gate", "environment": {"KYLE_LOCK_TOKEN": {"from_secret": "kyle_lock_token"}}},
    {"name": "gate", "secrets": ["kyle_lock_token_file"]},
])
def test_a_coordination_credential_handed_to_ci_is_a_finding(step: dict[str, object]) -> None:
    assert gate.pipeline_findings(json.dumps({"steps": [step]}))


def test_the_uncoordinated_merge_transcript_is_caught() -> None:
    calls, pr = _transcript("bad")
    found = gate.transcript_findings(calls, pr)
    assert found and "without a held lease" in found[0]


def test_the_coordinated_merge_transcript_passes() -> None:
    calls, pr = _transcript("good")
    assert gate.transcript_findings(calls, pr) == []


def test_merge_before_begin_and_a_repeated_merge_are_caught() -> None:
    calls, pr = _transcript("good")
    begin = next(i for i, c in enumerate(calls) if c["argv"][0] == "begin-merge")  # type: ignore[index]
    swapped = list(calls)
    swapped[begin], swapped[begin + 1] = swapped[begin + 1], swapped[begin]
    assert gate.transcript_findings(swapped, pr)
    merge = next(c for c in calls if c["argv"][:2] == ["pr", "merge"])  # type: ignore[index]
    assert any("second" in f for f in gate.transcript_findings([*calls[:-1], merge, calls[-1]], pr))


def test_cli_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate.main([str(CONTROLS / "good" / "ci.yml")]) == 0
    assert gate.main([str(gate.ROOT / ".woodpecker" / "ci.yml")]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("command", [
    "bash -c 'kyle-lock acquire main-merge --request-key ci'",
    "sh -euc 'echo x; kyle-lock run main-merge -- make test'",
    "eval kyle-lock acquire main-merge",
    "kyle-lock --url http://127.0.0.1:8000 acquire main-merge",
    "true && kyle-lock acquire main-merge",
])
def test_wrapped_and_chained_routes_are_findings(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)), command


@pytest.mark.parametrize("command", [
    "kyle-lock acquire full-suite --purpose main-merge",
    "kyle-lock acquire full-suite; echo main-merge acquire",
    "bash -c 'kyle-lock acquire full-suite'",
])
def test_a_neighbouring_resource_is_not_a_finding(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)) == [], command


@pytest.mark.parametrize("text", ["", "{}", "steps: []", "steps:\n  - name: plugin\n    image: x\n"])
def test_an_empty_population_is_not_a_pass(text: str) -> None:
    assert gate.pipeline_findings(text), repr(text)


def test_a_script_run_inside_an_inner_shell_is_followed() -> None:
    ci = {"steps": [{"name": "gate", "commands": ["bash -c 'bash scripts/merge-lock.sh'"]}]}
    found = gate.pipeline_findings(json.dumps(ci), CONTROLS / "bad")
    assert found and found[0].startswith("scripts/merge-lock.sh:4:")


@pytest.mark.parametrize("command", [
    "echo kyle-lock acquire main-merge",
    "echo bash -c 'kyle-lock acquire main-merge'",
    "grep -n kyle-lock scripts/x.sh main-merge acquire",
])
def test_kyle_lock_as_an_argument_is_not_an_invocation(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)) == [], command


@pytest.mark.parametrize("command", [
    "FOO=1 env -i kyle-lock acquire main-merge",
    "python3 scripts/kyle-lock run main-merge -- make test",
    "uv run --no-sync python3 /opt/kyle/scripts/kyle-lock acquire main-merge",
])
def test_kyle_lock_behind_a_wrapper_is_an_invocation(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)), command


def test_a_merge_after_a_lost_renewal_is_caught() -> None:
    calls, pr = _transcript("good")
    merge_at = next(i for i, c in enumerate(calls) if c["argv"][:2] == ["pr", "merge"])  # type: ignore[index]
    lost = {"tool": "lock", "argv": ["renew", "main-merge", "--request-id", "7", "--lease-id", "lease-7",
                                     "--generation", "1"], "exit": 12}
    assert gate.transcript_findings([*calls[:merge_at], lost, *calls[merge_at:]], pr)


@pytest.mark.parametrize("command", [
    "if kyle-lock acquire main-merge; then true; fi",
    "while kyle-lock acquire main-merge; do sleep 1; done",
    "until ! kyle-lock run main-merge -- make test; do :; done",
    "{ kyle-lock acquire main-merge; }",
])
def test_a_command_in_a_shell_condition_or_group_is_an_invocation(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci)), command


@pytest.mark.parametrize("command, caught", [
    ("cat scripts/merge-lock.sh", False),
    ("echo scripts/merge-lock.sh", False),
    ("grep -n acquire scripts/merge-lock.sh", False),
    ("./scripts/merge-lock.sh", True),
    ("source scripts/merge-lock.sh", True),
    (". scripts/merge-lock.sh", True),
])
def test_only_an_executed_script_is_followed(command: str, caught: bool) -> None:
    """Against the committed bad script: reading it is not running it."""
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert bool(gate.pipeline_findings(json.dumps(ci), CONTROLS / "bad")) is caught, command


def _cases(name: str) -> list[object]:
    data = json.loads((CONTROLS / name).read_text(encoding="utf-8"))
    cases = data["cases"]
    assert isinstance(cases, list)
    return cases


@pytest.mark.parametrize("case", _cases("refused.json"), ids=lambda c: c["command"][:40])  # type: ignore[index]
def test_every_refused_form_is_a_finding(case: dict[str, str]) -> None:
    ci = {"steps": [{"name": "gate", "commands": [case["command"]]}]}
    found = gate.pipeline_findings(json.dumps(ci), CONTROLS / "bad")
    assert found, case["command"]
    if case["kind"] == "unparseable":
        assert any("UNPARSEABLE" in f for f in found), found
    else:
        assert any("CI must never take main-merge" in f for f in found), found


@pytest.mark.parametrize("command", _cases("allowed.json"), ids=lambda c: str(c)[:40])
def test_no_refusal_fires_on_an_ordinary_form(command: str) -> None:
    ci = {"steps": [{"name": "gate", "commands": [command]}]}
    assert gate.pipeline_findings(json.dumps(ci), CONTROLS / "bad") == [], command


def test_the_refusals_do_not_fire_on_todays_pipeline() -> None:
    text = (gate.ROOT / ".woodpecker" / "ci.yml").read_text(encoding="utf-8")
    found = gate.pipeline_findings(text)
    assert not [f for f in found if "UNPARSEABLE" in f], found


def test_a_continuation_inside_a_followed_script_is_joined(tmp_path: Path) -> None:
    (tmp_path / "s.sh").write_text("#!/usr/bin/env bash\nkyle-lock \\\n  acquire main-merge\n", encoding="utf-8")
    ci = {"steps": [{"name": "gate", "commands": ["bash s.sh"]}]}
    assert gate.pipeline_findings(json.dumps(ci), tmp_path)
