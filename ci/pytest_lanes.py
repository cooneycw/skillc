"""Collection-time lane partition; never skips a selected item (#462)."""
from __future__ import annotations

import pytest

from ci.merge_pytest_reports import SERIAL_FILE


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--skillc-test-lane", choices=("ordinary", "serial"), default=None)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    lane = config.getoption("skillc_test_lane")
    if lane is None:
        return
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        is_serial = item.nodeid.split("::", 1)[0] == SERIAL_FILE
        (kept if is_serial == (lane == "serial") else deselected).append(item)
    items[:] = kept
    config.hook.pytest_deselected(items=deselected)
