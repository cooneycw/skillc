#!/usr/bin/env python3
"""Refuse a JUnit report that loses or substitutes collected pytest items (#364).

Collection is pytest --collect-only -q output, including its count summary.
Both counts and identities must match: a duplicate cannot replace a lost test.
--compare additionally requires identical per-test outcomes across two reports.
Durations, ordering, timestamps and machine paths are deliberately not compared.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

Identity = tuple[str, str]


def collected(path: Path) -> set[Identity]:
    text = path.read_text(encoding="utf-8")
    items: list[Identity] = []
    for line in text.splitlines():
        if not re.match(r"[^\s].*\.py::", line):
            continue
        # Match pytest's JUnit mangling: split only before the parameter id,
        # which may itself contain dots, slashes or '::'.
        main, bracket, params = line.partition("[")
        parts = main.split("::")
        parts[0] = parts[0].removesuffix(".py").replace("/", ".")
        items.append((".".join(parts[:-1]), parts[-1] + bracket + params))
    summaries = re.findall(r"^(\d+)(?:/\d+)? tests? collected\b", text, re.MULTILINE)
    if len(summaries) != 1 or int(summaries[0]) != len(items) or not items:
        raise ValueError("collection must contain a nonempty population and one matching count summary")
    if len(set(items)) != len(items):
        raise ValueError("collection contains duplicate test identities")
    return set(items)


def outcomes(path: Path) -> dict[Identity, str]:
    tree = ET.parse(path)
    if tree.getroot().tag not in {"testsuites", "testsuite"}:
        raise ValueError("report root must be testsuites or testsuite")
    result: dict[Identity, str] = {}
    for case in tree.iter("testcase"):
        classname, name = case.get("classname"), case.get("name")
        if not classname or not name:
            raise ValueError("testcase lacks classname or name")
        groups = [prop.get("value", "") for prop in case.findall("properties/property")
                  if prop.get("name") == "skillc_xdist_group"]
        if len(groups) > 1 or (groups and not groups[0]):
            raise ValueError("invalid xdist group property")
        if groups:
            # Our collection hook records the exact scheduler suffix, on both
            # serial and worker runs. Never strip arbitrary '@' parameter text.
            name = name.removesuffix("@" + groups[0])
        key = classname, name
        if key in result:
            raise ValueError(f"duplicate testcase: {key}")
        statuses = [node for node in case if node.tag in {"skipped", "failure", "error"}]
        if len(statuses) > 1:
            raise ValueError(f"ambiguous testcase outcome: {key}")
        status = "passed"
        if statuses:
            node = statuses[0]
            status = node.tag
            if status == "skipped" and node.get("type") == "pytest.xfail":
                status = "xfail"
        result[key] = status
    if not result:
        raise ValueError("report contains no testcases")
    return result


def check(collection: Path, report: Path, compare: Path | None = None) -> str:
    expected = collected(collection)
    actual = outcomes(report)
    missing, extra = expected - actual.keys(), actual.keys() - expected
    if missing or extra:
        raise ValueError(f"population mismatch: collected={len(expected)}, reported={len(actual)}, "
                         f"missing={sorted(missing)}, unexpected={sorted(extra)}")
    if compare is not None:
        other = outcomes(compare)
        differences = [(key, actual.get(key), other.get(key))
                       for key in sorted(actual.keys() | other.keys())
                       if actual.get(key) != other.get(key)]
        if differences:
            raise ValueError(f"per-test outcomes differ: {differences}")
    counts = dict(sorted(Counter(actual.values()).items()))
    return f"{len(expected)} collected identities match report; outcomes={counts}" + (
        "; comparison has identical per-test outcomes" if compare is not None else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.collection, args.report, args.compare)
    except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
        print(f"pytest-population: FAIL - {exc}", file=sys.stderr)
        return 1
    print(f"pytest-population: ok - {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
