"""#529 D3: the owner's pre-approval ("i approve the run now", #529 comment
6365908723) bound to the flow-check route probe declaration, digest
9f721d18. The stamp sits outside the digest; any change to a field inside it
- the bounds above all - no longer binds the approval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_live as fl

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = ROOT / "evals" / "level3" / "flow-check-route-live" / "declaration-draft.json"
DIGEST = "sha256:9f721d18c0da364be5dce393e51322a8c40a9c9e96daf3ba65015fe6bd24ba9c"


def _data() -> dict[str, Any]:
    return json.loads(DECLARATION.read_text(encoding="utf-8"))


def test_the_probe_declaration_carries_the_owner_s_approval_and_is_pinned() -> None:
    declaration = fl.parse_declaration(_data())
    assert declaration.digest == DIGEST
    approval = declaration.approval
    assert approval is not None and approval["by"] == "owner (cooneycw)" and approval["declaration_digest"] == DIGEST
    assert "'i approve the run now'" in approval["source"] and "issuecomment-6365908723" in approval["source"]
    fl.require_approved(declaration, ROOT)


def test_the_approved_declaration_is_inside_the_owner_s_bounds() -> None:
    """The owner's bounds (#529 comment 6365908723), held on the approved file."""
    data = _data()
    shared = data["shared"]
    assert data["attempts_per_case"] * len(data["cases"]) <= 2
    assert (shared["model"], shared["reasoning_effort"]) == ("gpt-6-astra", "high")
    assert shared["per_attempt_seconds"] <= 900 and shared["total_seconds"] <= 2700
    assert shared["token_pause_per_attempt"] == 1_500_000
    assert data["subject"]["revision"] == "652c01185bc73adf18df49f5b9d1d5ad77a038c7"


@pytest.mark.parametrize("path,value", [
    (("shared", "per_attempt_seconds"), 901), (("shared", "total_seconds"), 5400),
    (("shared", "token_pause_per_attempt"), 2_000_000), (("shared", "model"), "gpt-6-astra-mini"),
    (("attempts_per_case",), 3), (("run_store",), "~/skillc-evidence/flow-check-route/probe-652c0118-2"),
])
def test_red_the_approval_does_not_survive_a_changed_field(path: tuple[str, ...], value: object) -> None:
    data = _data()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(fl.LiveRefused):
        fl.require_approved(fl.parse_declaration(data), ROOT)


def test_red_without_its_stamp_the_declaration_is_refused() -> None:
    data = _data()
    del data["approval"]
    declaration = fl.parse_declaration(data)
    assert declaration.digest == DIGEST  # the stamp is outside the digest
    with pytest.raises(fl.LiveRefused, match="no approval record"):
        fl.require_approved(declaration, ROOT)
