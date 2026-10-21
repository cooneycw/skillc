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
        files = observation.get("transcript_files_found") if isinstance(observation, Mapping) else None
        return {"nested": nested, "failure": self.failure, "transcript_invocations": invocations,
                **assess(nested, invocations, declared_model, failure=self.failure,
                         nested_policy=self.nested_policy, sessions=files if isinstance(files, int) else None)}


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
           failure: str | None = None, nested_policy: str | None = CALIBRATION_POLICY,
           sessions: int | None = None) -> dict[str, Any]:
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
    if sessions is not None and sessions > 1:
        # A calibration attempt is one top-level session: another one is a
        # client the harness did not start (counter-model review, pass 1).
        bypass.append(f"{sessions} transcript sessions in one attempt")
    other_models: list[str] = []
    if hits is None:
        bypass.append("the transcript's codex invocations were not scanned")
    else:
        refused = 0
        if isinstance(nested, Mapping):
            refused = int(nested.get("confirmed") or 0) + int(nested.get("ancestry_unknown") or 0)
        bare = [h for h in hits if h.get("guarded") is True]
        bypass += ["a tool call ran a command the scan could not read" if h.get("unreadable")
                   else f"codex by path, past the guard: {h.get('program')}"
                   for h in hits if h.get("guarded") is not True]
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
#: argument as a command; then any `NAME=value` assignment prefixes.
_POSITION_START = (r"(?:^|[;&|(\n`{]|\$\(|(?<!\S)-\w*c\s+['\"]|\bxargs\s+|"
                   r"\b(?:exec|nohup|sudo|time|command|then|do|else|elif|if|while|until)\s+|!\s+|"
                   r"\btimeout\s+\S+\s+|\benv\s+(?:\S+=\S*\s+)*)")
_POSITION = _POSITION_START + r"\s*(?:[A-Za-z_]\w*=\S*\s+)*"
#: The text before a quote ends at a command position: the quoted word is the
#: program itself, never literal text (counter-model review, pass 2).
_AT_POSITION = re.compile("(?:" + _POSITION + r")$")
#: `rest` stops at a separator AND at a substitution or backtick, so a launch
#: nested inside an outer command's arguments is found at its own position
#: (counter-model review, pass 1).
_PROGRAM = re.compile(
    _POSITION + r"['\"]?(?P<program>(?:node(?:js)?\s+(?:-\S+\s+)*)?(?:\S*/)?codex(?:\.js|\.mjs)?)"
    r"(?=['\"]?(?:\s|$|;|&|\||\)|`))(?P<rest>(?:(?!\$\()[^\n;&|`)])*)")
_PROBE = re.compile(r"\b(?:command\s+-v|which|type|hash)\s+codex\b")
_MODEL_FLAG = re.compile(r"(?:--model|(?<!\S)-m)(?:\s+|=)|(?<!\S)-c\s+")
_MODEL_VALUE = re.compile(r"['\"]?(?P<m>[^\s'\"]+)")
_CONFIG_MODEL = re.compile(r"['\"]?model\s*=\s*['\"]?(?P<m>[^\s'\"]+)")
#: A command key, bare or quoted (`cmd:`, `"cmd":`), with its string literal.
_JS_CMD = re.compile(r"(?:\b|(?<=[\"']))(?:cmd|command)[\"']?\s*:\s*(?P<q>[\"'`])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)",
                     re.DOTALL)
#: A command-running call in a tool-call input, each judged on its own: its
#: argument must open with a literal `{cmd: "..."}` or it is unreadable
#: (counter-model review, pass 2 - one readable sibling masked the rest).
_RUNS_COMMAND = re.compile(r"\b(?:exec_command|shell|spawn|execFile|execSync|spawnSync)\s*\(")
_LITERAL_CMD_ARG = re.compile(r"\s*\{\s*[\"']?(?:cmd|command)[\"']?\s*:\s*(?P<q>[\"'`])")
#: `write_stdin` sends text to a running shell: that text is a command.
_JS_STDIN = re.compile(r"\bwrite_stdin\s*\(\s*\{[^}]*?[\"']?chars[\"']?\s*:\s*(?P<q>[\"'`])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)",
                       re.DOTALL)
#: Function-call tools that run no command (counter-model review, pass 2: an
#: ordinary `update_plan` read as an unreadable command and stopped the run).
#: Any other tool is scanned for `cmd`/`command`, and is unreadable without one.
NON_EXECUTING_TOOLS = frozenset({"update_plan", "view_image", "apply_patch", "list_mcp_resources",
                                 "list_mcp_resource_templates", "read_mcp_resource", "request_user_input"})
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
_EXEC_CONTEXT = re.compile(r"(?<!\S)-\w*c\s*$")


def _substitutions(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """`$( ... )` (nesting counted) and backtick spans inside [lo, hi)."""
    spans: list[tuple[int, int]] = []
    i = lo
    while i < hi:
        if text.startswith("$(", i):
            depth, j = 1, i + 2
            while j < hi and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            spans.append((i, j))
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1, hi)
            j = hi if j < 0 else j + 1
            spans.append((i, j))
            i = j
        else:
            i += 1
    return spans


