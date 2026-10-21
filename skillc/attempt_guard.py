"""The nested-codex guard on attempts with no fixture service (#500).

#434 put the guard (`codex_guard`, `fixture_overlay.install_codex_guard`) inside
`fixture_attempt.FixtureSession`, so only the Level-3 fixture path carried it.
Calibration attempts (`skillc calibration-run`, #287) never pass a fixture, so
an agent there could launch its own `codex` with any model and any server-side
configuration. In the #287 option-1 pilot one did: `codex exec --ephemeral
--model gpt-6-sol`, which reached the model, wrote no session file, and left
the attempt reading `model_eligible=True` (#500).

`AttemptGuard` is the guard half of `FixtureSession` and nothing else: the same
overlay, the same `codex_guard` route on the attempt's one trigger socket, the
same rule that a refused guard line makes the count unknown, and the same
finalize-time channel checks. `FixtureSession` is unchanged.

THE TRANSCRIPT SCAN IS A BACKSTOP, NOT THE GUARD (orchestrator condition 2 on
#500). The guard runs only in front of a BARE `codex`: a call by absolute path
(`/usr/local/bin/codex`, `node .../codex.js`) never reaches it and sends
nothing, so the guard's count can read zero with a nested client having run.
`scan_codex_invocations` reads the top-level transcript's own tool-call
commands for codex at a COMMAND position - by bare name or by path - and the
model each names. `assess` then treats any invocation the guard did not record
as nested-unrefused: credit is blocked and the schedule stops. It is a
heuristic over command text: a launch the transcript does not show (a script
the agent wrote and ran, a compiled helper) is not seen. A false hit fails
closed (a stop), never open.

Stdlib only, apart from the overlay (AGENTS.md).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import codex_guard as cg
from . import fixture_overlay as fo
from .decide_reply_channel import ChannelRefusal

#: The policy every calibration attempt runs under: flow:auto's Step 6
#: improvises a nested codex review, and the guard REFUSING it, before any
#: model contact, is containment working (#279 ruling G1, applied by #500).
CALIBRATION_POLICY = "refusal-expected"

Decide = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass
class AttemptGuard:
    """One attempt's guard, with no fixture service behind it."""

    attempt_id: str
    nested_policy: str | None = CALIBRATION_POLICY
    expected_top_level: int = 1
    overlay: dict[str, object] | None = None
    failure: str | None = None
    guard: cg.CodexGuardSession = field(init=False)
    _finished: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.nested_policy is not None and self.nested_policy not in cg.NESTED_POLICIES:
            raise ValueError(f"nested_policy must be one of {cg.NESTED_POLICIES}, not {self.nested_policy!r}")
        self.guard = cg.CodexGuardSession(self.attempt_id)

    def routes(self) -> dict[str, tuple[Decide, frozenset[str]]]:
        return {"codex_guard": (self.guard.decide, cg.REQUEST_KEYS)}

    def watch(self, decide: Decide) -> Decide:
        """`FixtureSession.watch`'s rule: a `codex_guard` request refused
        anywhere, the dispatcher's own key check included, marks the record
        unhealthy, so the count reads unknown, never zero."""
        def watched(request: Mapping[str, object]) -> Mapping[str, object]:
            try:
                return decide(request)
            except ChannelRefusal:
                if request.get("op") == "codex_guard":
                    self.guard.channel_unavailable = True
                raise
        return watched

    def bind(self, backend: Any, handle: object, environment: Mapping[str, str]) -> None:
        """Place the guard before the agent starts; any failure refuses the attempt."""
        try:
            self.overlay = fo.install_codex_guard(backend, handle, environment)
        except Exception as exc:
            self.failure = f"codex guard binding failed: {type(exc).__name__}: {exc}"
            raise

    def finish(self, backend: Any, handle: object) -> None:
        """After the agent stops: the channel's health, then the record closes."""
        with self._lock:
            if self._finished:
                return
            self._finished = True
        try:
            if backend.trigger_log(handle) is None:
                self.guard.channel_unavailable = True
        except Exception:  # noqa: BLE001 - a failed drain is an unhealthy channel, never a clean one
            self.guard.channel_unavailable = True
        try:
            dropped = backend.trigger_dropped(handle)
        except Exception:  # noqa: BLE001 - an unreadable count is incomplete coverage
            dropped = None
        if dropped is None or dropped > 0:
            self.guard.channel_unavailable = True
        self.guard.finalize()

    def record(self) -> dict[str, Any]:
        return cg.summarize(self.attempt_id, list(self.guard.decisions), self.guard.channel_unavailable,
                            expected_top_level=self.expected_top_level, nested_policy=self.nested_policy)

    def report(self, observation: object, declared_model: str | None = None) -> dict[str, Any]:
        """What the attempt's result carries: the guard's counts, the
        transcript backstop's hits, and the verdict both reach together."""
        nested = self.record()["nested"]
        invocations = (observation.get("transcript_codex_invocations")
                       if isinstance(observation, Mapping) else None)
        return {"nested": nested, "failure": self.failure, "transcript_invocations": invocations,
                **assess(nested, invocations, declared_model, failure=self.failure,
                         nested_policy=self.nested_policy)}


