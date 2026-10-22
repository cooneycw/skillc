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
        return 200, ja.tool_reply([{"id": c, "outcome": outcome, "evidence": ["e"]} for c in ids],
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
    assert len(sent) == 3 and all("max_tokens" not in r["body"] and "tool_choice" in r["body"] for r in sent)
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
        assert result["agreement"][c] == {"items": 3, "repeat_agreement": 1.0, "labelled": 3,
                                          "majority_matches_label": 3, "verdict": "reported"}
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
    with fake.running() as url, pytest.raises(jv.Refused, match="budget stop"):
        jv.run(root, data, labels, key_provider=lambda: "k", base_url=url)
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
    counts = {p.name: {"request_sha256": "sha256:" + "1" * 64, "request_bytes": 1, "input_tokens": 400_000}
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
