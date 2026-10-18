"""Release-aware loopback service for skillc#282's deploy verification.

Reads `current/release.json` ONCE, at start: a running process keeps serving
the release it started with even after `current` moves, which is exactly what
a deploy whose restart never happened looks like from outside.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = "127.0.0.1", 18080

with open(os.path.join(HERE, "current", "release.json"), encoding="utf-8") as f:
    RELEASE = json.load(f)
FAULTS = frozenset(RELEASE.get("faults", []))


def _route(path: str) -> tuple[int, dict]:
    if path == "/health":
        return 200, {"status": "ok"}  # health never sees the faults below
    if path == "/version":
        return 200, {"release": RELEASE["id"]}
    if path == "/calc":  # 2 + 3
        return 200, {"result": 6 if "calc-wrong" in FAULTS else 5}
    if path == "/metrics":
        return (500, {"status": "error"}) if "metrics-500" in FAULTS else (200, {"requests": 0})
    return 404, {"status": "not-found"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, payload = _route(self.path)
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"serving {RELEASE['id']} on {HOST}:{PORT}", file=sys.stderr, flush=True)
    server.serve_forever()
