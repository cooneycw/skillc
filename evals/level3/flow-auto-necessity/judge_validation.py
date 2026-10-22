#!/usr/bin/env python3
"""#513's paid held-out validation of the independent-tier judge: four steps.

  export   the retained live attempts become blinded ITEMS (observations.json +
           report.md each), a private attempt map, and a label TEMPLATE that
           names criterion ids only - never the rubric text (orchestrator ruling)
  count    each item's EXACT request body is counted by the free
           /v1/messages/count_tokens endpoint and bound to its sha256
  declare  the declaration: items, counts, k, max_tokens, the cited price, the
           labels' sha256 and the worst case, refused above the $5 ceiling
  run      ONLY an approved declaration: k judge calls per item, every one
           checked before it leaves (body sha unchanged, budget can take a
           worst-case reply), the labels re-hashed, agreement reported

THE BOUND (orchestrator ruling A on #513): 1.10 x counted input tokens x the
input price, plus calls x max_tokens x the output price. The counts are an
estimate (the endpoint's own words), hence the 10%. THE RUNTIME STOP IS THE
REAL GUARD: the running cost is taken from each reply's `usage`, and the next
call is refused when a worst-case reply could cross the ceiling. A reply that
reports no usage is charged its worst case.

What it reports is agreement, never correctness: per criterion, how often the
judge's majority over k matches the hand label, and how often all k calls
agree. A criterion below the declared repeat-agreement threshold is UNKNOWN.
Everything item-level stays in the private output directory; stdout carries
counts only.

Stdlib only, apart from skillc itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from skillc import cost_estimate, judge, trial
from skillc import fixture_live as fl
from skillc import judge_anthropic as ja

KIND = "judge-validation-declaration"
SCHEMA = 1
OBSERVATIONS = "observations.json"
REPORT = "report.md"
OUTCOMES = ("SATISFIED", "VIOLATED", "UNKNOWN")
COUNT_MARGIN = 1.10
CRITERIA: tuple[str, ...] = tuple(json.loads((HERE / "grader.json").read_text(encoding="utf-8"))["criteria"])
RUBRIC: dict[str, str] = json.loads((HERE / "judge-rubric.json").read_text(encoding="utf-8"))["criteria"]
GOAL = (HERE / "goal.md").read_text(encoding="utf-8")


class Refused(Exception):
    """The step cannot run on these inputs; nothing is sent or spent."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(data: Mapping[str, Any]) -> str:
    """The declaration's identity: canonical JSON, the approval excluded."""
    return sha256_bytes(json.dumps({k: v for k, v in data.items() if k != "approval"},
                                   sort_keys=True, separators=(",", ":")).encode("utf-8"))


def make_judge(*, key_provider: ja.KeyProvider, base_url: str = ja.DEFAULT_BASE_URL, max_tokens: int = 1536,
               before_send: Any = None, usage_sink: Any = None) -> ja.AnthropicJudge:
    return ja.AnthropicJudge(key_provider=key_provider, criteria_text=RUBRIC,
                             observation_files=frozenset({OBSERVATIONS}), base_url=base_url, max_tokens=max_tokens,
                             before_send=before_send, usage_sink=usage_sink)


def item_files(item: Path) -> list[tuple[str, bytes]]:
    return [(OBSERVATIONS, (item / OBSERVATIONS).read_bytes()), (REPORT, (item / REPORT).read_bytes())]


def items_of(root: Path) -> list[Path]:
    items = sorted(p for p in (root / "items").iterdir() if p.is_dir()) if (root / "items").is_dir() else []
    if not items:
        raise Refused(f"{root}/items holds no item: an empty population is not a validation")
    return items


# ------------------------------------------------------------------ export

