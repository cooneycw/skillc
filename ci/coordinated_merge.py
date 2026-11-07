#!/usr/bin/env python3
"""Merge one skillc PR under Kyle's ``main-merge`` lease and barrier (Kyle #2130).

**Merger tool. Never run in CI.** It is what a merger runs instead of a bare
``gh pr merge``, and it needs a merger's credentials: ``gh``'s own auth and a
Kyle coordination service principal. CI must never hold either, and must never
acquire ``main-merge`` (see "Why CI never acquires" below).

**Inert until the joint switch.** Unless :func:`admission_on` reads the
switch as on, it refuses with exit 2 and touches nothing: until the owner
switches all three repositories together, the legacy merge procedure governs.
Nothing in this repository calls it. The switch is the same flag file CPP's
client helpers read, ON only for the exact bytes ``on\n``, so the joint switch
is one action for both clients. ``SKILLC_COORDINATION_ADMISSION_FILE``
overrides its path, for tests.

The merge-intent state file lives under an explicit ``--state-dir`` with no
default: it is the recovery record, so it belongs where it survives a respawn
(``/workspace`` in a session container), not wherever ``$HOME`` happens to be.

The client is Kyle's ``scripts/kyle-lock``, named explicitly by
``KYLE_LOCK_CLIENT`` (no default, the same rule kyle-lock applies to its own
URL and token). kyle-lock reads ``KYLE_LOCK_URL`` and ``KYLE_LOCK_TOKEN`` /
``KYLE_LOCK_TOKEN_FILE`` itself; this tool never sees the token.

Sequence (ADR 0011 D3):

1. ``acquire main-merge`` until held. Queued, frozen, refused or unavailable
   ends here with **zero** merge calls.
2. Exact-head validation: the PR is open, its head is ``--head``, and Kyle's
   CI evidence for the PR is success on that same SHA.
3. ``begin-merge`` records UNKNOWN intent durably **before** any merge call.
4. The local state file is marked ``merge_sent`` **before** ``gh pr merge``, so
   no rerun can ever issue a second, possibly ambiguous, merge.
5. ``gh pr merge --squash --match-head-commit <head>``, then the squash SHA is
   read back from GitHub and ``record-merge`` attaches it to the same barrier.
6. The lease is renewed while the exact main push pipeline (sha, push, main) is
   read until terminal. Green exits 0; red exits 1 and is never success.

The barrier, not the lease, is what holds successors: if this process dies at
any point after step 3, Kyle's barrier keeps ``main-merge`` blocked. An
UNKNOWN outcome is resolved only by tier 3 (``kyle-lock resolve-barrier``);
this tool never infers "no merge" from GitHub.

Why CI never acquires: the merger holds ``main-merge`` while it waits for the
main push pipeline. A pipeline step that acquired ``main-merge`` would wait for
the merger, which is waiting for it. ``ci/merge_admission.py`` is the gate that
fails a pipeline doing so.

Exit codes: 0 merged and main green; 1 merged and main red; 2 usage or
admission off; 3 refused (including a failed exact-head check); 4 merge outcome
unknown (rerun with ``--resume``, or tier-3 resolution); 10 queued; 11 frozen;
12 lease lost; 75 coordination or CI evidence unavailable.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = "cooneycw/skillc"
RESOURCE = "main-merge"
ADMISSION_FILE_ENV = "SKILLC_COORDINATION_ADMISSION_FILE"
ADMISSION_ON = b"on\n"
CLIENT_ENV = "KYLE_LOCK_CLIENT"

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_UNKNOWN = 4
EXIT_QUEUED = 10
EXIT_FROZEN = 11
EXIT_LOST = 12
EXIT_UNAVAILABLE = 75

SHA_RE = re.compile(r"[0-9a-f]{40}")

#: Called as lock(argv) -> (exit code, parsed JSON object or None).
LockCall = Callable[[list[str]], tuple[int, Any]]
#: Called as gh(argv) -> (exit code, stdout).
GhCall = Callable[[list[str]], tuple[int, str]]


def admission_file() -> Path:
    override = os.environ.get(ADMISSION_FILE_ENV)
    if override:
        return Path(override)
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "claude-power-pack" / "coordination" / "admission"


def admission_on() -> bool:
    """The one place the switch is read. Missing, unreadable or any other
    bytes are OFF: only an explicit ``on\\n`` admits."""
    try:
        return admission_file().read_bytes() == ADMISSION_ON
    except OSError:
        return False


def _log(message: str) -> None:
    print(f"coordinated-merge: {message}", file=sys.stderr, flush=True)


def subprocess_lock(client: str) -> LockCall:
    def call(argv: list[str]) -> tuple[int, Any]:
        done = subprocess.run([client, *argv], capture_output=True, text=True, check=False)
        try:
            answer = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else None
        except (json.JSONDecodeError, IndexError):
            answer = None
        return done.returncode, answer
    return call


def subprocess_gh(argv: list[str]) -> tuple[int, str]:
    done = subprocess.run(["gh", *argv], capture_output=True, text=True, check=False)
    return done.returncode, done.stdout


@dataclass
class Settings:
    pr: int
    head: str
    state_dir: Path
    resume: bool = False
    acquire_wait: float = 600.0
    ci_timeout: float = 3600.0
    poll: float = 20.0


class Merger:
    def __init__(self, settings: Settings, lock: LockCall, gh: GhCall,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.s = settings
        self.lock = lock
        self.gh = gh
        self.sleep = sleep
        self.clock = clock
        self.state: dict[str, Any] = {}

    # -- local recovery state ------------------------------------------------

    @property
    def state_path(self) -> Path:
        return self.s.state_dir / f"{REPO.replace('/', '__')}-pr{self.s.pr}.json"

    def _save(self, **changes: Any) -> None:
        """Durable before it returns: the merge call trusts it."""
        self.state.update(changes)
        self.s.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.state, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.state_path)
        directory = os.open(self.s.state_dir, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _fence(self) -> list[str]:
        return ["--request-id", str(self.state["request_id"]),
                "--lease-id", str(self.state["lease_id"]),
                "--generation", str(self.state["generation"])]

    # -- steps ---------------------------------------------------------------

    def run(self) -> int:
        """One process per PR record: a concurrent resume would otherwise
        read the same phase and issue the same merge twice."""
        self.s.state_dir.mkdir(parents=True, exist_ok=True)
        with self.state_path.with_suffix(".lock").open("a") as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _log(f"another merger process holds {self.state_path}; refusing")
                return EXIT_REFUSED
            return self._run_locked()

    def _run_locked(self) -> int:
        if self.state_path.exists():
            if not self.s.resume:
                _log(f"{self.state_path} records an unfinished merge; rerun with --resume")
                return EXIT_REFUSED
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (self.state.get("pr"), self.state.get("head")) != (self.s.pr, self.s.head):
                _log("the recorded merge is for a different PR or head; refusing")
                return EXIT_REFUSED
        elif self.s.resume:
            _log("nothing to resume")
            return EXIT_REFUSED
        phase = self.state.get("phase")
        if phase is None:
            code = self._acquire()
            if code:
                return code
            phase = "held"
        if phase == "held":
            code = self._validate_head()
            if code:
                # No intent exists yet, so nothing needs recovering.
                self._release()
                self.state_path.unlink(missing_ok=True)
                return code
            # From here an intent may exist, so the record is never deleted.
            self._save(phase="begin_pending")
            code = self._begin()
            if code:
                return code
            phase = "begun"
        elif phase == "begin_pending":
            # The begin response was lost: re-ask the idempotent begin, then
            # validate again, since the head may have moved meanwhile.
            code = self._begin()
            if code:
                return code
            code = self._validate_head()
            if code:
                _log(f"barrier {self.state.get('barrier_id')} records intent with no merge sent; "
                     "it stays blocked until tier 3 resolves it (resolve-barrier --outcome closed)")
                return EXIT_UNKNOWN
            phase = "begun"
        if phase == "begun":
            # Mark BEFORE the call, durably: from here a rerun never merges again.
            try:
                self._save(phase="merge_sent")
            except OSError as exc:
                _log(f"could not persist the merge marker ({exc}); not merging")
                return EXIT_UNAVAILABLE
            merged, _ = self.gh(["pr", "merge", str(self.s.pr), "--repo", REPO, "--squash",
                                 "--match-head-commit", self.s.head])
            if merged:
                _log(f"gh pr merge exited {merged}; reading the outcome back from GitHub")
            phase = "merge_sent"
        if phase == "merge_sent":
            code = self._record()
            if code:
                return code
            phase = "recorded"
        if phase == "recorded":
            return self._await_main()
        _log(f"unreadable recorded phase {phase!r}; refusing")
        return EXIT_REFUSED

    def _acquire(self) -> int:
        key = f"skillc-merge-pr{self.s.pr}-{uuid.uuid4().hex[:12]}"
        deadline = self.clock() + self.s.acquire_wait
        while True:
            code, answer = self.lock(["acquire", RESOURCE, "--request-key", key,
                                      "--pr", str(self.s.pr), "--purpose", f"merge {REPO}#{self.s.pr}"])
            answer = answer if isinstance(answer, dict) else {}
            if code == 0 and answer.get("state") == "held":
                fence = {k: answer.get(k) for k in ("request_id", "lease_id", "generation")}
                if not (isinstance(fence["request_id"], int) and isinstance(fence["generation"], int)
                        and isinstance(fence["lease_id"], str) and fence["lease_id"]):
                    _log("held answer without a usable fence; refusing")
                    return EXIT_UNAVAILABLE
                self._save(pr=self.s.pr, head=self.s.head, phase="held", **fence)
                return EXIT_OK
            if code not in (EXIT_QUEUED, EXIT_FROZEN, EXIT_UNAVAILABLE):
                _log(f"acquire refused (exit {code}): {answer.get('reason', answer.get('state'))}")
                return EXIT_REFUSED if code != EXIT_LOST else EXIT_LOST
            if self.clock() >= deadline:
                if code == EXIT_QUEUED and isinstance(answer.get("request_id"), int):
                    self.lock(["cancel", RESOURCE, "--request-id", str(answer["request_id"])])
                _log(f"no grant within {self.s.acquire_wait:g}s (last: {answer.get('state')})")
                return code
            self.sleep(float(answer.get("retry_after") or self.s.poll))

    def _validate_head(self) -> int:
        code, out = self.gh(["pr", "view", str(self.s.pr), "--repo", REPO,
                             "--json", "state,headRefOid,isDraft"])
        try:
            view = json.loads(out) if code == 0 else None
        except json.JSONDecodeError:
            view = None
        if not isinstance(view, dict):
            _log("could not read the PR from GitHub")
            return EXIT_UNAVAILABLE
        if view.get("state") != "OPEN" or view.get("isDraft"):
            _log(f"PR is {view.get('state')} (draft={view.get('isDraft')}); refusing")
            return EXIT_REFUSED
        if view.get("headRefOid") != self.s.head:
            _log(f"PR head is {view.get('headRefOid')}, not the validated {self.s.head}; refusing")
            return EXIT_REFUSED
        code, answer = self.lock(["ci", "--repo", REPO, "--pr", str(self.s.pr)])
        answer = answer if isinstance(answer, dict) else {}
        if code == EXIT_OK and answer.get("sha", "").lower() == self.s.head:
            return EXIT_OK
        if code == EXIT_OK:
            _log(f"CI evidence is for {answer.get('sha')}, not {self.s.head}; refusing")
            return EXIT_REFUSED
        _log(f"PR CI is not green on {self.s.head} (exit {code}); refusing")
        return EXIT_REFUSED if code in (EXIT_RED, EXIT_REFUSED) else EXIT_UNAVAILABLE

    def _begin(self) -> int:
        code, answer = self.lock(["begin-merge", RESOURCE, *self._fence(),
                                  "--repo", REPO, "--pr", str(self.s.pr)])
        barrier = answer.get("barrier") if isinstance(answer, dict) else None
        if code != EXIT_OK or not isinstance(barrier, dict) or not isinstance(barrier.get("id"), int):
            _log(f"begin-merge was not confirmed (exit {code}); no merge was attempted")
            # Unconfirmed: the intent may or may not exist. Keep the fence on
            # disk (phase "held") so --resume re-asks the idempotent begin.
            return code or EXIT_UNAVAILABLE
        self._save(phase="begun", barrier_id=barrier["id"])
        return EXIT_OK

    def _record(self) -> int:
        code, out = self.gh(["pr", "view", str(self.s.pr), "--repo", REPO, "--json", "state,mergeCommit"])
        try:
            view = json.loads(out) if code == 0 else None
        except json.JSONDecodeError:
            view = None
        commit = view.get("mergeCommit") if isinstance(view, dict) else None
        sha = commit.get("oid") if isinstance(commit, dict) else None
        if not (isinstance(view, dict) and view.get("state") == "MERGED"
                and isinstance(sha, str) and SHA_RE.fullmatch(sha)):
            # Never infer "no merge": UNKNOWN stays blocked for --resume or tier 3.
            _log(f"merge outcome unknown for barrier {self.state.get('barrier_id')}; "
                 "rerun with --resume, or resolve it with tier-3 resolve-barrier")
            return EXIT_UNKNOWN
        code, _ = self.lock(["record-merge", RESOURCE, *self._fence(),
                                  "--barrier-id", str(self.state["barrier_id"]), "--squash-sha", sha])
        if code != EXIT_OK:
            _log(f"record-merge was not confirmed (exit {code}) for {sha}; rerun with --resume")
            return EXIT_LOST if code == EXIT_LOST else EXIT_UNKNOWN
        self._save(phase="recorded", squash_sha=sha)
        return EXIT_OK

    def _await_main(self) -> int:
        sha = self.state["squash_sha"]
        deadline = self.clock() + self.s.ci_timeout
        while True:
            code, _ = self.lock(["renew", RESOURCE, *self._fence()])
            if code == EXIT_LOST:
                # The barrier still blocks successors; it closes on Kyle's own
                # reading of this push, never because this process went away.
                # Nothing is left for this record to do, so it is retired.
                self.state_path.unlink(missing_ok=True)
                _log("lease lost; the recorded barrier keeps main-merge blocked until Kyle reads the push")
                return EXIT_LOST
            if code != EXIT_OK:
                _log(f"lease renewal unconfirmed (exit {code}); rerun with --resume")
                return EXIT_UNAVAILABLE
            code, _ = self.lock(["ci", "--repo", REPO, "--sha", sha, "--event", "push", "--branch", "main"])
            if code in (EXIT_OK, EXIT_RED):
                self._release()
                self.state_path.unlink(missing_ok=True)
                _log(f"main push {sha} is {'green' if code == EXIT_OK else 'RED'}")
                return code
            if self.clock() >= deadline:
                # Keep the lease and the record: a resume renews and keeps reading.
                _log(f"main push {sha} not terminal within {self.s.ci_timeout:g}s; "
                     "lease kept, rerun with --resume")
                return EXIT_UNAVAILABLE
            self.sleep(self.s.poll)

    def _release(self) -> None:
        if "lease_id" in self.state:
            self.lock(["release", RESOURCE, *self._fence()])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head", required=True, help="the full 40-hex head SHA you validated")
    parser.add_argument("--resume", action="store_true", help="continue a recorded unfinished merge")
    parser.add_argument("--state-dir", type=Path, required=True,
                        help="where the merge-intent recovery record lives; keep it under /workspace")
    parser.add_argument("--acquire-wait", type=float, default=600.0)
    parser.add_argument("--ci-timeout", type=float, default=3600.0)
    parser.add_argument("--poll", type=float, default=20.0)
    return parser


def main(argv: list[str] | None = None, *, lock: LockCall | None = None, gh: GhCall | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not admission_on():
        _log(f"admission is off ({admission_file()} is not 'on'); the legacy merge procedure governs")
        return EXIT_USAGE
    if args.pr <= 0 or not SHA_RE.fullmatch(args.head):
        _log("--pr must be positive and --head a full lowercase 40-hex SHA")
        return EXIT_USAGE
    if lock is None:
        client = os.environ.get(CLIENT_ENV, "")
        if not client:
            _log(f"{CLIENT_ENV} must name Kyle's scripts/kyle-lock; there is no default")
            return EXIT_USAGE
        lock = subprocess_lock(client)
    settings = Settings(pr=args.pr, head=args.head, state_dir=args.state_dir, resume=args.resume,
                        acquire_wait=args.acquire_wait, ci_timeout=args.ci_timeout, poll=args.poll)
    return Merger(settings, lock, gh or subprocess_gh).run()


if __name__ == "__main__":
    sys.exit(main())
