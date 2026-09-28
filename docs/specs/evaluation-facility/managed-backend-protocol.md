# Managed-container backend protocol (#64)

- Status: Proposed - no platform implements this yet. skillc's client
  (`skillc/managed_backend.py`) and a test-only stub server are the only
  things that speak it today.
- Date: 2026-09-28
- Governing documents: [interfaces.md](interfaces.md) (the `ExecutionBackend`
  seam this protocol implements over a socket), `skillc/backend.py` (the
  Python `Protocol` itself)
- Delivery issue: [#64](https://github.com/cooneycw/skillc/issues/64)

## What this is

`skillc/backend.py`'s `ExecutionBackend` seam lets a trial run inside
isolation skillc does not itself drive. `skillc/docker_backend.py` is the
closing, self-contained implementation (#10) and needs nothing else. This
protocol is for a SECOND kind of implementation: skillc talking to a platform
that already manages its own containers and is willing to run one trial
inside a container it creates, in exchange for skillc never having to know
anything about that platform.

**skillc depends on no platform to implement this.** Nothing under `skillc/`
imports, names or assumes any particular platform. This page describes a
contract; any platform that implements it can back `ManagedBackend`. A
platform absent, unreachable, or refusing this protocol makes the backend
`unavailable` - never a fallback to the reference `DockerBackend` or to a bare
host process (`skillc/backend.py`'s own structural rule).

### Implementers

No platform implements this protocol yet. A first intended implementer is
tracked as its own issue in a different project: an executor-mediated
test-container class for skillc trials
([cooneycw/kyle#1397](https://github.com/cooneycw/kyle/issues/1397)), distinct
from that project's session containers. That issue is a consumer of this
page, not its source - nothing below assumes anything about how any
particular platform is built.

## Transport

A single Unix domain socket, whose path is read from
`SKILLC_MANAGED_BACKEND_SOCKET`. The variable unset, or the socket
unreachable, makes `prepare()` raise `BackendUnavailable` immediately -
`describe()` itself never fails (it reports `version="unreachable"` instead,
matching `DockerBackend.describe()`'s own convention of never raising).

**One connection per request.** The client opens a new connection, writes
exactly one request line, reads exactly one response line, and closes. No
multiplexing, no persistent session, no server-pushed messages. State that
must outlive one request (what a `handle` refers to) lives entirely on the
platform's side, keyed by the opaque token `prepare()` returned.

Stdlib only on the skillc side (`socket`, `json`) - no dependency, and no
requirement on what the platform is written in.

## Framing

One JSON object per line (`\n`-terminated), UTF-8. A request:

```json
{"op": "prepare", "protocol": 1, "attempt_id": "a-1a2b3c"}
```

A successful response:

```json
{"ok": true, "result": {"handle": "h-9f8e7d"}}
```

A failed response:

```json
{"ok": false, "error": "no capacity"}
```

There is no third shape. `error` is a free-text string for logs; skillc never
parses it for control flow, and a platform must not fold anything into it
that could not appear in a public issue or log (the credential rule below
applies here too).

## Closed schema, both directions

**The server must refuse an unrecognized request field**, not ignore it -
`{"ok": false, "error": "..."}`, never a partial success. **The client
refuses an unrecognized response field** the same way: any key in a `result`
object outside [the response field table](#response-fields) is treated
exactly like a transport failure for that call (see
[Error and unavailable semantics](#error-and-unavailable-semantics)). Silent
tolerance on either side is how a schema drifts without anyone noticing;
`tests/test_managed_backend.py` proves the client's own request builder never
emits a field outside [the request field table](#request-fields), parsed from
this page directly, so the doc and the code cannot drift apart unnoticed.

## Versioning

Every request carries `"protocol": 1` (an integer, not a string). A server
that does not support the given version refuses the request the ordinary way
(`{"ok": false, "error": "..."}`) - there is no separate version-negotiation
message. `1` is the only version this page or the client defines.

## The eight operations

One operation per `ExecutionBackend` seam method (`skillc/backend.py`), 1:1 -
no batching, no additional verbs:

| Op | Seam method | Step (interfaces.md) |
|---|---|---|
| `describe` | `describe()` | 1 |
| `prepare` | `prepare(attempt_id)` | 3 |
| `install` | `install(handle, surface)` | 4 |
| `execute` | `execute(handle, argv, limits, cancel, stdin)` | 5 |
| `confirm_stopped` | `confirm_stopped(handle)` | 6 |
| `export` | `export(handle, dest)` | 7 (backend side) |
| `destroy` | `destroy(handle)` | 9 |
| `confirm_absent` | `confirm_absent(handle)` | 9 |

### Request fields

Every request's `op` and `protocol` fields are listed per-op below rather
than factored out, so the parity test can read one flat table.

| Op | Field | Required | Notes |
|---|---|---|---|
| describe | op | yes | literal `"describe"` |
| describe | protocol | yes | |
| prepare | op | yes | literal `"prepare"` |
| prepare | protocol | yes | |
| prepare | attempt_id | yes | skillc's own attempt id - already content-free |
| prepare | credential | no | present only when a credential source is configured (see below); a bare opaque string, never structured |
| install | op | yes | |
| install | protocol | yes | |
| install | handle | yes | the opaque token `prepare` returned |
| install | attempt_id | yes | |
| install | surface | yes | `{relative_path: {"content_b64": "..."}}` - every declared entry, host path or raw bytes, is read/encoded client-side into base64 content; the platform never reads the controller's own filesystem |
| install | canary_nonce | no | present only when the caller planted a liveness canary (`lifecycle.CANARY_NONCE_KEY`) |
| execute | op | yes | |
| execute | protocol | yes | |
| execute | handle | yes | |
| execute | attempt_id | yes | |
| execute | argv | yes | list of strings |
| execute | timeout | yes | seconds, float |
| execute | grace | yes | seconds, float |
| execute | max_captured_stdout_bytes | yes | integer |
| execute | max_captured_stderr_bytes | yes | integer |
| execute | stdin_b64 | no | present only when the caller passed `stdin` |
| confirm_stopped | op | yes | |
| confirm_stopped | protocol | yes | |
| confirm_stopped | handle | yes | |
| confirm_stopped | attempt_id | yes | |
| export | op | yes | |
| export | protocol | yes | |
| export | handle | yes | |
| export | attempt_id | yes | |
| destroy | op | yes | |
| destroy | protocol | yes | |
| destroy | handle | yes | |
| destroy | attempt_id | yes | |
| confirm_absent | op | yes | |
| confirm_absent | protocol | yes | |
| confirm_absent | handle | yes | |
| confirm_absent | attempt_id | yes | |

`attempt_id` rides every attempt-scoped request in addition to `handle`
(redundant with what the platform already bound at `prepare`) so a platform
can cross-check the two agree without relying on skillc alone to keep them
paired correctly.

### Response fields

Present under `result` only when `"ok": true`. `destroy`'s `result` is always
`{}` and is not listed below.

| Op | Field | Required | Notes |
|---|---|---|---|
| describe | name | yes | |
| describe | version | yes | |
| describe | isolation | yes | list of strings - claims this backend makes |
| describe | unobserved | yes | list of strings - claims it does not make |
| prepare | handle | yes | opaque, content-free token - see [Handle rule](#the-handle-rule) |
| install | discovery_canary | yes | `"SATISFIED"` or `"VIOLATED"` |
| install | baseline_absence | yes | `"SATISFIED"` or `"VIOLATED"` |
| install | declared | yes | integer |
| install | installed | yes | integer |
| install | image_digest | yes | string or `null` - an immutable image digest, never a floating tag |
| install | canary_path | no | present only when a nonce was planted and the plant succeeded |
| execute | reason | yes | `"exited"` \| `"timeout"` \| `"operator-cancelled"` \| `"launch-failed"` |
| execute | exit_code | yes | integer or `null` |
| execute | error | yes | string or `null` |
| execute | signal | yes | string or `null` - an EXPLICIT signal name, never inferred from an exit code alone |
| execute | stdout_truncated | yes | boolean |
| execute | stdout_bytes | yes | integer - a count, not the content; the subject's own captured stdout is written into the workspace at `<workspace>/observations` (the same convention `DockerBackend.execute()` uses) and retrieved via `export`, never returned inline here |
| confirm_stopped | state | yes | `"confirmed"` \| `"not-confirmed"` \| `"unknown"` |
| export | archive_b64 | yes | base64 tar stream of the attempt's workspace contents (contents only, not nested under a workspace-named directory) |
| confirm_absent | state | yes | `"confirmed"` \| `"not-confirmed"` \| `"unknown"` |

## Error and unavailable semantics

The protocol layer has exactly one failure shape: a connection could not be
made, timed out, sent malformed JSON, sent a response with a field outside
[the response table](#response-fields), or answered `{"ok": false, ...}`.
**Every one of those is the same fact - "this call did not succeed" - and the
client maps that one fact differently per seam method, matching
`skillc/backend.py`'s own per-method contract exactly (the same mapping
`DockerBackend` already uses for a dead docker daemon):**

| Seam method | On protocol/transport failure |
|---|---|
| `describe()` | Never raises. Returns a `BackendDescription` with `version="unreachable"`. |
| `prepare()` | Raises `BackendUnavailable`. |
| `install()` | Raises `BackendUnavailable` (a materialization failure makes this attempt's backend unusable, exactly like an unreachable daemon - `DockerBackend.install()`'s own stated reasoning). |
| `execute()` | Never raises. Returns `ExecuteResult(reason="launch-failed", exit_code=None, error=...)`. |
| `confirm_stopped()` | Returns `Confirmation.UNKNOWN` - never a guessed `CONFIRMED`/`NOT_CONFIRMED`. |
| `export()` | Raises `OSError`. |
| `destroy()` | Never raises (best-effort; `confirm_absent()` is what a caller trusts). |
| `confirm_absent()` | Returns `Confirmation.UNKNOWN` - never a guessed `CONFIRMED`/`NOT_CONFIRMED`. |

This is not a new rule invented for the socket transport - it is
`skillc/backend.py`'s existing per-method contract, applied to one more kind
of failure (`OSError`, timeout, and malformed/out-of-schema response) beside
the ones `DockerBackend` already maps (a dead daemon, a failed `docker run`).
A transport failure reaching `confirm_stopped`/`confirm_absent` specifically
must never be read as a confirmed stop or a confirmed absence - the same rule
`Confirmation.UNKNOWN`'s own docstring states for any backend that "cannot be
reached to ask."

## The handle rule

`skillc/backend.py`'s neutral-identity obligation applies to this protocol's
`handle` exactly as it applies to any other backend's: the token `prepare`
returns must be opaque and content-free - never a hostname, container name,
session id, or anything else that would make `str(handle)` leak something
host-identifying if it ended up in a ledger, a receipt, or a public issue. The
client does not parse or interpret the token; it is a bare string, round-tripped
verbatim on every later request for that attempt. Whether a given platform's
tokens actually satisfy this is a property of that platform's implementation,
not of this page - `tests/test_managed_backend.py` proves skillc's own
leak-check instrument (#63, `skillc/leak.py`) catches a token that violates it,
against a deliberately non-neutral token planted by the test stub; that proves
the CHECK, not any real platform's compliance.

## Credential hook, without choosing auth

A platform will almost certainly require a credential to authorize container
creation - the same reasoning that scopes access by credential, never by
request field, on other systems this protocol may end up talking to. This
page does not choose that mechanism; it gives the client an optional,
narrowly-scoped hook instead:

- `SKILLC_MANAGED_BACKEND_TOKEN_FILE`, when set, names a file whose contents
  (read once per `ManagedBackend` instance, stripped of trailing whitespace)
  become the `credential` field on `prepare` requests only - never repeated on
  `install`/`execute`/`confirm_stopped`/`export`/`destroy`/`confirm_absent`,
  since the platform is expected to scope the whole attempt to the credential
  presented once at allocation, not to re-authorize every call.
- The credential **never appears** in `describe()`'s claims, in any
  `ExecutionBackend` return value, in an exception message, in a log line this
  module writes, or in `str(handle)`. `tests/test_managed_backend.py` runs a
  full stub lifecycle with a planted token and leak-checks (#63) every record,
  report and exception text the run produces; the token must not appear
  anywhere in that output.
- Unset `SKILLC_MANAGED_BACKEND_TOKEN_FILE` omits `credential` from the
  `prepare` request entirely, rather than sending an empty string - a platform
  that requires one refuses the request the ordinary way.

## Not yet covered

- **Streaming.** `execute`'s response is a single blocking reply once the
  subject stops (or the platform times it out); there is no progress
  streaming or partial-output delivery. A later protocol version may add one;
  this page reserves nothing for it yet.
- **`export`'s whole-archive-in-one-response shape** is simple but unbounded -
  nothing here caps `archive_b64`'s size. A production platform will likely
  want a size bound or a chunked transfer; this page does not specify one
  yet, and a caller should treat an oversized response as a transport failure
  (see [Error and unavailable semantics](#error-and-unavailable-semantics)).
- **Conformance against a real platform.** This page, and `ManagedBackend`,
  are proven only against `tests/fixtures/managed-backend/stub_server.py`, a
  test-only stand-in. `interfaces.md`'s conformance cases through a REAL
  platform-created container, and parity with `DockerBackend` on the same
  trial, are owed once a platform actually implements this page -
  `docs/specs/evaluation-facility/support-matrix.md` carries that row as
  `owed`, not `demonstrated`, until then.
