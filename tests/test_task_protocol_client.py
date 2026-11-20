"""The standalone role-facing client (skillc/task_protocol_client.py, B5a).

Its bytes are copied into every sandbox, so it must import nothing from
skillc, read no environment, and agree exactly with task_protocol_schema."""

from __future__ import annotations

import ast
import json
import shutil
import socket
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_client as client
from skillc import task_protocol_schema as schema

SOURCE = Path(client.__file__).read_text()
SCHEMA_CASES = json.loads((Path(__file__).resolve().parent.parent / "controls"
                           / "task-protocol-schema" / "cases.json").read_text())


def _foreign_imports(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = ["." * node.level + (node.module or "")] if node.level else [node.module or ""]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if name.startswith(".") or top == "skillc" or top not in sys.stdlib_module_names:
                found.add(name)
    return found


def test_the_import_check_can_fail() -> None:
    assert _foreign_imports("from .task_protocol_schema import VERSION") == {
        ".task_protocol_schema"}
    assert _foreign_imports("import skillc.backend") == {"skillc.backend"}
    assert _foreign_imports("import requests") == {"requests"}
    assert _foreign_imports("import json, socket") == set()


def test_the_client_is_standalone_and_reads_no_environment() -> None:
    assert _foreign_imports(SOURCE) == set()
    tree = ast.parse(SOURCE)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"environ", "getenv", "environb"}
    assert "open(" not in SOURCE


def test_the_vocabulary_matches_the_schema() -> None:
    assert client.VERSION == schema.VERSION
    assert client.MAX_BYTES == schema.MAX_REQUEST_BYTES
    assert client.MAX_REQUEST_NUMBER == schema.MAX_REQUEST_NUMBER
    assert client.OPERATIONS == schema.OPERATIONS
    assert client.REFUSAL_REASONS == schema.REFUSAL_REASONS
    assert client.DECISIONS == schema.DECISIONS
    assert client.REJECTIONS == schema.REJECTIONS
    assert client.ENDPOINT == "/run/skillc-task-protocol/channel.sock"


@pytest.mark.parametrize("case", [c for c in SCHEMA_CASES["requests"]
                                  if c["expect"] == "accepted"], ids=lambda c: c["name"])
def test_every_accepted_request_encodes_exactly_as_the_schema(case: dict[str, Any]) -> None:
    fields = json.loads(case["canonical"])
    built = client.request_fields(fields["op"], fields["request"], fields.get("offer_id"),
                                  fields.get("reason"))
    parsed = schema.parse_request(client.encode(built))
    assert isinstance(parsed, schema.Request)
    assert schema.encode_request(parsed) == client.encode(built)


@pytest.mark.parametrize("case", SCHEMA_CASES["receipts"], ids=lambda c: c["name"])
def test_the_receipt_reader_agrees_with_the_schema(case: dict[str, Any]) -> None:
    raw = case["raw"].encode()
    assert (client.parse_receipt(raw) is not None) is (schema.parse_receipt(raw) is not None)


def test_every_schema_receipt_round_trips_through_the_client() -> None:
    receipts = [schema.Receipt(1, d, "o-1", None) for d in schema.DECISIONS if d != "rejected"]
    receipts += [schema.Receipt(None, "rejected", None, r) for r in schema.REJECTIONS]
    for receipt in receipts:
        parsed = client.parse_receipt(receipt.encode())
        assert parsed is not None and client.encode(parsed) == receipt.encode()


@pytest.mark.parametrize("args", [
    ["offer", "--request", "1"],
    ["ack", "--request", "2", "--offer", "o-1"],
    ["complete", "--request", "3", "--offer", "o-1"],
    ["refuse", "--request", "4", "--offer", "o-1", "--reason", "blocked"],
])
def test_valid_commands_send_their_request(args: list[str], server: Any) -> None:
    server.reply = schema.Receipt(1, "offered", "o-1").encode()
    assert client.main(args, server.path) == client.EXIT_DECIDED
    sent = schema.parse_request(server.received[-1])
    assert isinstance(sent, schema.Request) and sent.op == args[0]


@pytest.mark.parametrize("args", [
    [], ["fetch", "--request", "1"], ["offer"], ["offer", "--request", "0"],
    ["offer", "--request", "1", "--offer", "o-1"], ["ack", "--request", "2"],
    ["ack", "--request", "2", "--offer", "-bad"], ["refuse", "--request", "4", "--offer", "o-1"],
    ["refuse", "--request", "4", "--offer", "o-1", "--reason", "free text"],
    ["offer", "--request", "1", "--role", "worker-b"],
    ["offer", "--request", "1", "--endpoint", "/tmp/other.sock"],
])
def test_out_of_grammar_commands_are_usage_errors(args: list[str], server: Any) -> None:
    assert client.main(args, server.path) == client.EXIT_USAGE
    assert server.received == []


@pytest.mark.parametrize("reply,code", [
    (schema.Receipt(1, "acknowledged", "o-1").encode(), client.EXIT_DECIDED),
    (schema.Receipt(1, "rejected", "o-1", "late").encode(), client.EXIT_REJECTED),
    (b"", client.EXIT_UNAVAILABLE),
    (b'{"decision":"passed","request":1,"version":1}\n', client.EXIT_UNAVAILABLE),
    (b'{"version":1,"decision":"offered","offer_id":"o-1","request":1}\n', client.EXIT_UNAVAILABLE),
])
def test_exit_codes_follow_the_receipt(reply: bytes, code: int, server: Any) -> None:
    server.reply = reply
    assert client.main(["ack", "--request", "1", "--offer", "o-1"], server.path) == code


def test_no_endpoint_is_unavailable(tmp_path: Path) -> None:
    assert client.main(["offer", "--request", "1"], str(tmp_path / "absent.sock")) == (
        client.EXIT_UNAVAILABLE)


class _Server:
    def __init__(self, path: str) -> None:
        self.path, self.reply = path, b""
        self.received: list[bytes] = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    data += chunk
                self.received.append(data)
                conn.sendall(self.reply)


@pytest.fixture
def server() -> Iterator[_Server]:
    short = tempfile.mkdtemp(prefix="tpc-", dir="/tmp")
    running = _Server(str(Path(short) / "c.sock"))
    yield running
    running.stop.set()
    running.sock.close()
    running.thread.join(5)
    shutil.rmtree(short, ignore_errors=True)
