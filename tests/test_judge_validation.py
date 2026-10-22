"""#513's validation harness (`evals/level3/flow-auto-necessity/judge_validation.py`),
driven only by the committed FakeMessagesServer and synthetic items. No test
reads a real report, holds a key, or makes a real call."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from skillc import judge_anthropic as ja

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "judge_validation", ROOT / "evals" / "level3" / "flow-auto-necessity" / "judge_validation.py")
assert _spec and _spec.loader
jv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jv)

PRICE = {"input_usd_per_million": 4.0, "output_usd_per_million": 20.0,
         "source_url": "https://example.invalid/pricing", "read_on": "2026-10-22"}


def _items(tmp_path: Path, n: int = 3) -> Path:
    root = tmp_path / "export"
    manifest = {}
    for i in range(1, n + 1):
        d = root / "items" / f"item-{i:02d}"
        d.mkdir(parents=True)
        (d / jv.OBSERVATIONS).write_text(json.dumps({"case": "twin", "service": {"events": i}}))
        (d / jv.REPORT).write_text(f"Verdict: Still needed. Report {i}.")
        manifest[d.name] = {name: jv.sha256_bytes(data) for name, data in jv.item_files(d)}
    (root / "items-manifest.json").write_text(json.dumps(manifest))
    return root


def _labels(tmp_path: Path, root: Path, outcome: str = "SATISFIED") -> Path:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({"schema": 1, "labeller": "a fresh session", "labelled_at": "2026-10-22",
                                "items": {p.name: dict.fromkeys(jv.CRITERIA, outcome) for p in jv.items_of(root)}}))
    return path


def _always(outcome: str, usage: Mapping[str, int] | None = None) -> ja.Responder:
    def respond(body: Mapping[str, Any]) -> tuple[int, bytes]:
        ids = [c["id"] for c in ja.user_document(body)["criteria"]]
        billed = {"input_tokens": len(json.dumps(body)) // 4, "output_tokens": 300}  # what the fake counts
        return 200, ja.verdict_reply([{"id": c, "outcome": outcome, "evidence": ["e"]} for c in ids],
                                  usage=billed if usage is None else usage)
    return respond


def _declared(tmp_path: Path, fake: ja.FakeMessagesServer, url: str, *, k: int = 3) -> tuple[Path, dict[str, Any], Path]:
    root = _items(tmp_path)
    counts = jv.count(root, jv.make_judge(key_provider=lambda: "k", base_url=url))
    labels = _labels(tmp_path, root)
    data = jv.declare(root, counts, labels, k=k, max_tokens=1536, price=PRICE, secret_id="skillc", threshold=2 / 3)
    data["approval"] = {"by": "orchestrator", "source": "test", "declaration_digest": jv.digest(data)}
    return root, data, labels


def test_count_binds_each_exact_body_to_its_sha_and_strips_max_tokens(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root = _items(tmp_path)
        counts = jv.count(root, jv.make_judge(key_provider=lambda: "k", base_url=url))
    assert sorted(counts) == ["item-01", "item-02", "item-03"]
    sent = [r for r in fake.requests if r["path"].endswith("/count_tokens")]
    assert len(sent) == 3 and all("max_tokens" not in r["body"] and "output_config" in r["body"] and "tool_choice" not in r["body"] for r in sent)
    for item, entry in counts.items():
        body = jv.make_judge(key_provider=lambda: "k").request_body(
            jv.CRITERIA, jv.GOAL, jv.item_files(root / "items" / item))
        assert entry["request_sha256"] == jv.sha256_bytes(body) and entry["input_tokens"] > 0


def test_an_approved_run_makes_k_calls_per_item_and_reports_agreement(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root, data, labels = _declared(tmp_path, fake, url)
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["calls"] == 9 == len([r for r in fake.requests if r["path"] == "/v1/messages"])
    for c in jv.CRITERIA:
        assert result["agreement"][c] == {"attempted": 3, "answered": 3, "repeat_agreement": 1.0, "unresolved": 0,
                                          "labelled": 3, "majority_matches_label": 3, "constant_satisfied_matches": 3,
                                          "violated_labelled": 0, "violated_recalled": 0, "satisfied_labelled": 3,
                                          "false_alarms": 0, "verdict": "reported"}
    assert result["status"] == "COMPLETE" and result["limits"] == jv.LIMITS and "LIMITS:" in result["headline"]
    assert 0 < result["spent_usd"] <= data["worst_case_usd"]


def test_red_labels_whose_sha_is_not_the_declared_one_are_refused(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root, data, labels = _declared(tmp_path, fake, url)
        before = len(fake.requests)
        text = json.loads(labels.read_text())
        text["items"]["item-01"][jv.CRITERIA[0]] = "VIOLATED"  # a relabel after declaration
        labels.write_text(json.dumps(text))
        with pytest.raises(jv.Refused, match="labels .* are not the declared"):
            jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert len(fake.requests) == before  # nothing sent


def _note(keys: list[str]) -> str:
    keys.append("read")
    return "k"


def test_red_a_body_changed_after_counting_is_refused_before_the_key(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    keys: list[str] = []
    with fake.running() as url:
        root, data, labels = _declared(tmp_path, fake, url)
        before = len(fake.requests)
        data = json.loads(json.dumps(data))
        data["counts"]["item-01"]["request_sha256"] = "sha256:" + "0" * 64
        data["approval"]["declaration_digest"] = jv.digest(data)
        with pytest.raises(jv.Refused, match="item-01: the request body changed after it was counted"):
            jv.run(root, data, labels, key_provider=lambda: _note(keys), base_url=url)
    assert keys == [] and len(fake.requests) == before


def test_red_inflated_usage_stops_the_run_early(tmp_path: Path) -> None:
    """The runtime stop is the real guard: a provider billing far more than the
    count predicted is stopped once a worst-case reply could cross $5."""
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url)
    fake = ja.FakeMessagesServer(_always("SATISFIED", usage={"input_tokens": 600_000, "output_tokens": 1500}))
    with fake.running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["status"] == "STOPPED" and "budget stop" in result["stopped"]
    paid = [r for r in fake.requests if r["path"] == "/v1/messages"]
    assert len(paid) == 1  # the first over-count reply breaks the bound; nothing more is sent
    assert (600_000 * 4 + 1500 * 20) / 1e6 <= 5.0


def test_red_a_reply_with_no_usage_is_charged_its_worst_case() -> None:
    budget = jv.Budget(ja_price(), max_tokens=1536, ceiling=5.0)
    budget.admit(10_000)
    budget.charge(ja.reply_usage(b'{"type": "message"}'))
    assert budget.spent == pytest.approx((1.10 * 10_000 * 4 + 1536 * 20) / 1e6)


def ja_price() -> Any:
    from skillc import cost_estimate
    return cost_estimate.ModelPrice("claude-opus-5-5", 4.0, 20.0, "https://example.invalid/pricing")


def test_red_an_unapproved_or_re_edited_declaration_is_refused(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root, data, labels = _declared(tmp_path, fake, url)
        unapproved = {k: v for k, v in data.items() if k != "approval"}
        with pytest.raises(jv.Refused, match="not approved"):
            jv.run(root, unapproved, labels, key_provider=lambda: "k", base_url=url)
        edited = {**data, "k": 4}  # the approval's digest no longer binds it
        with pytest.raises(jv.Refused, match="not approved"):
            jv.run(root, edited, labels, key_provider=lambda: "k", base_url=url)


def test_red_a_worst_case_over_the_ceiling_is_refused_at_declare(tmp_path: Path) -> None:
    root = _items(tmp_path)
    labels = _labels(tmp_path, root)
    counts = {p.name: {"request_sha256": "sha256:" + "1" * 64, "request_bytes": 1, "max_tokens": 1536, "effort": "medium",
                       "input_tokens": 400_000}
              for p in jv.items_of(root)}
    with pytest.raises(jv.Refused, match=r"worst case \$\d+\.\d\d exceeds the \$5\.00 ceiling"):
        jv.declare(root, counts, labels, k=3, max_tokens=1536, price=PRICE, secret_id="skillc", threshold=2 / 3)


@pytest.mark.parametrize(("edit", "match"), [
    (lambda d: d.update(labeller=None), "labeller and labelled_at"),
    (lambda d: d["items"]["item-01"].update({jv.CRITERIA[0]: None}), "must label every criterion"),
    (lambda d: d["items"].pop("item-03"), "exactly the 3 exported items"),
])
def test_red_an_incomplete_label_file_is_refused(tmp_path: Path, edit: Any, match: str) -> None:
    root = _items(tmp_path)
    labels = _labels(tmp_path, root)
    data = json.loads(labels.read_text())
    edit(data)
    labels.write_text(json.dumps(data))
    with pytest.raises(jv.Refused, match=match):
        jv.load_labels(labels, [p.name for p in jv.items_of(root)])


def test_a_criterion_the_judge_flips_on_is_unknown_not_reported() -> None:
    flip = {"item-01": [{c: "SATISFIED" for c in jv.CRITERIA}, {c: "VIOLATED" for c in jv.CRITERIA},
                        {c: "SATISFIED" for c in jv.CRITERIA}]}
    labels = {"item-01": {c: "SATISFIED" for c in jv.CRITERIA}}
    report = jv.agreement(flip, labels, threshold=2 / 3)
    assert all(r["repeat_agreement"] == 0.0 and r["verdict"] == "UNKNOWN" for r in report.values())
    assert all(r["majority_matches_label"] == 1 for r in report.values())  # 2 of 3 is a strict majority


def test_the_label_template_names_criterion_ids_and_never_the_rubric() -> None:
    template = {"items": {"item-01": dict.fromkeys(jv.CRITERIA)}}
    text = json.dumps(template)
    assert all(definition not in text for definition in jv.RUBRIC.values())


def test_a_paid_run_needs_the_operator_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SKILLC_ALLOW_PAID_JUDGE", raising=False)
    assert jv.main(["run", "--items", str(tmp_path), "--declaration", str(tmp_path / "d.json"),
                    "--labels", str(tmp_path / "l.json"), "--out", str(tmp_path / "o.json")]) == 2
    assert "SKILLC_ALLOW_PAID_JUDGE=1" in capsys.readouterr().err


def test_the_constant_satisfied_control_matches_raw_agreement_and_recalls_nothing() -> None:
    """The orchestrator's control on lopsided labels: a judge that says SATISFIED
    to everything scores the baseline exactly and recalls no violation, so raw
    agreement alone cannot tell it from a real judge."""
    labels = {f"item-{i}": {c: ("VIOLATED" if i == 0 else "SATISFIED") for c in jv.CRITERIA} for i in range(4)}
    constant = {item: [{c: "SATISFIED" for c in jv.CRITERIA}] * 3 for item in labels}
    sees = {item: [{c: labels[item][c] for c in jv.CRITERIA}] * 3 for item in labels}
    for c in jv.CRITERIA:
        a, b = jv.agreement(constant, labels, 2 / 3)[c], jv.agreement(sees, labels, 2 / 3)[c]
        assert a["majority_matches_label"] == a["constant_satisfied_matches"] == 3 and a["violated_recalled"] == 0
        assert a["false_alarms"] == 0
        assert b["majority_matches_label"] == 4 and b["violated_recalled"] == b["violated_labelled"] == 1



# --- Codex review of the harness (2026-10-22): one red per finding ---------

def _settled(responder: ja.Responder, **kw: Any) -> list[Mapping[str, int]]:
    seen: list[Mapping[str, int]] = []
    fake = ja.FakeMessagesServer(responder)
    with fake.running() as url:
        j = ja.AnthropicJudge(key_provider=lambda: "k", criteria_text=jv.RUBRIC, base_url=url, timeout=5.0,
                              usage_sink=seen.append, **kw)
        jv.judge.run_tier(jv.judge.INDEPENDENT_TIER, j, jv.CRITERIA, jv.GOAL, [("report.md", b"hi")])
    return seen


@pytest.mark.parametrize(("responder", "kw"), [
    (_always("SATISFIED"), {"max_response_bytes": 16}),          # oversize: read, then refused
    (lambda b: (500, b'{"type": "error"}'), {}),                   # an HTTP error after dispatch
])
def test_red_every_dispatched_request_settles_its_usage_exactly_once(responder: Any, kw: dict[str, Any]) -> None:
    """Failed reads used to raise before the sink, so the budget charged nothing."""
    assert _settled(responder, **kw) == [ja.UNKNOWN_USAGE]


def test_red_a_known_input_overrun_breaks_the_budget_even_with_output_missing() -> None:
    budget = jv.Budget(ja_price(), max_tokens=1536, ceiling=5.0)
    budget.admit(1000)
    budget.charge({"input_tokens": 2_000_000, "output_tokens": -1})
    assert budget.broken is not None
    assert budget.spent == pytest.approx((2_000_000 * 4 + 1536 * 20) / 1e6)  # known input as billed, output at worst


def test_red_the_count_path_runs_the_same_leak_checks_before_anything_leaves(tmp_path: Path) -> None:
    root = _items(tmp_path)
    leaky = root / "items" / "item-01" / jv.OBSERVATIONS
    leaky.write_text(json.dumps({"case": "twin", "where": "/home/" + "example/private-task"}))
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url, pytest.raises(jv.judge.JudgeInputLeaked):
        jv.count(root, jv.make_judge(key_provider=lambda: "k", base_url=url))
    assert fake.requests == []


def test_red_a_breach_on_the_final_reply_stops_the_run_and_says_so(tmp_path: Path) -> None:
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url, k=1)
    calls = []

    def respond(body: Mapping[str, Any]) -> tuple[int, bytes]:
        calls.append(1)
        usage = {"input_tokens": 10, "output_tokens": 10} if len(calls) < 3 else {"input_tokens": 900_000,
                                                                                 "output_tokens": 10}
        return _always("SATISFIED", usage=usage)(dict(body))
    fake = ja.FakeMessagesServer(respond)
    with fake.running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["calls"] == 3 and result["status"] == "STOPPED" and "budget stop" in result["stopped"]
    assert result["headline"].startswith("STOPPED (")


def test_red_unavailable_calls_are_missing_answers_not_unanimous_votes() -> None:
    labels = {"item-01": {c: "SATISFIED" for c in jv.CRITERIA}}
    report = jv.agreement({"item-01": [None, None, None]}, labels, 2 / 3, k=3)
    assert all(r["answered"] == 0 and r["repeat_agreement"] is None and r["verdict"] == "UNKNOWN"
               for r in report.values())


def test_red_a_tie_is_unresolved_and_order_does_not_move_any_score() -> None:
    labels = {"item-01": {c: "VIOLATED" for c in jv.CRITERIA}}
    votes = [{c: o for c in jv.CRITERIA} for o in ("SATISFIED", "VIOLATED", "UNKNOWN")]
    a = jv.agreement({"item-01": votes}, labels, 2 / 3)
    b = jv.agreement({"item-01": list(reversed(votes))}, labels, 2 / 3)
    assert a == b
    assert all(r["unresolved"] == 1 and r["violated_recalled"] == 0 and r["majority_matches_label"] == 0
               for r in a.values())


def test_red_counts_taken_at_another_max_tokens_are_refused_at_declare(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root = _items(tmp_path)
        counts = jv.count(root, jv.make_judge(key_provider=lambda: "k", base_url=url, max_tokens=1024))
    labels = _labels(tmp_path, root)
    with pytest.raises(jv.Refused, match="another max_tokens than the declared 1536"):
        jv.declare(root, counts, labels, k=3, max_tokens=1536, price=PRICE, secret_id="skillc", threshold=2 / 3)


def test_red_a_run_whose_calls_are_all_unavailable_certifies_nothing(tmp_path: Path) -> None:
    """End to end: UNAVAILABLE replies are recorded as missing answers, so they
    can never read as three unanimous UNKNOWN votes with perfect agreement."""
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url)
    fake = ja.FakeMessagesServer(lambda b: (500, b'{"type": "error"}'))
    with fake.running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert all(o is None for runs in result["outcomes"].values() for o in runs)
    assert all(r["answered"] == 0 and r["verdict"] == "UNKNOWN" for r in result["agreement"].values())


# --- #513 run 1: 60 of 60 unavailable read COMPLETE -------------------------

def test_red_513_a_run_below_its_answered_floor_is_failed_and_says_why(tmp_path: Path) -> None:
    """Run 1 spent $3.40, answered 0 of 60 and read COMPLETE. Below the
    declared floor a run is FAILED, and every call's reason and envelope is kept."""
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url)
    reply = json.dumps({"type": "message", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "not json"}]}).encode()
    with ja.FakeMessagesServer(lambda b: (200, reply)).running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["status"] == "FAILED" and result["answered_calls"] == 0
    assert "below the declared floor" in result["stopped"] and result["headline"].startswith("STOPPED (only 0 of 9")
    assert len(result["calls_log"]) == 9
    assert all(c["status"] == "UNAVAILABLE" and "not JSON" in c["reason"]
               and c["envelope"]["block_types"] == ["text"] for c in result["calls_log"])


