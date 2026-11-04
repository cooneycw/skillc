"""Trusted independent Decimal oracle; participant success claims are unused."""
import itertools
import json
import sys
from decimal import ROUND_HALF_UP, Decimal


def judge(envelope):
    delivery, behavior = "UNKNOWN", "UNKNOWN"
    try:
        trusted = json.loads(envelope["trusted"])
        assert trusted["task"] == "wave-rehearsal-quote:1"
        assert trusted["delivery"] in ("SATISFIED", "VIOLATED")
        delivery = trusted["delivery"]
        report = json.loads(envelope["observations"])
        vectors = list(itertools.product((0, 1, 2, 4), (0, 1, 7, 123, 199), (0, 500, 1300, 5000, 10000)))
        assert len(report["rows"]) == len(vectors) == 100
        correct = True
        for vector, row in zip(vectors, report["rows"], strict=True):
            assert row["input"] == list(vector)
            qty, unit, bp = vector
            net = Decimal(qty) * Decimal(unit)
            tax = (net * Decimal(bp) / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            expected = [int(net), int(tax), int(net + tax)]
            actual = row.get("value")
            correct = correct and (isinstance(actual, list) and len(actual) == 3
                                   and all(type(item) is int for item in actual) and actual == expected)
        behavior = "SATISFIED" if correct else "VIOLATED"
    except (KeyError, ValueError, TypeError, AssertionError):
        pass
    criteria = []
    for key, outcome in (("delivery", delivery), ("behavior", behavior)):
        detail = {"missing": "complete bound observation unavailable"} if outcome == "UNKNOWN" else {
            "evidence": ["controller remote delivery and 100 independent arithmetic vectors"]}
        criteria.append({"id": key, "mandatory": True, "outcome": outcome, **detail})
    return {"grader": {"id": "wave-rehearsal-quote", "revision": "1"}, "criteria": criteria}


if __name__ == "__main__":
    print(json.dumps(judge(json.load(sys.stdin))))
