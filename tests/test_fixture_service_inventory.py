"""The fixture service covers what the pinned workflow actually calls (#276).

`docs/specs/evaluation-facility/fixture-service-gh-inventory.txt` lists every
gh call and every `--jq` filter in the pinned CPP 86641e8 flow:auto lane.
This instrument checks that each call parses under the closed grammar, and
that each filter is on `JQ_ALLOWLIST` AND evaluates under real jq on its
recorded payload. Its committed negative controls - a call outside the
grammar and a filter off the allowlist - must be reported UNCOVERED; if they
are not, the check is blind and the green means nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import fixture_service as fs

INVENTORY = (Path(__file__).resolve().parent.parent / "docs" / "specs" / "evaluation-facility"
             / "fixture-service-gh-inventory.txt")
needs_jq = pytest.mark.skipif(fs.measure_jq()[0] is None, reason="jq 1.7.x is not installed")


def _entries() -> list[tuple[str, str, list[object]]]:
    rows = []
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        kind, source, *columns = line.split("\t")
        rows.append((kind, source, [json.loads(c) for c in columns]))
    extension = json.loads(INVENTORY.with_name("fixture-service-wave-gh-inventory.json").read_text())
    payloads = {
        "issue.view": {"body": "fixture", "labels": [{"name": "bug"}]},
        "issue.list": [{"number": 1, "title": "T001: fixture", "body": "Blocked by #2"}],
        "pr.view": {"headRefOid": "a" * 40, "statusCheckRollup": []},
        "pr.list": [{"number": 4, "state": "OPEN", "headRefOid": "a" * 40}],
        "repo.view": {"nameWithOwner": "fixture/widget"},
        "api.user": {"login": "fixture-subject", "email": "fixture@fixture.invalid"},
    }
    for case in extension["extension_cases"] + extension["issue_required_capabilities"]:
        argv = case["argv"]
        rows.append(("call", case["source"], [argv]))
        if "--jq" in argv:
            op = "api.user" if argv[:2] == ["api", "user"] else ".".join(argv[:2])
            rows.append(("jq", case["source"], [argv[argv.index("--jq") + 1], payloads[op]]))
    return rows


def uncovered(entries: list[tuple[str, str, list[object]]], jq_path: str) -> list[tuple[str, str, str]]:
    """Every entry the service does NOT cover, as `(kind, source, why)`."""
    misses = []
    for kind, source, columns in entries:
        if kind in ("call", "control-call"):
            argv = columns[0]
            assert isinstance(argv, list)
            try:
                fs.parse_argv([str(a) for a in argv])
            except fs.Unsupported as exc:
                misses.append((kind, source, str(exc)))
        elif kind in ("jq", "control-jq"):
            jq_filter, payload = columns
            assert isinstance(jq_filter, str)
            if jq_filter not in fs.JQ_ALLOWLIST:
                misses.append((kind, source, "not on JQ_ALLOWLIST"))
                continue
            code, _, err = fs.run_jq(jq_path, jq_filter, payload)
            if code != 0:
                misses.append((kind, source, f"real jq failed: {err.strip()}"))
        else:
            misses.append((kind, source, "unknown inventory kind"))
    return misses


@needs_jq
def test_every_inventory_call_and_filter_is_covered_and_only_the_controls_are_not() -> None:
    jq_path, _ = fs.measure_jq()
    assert jq_path is not None
    entries = _entries()
    real = [e for e in entries if not e[0].startswith("control-")]
    controls = [e for e in entries if e[0].startswith("control-")]
    assert len(real) > 50 and {e[0] for e in controls} == {"control-call", "control-jq"}
    misses = uncovered(entries, jq_path)
    # The controls prove the instrument can say "uncovered"; nothing else may.
    assert sorted((k, s) for k, s, _ in misses) == sorted((k, s) for k, s, _ in controls), misses


def test_the_allowlist_holds_exactly_the_inventory_filters() -> None:
    filters = {c[0] for k, _, c in _entries() if k == "jq"}
    # No dead allowlist entry that nothing pinned uses, and no inventory filter off it.
    assert filters == set(fs.JQ_ALLOWLIST)


@needs_jq
def test_a_filter_that_parses_but_fails_under_real_jq_is_reported() -> None:
    jq_path, _ = fs.measure_jq()
    assert jq_path is not None
    # On the allowlist, but the payload cannot be iterated: real jq exits nonzero.
    bad: list[tuple[str, str, list[object]]] = [("jq", "control:runtime", [".contexts[]", {"contexts": None}])]
    misses = uncovered(bad, jq_path)
    assert len(misses) == 1 and misses[0][2].startswith("real jq failed")


def test_every_call_names_a_pinned_source_line() -> None:
    for kind, source, _ in _entries():
        if kind.startswith("control-"):
            assert source.startswith("control:")
            continue
        if source == "skillc#636":
            continue  # capability explicitly required by the task, no pinned caller
        path, _, line = source.rpartition(":")
        assert path.startswith(("scripts/", ".claude/commands/flow/", "codex/skills/")) and line.isdigit(), source