def export(runs: Sequence[Path], out: Path, *, seed: int) -> dict[str, Any]:
    """Blind the retained, approved live attempts of `runs` into `out`."""
    if out.exists():
        raise Refused(f"{out} exists; an export never overwrites")
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for run in runs:
        report = json.loads((run / fl.REPORT_FILENAME).read_text(encoding="utf-8"))
        if report.get("approved") is not True or report.get("rehearsal") is not None:
            raise Refused(f"{run} is not an approved live run")
        stores = [p for p in (run / "store").iterdir() if (p / trial.LEDGER).is_file()]
        if len(stores) != 1:
            raise Refused(f"{run}/store holds {len(stores)} experiment(s), not exactly one")
        scratch = out.parent / f".{out.name}-store-{len(rows)}"
        import shutil
        shutil.copytree(stores[0], scratch)  # only a copy is ever opened (as judge_replay does)
        try:
            experiment = trial.Experiment.open(scratch)
            ids = [str(a["attempt_id"]) for _, a in experiment.attempts()]
            for attempt_id, extras in fl._retained_fixture_extras(experiment, ids).items():
                if not isinstance(extras, dict):
                    raise Refused(f"{run} {attempt_id}: {extras}")
                rows.append((str(run.name), attempt_id, dict(extras)))
        finally:
            shutil.rmtree(scratch)
    random.Random(seed).shuffle(rows)
    (out / "items").mkdir(parents=True)
    attempt_map, manifest = {}, {}
    for n, (run_name, attempt_id, extras) in enumerate(rows, start=1):
        item_id = f"item-{n:02d}"
        report_text = extras.pop("final_report")
        if not isinstance(report_text, str) or not report_text.strip():
            raise Refused(f"{run_name} {attempt_id} has no final report to judge")
        d = out / "items" / item_id
        d.mkdir()
        (d / OBSERVATIONS).write_bytes(json.dumps(extras, sort_keys=True).encode("utf-8"))
        (d / REPORT).write_bytes(report_text.encode("utf-8"))
        attempt_map[item_id] = {"run": run_name, "attempt_id": attempt_id}
        manifest[item_id] = {name: sha256_bytes(data) for name, data in item_files(d)}
    (out / "attempt-map.json").write_text(json.dumps(attempt_map, indent=1, sort_keys=True) + "\n")
    (out / "items-manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    template = {"schema": SCHEMA, "labeller": None, "labelled_at": None,
                "_instructions": "Fill each criterion with SATISFIED, VIOLATED or UNKNOWN from the item's "
                                 "observations.json and report.md and #513's criterion definitions only.",
                "items": {item_id: dict.fromkeys(CRITERIA) for item_id in manifest}}
    (out / "labels-template.json").write_text(json.dumps(template, indent=1) + "\n")
    return {"items": len(manifest), "items_digest": sha256_bytes(json.dumps(manifest, sort_keys=True).encode())}


# ------------------------------------------------------------------ count

def count(root: Path, j: ja.AnthropicJudge) -> dict[str, dict[str, Any]]:
    counts = {}
    for item in items_of(root):
        body = j.request_body(CRITERIA, GOAL, item_files(item))
        counts[item.name] = {"request_sha256": sha256_bytes(body), "request_bytes": len(body),
                             "input_tokens": j.count_tokens(body)}
    return counts


# ------------------------------------------------------------------ declare