def credit_block(report: Mapping[str, Any] | None) -> str | None:
    """The credit gate's reason from an `AttemptGuard.report`, or None."""
    if not isinstance(report, Mapping):
        return "not credited: nested-codex guard record absent"
    reason = report.get("block")
    return str(reason) if reason is not None else None


def containment_trigger(record: Mapping[str, Any]) -> str | None:
    """Why this attempt stops a calibration schedule, or None. Only a
    dispatched attempt is read; for one, a missing guard report is a stop."""
    if record.get("disposition") in ("not-run", "unavailable"):
        return None
    report = record.get("codex_guard")
    if not isinstance(report, Mapping):
        return "the nested-codex guard report is missing for a dispatched attempt"
    stop = report.get("stop")
    return str(stop) if stop is not None else None


# ------------------------------------------------------------------ assessment

def assess(nested: Mapping[str, Any] | None, invocations: object, declared_model: str | None, *,
           failure: str | None = None, nested_policy: str | None = CALIBRATION_POLICY) -> dict[str, Any]:
    """The guard record and the transcript backstop, read together.

    - `block`: why the attempt is not credited (`codex_guard.credit_block`
      under the policy, then any bypass), or None.
    - `stop`: why the schedule stops, or None. A refusals-only record under
      `refusal-expected` does not stop; a passed-through, suspected,
      ancestry-unknown or unknown record does, and so does any bypass.
    - `bypass`: transcript invocations the guard did not record: every one by a
      path other than the guard's own, and bare ones beyond the guard's
      refusals (a guarded, refused launch is never counted twice).
    - `other_models`: models named by a nested invocation that are not the
      declared one - a nested session on another model makes the attempt
      ineligible whether or not it was refused, because a refused one cannot
      be told apart from one that ran by the transcript alone.
    """
    hits = [h for h in invocations if isinstance(h, Mapping)] if isinstance(invocations, list) else None
    bypass: list[str] = []
    other_models: list[str] = []
    if hits is None:
        bypass.append("the transcript's codex invocations were not scanned")
    else:
        refused = 0
        if isinstance(nested, Mapping):
            refused = int(nested.get("confirmed") or 0) + int(nested.get("ancestry_unknown") or 0)
        bare = [h for h in hits if h.get("guarded") is True]
        bypass += [f"codex by path, past the guard: {h.get('program')}" for h in hits if h.get("guarded") is not True]
        if len(bare) > refused:
            bypass.append(f"{len(bare)} bare codex invocation(s) in the transcript, {refused} refused by the guard")
        if declared_model is not None:
            other_models = sorted({str(h["model"]) for h in hits
                                   if isinstance(h.get("model"), str) and h["model"] != declared_model})
    block = failure and f"not credited: {failure}"
    block = block or cg.credit_block({"nested": nested} if nested is not None else None, nested_policy=nested_policy)
    if block is None and bypass:
        block = "not credited: nested codex past the guard (" + "; ".join(bypass) + ")"
    stop: str | None = None
    if failure:
        stop = failure
    elif bypass:
        stop = "nested codex past the guard: " + "; ".join(bypass)
    elif not (nested_policy == CALIBRATION_POLICY and cg.refusals_only(nested)):
        status = nested.get("status") if isinstance(nested, Mapping) else None
        if status != "zero":
            stop = cg.credit_block({"nested": nested} if nested is not None else None) or \
                f"nested-codex status {status!r}"
    return {"block": block, "stop": stop, "bypass": bypass, "other_models": other_models}


