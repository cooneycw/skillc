"""#460: the egress live tests' failure diagnostics, kept out of the
`real_docker`-marked module so they are unit-tested without a daemon
(tests/test_egress.py).

A deny, resolution or isolation failure used to say only that the property
failed. Each one can mean a reached origin (the only leak path), a proxy that
was not yet listening (Errno 111, no CONNECT logged), a client timeout, a
closed connection or a missing proxy env. This names which.

LEAK SAFETY: IPv4 addresses are redacted before anything is formatted.
"""

from __future__ import annotations

import json
import re

from skillc import egress as eg

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def redact(text: str) -> str:
    return _IPV4.sub("<ipv4>", text)


def _events(log: bytes) -> list[object]:
    events: list[object] = []
    for line in log.decode("utf-8", "replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def describe_observation(results: dict[str, dict[str, object]], log: bytes | None) -> str:
    """Per target, the probe's result and its status or error (160 chars),
    then the proxy log's summary and whether its start line is present."""
    parts = []
    for target, result in results.items():
        if result.get("result") == "http":
            seen = f"REACHED an origin, HTTP {result.get('status')}"
        elif "error" in result:
            seen = f"error {str(result['error'])[:160]}"
        else:
            seen = str(result.get("result"))
        parts.append(f"{target}: {seen}")
    if log is None:
        parts.append("proxy log: unreadable")
    else:
        summary = eg.summarize_log(log)
        start = any(isinstance(e, dict) and e.get("event") == "start" for e in _events(log))
        parts.append("proxy log: start line " + ("present" if start else "ABSENT") + ", "
                     + ", ".join(f"{key}={summary.get(key)}" for key in
                                 ("allowed", "denied", "peer_rejected", "upstream_failed", "unparsed_lines")))
    return redact("; ".join(parts))
