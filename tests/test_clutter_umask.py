"""#727: a delivered file is matched the way git sees it - same bytes, same
owner-execute bit - whatever the umask that created it.

Every case runs under umask 022, 0002 and 077 (the orchestrator's gate), so the
tolerance is shown general rather than tuned to one value. The NOT_CLEAN cases
are the point: the census became MORE tolerant, and each case here names an
input it must still call clutter.
"""
from __future__ import annotations

import copy
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_clutter_capture import git, inventory
from test_clutter_capture import namespace as namespace  # noqa: PLC0414

from skillc import clutter as c
from skillc import clutter_capture as capture
from skillc import clutter_delivery as delivery
from skillc import git_snapshot as gs

UMASKS = (0o022, 0o002, 0o077)
FILE = 'file:/work/repo/nhl/api.py'


@pytest.fixture(params=UMASKS, ids=lambda m: f'umask-{m:04o}')
def umask(request: pytest.FixtureRequest) -> Iterator[int]:
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


def _deliver(namespace: tuple[Path, c.Policy, Path], case: str) -> dict[str, Any]:
    """Commit and push nhl/api.py, apply `case` to the workspace, classify."""
    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['delivered'] = []
    raw['delivered_commit_roles'] = ['agent']
    policy = c.parse_policy(raw)
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    repo = root / 'work/repo'
    (repo / 'nhl').mkdir()
    api = repo / 'nhl/api.py'
    api.write_text('source\n')
    if case == 'executable-dropped':
        api.chmod(api.stat().st_mode | stat.S_IXUSR)  # delivered as 100755
    git(repo, 'add', 'nhl/api.py')
    git(repo, 'commit', '-qm', 'delivered source')
    git(repo, 'push', str(root / 'work/fixture.git'), 'main')
    mode = stat.S_IMODE(api.stat().st_mode)
    if case == 'extra':
        (repo / 'leftover.txt').write_text('not delivered')
    elif case == 'content':
        api.write_text('uncommitted replacement\n')
    elif case == 'executable-added':
        api.chmod(mode | stat.S_IXUSR)  # delivered 100644, now executable
    elif case == 'executable-dropped':
        api.chmod(mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))  # delivered 100755, now not
    elif case == 'setuid':
        api.chmod(mode | stat.S_ISUID)
    elif case == 'group-writable':
        api.chmod(mode | stat.S_IWGRP | stat.S_IWOTH)  # the documented blind spot: still delivered
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    commit = remote.refs()['refs/heads/main']
    after = observer.capture('after')
    binding = delivery.handoff_binding(policy, before, after)
    evidence = {'agent': delivery.capture_commit('agent', remote, commit, binding=binding)}
    handoff = {'binding': binding, 'role_stops': {'agent': 'confirmed'},
               'helper_stop': 'confirmed', 'delivered_commits': {'agent': commit}}
    return c.classify(policy, before, after, delivered_captures=evidence, delivered_handoff=handoff)


def _clutter(report: dict[str, Any]) -> set[str]:
    return {row['key'] for row in report['additions']['clutter']}


def test_a_delivered_file_reads_delivered_under_any_umask(
        namespace: tuple[Path, c.Policy, Path], umask: int) -> None:
    """The bug (#727): under umask 0002 a correctly delivered file was 0o664
    on disk, never matched git's 100644, and read as clutter."""
    report = _deliver(namespace, 'delivered')
    assert report['status'] == 'CLEAN', report['additions']['clutter']
    assert report['counts']['delivered'] == 2  # the package directory and the file


@pytest.mark.parametrize(('case', 'key'), [
    ('extra', 'file:/work/repo/leftover.txt'),
    ('content', FILE),
    ('executable-added', FILE),
    ('executable-dropped', FILE),
    ('setuid', FILE),
])
def test_a_real_difference_is_still_clutter_under_any_umask(
        namespace: tuple[Path, c.Policy, Path], umask: int, case: str, key: str) -> None:
    report = _deliver(namespace, case)
    assert report['status'] == 'NOT_CLEAN' and key in _clutter(report), report['additions']


def test_group_and_world_write_bits_are_the_named_blind_spot(
        namespace: tuple[Path, c.Policy, Path], umask: int) -> None:
    """Git cannot record them, so a delivered file carrying them still reads
    delivered. Documented in docs/specs/evaluation-facility/clutter.md."""
    assert _deliver(namespace, 'group-writable')['status'] == 'CLEAN'


# ---------------------------------------------------------------- the git rule, directly


def _expect(executable: bool, data: bytes = b'source\n') -> delivery.Expected:
    import hashlib

    return delivery.Expected('file', executable, hashlib.sha256(data).hexdigest(), '')


def _observed(mode: int, data: bytes = b'source\n') -> str:
    import hashlib

    return c.digest({'mode': mode, 'digest': hashlib.sha256(data).hexdigest()})


@pytest.mark.parametrize(('mode', 'executable', 'accepted'), [
    (0o644, False, True), (0o664, False, True), (0o600, False, True), (0o666, False, True), (0o000, False, True),
    (0o755, True, True), (0o775, True, True), (0o700, True, True), (0o744, True, True),
    (0o755, False, False), (0o744, False, False), (0o100, False, False),
    (0o644, True, False), (0o655, True, False),  # only S_IXUSR counts, as in git
    (0o4644, False, False), (0o2644, False, False), (0o1644, False, False), (0o4755, True, False),
])
def test_accepts_follows_gits_owner_execute_rule(mode: int, executable: bool, accepted: bool) -> None:
    assert delivery.accepts(_expect(executable), _observed(mode)) is accepted


def test_accepts_needs_the_same_bytes() -> None:
    assert not delivery.accepts(_expect(False), _observed(0o644, b'other\n'))


def test_the_candidate_cost_is_bounded_per_added_delivered_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate's cost pin: at most 256 candidate digests per added delivered
    file (the 0o777 modes whose S_IXUSR agrees), never more, however large
    the delivered set."""
    calls = 0
    real = delivery.digest

    def counting(value: object) -> str:
        nonlocal calls
        calls += 1
        return real(value)

    monkeypatch.setattr(delivery, 'digest', counting)
    files = 300
    for n in range(files):
        assert not delivery.accepts(_expect(n % 2 == 0, f'{n}'.encode()), _observed(0o4644))  # worst case: no match
    assert calls == files * delivery.CANDIDATES_PER_FILE == files * 256
