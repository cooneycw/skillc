"""No-leak controls for Contract A part 2 (#797 A-2).

The teardown evidence holds container ids, pids, cgroup paths, namespace
inodes and bind sources. A synthetic marker is planted in a fake cgroup path
and in a bind source directory name, and neither it nor the container id may
appear in any repr, observation or refusal (or its exception chain), or in
captured output (the autouse audit from test_remnant_scan). A leaking repr
twin must fail the oracle, and the identity refuses pickle and copy.
"""
from __future__ import annotations

import copy
import os
import pickle
import sys
from pathlib import Path

import pytest
from test_remnant_scan import audit_captured_output, no_marker, references  # noqa: F401
from test_run_window_teardown import CID, CONTAINER_NS, DIR, PROC_ROW, ROOT_ROW, FakeDocker, FakeProc, proc_entry, table

from skillc import run_window_absence as ra
from skillc import run_window_teardown as rt
from skillc.remnant_scan import References

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A requires Linux O_PATH and /proc')


def marked_capture(tmp_path: Path) -> tuple[rt.LaunchIdentity, References]:
    refs = references(filename=True)
    marker = os.fsdecode(refs._values[0])
    bind = tmp_path.resolve() / marker
    bind.mkdir()
    docker = FakeDocker()
    docker.info = {**docker.info, 'Mounts': [{'Type': 'bind', 'Source': str(bind), 'Destination': '/w'}]}
    proc = FakeProc({'1': proc_entry('1'),
                     '4242': proc_entry('4242', cgroup='/docker/' + marker + f'/{CID}', ns=CONTAINER_NS,
                                        root_view={'/': DIR, '/w': DIR},
                                        mountinfo=table(ROOT_ROW, PROC_ROW, '81 1 0:1 / /w rw - ext4 /dev/x rw'))})
    ident = rt.capture_launch_identity('skillc-attempt', generation=object(), docker=docker, proc=proc)
    assert ident.usable
    return ident, refs


def test_identity_and_observations_disclose_nothing(tmp_path: Path) -> None:
    ident, refs = marked_capture(tmp_path)
    results = [ident, rt.fact_channel_isolated([ident]),
               rt.confirm_teardown([ident], docker=FakeDocker(present=False),
                                   proc=FakeProc({'1': proc_entry('1')}))]
    assert results[2] is ra.NEG
    out = '\n'.join(f'{r!r}\n{r!s}' for r in results).encode('utf-8', 'surrogateescape')
    no_marker(out, refs)
    no_marker(out, References((CID.encode(),)))
    assert b'4242' not in out


def test_capture_refusal_is_fixed_text() -> None:
    with pytest.raises(ra.CensusRefused) as caught:
        rt.capture_launch_identity(CID, generation=None, docker=FakeDocker(), proc=FakeProc({}))
    assert CID not in str(caught.value) and caught.value.__context__ is None


def test_identity_refuses_pickle_and_copy(tmp_path: Path) -> None:
    ident, _ = marked_capture(tmp_path)
    for attempt in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            attempt(ident)


class LeakingIdentity(rt.LaunchIdentity):
    def __repr__(self) -> str:
        return '<LaunchIdentity ' + ' '.join(path for _, _, path in self._cgroups) + '>'


def test_oracle_rejects_a_leaking_identity_twin(tmp_path: Path) -> None:
    ident, refs = marked_capture(tmp_path)
    leaking = LeakingIdentity(object())
    leaking._cgroups = ident._cgroups
    with pytest.raises(AssertionError):
        no_marker(repr(leaking).encode('utf-8', 'surrogateescape'), refs)
    no_marker(repr(ident).encode('utf-8', 'surrogateescape'), refs)