# -------------------------------------------------- the transcript backstop

#: The guard's own placement: a call to it by path is still guarded.
GUARDED_PATHS = frozenset({fo.CODEX_GUARD_PATH})

#: A command position: the start of a command, or after a separator, a
#: subshell or substitution opener, a `-c` string, or a wrapper that runs its
#: argument as a command.
_POSITION = (r"(?:^|[;&|(\n`{]|\$\(|(?<!\S)-\w*c\s+['\"]|\bxargs\s+|"
             r"\b(?:exec|nohup|sudo|time|command)\s+|\btimeout\s+\S+\s+|\benv\s+(?:\S+=\S*\s+)*)")
_PROGRAM = re.compile(
    _POSITION + r"\s*['\"]?(?P<program>(?:node(?:js)?\s+(?:-\S+\s+)*)?(?:\S*/)?codex(?:\.js|\.mjs)?)"
    r"(?=['\"]?(?:\s|$|;|&|\|))(?P<rest>[^\n;&|]*)")
_PROBE = re.compile(r"\b(?:command\s+-v|which|type|hash)\s+codex\b")
_MODEL = re.compile(r"(?:--model|(?<!\S)-m)(?:\s+|=)['\"]?(?P<m>[^\s'\"]+)|-c\s+['\"]?model=['\"]?(?P<c>[^\s'\"]+)")
_JS_CMD = re.compile(r"\b(?:cmd|command)\s*:\s*(?P<q>[\"'`])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)", re.DOTALL)


def _js_string(body: str, quote: str) -> str:
    """A JS string literal's value; undecodable escapes keep the raw text,
    which the scan still reads (it fails toward a hit, never away from one)."""
    if quote != '"':
        body = re.sub(r'(?<!\\)"', '\\"', body.replace("\\" + quote, quote))
    try:
        value = json.loads('"' + body + '"')
    except ValueError:
        return body
    return value if isinstance(value, str) else body


def _commands(payload: Mapping[str, Any]) -> list[str]:
    """Every shell command one tool-call item carries, as text."""
    out: list[str] = []
    kind = payload.get("type")
    if kind in ("function_call", "local_shell_call"):
        raw = payload.get("arguments") if kind == "function_call" else payload.get("action")
        args: object = raw
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except ValueError:
                args = raw
        if isinstance(args, Mapping):
            for key in ("cmd", "command"):
                value = args.get(key)
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, list):
                    out.append(" ".join(map(str, value)))
        elif isinstance(args, str):
            out.append(args)
    elif kind == "custom_tool_call":
        source = payload.get("input")
        if isinstance(source, str):
            out.extend(_js_string(m.group("s"), m.group("q")) for m in _JS_CMD.finditer(source))
    return out


def scan_command(command: str) -> list[dict[str, Any]]:
    """Codex invocations at a command position in one command string."""
    hits: list[dict[str, Any]] = []
    for m in _PROGRAM.finditer(command):
        program = m.group("program").strip()
        start = m.start("program")
        if _PROBE.search(command[max(0, start - 16):m.end("program")]):
            continue  # `command -v codex`: a lookup, not a launch
        path = program.split()[-1]
        guarded = not program.startswith("node") and ("/" not in path or path in GUARDED_PATHS)
        model_match = _MODEL.search(m.group("rest"))
        model = (model_match.group("m") or model_match.group("c")) if model_match else None
        hits.append({"program": program, "guarded": guarded, "model": model,
                     "argv_head": (program + m.group("rest"))[:200]})
    return hits


def scan_codex_invocations(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every codex invocation the transcript's tool-call commands show."""
    hits: list[dict[str, Any]] = []
    for line in lines:
        if line.get("type") != "response_item":
            continue
        payload = line.get("payload")
        if not isinstance(payload, Mapping):
            continue
        for command in _commands(payload):
            hits.extend(scan_command(command))
    return hits


def scan_transcript_text(text: str) -> list[dict[str, Any]]:
    lines: list[Mapping[str, Any]] = []
    for raw in text.splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, Mapping):
            lines.append(obj)
    return scan_codex_invocations(lines)