def executable_view(command: str) -> str:
    """`command` with LITERAL text blanked to spaces, same length: a quoted
    string, unless it is a `-c` script, keeps only its command substitutions,
    and so does a heredoc body (a quoted delimiter keeps nothing). So
    `echo 'codex exec x'` launches nothing, while `sh -c 'codex exec x'` and
    `"$(codex exec x)"` do (counter-model review, pass 1)."""
    n = len(command)
    blank = [False] * n

    def mask(lo: int, hi: int, keep_substitutions: bool) -> None:
        keep = {k for a, b in (_substitutions(command, lo, hi) if keep_substitutions else []) for k in range(a, b)}
        for k in range(lo, hi):
            if k not in keep:
                blank[k] = True

    for m in _HEREDOC.finditer(command):
        body = command.find("\n", m.end())
        if body < 0:
            continue
        end = body + 1
        while end < n:
            line_end = command.find("\n", end)
            line_end = n if line_end < 0 else line_end
            if command[end:line_end].strip() == m.group(2):
                break
            end = line_end + 1
        mask(body + 1, min(end, n), keep_substitutions=not m.group(1))
    i = 0
    while i < n:
        c = command[i]
        if blank[i]:
            i += 1
        elif c == "\\":
            i += 2
        elif c in "'\"":
            j = i + 1
            while j < n and command[j] != c:
                j += 2 if c == '"' and command[j] == "\\" else 1
            if not _EXEC_CONTEXT.search(command[:i]) and not _AT_POSITION.search(command[:i]):
                mask(i + 1, min(j, n), keep_substitutions=c == '"')
            i = j + 1
        else:
            i += 1
    return "".join(" " if blank[k] and command[k] != "\n" else command[k] for k in range(n))


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


def _commands(payload: Mapping[str, Any]) -> tuple[list[str], bool]:
    """Every shell command one tool-call item carries, as text, and whether
    the item runs a command that could NOT be read - which is never "no
    launch" (counter-model review, passes 1 and 2)."""
    out: list[str] = []
    kind = payload.get("type")
    unreadable = False
    if kind in ("function_call", "local_shell_call"):
        raw = payload.get("arguments") if kind == "function_call" else payload.get("action")
        args: object = raw
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except ValueError:
                args = raw
        name = payload.get("name") if kind == "function_call" else "local_shell"
        if name in NON_EXECUTING_TOOLS:
            return out, False
        if name == "write_stdin":
            chars = args.get("chars") if isinstance(args, Mapping) else None
            return ([chars] if isinstance(chars, str) and chars else []), not isinstance(args, Mapping)
        if isinstance(args, Mapping):
            for key in ("cmd", "command"):
                value = args.get(key)
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, list):
                    out.append(" ".join(map(str, value)))
        elif isinstance(args, str):
            out.append(args)
        unreadable = not out
    elif kind == "custom_tool_call":
        source = payload.get("input")
        if not isinstance(source, str):
            return out, True
        out.extend(_js_string(m.group("s"), m.group("q")) for m in _JS_CMD.finditer(source))
        out.extend(_js_string(m.group("s"), m.group("q")) for m in _JS_STDIN.finditer(source))
        for call in _RUNS_COMMAND.finditer(source):
            literal = _LITERAL_CMD_ARG.match(source, call.end())
            if literal is None:
                unreadable = True
            elif literal.group("q") == "`":
                # A template literal can splice in any text: unreadable unless plain.
                close = source.find("`", literal.end())
                if close < 0 or "${" in source[literal.end():close]:
                    unreadable = True
    return out, unreadable


def _model(original: str, view: str, lo: int, hi: int) -> str | None:
    """The model a launch names, located on the executable view (a flag inside
    literal text is no flag) and read from the original (its value may be quoted)."""
    for flag in _MODEL_FLAG.finditer(view, lo, hi):
        if flag.group().lstrip().startswith("-c"):
            value = _CONFIG_MODEL.match(original, flag.end())
        else:
            value = _MODEL_VALUE.match(original, flag.end())
        if value is not None:
            return value.group("m")
    return None


def scan_command(command: str) -> list[dict[str, Any]]:
    """Codex invocations at a command position in one command string."""
    view = executable_view(command)
    hits: list[dict[str, Any]] = []
    for m in _PROGRAM.finditer(view):
        program = m.group("program").strip()
        start = m.start("program")
        if _PROBE.search(view[max(0, start - 16):m.end("program")]):
            continue  # `command -v codex`: a lookup, not a launch
        path = program.split()[-1]
        guarded = not program.startswith("node") and ("/" not in path or path in GUARDED_PATHS)
        hits.append({"program": program, "guarded": guarded,
                     "model": _model(command, view, m.start("rest"), m.end("rest")),
                     "argv_head": command[m.start("program"):m.end("rest")][:200]})
    return hits


def scan_codex_invocations(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every codex invocation the transcript's tool-call commands show, and an
    `unreadable` hit for each tool call that ran a command the scan could not read."""
    hits: list[dict[str, Any]] = []
    for line in lines:
        if line.get("type") != "response_item":
            continue
        payload = line.get("payload")
        if not isinstance(payload, Mapping):
            continue
        commands, unreadable = _commands(payload)
        if unreadable:
            hits.append({"program": None, "guarded": False, "model": None, "unreadable": True,
                         "argv_head": json.dumps(payload)[:200]})
        for command in commands:
            hits.extend(scan_command(command))
    return hits


def scan_transcript_text(text: str) -> list[dict[str, Any]] | None:
    """The scan over one raw transcript, or None when the transcript could
    not be read whole: empty, or a non-empty line that is not a JSON object.
    None is "not scanned", which `assess` stops on - never a clean zero
    (counter-model review, pass 2)."""
    lines: list[Mapping[str, Any]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(obj, Mapping):
            return None
        lines.append(obj)
    if not lines:
        return None
    return scan_codex_invocations(lines)
