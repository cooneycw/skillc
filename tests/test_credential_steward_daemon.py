"""#518 review: the in-container credential steward's OWN behaviour, run on the
host against a temporary directory (inotify, no docker). Its events are
collected in place of the trigger socket. The real container run is
`test_credential_steward_live.py`; these are the reds that need a filesystem
an attacker can shape, which a live run cannot set up cheaply:

- a planted symlink is never followed by a root read, write or unlink;
- the restore is the steward's own, and its own write is never counted as a
  client read;
- a re-created file is captured only once its writer closes it;
- a capture that fails after a re-creation stays reported;
- a watch the kernel invalidates is reported, never silently lost.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import credential_steward as cs

pytestmark = pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs Linux inotify and /proc")
DUMMY = b'{"tokens": {"refresh_token": "rt-DUMMY"}}\n'


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("skillc_credential_steward_daemon", cs.STEWARD_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Steward:
    def __init__(self, tmp: Path, *, quiet_s: float = 0.3, deadline_s: float = 5.0) -> None:
        self.mod = _load()
        self.events: list[tuple[str, dict[str, int]]] = []
        self.mod._send = lambda event, **counts: self.events.append((event, counts))
        self.home, self.vault = tmp / "home" / ".codex", tmp / "vault"
        self.home.mkdir(parents=True)
        (self.home / "auth.json").write_bytes(DUMMY)
        self.thread = threading.Thread(target=self.mod.run, args=(str(self.home), str(self.vault), quiet_s, deadline_s),
                                       daemon=True)

    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def wait(self, event: str, count: int = 1, seconds: float = 10.0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.names().count(event) >= count:
                return True
            time.sleep(0.02)
        return False

    def read_like_the_client(self) -> None:
        for _ in range(4):
            (self.home / "auth.json").read_bytes()

    def withdrawn(self) -> None:
        self.thread.start()
        assert self.wait("armed")
        self.read_like_the_client()
        assert self.wait("withdrawn"), self.events
        assert not (self.home / "auth.json").exists()

    def rearm(self) -> None:
        self.mod._rearm = True

    def stop(self) -> None:
        self.mod._stop = True
        self.thread.join(5)
        assert not self.thread.is_alive()


@pytest.fixture
def steward(tmp_path: Path) -> Iterator[Steward]:
    s = Steward(tmp_path)
    yield s
    s.mod._stop = True
    if s.thread.is_alive():
        s.thread.join(5)


def test_withdraw_then_restore_then_withdraw_again(steward: Steward) -> None:
    steward.withdrawn()
    assert (steward.vault / "auth.json").read_bytes() == DUMMY
    steward.rearm()
    assert steward.wait("armed", 2)
    restored = os.stat(steward.home / "auth.json")
    assert (steward.home / "auth.json").read_bytes() == DUMMY and restored.st_mode & 0o777 == 0o600
    assert (restored.st_uid, restored.st_gid) == (os.stat(steward.home).st_uid, os.stat(steward.home).st_gid)
    steward.read_like_the_client()
    assert steward.wait("withdrawn", 2)
    steward.stop()
    assert steward.names() == ["armed", "withdrawn", "armed", "withdrawn", "stopped"]


def test_red_the_restore_is_not_counted_as_a_client_read(tmp_path: Path) -> None:
    """Re-armed with no client read after it, the steward has no evidence the
    client loaded the file: only the deadline withdraws it, with zero opens."""
    steward = Steward(tmp_path, deadline_s=1.5)
    steward.withdrawn()
    steward.rearm()
    assert steward.wait("armed", 2)
    assert steward.wait("withdrawn-at-deadline"), steward.events
    steward.stop()
    assert steward.events[-2] == ("withdrawn-at-deadline", {"opens": 0, "closes": 0})


def test_red_a_planted_symlink_is_never_followed(steward: Steward, tmp_path: Path) -> None:
    """While withdrawn, the candidate plants `auth.json -> victim`: the steward
    must neither read the victim into the vault nor unlink through the link."""
    victim = tmp_path / "victim"
    victim.write_bytes(b"ROOT-ONLY")
    steward.withdrawn()
    (steward.home / "auth.json").symlink_to(victim)
    assert steward.wait("error"), steward.events
    assert victim.read_bytes() == b"ROOT-ONLY"
    assert (steward.vault / "auth.json").read_bytes() == DUMMY
    assert "refreshed-captured" not in steward.names()


def test_red_the_restore_replaces_a_planted_link_rather_than_writing_through_it(steward: Steward,
                                                                                tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"ROOT-ONLY")
    steward.withdrawn()
    os.symlink(victim, steward.home / steward.mod.RESTORE_TMP)  # the restore's own temporary name
    steward.rearm()
    assert steward.wait("armed", 2), steward.events
    assert victim.read_bytes() == b"ROOT-ONLY"
    assert not (steward.home / "auth.json").is_symlink() and (steward.home / "auth.json").read_bytes() == DUMMY


def test_red_a_recreation_is_captured_only_after_its_writer_closes(steward: Steward) -> None:
    steward.withdrawn()
    with open(steward.home / "auth.json", "wb") as handle:
        handle.write(b'{"part": 1,')
        handle.flush()
        time.sleep(0.6)  # far past the old fixed 50 ms
        handle.write(b' "part": 2}')
    assert steward.wait("refreshed-captured"), steward.events
    assert (steward.vault / "auth.json").read_bytes() == b'{"part": 1, "part": 2}'
    assert (steward.vault / "auth.previous.json").read_bytes() == DUMMY
    assert not (steward.home / "auth.json").exists()


def test_red_a_failed_capture_after_a_recreation_stays_reported(steward: Steward) -> None:
    steward.withdrawn()
    (steward.vault / ".auth.json.tmp").mkdir()  # the capture's write fails, root or not
    (steward.home / "auth.json").write_bytes(b"rotated")
    assert steward.wait("error"), steward.events
    assert "refreshed-captured" not in steward.names()
    (steward.vault / ".auth.json.tmp").rmdir()
    assert steward.wait("refreshed-captured", seconds=6), steward.events  # still latched, retried
    steward.stop()
    record = _record(steward.events)
    assert record["status"] == "refreshed" and record["errors"] == 1


def test_red_an_invalidated_watch_is_reported(steward: Steward) -> None:
    """The kernel drops the watch when its directory is moved away: events
    after that are lost, so the record must not read held."""
    steward.withdrawn()
    steward.home.rename(steward.home.with_name("moved"))
    assert steward.wait("error"), steward.events
    steward.stop()
    assert _record(steward.events)["status"] == "unknown"


def test_a_nameless_overflow_event_is_parsed(tmp_path: Path) -> None:
    mod = _load()
    read, write = os.pipe()
    os.write(write, mod.struct.pack("iIII", -1, mod.IN_Q_OVERFLOW, 0, 0))
    assert mod._events(read, 1.0) == [mod.IN_Q_OVERFLOW]
    os.write(write, mod.struct.pack("iIII", 1, mod.IN_OPEN, 0, 16) + b"other.json".ljust(16, b"\0"))
    assert mod._events(read, 1.0) == []


def _record(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    session = cs.CredentialStewardSession("a-1")
    for seq, (event, counts) in enumerate(events, start=1):
        session.decide({"op": "credential_steward", "event": event, "seq": seq,
                        "opens": counts.get("opens", 0), "closes": counts.get("closes", 0)})
    return session.finalize(expected_arms=[e for e, _ in events].count("armed"))