def load_labels(path: Path, items: Sequence[str]) -> tuple[dict[str, dict[str, str]], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    labels = data.get("items") if isinstance(data, dict) else None
    if not isinstance(labels, dict) or set(labels) != set(items):
        raise Refused(f"{path}: labels must name exactly the {len(items)} exported items")
    for item_id, row in labels.items():
        if not isinstance(row, dict) or set(row) != set(CRITERIA) or any(v not in OUTCOMES for v in row.values()):
            raise Refused(f"{path}: {item_id} must label every criterion with one of {list(OUTCOMES)}")
    if not data.get("labeller") or not data.get("labelled_at"):
        raise Refused(f"{path}: labeller and labelled_at must be recorded")
    return labels, sha256_bytes(raw)


def worst_case(counts: Mapping[str, Mapping[str, Any]], k: int, max_tokens: int,
               price: cost_estimate.ModelPrice) -> float:
    counted = sum(int(c["input_tokens"]) for c in counts.values())
    calls = k * len(counts)
    return (COUNT_MARGIN * counted * k * price.input_usd_per_million
            + calls * max_tokens * price.output_usd_per_million) / 1_000_000


def declare(root: Path, counts: Mapping[str, Mapping[str, Any]], labels_path: Path, *, k: int, max_tokens: int,
            price: Mapping[str, Any], secret_id: str, threshold: float) -> dict[str, Any]:
    items = [p.name for p in items_of(root)]
    if sorted(counts) != sorted(items):
        raise Refused("the counts do not name exactly the exported items")
    _, labels_sha = load_labels(labels_path, items)
    model_price = cost_estimate.ModelPrice(ja.DEFAULT_MODEL, price["input_usd_per_million"],
                                           price["output_usd_per_million"], price["source_url"])
    bound = worst_case(counts, k, max_tokens, model_price)
    if bound > cost_estimate.CEILING_USD:
        raise Refused(f"worst case ${bound:.2f} exceeds the ${cost_estimate.CEILING_USD:.2f} ceiling")
    manifest = json.loads((root / "items-manifest.json").read_text())
    return {"kind": KIND, "schema": SCHEMA, "model": ja.DEFAULT_MODEL, "secret_id": secret_id, "k": k,
            "max_tokens": max_tokens, "repeat_agreement_threshold": threshold, "price": dict(price),
            "count_margin": COUNT_MARGIN, "calls": k * len(items),
            "items_digest": sha256_bytes(json.dumps(manifest, sort_keys=True).encode()),
            "labels_sha256": labels_sha, "counts": dict(counts), "worst_case_usd": round(bound, 4)}


# ------------------------------------------------------------------ run

class Budget:
    """The runtime stop: spent-so-far from each reply's usage, and no call that
    a worst-case reply could push over the ceiling.

    The worst case rests on the COUNT. A reply billing more input than
    `COUNT_MARGIN` x its count means the count no longer bounds anything, so
    every later call is refused. What cannot be prevented is that one reply's
    own overrun: it is known only once billed."""

    def __init__(self, price: cost_estimate.ModelPrice, max_tokens: int, ceiling: float) -> None:
        self.price, self.max_tokens, self.ceiling = price, max_tokens, ceiling
        self.spent = 0.0
        self.pending_worst: float | None = None
        self.pending_counted = 0
        self.broken: str | None = None

    def admit(self, counted_input: int) -> None:
        if self.broken is not None:
            raise Refused(f"budget stop: {self.broken}")
        worst = (COUNT_MARGIN * counted_input * self.price.input_usd_per_million
                 + self.max_tokens * self.price.output_usd_per_million) / 1_000_000
        self.pending_counted = counted_input
        if self.spent + worst > self.ceiling:
            raise Refused(f"budget stop: ${self.spent:.4f} spent, a worst-case reply (${worst:.4f}) "
                          f"could cross the ${self.ceiling:.2f} ceiling")
        self.pending_worst = worst

    def charge(self, usage: Mapping[str, int]) -> None:
        worst = self.pending_worst or 0.0
        self.pending_worst = None
        fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        if any(usage.get(f, -1) < 0 for f in fields[:2]):
            self.spent += worst  # unreported usage is charged its worst case
            return
        tokens_in = usage["input_tokens"] + max(0, usage.get("cache_creation_input_tokens", 0)) \
            + max(0, usage.get("cache_read_input_tokens", 0))
        self.spent += (tokens_in * self.price.input_usd_per_million
                       + usage["output_tokens"] * self.price.output_usd_per_million) / 1_000_000
        if tokens_in > COUNT_MARGIN * self.pending_counted:
            self.broken = (f"a reply billed {tokens_in} input tokens against a count of {self.pending_counted}; "
                           "the count no longer bounds the spend")


def run(root: Path, declaration: Mapping[str, Any], labels_path: Path, *, key_provider: ja.KeyProvider,
        base_url: str = ja.DEFAULT_BASE_URL) -> dict[str, Any]:
    approval = declaration.get("approval")
    if not isinstance(approval, dict) or approval.get("declaration_digest") != digest(declaration) \
            or not approval.get("by") or not approval.get("source"):
        raise Refused("not approved: approval.declaration_digest must equal this declaration's digest, "
                      "with by and source recorded")
    items = items_of(root)
    names = [p.name for p in items]
    manifest = json.loads((root / "items-manifest.json").read_text())
    if sha256_bytes(json.dumps(manifest, sort_keys=True).encode()) != declaration["items_digest"]:
        raise Refused("the items manifest is not the declared one")
    labels, labels_sha = load_labels(labels_path, names)
    if labels_sha != declaration["labels_sha256"]:
        raise Refused(f"labels {labels_sha} are not the declared {declaration['labels_sha256']}")
    price = cost_estimate.ModelPrice(declaration["model"], declaration["price"]["input_usd_per_million"],
                                     declaration["price"]["output_usd_per_million"], declaration["price"]["source_url"])
    budget = Budget(price, int(declaration["max_tokens"]), cost_estimate.CEILING_USD)
    expected: dict[str, str] = {}

    def before_send(body: bytes) -> None:
        item_id = expected["item"]
        declared = declaration["counts"][item_id]
        if sha256_bytes(body) != declared["request_sha256"]:
            raise Refused(f"{item_id}: the request body changed after it was counted")
        budget.admit(int(declared["input_tokens"]))

    j = make_judge(key_provider=key_provider, base_url=base_url, max_tokens=int(declaration["max_tokens"]),
                   before_send=before_send, usage_sink=budget.charge)
    k = int(declaration["k"])
    outcomes: dict[str, list[dict[str, str]]] = {}
    calls = 0
    for item in items:
        expected["item"] = item.name
        outcomes[item.name] = []
        for _ in range(k):
            if calls >= int(declaration["calls"]):
                raise Refused("the declared call count is exhausted")
            calls += 1
            tier = judge.run_tier(judge.INDEPENDENT_TIER, j, CRITERIA, GOAL, item_files(item))
            got = {str(c["id"]): str(c["outcome"]) for c in tier.get("criteria") or []}  # type: ignore[union-attr]
            outcomes[item.name].append({c: got.get(c, "UNKNOWN") for c in CRITERIA})
    return {"calls": calls, "spent_usd": round(budget.spent, 4),
            "agreement": agreement(outcomes, labels, float(declaration["repeat_agreement_threshold"])),
            "outcomes": outcomes}


def agreement(outcomes: Mapping[str, Sequence[Mapping[str, str]]], labels: Mapping[str, Mapping[str, str]],
              threshold: float) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for c in CRITERIA:
        stable = matched = labelled = 0
        for item_id, runs in outcomes.items():
            votes = Counter(r[c] for r in runs)
            majority, top = votes.most_common(1)[0]
            stable += top == len(runs)
            if labels[item_id][c] != "UNKNOWN":
                labelled += 1
                matched += majority == labels[item_id][c]
        repeat = stable / len(outcomes)
        report[c] = {"items": len(outcomes), "repeat_agreement": round(repeat, 3),
                     "labelled": labelled, "majority_matches_label": matched,
                     "verdict": "UNKNOWN" if repeat < threshold else "reported"}
    return report


# ------------------------------------------------------------------ cli

def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="step", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run", type=Path, action="append", required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--seed", type=int, required=True)
    c = sub.add_parser("count")
    c.add_argument("--items", type=Path, required=True)
    c.add_argument("--secret-id", required=True)
    c.add_argument("--out", type=Path, required=True)
    d = sub.add_parser("declare")
    d.add_argument("--items", type=Path, required=True)
    d.add_argument("--counts", type=Path, required=True)
    d.add_argument("--labels", type=Path, required=True)
    d.add_argument("--price", type=Path, required=True, help="JSON: in/out USD per million, source_url, read_on")
    d.add_argument("--secret-id", required=True)
    d.add_argument("--k", type=int, default=3)
    d.add_argument("--max-tokens", type=int, default=1536)
    d.add_argument("--threshold", type=float, default=2 / 3)
    d.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--items", type=Path, required=True)
    r.add_argument("--declaration", type=Path, required=True)
    r.add_argument("--labels", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.step == "export":
            print(json.dumps(export(args.run, args.out, seed=args.seed)))
        elif args.step == "count":
            counts = count(args.items, make_judge(key_provider=ja.aws_secret_key_provider(args.secret_id)))
            args.out.write_text(json.dumps(counts, indent=1, sort_keys=True) + "\n")
            print(json.dumps({"items": len(counts), "input_tokens": sum(v["input_tokens"] for v in counts.values())}))
        elif args.step == "declare":
            data = declare(args.items, json.loads(args.counts.read_text()), args.labels, k=args.k,
                           max_tokens=args.max_tokens, price=json.loads(args.price.read_text()),
                           secret_id=args.secret_id, threshold=args.threshold)
            args.out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
            print(json.dumps({"digest": digest(data), "calls": data["calls"], "worst_case_usd": data["worst_case_usd"]}))
        else:
            if os.environ.get("SKILLC_ALLOW_PAID_JUDGE") != "1":
                raise Refused("a paid run needs SKILLC_ALLOW_PAID_JUDGE=1 in its environment")
            declaration = json.loads(args.declaration.read_text())
            result = run(args.items, declaration, args.labels,
                         key_provider=ja.aws_secret_key_provider(declaration["secret_id"]))
            args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
            print(json.dumps({"calls": result["calls"], "spent_usd": result["spent_usd"],
                              "agreement": result["agreement"]}))
    except (Refused, judge.JudgeUnavailable, judge.JudgeInputLeaked, ValueError, OSError) as exc:
        print(f"judge-validation: refused - {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