def test_counts_at_another_effort_are_refused_and_the_declaration_pins_it(tmp_path: Path) -> None:
    fake = ja.FakeMessagesServer(_always("SATISFIED"))
    with fake.running() as url:
        root = _items(tmp_path)
        counts = jv.count(root, jv.make_judge(key_provider=lambda: "k", base_url=url, effort="high"))
    labels = _labels(tmp_path, root)
    with pytest.raises(jv.Refused, match="another effort than the declared 'medium'"):
        jv.declare(root, counts, labels, k=3, max_tokens=1536, price=PRICE, secret_id="skillc", threshold=2 / 3)
    data = jv.declare(root, counts, labels, k=3, max_tokens=1536, price=PRICE, secret_id="skillc",
                      threshold=2 / 3, effort="high")
    assert data["effort"] == "high" and data["min_answered_calls"] == 9  # ceil(0.9 x 9)
    assert all(r["body"]["output_config"]["effort"] == "high" for r in fake.requests)



def test_red_empty_verdict_lists_are_not_answered_calls(tmp_path: Path) -> None:
    """Codex review: nine {"verdicts": []} replies read COMPLETE with perfect
    agreement, because run_tier fills the gaps with synthesized UNKNOWNs."""
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url)
    with ja.FakeMessagesServer(lambda b: (200, ja.verdict_reply([]))).running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["status"] == "FAILED" and result["answered_calls"] == 0
    assert all(c["synthesized"] and all(m.startswith("judge returned no verdict") for m in c["synthesized"].values())
               for c in result["calls_log"])


def test_a_judges_own_unknown_with_a_reason_is_an_answer(tmp_path: Path) -> None:
    with ja.FakeMessagesServer(_always("SATISFIED")).running() as url:
        root, data, labels = _declared(tmp_path, ja.FakeMessagesServer(_always("SATISFIED")), url)

    def respond(body: Mapping[str, Any]) -> tuple[int, bytes]:
        ids = [c["id"] for c in ja.user_document(body)["criteria"]]
        return 200, ja.verdict_reply([{"id": c, "outcome": "UNKNOWN", "missing": "the gate record is absent"}
                                      for c in ids])
    with ja.FakeMessagesServer(respond).running() as url:
        result = jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
    assert result["status"] == "COMPLETE" and result["answered_calls"] == 9
