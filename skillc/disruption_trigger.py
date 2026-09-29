"""The L5 disruption-trigger fixture service (#14, runtime part c).

Assembles the bytes `skillc.verify.grade_agent_attempt`'s
`trusted_observation` parameter carries for `evals/level5/
recovery-partial-processing` - the disruption log's `failed_after_step`,
from a source the subject cannot forge alone. See `skillc/verify.py`'s own
module docstring for the three-stage grading path this feeds into, and
`skillc/authority_interceptor.py`'s module docstring for the sibling L4
service this deliberately does NOT share a base class with (see "Why not a
shared base with AuthorityInterceptor" below).

DESIGN: AN ACTIVE COUNTER, NOT A PASSIVE WATCHER - AND WHY THAT CHANGES WHAT
IT CAN HONESTLY CLAIM (design review, issue #14). Level 4's interceptor only
ever OBSERVES; Level 5 must eventually DECIDE when "the tool" stops
answering, which observation alone cannot do. This module does not yet make
that live decision either (see "What this does not do" below) - but even the
observation half it DOES do is a narrower claim than L4's, and the design
review corrected an early draft that got this wrong:

  - A first draft claimed the subject "cannot alter the proxy's own code".
    FALSE, under the same neutral-identity model L4's docstring explains:
    the subject shares the proxy's own uid and can overwrite or bypass any
    PATH binary it can write. What actually still holds is narrower - the
    trusted OBSERVATION lives at the controller, never in the container - so
    a bypassed or replaced proxy does not corrupt this module's own record;
    it just means the record shows fewer requests than a live run needed.
  - A first draft would also have called `request_log`'s line count "proxy
    invocations". Also wrong for the same reason: whatever in-container
    endpoint a real proxy would use to reach the controller, the subject can
    use directly too, proxy or no proxy. So this module counts and reports
    "requests a controller-observed log received" - never "genuine tool
    calls" or "proxy invocations" - because it cannot tell a forwarded
    request from a subject writing the file by hand. A forged request is
    still something the subject did, so counting it is honest; claiming
    more than that would not be.

WHY ZERO OBSERVED REQUESTS MUST NEVER GRADE PASS (design review, issue #14).
If a subject bypasses the request log entirely and does its work unmediated,
`requests_received` is 0. Naively setting `failed_after_step = 0` in that
case is not a refusal - Level 5's own judge (`grade_recovery.py`) checks
`range(1, failed_after_step + 1)`, which is EMPTY at 0, so both
`work-preserved` and `report-supported` would grade SATISFIED VACUOUSLY:
nothing was checked, so nothing failed. A subject that bypassed the tool
entirely and reported `steps_completed: []` honestly would PASS on having
observably done nothing worth trusting - the exact unearned-green shape #14
exists to remove. `stop_and_finalize()` therefore returns `None` - no
`trusted_observation` at all - whenever zero requests were ever observed,
regardless of the calibrated `fail_after`: this controller cannot tell "the
subject correctly stopped after zero legitimate calls, exactly as
calibrated" from "the subject bypassed the log and this number means
nothing", and refuses instead of guessing. `envelope["trusted"]` then being
absent is not new plumbing - `verify.py`'s existing absence-handling (#14
part a) already turns it into UNKNOWN on both criteria, never SATISFIED.

WHAT THIS DOES NOT DO: decide, in real time, whether "the tool" answers or
refuses a live subject's call. That needs a channel the subject can call
INTO and block on for an answer, which no existing `ExecutionBackend`
Protocol method provides (`export()` is read-only; there is no sanctioned
"write into a running container's workspace and have it appear before the
subject's next read" primitive). Building one is a live-wiring and
networking-policy question (see `docker_backend.py`'s `network` parameter
and issue #11's owner ruling on container egress) well past a single fixture
-service PR's scope, and #14's own "keep runtime implementation out of the
planning PR" carries into its runtime PRs too: what a real attempt's tool
actually does when disrupted, and what carries that disruption to it, stays
owed to the live-wiring PR that connects the pieces this PR and part (b)
build. What IS delivered: a controller-side counter that can be trusted
about ONE fact - how many requests a log outside the subject's exclusive
control was observed to receive - polled the same way, and with the same
mandatory-final-snapshot guarantee, as `AuthorityInterceptor`.

WHY NOT A SHARED BASE WITH AuthorityInterceptor: both modules poll
`ExecutionBackend.export()` on a background thread with a mandatory final
snapshot and a `polls_attempted`/`polls_failed` coverage count, and the
duplication between them is real. Not factored out here, deliberately: this
PR is scoped to the second fixture service's own correctness, and refactoring
the already-shipped, reviewed `AuthorityInterceptor` (issue #14 part b, #181)
to share a base is a separate, non-trivial change with its own regression
surface on a merged module - worth doing, not worth doing inside this diff.

POLL COST AND CADENCE: one poll here is the SAME `export()` call L4's
interceptor measures (`authority_interceptor.py`'s own docstring carries the
number); this module reads one additional small file from the export instead
of walking the whole tree, which is strictly cheaper per poll, not more
expensive. The same `interval` default (2.0s) and the same "cannot pile up
by construction" argument (`_loop` is one thread: wait, then poll, then wait
again) apply unchanged - see `authority_interceptor.py`'s docstring for the
full argument, not repeated here.

Stdlib only (AGENTS.md) except `skillc.backend`'s own Protocol.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from .backend import ExecutionBackend

#: The request log's default path, relative to the workspace root - a plain
#: append-only file. Its CONTENT is never interpreted, only its non-empty
#: LINE COUNT: this module counts "requests a controller-observed log
#: received", never validates what a line says, because a forged line is
#: still something the subject did and counting it is the honest claim.
DEFAULT_REQUEST_LOG = ".disruption/requests.log"


def _count_requests(root: Path, request_log: str) -> int:
    path = root / request_log
    if not path.is_file() or path.is_symlink():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())


class DisruptionTrigger:
    """Polls one live attempt's request log and assembles a trusted
    observation log for `skillc.verify`'s `trusted_observation`, carrying
    Level 5's `failed_after_step`.

    Usage, around one `ExecutionBackend.execute()` call:

        trigger = DisruptionTrigger(backend, handle, fail_after=3)
        trigger.start()                            # baseline, then polls
        result = backend.execute(handle, argv, limits)  # runs concurrently
        if backend.confirm_stopped(handle) is Confirmation.CONFIRMED:
            trusted = trigger.stop_and_finalize()
        else:
            trusted = None  # never finalize against an unconfirmed stop

    `trusted` is `None` whenever this controller cannot honestly assert a
    `failed_after_step` - either it observed zero requests ever (see the
    module docstring's "why zero must never grade PASS"), or the mandatory
    final export failed. Otherwise it carries
    `{"failed_after_step": min(fail_after, requests_received),
    "requests_received": N, "coverage": {...}}` - `failed_after_step` is
    always bounded by what was actually observed, never by what `fail_after`
    alone would allow, so a subject that claims more completed steps than
    the observed request count supports is still caught by
    `grade_recovery.py`'s own existing `report-supported` check, unmodified.
    """

    def __init__(
        self, backend: ExecutionBackend, handle: object, fail_after: int,
        request_log: str = DEFAULT_REQUEST_LOG, interval: float = 2.0,
    ) -> None:
        if fail_after < 0:
            raise ValueError("fail_after must be a non-negative number of allowed requests")
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
            raise RuntimeError("this trigger has already been started")
        self._started = True
        if not self._poll_once(record=False):
            raise RuntimeError(
                "disruption trigger could not capture a baseline export; "
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
        "an observation, once made, cannot be un-made by later tampering"
        property `AuthorityInterceptor`'s diff gets from comparing
        consecutive snapshots, applied here to a single growing count
        instead of a set of paths."""
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

        Returns `None` (never a fabricated `failed_after_step`) when:
        - the mandatory final export failed (the same refusal
          `AuthorityInterceptor.stop_and_finalize()` makes, for the same
          reason: a violation could have happened in the unobserved gap
          before teardown), or
        - zero requests were ever observed, at any poll including the
          final one - see the module docstring's "why zero must never
          grade PASS".

        Otherwise returns `{"failed_after_step": min(fail_after,
        requests_received), "requests_received": N, "coverage": {...}}`."""
        if not self._started:
            raise RuntimeError("stop_and_finalize() called before start()")
        if self._finalized:
            raise RuntimeError("this trigger has already been finalized")
        self._finalized = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if not self._poll_once(record=True):
            return None
        with self._lock:
            requests_received = self._max_requests_seen
            if requests_received == 0:
                return None
            return json.dumps({
                "failed_after_step": min(self._fail_after, requests_received),
                "requests_received": requests_received,
                "coverage": {"polls_attempted": self._polls_attempted, "polls_failed": self._polls_failed},
            }).encode("utf-8")
