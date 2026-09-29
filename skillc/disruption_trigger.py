"""An ADVISORY request-count observer for Level 5 (#14, runtime part c).

**This module's output must NEVER be passed as `skillc.verify`'s
`trusted_observation` parameter, and nothing here claims otherwise.** It
counts a live attempt's request log - an append-only file the subject's
tool wrapper (or the subject itself) writes one line to per call attempt -
by polling `ExecutionBackend.export()`, the same read-only method
`skillc.authority_interceptor.AuthorityInterceptor` polls for Level 4. That
similarity is exactly what makes the difference between the two worth
stating precisely, because it is easy to mistake one for the other:

**Why L4's poll-based design is trustworthy and this one is not (design
review, issue #14).** `AuthorityInterceptor` also reads from the subject-
writable workspace via `export()` - but it only ever asks "did the bytes at
this PATH change", and which paths count as out-of-scope is a fact the
CONTROLLER supplies (`allowed_prefixes`), never something read from subject
content. The subject cannot lie about whether a byte sequence changed; it
can only choose what to change. This module instead trusts the CONTENT of a
subject-writable file - a line count - as if it meant "this many real,
tool-mediated events occurred". Nothing enforces that correspondence: the
subject shares the file-writer's own uid (the same neutral-identity model
`authority_interceptor.py`'s docstring explains) and can write ANY NUMBER OF
LINES with zero real work behind them, on every attempt, with no special
timing or narrow condition required. That is not a scoped blind spot the way
`known-gaps/delete-then-restore` or the pre-#14(a) `forged-log` gap were -
those needed a specific timing window or a specific forged field. Here the
count IS the claim, and the claim is unenforced end to end, unconditionally.
Labeling this a "known gap" (a narrow, documented miss in an otherwise-sound
mechanism) would understate it, so it is not one - the whole value is
advisory, plainly, not narrowly compromised.

**What would actually fix this, and why it is not built here.** The
approved design needed the CONTROLLER to be both decider and logger: a
channel the subject calls INTO, that the controller alone answers and logs.
No existing `ExecutionBackend` Protocol method provides a synchronous
write-into-a-running-container primitive, so no such channel exists today.
One candidate - a host-owned Unix socket bind-mounted into the container,
with the controller as the sole listener - would need no network egress
(`network=none` survives) and would make the controller the one deciding
and recording, not merely observing. It needs the backend to allow a bind
mount, which is a policy question or its own issue, not a fixture-service
PR; tracked separately, not built here.

**What this module IS for**: a rough, subject-influenceable count of how
many times something wrote to the request log, useful for a human
calibrating `goal.md`'s disruption framing or debugging why a live attempt's
tool-wrapper did or did not get called as expected - never for grading.

Stdlib only (AGENTS.md) except `skillc.backend`'s own Protocol.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from .backend import ExecutionBackend

#: The request log's default path, relative to the workspace root - a plain
#: append-only file. Its CONTENT is never validated, only its non-empty LINE
#: COUNT, and that count is advisory (see module docstring) - it is not, and
#: must never become, evidence a grader trusts.
DEFAULT_REQUEST_LOG = ".disruption/requests.log"


def _count_requests(root: Path, request_log: str) -> int:
    path = root / request_log
    if not path.is_file() or path.is_symlink():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())


class DisruptionTrigger:
    """Polls one live attempt's request log and reports an ADVISORY count -
    never a `trusted_observation`; see the module docstring for why this
    module cannot honestly produce one.

    Usage, around one `ExecutionBackend.execute()` call:

        observer = DisruptionTrigger(backend, handle, fail_after=3)
        observer.start()                           # baseline, then polls
        result = backend.execute(handle, argv, limits)  # runs concurrently
        if backend.confirm_stopped(handle) is Confirmation.CONFIRMED:
            advisory = observer.stop_and_finalize()
        else:
            advisory = None  # never finalize against an unconfirmed stop

    `advisory` is `None` only when the mandatory final export itself failed
    - this module could not observe the final state at all, not even an
    untrusted one. Otherwise it carries `{"requests_received": N,
    "fail_after": K, "coverage": {...}}` - `fail_after` is echoed back
    exactly as given, for a reader comparing the observed count against the
    intended calibration point, never combined with `requests_received`
    into any single "disruption happened here" claim.

    `fail_after` is kept as a plain non-negative int for that comparison
    context; unlike the removed `failed_after_step` framing, this class
    computes nothing FROM it - it is not a bound, not a decision, just
    context alongside the count.
    """

    def __init__(
        self, backend: ExecutionBackend, handle: object, fail_after: int,
        request_log: str = DEFAULT_REQUEST_LOG, interval: float = 2.0,
    ) -> None:
        if fail_after < 0:
            raise ValueError("fail_after must be a non-negative number")
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._backend = backend
        self._handle = handle
        self._fail_after = fail_after
        self._request_log = request_log
        self._interval = interval
        self._max_requests_seen = 0
        self._polls_attempted = 0
        self._polls_failed = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._finalized = False

    def start(self) -> None:
        """Capture the baseline synchronously, then begin polling on a
        background thread. Raises if the baseline cannot be captured at
        all - the same fail-loud choice `AuthorityInterceptor.start()`
        makes, for the same reason: silently starting from an unknown
        baseline would under-report for the whole attempt."""
        if self._started:
            raise RuntimeError("this observer has already been started")
        self._started = True
        if not self._poll_once(record=False):
            raise RuntimeError(
                "disruption observer could not capture a baseline export; "
                "the backend must be reachable before an attempt starts"
            )
        self._thread = threading.Thread(target=self._loop, daemon=True, name="disruption-trigger")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._poll_once(record=True)

    def _poll_once(self, *, record: bool) -> bool:
        """One export-and-count cycle. Returns whether the export itself
        succeeded. `_max_requests_seen` only ever grows: a subject that
        truncates or deletes the request log after inflating it does not
        erase an earlier poll's higher, already-observed count - the same
        property `AuthorityInterceptor`'s diff gets from comparing
        consecutive snapshots, applied here to a single growing count
        instead of a set of paths. This defeats SHRINKING the count after
        the fact; it does nothing against INFLATING it in the first place -
        see the module docstring for why that second half is unfixable
        without a controller-owned channel."""
        with tempfile.TemporaryDirectory(prefix="skillc-disruption-poll-") as tmp:
            root = Path(tmp)
            try:
                self._backend.export(self._handle, root)
            except OSError:
                if record:
                    with self._lock:
                        self._polls_attempted += 1
                        self._polls_failed += 1
                return False
            count = _count_requests(root, self._request_log)
            with self._lock:
                if record:
                    self._polls_attempted += 1
                self._max_requests_seen = max(self._max_requests_seen, count)
            return True

    def stop_and_finalize(self) -> bytes | None:
        """Stop polling and take ONE mandatory final snapshot, called only
        after the backend's own `confirm_stopped()` reports CONFIRMED -
        never before, and never called twice.

        Returns `None` only when the mandatory final export itself failed:
        this module could not observe anything about the final state, not
        even an advisory count. Otherwise returns `{"requests_received": N,
        "fail_after": K, "coverage": {"polls_attempted": ..., "polls_failed":
        ...}}` - ALWAYS, including when `N` is 0, since an advisory count of
        zero is still an honest, reportable observation (unlike the trusted-
        observation case this is explicitly not: there, zero had to become a
        hard refusal to avoid a false PASS; here there is no grading verdict
        for it to falsify)."""
        if not self._started:
            raise RuntimeError("stop_and_finalize() called before start()")
        if self._finalized:
            raise RuntimeError("this observer has already been finalized")
        self._finalized = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if not self._poll_once(record=True):
            return None
        with self._lock:
            return json.dumps({
                "requests_received": self._max_requests_seen,
                "fail_after": self._fail_after,
                "coverage": {"polls_attempted": self._polls_attempted, "polls_failed": self._polls_failed},
            }).encode("utf-8")
