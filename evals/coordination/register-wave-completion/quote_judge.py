"""Trusted judge: independent arithmetic and controller-frozen delivery facts."""

import itertools
import json
import sys
from decimal import ROUND_HALF_UP, Decimal


def judge(envelope):
    criteria = []
    try:
        trusted = json.loads(envelope["trusted"])
        assert trusted["version"] == 1 and trusted["task"] == "coordination-quote:1"
        assert len(trusted["patches"]) == 2 and trusted["service_attempt"]
        delivery = trusted["delivery"]
        assert delivery in ("SATISFIED", "VIOLATED")
    except (KeyError, ValueError, TypeError, AssertionError):
        trusted, delivery = None, "UNKNOWN"
    criteria.append({"id": "delivery", "mandatory": True, "outcome": delivery,
                     **({"missing": "controller delivery observation unavailable"} if delivery == "UNKNOWN"
                        else {"evidence": [json.dumps(trusted, sort_keys=True)]})})
    outcome, evidence = "UNKNOWN", "behavior observations unavailable or unbound"
    try:
        report = json.loads(envelope["observations"])
        vectors = list(itertools.product((0, 1, 2, 4), (0, 1, 7, 123, 199), (0, 500, 1300, 5000, 10000)))
        assert trusted and report["source"] == trusted["source"]
        assert len(report["rows"]) == len(vectors) == 100
        wrong = []
        for vector, row in zip(vectors, report["rows"], strict=True):
            assert row["input"] == list(vector)
            qty, unit, bp = vector
            net = int(Decimal(qty) * Decimal(unit))
            due = int((Decimal(net) * Decimal(bp) / Decimal(10000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            value = row.get("value")
            if (not isinstance(value, list) or len(value) != 3
                    or any(type(v) is not int for v in value) or value != [net, due, net + due]):
                wrong.append(vector)
        outcome = "VIOLATED" if wrong else "SATISFIED"
        evidence = f"100 public vectors executed; {len(wrong)} wrong; first={wrong[:1]}"
    except (KeyError, ValueError, TypeError, AssertionError):
        pass
    criteria.append({"id": "behavior", "mandatory": True, "outcome": outcome,
                     **({"missing": evidence} if outcome == "UNKNOWN" else {"evidence": [evidence]})})
    return {"grader": {"id": "coordination-quote", "revision": "1"}, "criteria": criteria}


if __name__ == "__main__":
    print(json.dumps(judge(json.load(sys.stdin))))
