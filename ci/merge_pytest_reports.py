"""Merge both required lane reports against one independent full collection (#462)."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ci.check_pytest_population import check, collected, outcomes

SERIAL_CLASS = "tests.test_load_harness"
SERIAL_FILE = "tests/test_load_harness.py"


def serial_identity(classname: str) -> bool:
    return classname == SERIAL_CLASS or classname.startswith(SERIAL_CLASS + ".")


def merge(collection: Path, ordinary: Path, serial: Path, output: Path) -> str:
    paths = [collection, ordinary, serial, output]
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("collection, lane reports and output must be distinct files")
    output.unlink(missing_ok=True)
    expected = collected(collection)
    combined: ET.Element = ET.Element("testsuites")
    seen: set[tuple[str, str]] = set()
    for lane, path in (("ordinary", ordinary), ("serial", serial)):
        root = ET.parse(path).getroot()
        if root.tag not in {"testsuite", "testsuites"}:
            raise ValueError(f"{lane} report has invalid root")
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        if not suites:
            raise ValueError(f"{lane} report has no testsuite")
        for suite in suites:
            if int(suite.get("tests", "-1")) != len(list(suite.iter("testcase"))):
                raise ValueError(f"{lane} report has inconsistent declared population")
        required = {key for key in expected if serial_identity(key[0]) == (lane == "serial")}
        if not required and not list(root.iter("testcase")):
            actual: dict[tuple[str, str], str] = {}
        else:
            actual = outcomes(path)
        duplicate = seen.intersection(actual)
        if duplicate:
            raise ValueError(f"duplicate identities across lanes: {sorted(duplicate)}")
        if set(actual) != required:
            raise ValueError(f"{lane} population mismatch: missing={sorted(required - actual.keys())}, "
                             f"unexpected={sorted(actual.keys() - required)}")
        seen.update(actual)
        if root.tag == "testsuite":
            combined.append(root)
        else:
            combined.extend(root.findall("testsuite"))
    # Only a complete pair can publish the report consumed by the downstream gates.
    temporary = output.with_name(output.name + ".tmp")
    try:
        ET.ElementTree(combined).write(temporary, encoding="utf-8", xml_declaration=True)
        message = check(collection, temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("ordinary", type=Path)
    parser.add_argument("serial", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        message = merge(args.collection, args.ordinary, args.serial, args.output)
    except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
        print(f"pytest-lanes: FAIL - {exc}", file=sys.stderr)
        return 1
    print(f"pytest-lanes: ok - {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
