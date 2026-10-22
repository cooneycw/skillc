"""The agent trial driver (issue #106): one real-agent attempt, end to end,
through `skillc/lifecycle.py`'s `ExecutionBackend` seam.

Composes, for one client (Claude Code or Codex), pieces that were each
merged separately and never run together before this module:

  - the subscription-login credential (#98, `skillc/credential.py`) -
    resolved, freshness-checked, and delivered into the container's home
    directory via `docker_backend.DockerBackend.deliver_home_file`, from
    `lifecycle.run_through_backend`'s `before_execute` hook (#108);
  - the per-trial home and onboarding seed (#78, `skillc/trial_bootstrap.py`)
    - delivered the same way, for the same structural reason: a container's
      home directory is reachable only through `deliver_home_file`, never
      `install()`'s `CONTAINER_WORKSPACE`-only `surface`;
  - the real transcript, discovered (not guessed) after the agent stops via
    `docker_backend.DockerBackend.read_home_tree` - neither client's
    transcript filename is known in advance, since each embeds a
    session id the CLI itself chooses at runtime - and normalized through
    the per-client transcript adapter (#107,
    `skillc/transcript_adapter.py`), from `run_through_backend`'s
    `observe_before_teardown` hook (#108). The prompt-delivery check and the
    liveness canary
    (`skillc/trial_bootstrap.verify_first_user_message`, `.check_canary`)
    both run against that REAL transcript here, never a synthetic one;
  - `refresh_observed` (#98): the credential is read back the same way and
    compared against what was delivered, recorded in the same observation.

FAILURE SEMANTICS, exactly `lifecycle.py`'s own two-hook design (see that
module's docstring): a `before_execute` failure (credential expired,
delivery failed, a bad seed) BLOCKS the attempt - `execute()` never runs,
and the attempt is finalized `unavailable`. A `observe_before_teardown`
failure (the transcript could not be found or parsed) is recorded as an
UNKNOWN observation, and the attempt still reaches whatever disposition
`lifecycle.py` itself derives - a fact ABOUT the attempt, never a reason to
hide that it happened.

GRADING IS A SEPARATE, LATER GATE THIS MODULE OWNS, layered ON TOP of
`lifecycle.py`'s own disposition (#106's own acceptance: "prompt-delivery
mismatch: the attempt is BLOCKED, not graded"). `lifecycle.py` stays
generic - it has no concept of "graded" at all - so `run_one_attempt`
itself refuses to call `verify.grade_agent_attempt` unless the observation shows
BOTH the prompt-delivery check and the liveness canary were confirmed
against the real transcript. A captured-but-unconfirmed attempt is real
data (kept in the record, under `observation`), but never handed to the
verifier as something worth grading.

STRUCTURALLY UNABLE TO LAUNCH WITHOUT `SKILLC_ALLOW_REAL_AGENT=1` - this
module adds no new gate here; every call passes through
`lifecycle.run_through_backend`'s own existing `_refuse_real_agent`, unchanged.

NO REAL MODEL CALL ANYWHERE IN THIS MODULE'S OWN TEST SUITE (#106's own
acceptance, mirroring #96's structural test for the judge) -
`tests/test_agent_trial.py` runs entirely against the fake docker CLI and
`tests/fixtures/agent-trial/fake_agent_client.py`, a scripted stand-in that
writes a realistic transcript for each client format, never a real
`claude`/`codex` binary.

THE OPERATOR'S LIVE RUN (issue #106, `evals/agent-trial-live/README.md`):
codex-cli 0.157.1, on a real subscription login, once per collection. The
real argv stays caller-supplied (this module takes `base_argv` and `prompt`
as parameters, deliberately never inventing its own - the same layering
`run_through_backend` itself already uses for `argv`). The host login still
answered `codex login status` afterwards, with a byte-identical credential
file. `transcript_census` found no unrecognized transcript types. Still NOT
shown: an in-container token refresh, Claude Code (#124), and drift in any
later CLI version - the census is how a later run would see it.

Docker-specific, deliberately: `deliver_home_file`/`read_home_file`/
`read_home_tree` are `DockerBackend` methods, not part of the generic
`ExecutionBackend` Protocol (see `docker_backend.py`'s own docstring) - this
module is the first caller that needs them, so it is the first to require a
concrete `DockerBackend` rather than the Protocol alone.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import functools
import hashlib
import json
import posixpath
import re
import secrets
import shlex
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from . import attempt_guard as ag
from . import codex_guard as cg
from . import controller_turns as ct
from . import (
    credential,
    demo,
    gate_overlay,
    leak,
    profile,
    records,
    stage_capture,
    trial,
    trial_bootstrap,
    verify,
    witness_capture,
)
from . import credential_steward as cs
from . import egress as eg
from . import fixture_overlay as fo
from . import fixture_service as fs
from . import project_gate as pg
from . import runtime_supply as rs
from . import source_digest as sd
from . import transcript_adapter as ta
from .backend import (
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    ExecutionBackend,
    Limits,
    TurnCapableBackend,
)
from .decide_reply_channel import ChannelRefusal
from .docker_backend import (
    CANARY_RESULT_FILENAME,
    CONTAINER_HOME,
    CONTAINER_WORKSPACE,
    TRIGGER_SOCKET_PATH,
    DockerBackend,
)
from .fixture_attempt import AttemptFixture, FixtureSession
from .gate_witness import GateWitness, GateWitnessRecord
from .lifecycle import run_through_backend
from .ordering import Order
from .trial_bootstrap import CanaryNotSatisfied, MCPServerSpec, PromptDeliveryError


@dataclass(frozen=True)
class ClientSpec:
    """Everything about ONE client that is structurally FIXED, never
    per-attempt - named explicitly, never inferred (the same "no scan, no
    guess" discipline `credential.py`'s own `resolve_path` already applies).
    Per-attempt facts (the prompt, the skill under test, the argv) are
    parameters to `run_one_attempt`, never baked in here."""

    name: str  # credential.CLIENT_SPECS' own key: "claude" | "codex"
    pinned_version_key: str  # docker/trial/pinned-versions.json's own key: "claude_code" | "codex"
    transcript_container_reldir: str  # e.g. ".claude/projects" | ".codex/sessions"
    transcript_suffix: str
    parse_transcript: Callable[[str], list[ta.NormalizedEvent]]
    supports_name_flag: bool
    #: "structural" | "heuristic" - see `TranscriptObservation.skill_invocation_detection`.
    skill_invocation_detection: str
    #: Client-specific extra home files beyond the credential - the
    #: onboarding seed dance for Claude Code (#78); nothing at all for Codex,
    #: whose `exec` subcommand needed no seed in every live probe run for
    #: #106/#107 (confirmed empirically, 2026-09-27, not assumed).
    compose_home_files: Callable[[_AttemptContext], dict[str, bytes]]
    #: Reads the run's own identity (observed model, CLI version, token usage,
    #: the agent's closing message) out of the raw transcript - issue #12.
    #: `None` for a client with no adapter yet, recorded as `run_metadata: None`.
    run_metadata: Callable[[str], dict[str, object]] | None = None
    #: Reads the skills the client itself listed to the model out of the
    #: real transcript (issue #124) - `None` when this client's transcript
    #: carries no such listing at all. Codex's rollout has none this adapter
    #: reads; its discovery evidence is the model-free canary instead.
    read_skill_listing: Callable[[str], tuple[str, ...] | None] | None = None


@dataclass(frozen=True)
class _AttemptContext:
    """Everything a `compose_home_files` implementation needs, gathered in
    one place so `ClientSpec` stays a plain, picklable-shaped record."""

    workdir: PurePosixPath
    mcp_servers: Mapping[str, MCPServerSpec]
    cli_version: str


def _claude_home_files(ctx: _AttemptContext) -> dict[str, bytes]:
    seed = trial_bootstrap.compose_claude_seed(ctx.workdir, list(ctx.mcp_servers), ctx.cli_version)
    seed_bytes = json.dumps(dict(seed), indent=2, sort_keys=True).encode("utf-8")
    # validate_seed_before_launch reads from a real path - checked against
    # THESE bytes via a throwaway temp file, never skipped just because the
    # delivery target is a container rather than a host home this time.
    with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
        tmp.write(seed_bytes)
        tmp.flush()
        trial_bootstrap.validate_seed_before_launch(Path(tmp.name), ctx.workdir, ctx.cli_version)
    files = {".claude.json": seed_bytes}
    if ctx.mcp_servers:
        mcp_config = trial_bootstrap.compose_mcp_config(ctx.mcp_servers)
        files[".mcp.json"] = json.dumps(mcp_config, indent=2, sort_keys=True).encode("utf-8")
    return files


def _codex_home_files(ctx: _AttemptContext) -> dict[str, bytes]:
    return {}


#: The `response_item` payload types `transcript_adapter.parse_codex_transcript`
#: either normalizes (`message`, `custom_tool_call`, `custom_tool_call_output`)
#: or deliberately ignores (`reasoning`), as observed on codex-cli 0.157.1
#: (tests/fixtures/transcripts/codex/README.md). Any OTHER payload type in a
#: real transcript is format drift the adapter silently skips - e.g. a tool
#: call arriving as a new payload type would never pair with its result, and
#: the canary would read "no tool use" on a genuinely live run (issue #106's
#: owed "real transcript format drift").
#: #486 (2026-10-20): `function_call` / `function_call_output` (the model's
#: `exec_command` calls) are now normalized too. A type outside this set is
#: no longer only recorded: it blocks credit (the gate below) and, on the
#: live fixture path, stops the schedule (`fixture_live.containment_trigger`).
CODEX_KNOWN_RESPONSE_ITEM_TYPES = frozenset({"message", "custom_tool_call", "custom_tool_call_output", "reasoning",
                                             "function_call", "function_call_output"})


def credit_block(
    observation: object, *, client: str, disposition: object, witness_failure: str | None = None,
    fixture_block: Callable[[], str | None] | None = None,
) -> str | None:
    """Why an attempt is NOT graded, or `None` when grading may run - the
    credit gate, in the order it has always applied. Pure, so a retained run's
    re-grade (#486) applies the SAME gate a live attempt does. `fixture_block`
    is evaluated only when every earlier condition has passed, as before."""
    if witness_failure is not None:
        return witness_failure
    if disposition != "captured":
        return f"attempt disposition is {disposition!r}, not captured"
    if not isinstance(observation, dict) or observation.get("status") == "unknown":
        return "the transcript observation is unknown - never graded on an unconfirmed attempt"
    if not observation.get("grading_eligible"):
        return (
            f"prompt_delivered={observation.get('prompt_delivered')!r}, "
            f"canary_satisfied={observation.get('canary_satisfied')!r} - "
            "never graded without both confirmed against the real transcript"
        )
    if not isinstance(observation.get("server_side_tool_uses"), list):
        # #442: the census never inspected the raw transcript - unknown,
        # never read as clean.
        return "not credited: server-side tool inspection unavailable"
    if server_side := observation["server_side_tool_uses"]:
        # #442: a tool that ran at the provider reached outside the
        # controlled environment; the attempt stays in every account, but
        # is never credited.
        return f"not credited: server-side tool observed ({', '.join(server_side)})"
    if client == "codex" and (incomplete := _census_incomplete(observation)):
        # Counter-model review, pass 2 (#486): the same coverage `fixture_live.
        # containment_trigger` requires - a stop that fires after grading
        # does not undo a credit already given, and other callers have no stop.
        return f"not credited: the transcript census is incomplete ({incomplete})"
    if client == "codex" and not isinstance(observation.get("transcript_unrecognized_types"), list):
        # #486: a census that could not assess the transcript's own item
        # types is unknown, never clean.
        return "not credited: the transcript census could not assess its response-item types"
    if drift := observation.get("transcript_unrecognized_types"):
        # #486: format drift FAILS CLOSED. On 2026-10-20 the census listed
        # function_call/function_call_output on every attempt and nothing
        # read it; 10 paid attempts went ungraded in silence.
        return (f"not credited: transcript format drift - unrecognized response-item types "
                f"{sorted(map(str, drift))}; the adapter cannot read these lines")
    if fixture_block is not None and (block := fixture_block()):
        # #434: the same posture for the fixture's own evidence and for a
        # nested codex (D3 ruling): in every account, never credited.
        return block
    return None


def _census_incomplete(observation: Mapping[str, object]) -> str | None:
    """Why a codex census does not cover its whole transcript, or `None`: no
    response item inspected, a census error, or a line skipped as unparseable
    or non-object (a truncated item parses as nothing). #486."""
    inspected = observation.get("transcript_response_items_inspected")
    if isinstance(inspected, bool) or not isinstance(inspected, int) or inspected < 1:
        return f"response items inspected {inspected!r}"
    if observation.get("transcript_census_error"):
        return f"census error {observation.get('transcript_census_error')!r}"
    line_types = observation.get("transcript_line_types")
    if not isinstance(line_types, Mapping):
        return "no line-type census"
    skipped = {k: v for k, v in line_types.items() if k in ("<unparseable>", "<non-object>")}
    return f"skipped lines {skipped}" if skipped else None


def transcript_census(client: str, raw: str) -> dict[str, object]:
    """What the REAL transcript's own format looked like, independent of what
    the adapter made of it (issue #106): the client version and model the
    transcript itself names, a count per line type, and - for codex - every
    `response_item` payload type the adapter does not know, and how many
    response items there were to judge (zero reads as not assessed). Only those three
    identity fields are read; nothing account-scoped (codex's session_meta
    also carries account and user ids) is ever copied into the census.

    `unrecognized_types` is `None` for Claude Code: its transcript carries
    many top-level line types the adapter legitimately ignores, and no drift
    rule has been grounded for it yet (#124 is the Claude Code arm) - `None`
    means "not assessed", never "no drift"."""
    line_types: dict[str, int] = {}
    client_version: str | None = None
    model: str | None = None
    unrecognized: set[str] = set()
    response_items = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            line_types["<unparseable>"] = line_types.get("<unparseable>", 0) + 1
            continue
        if not isinstance(obj, dict):
            line_types["<non-object>"] = line_types.get("<non-object>", 0) + 1
            continue
        top = str(obj.get("type"))
        payload = obj.get("payload")
        payload_type = payload.get("type") if isinstance(payload, dict) else None
        key = f"{top}/{payload_type}" if payload_type is not None else top
        line_types[key] = line_types.get(key, 0) + 1
        if client == "codex":
            if top == "session_meta" and isinstance(payload, dict) and isinstance(payload.get("cli_version"), str):
                client_version = client_version or payload["cli_version"]
            if top == "turn_context" and isinstance(payload, dict) and isinstance(payload.get("model"), str):
                model = model or payload["model"]
            if top == "response_item":
                response_items += 1
                # A non-string type (a list, an object) is malformed, not
                # unhashable-and-fatal (codex review): the adapter skips such
                # a row, and the census must not be the thing that crashes.
                if not isinstance(payload_type, str):
                    unrecognized.add(f"<non-string:{type(payload_type).__name__}>")
                elif payload_type not in CODEX_KNOWN_RESPONSE_ITEM_TYPES:
                    unrecognized.add(payload_type)
        else:
            if isinstance(obj.get("version"), str):
                client_version = client_version or obj["version"]
            message = obj.get("message")
            if top == "assistant" and isinstance(message, dict) and isinstance(message.get("model"), str):
                model = model or message["model"]
    return {
        "transcript_client_version": client_version,
        "transcript_model": model,
        "transcript_line_types": dict(sorted(line_types.items())),
        "transcript_response_items_inspected": response_items if client == "codex" else None,
        # An empty population is "not assessed", never a clean result (codex
        # review): a transcript whose response items vanished or were renamed
        # entirely is exactly the drift this exists to see.
        "transcript_unrecognized_types": sorted(unrecognized) if client == "codex" and response_items else None,
    }


CLIENT_SPECS: dict[str, ClientSpec] = {
    "claude": ClientSpec(
        name="claude",
        pinned_version_key="claude_code",
        transcript_container_reldir=".claude/projects",
        transcript_suffix=".jsonl",
        parse_transcript=ta.parse_claude_code_transcript,
        supports_name_flag=True,
        skill_invocation_detection="structural",
        compose_home_files=_claude_home_files,
        read_skill_listing=ta.claude_code_skill_listing,
    ),
    "codex": ClientSpec(
        name="codex",
        pinned_version_key="codex",
        transcript_container_reldir=".codex/sessions",
        transcript_suffix=".jsonl",
        parse_transcript=ta.parse_codex_transcript,
        supports_name_flag=False,
        skill_invocation_detection="heuristic",
        compose_home_files=_codex_home_files,
        run_metadata=ta.codex_run_metadata,
    ),
}


class ServerSideChannelRefused(Exception):
    """#442: a live codex attempt was about to run with a channel to the
    outside that skillc does not control - a server-side tool left on (web
    search, remote plugins/apps), or an open network with no provider-only
    egress policy. Raised before any container exists, so nothing is spent."""


#: #442: response-item and event types that are a SERVER-SIDE tool, which runs
#: at the model provider and so never touches the container's network. Any of
#: them in a live transcript means the attempt reached outside the controlled
#: environment, and its result is not credited.
_SERVER_SIDE_TYPE = re.compile(r"web_search|mcp_|image_generation|tool_search|remote_plugin|plugin|connector|app_call|"
                               r"computer_call|browser")
#: A tool CALL whose name points at a plugin, app or MCP server. A remote plugin
#: can surface as an ordinary `function_call` with a namespaced name, which a
#: count of line types cannot see.
_SERVER_SIDE_NAME = re.compile(r"mcp__|@openai-curated|openai-curated-remote|^(apps?|plugins?|web|browser|image_gen)[._:]",
                               re.IGNORECASE)
_CALL_TYPES = frozenset({"function_call", "custom_tool_call", "local_shell_call", "mcp_tool_call"})
#: A call's own `namespace` field naming a server-side tool family, matched
#: EXACTLY (counter-model review: `namespace: "web"` with `name: "run"` has no
#: punctuation for a name pattern to find).
_SERVER_SIDE_NAMESPACES = frozenset({
    "web", "web_search", "browser", "image_gen", "image_generation", "apps", "app", "plugins", "plugin",
    "connector", "connectors", "mcp", "remote_plugin", "tool_search", "computer",
})


def server_side_tool_uses(
    transcript: bytes | None, line_types: Mapping[str, object] | None,
    local_mcp_servers: frozenset[str] = frozenset(),
) -> list[str]:
    """#442: each server-side tool use the attempt's transcript shows, as
    `<type>` or `<type>:<name>` (sorted, deduplicated). With the transcript,
    every item is read - types AND call names - and an MCP call to a server
    skillc itself configured for the attempt (`local_mcp_servers`, run inside
    the container) is local, not server-side. Without it, only the census line
    types can be read, so any MCP-looking type counts. Empty means none was
    seen in what was read; the caller must not pass "nothing read" as clean."""
    found: set[str] = set()
    if transcript is None:
        for key in (line_types or {}):
            if _SERVER_SIDE_TYPE.search(str(key).split("/", 1)[-1]):
                found.add(str(key))
        return sorted(found)
    for line in transcript.decode("utf-8", "replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        payload = entry.get("payload") if isinstance(entry, dict) else None
        if not isinstance(payload, dict):
            continue
        kind, top = str(payload.get("type")), str(entry.get("type"))
        server = payload.get("server")
        names = [n for n in (payload.get(k) for k in ("name", "server", "namespace")) if isinstance(n, str)]
        local = (isinstance(server, str) and server in local_mcp_servers) or any(
            n.startswith(f"mcp__{s}__") for n in names for s in local_mcp_servers)
        if local:
            continue
        if _SERVER_SIDE_TYPE.search(kind):
            found.add(f"{top}/{kind}")
        if kind in _CALL_TYPES:
            for name in names:
                if _SERVER_SIDE_NAME.search(name):
                    found.add(f"{top}/{kind}:{name}")
            namespace = payload.get("namespace")
            if isinstance(namespace, str) and namespace.lower() in _SERVER_SIDE_NAMESPACES:
                found.add(f"{top}/{kind}:{namespace}/{payload.get('name')}")
    return sorted(found)


class HomeFileVerificationRefused(Exception):
    """skillc#334: a delivered home file's in-container digest disagreed
    with what was expected, or could not be read back at all. Host-side
    byte checks (the ones `calibration_run._closure_home_files` already
    runs before any container exists) prove what was SENT; this proves
    what ARRIVED - a `before_execute` hook failure, so it blocks the
    attempt before the agent starts (`lifecycle.py`'s own contract), never
    folded into a normal exit code."""


_TOOLS_MARKER = "---skillc-334-tools---"

#: skillc#334 step 4: the flow-check
#: gate-witness overlay fires whenever the attempt's own `gate_entrypoint`
#: is given - an explicit, caller-supplied fact (ultimately the SUBJECT's
#: own profile declaration, threaded through `calibration_run.Treatment`),
#: never inferred from whether some file happens to be present in
#: #505: the in-container executable-bit read-back's line prefix.
_XMODE_PREFIX = "SKILLC-XMODE:"
#: #505: a source git mode -> the OWNER-ONLY delivery mode. Never broader than
#: the source (0755 -> 0700); a file with no recorded mode stays 0600.
_DELIVERY_MODES = {"100755": 0o700, "100644": 0o600}


def delivery_mode(relpath: str, modes: Mapping[str, str] | None) -> int:
    """The mode one installed file is delivered at (#505)."""
    if modes is None or relpath not in modes:
        return 0o600
    mode = modes[relpath]
    if mode not in _DELIVERY_MODES:
        raise HomeFileVerificationRefused(f"{relpath}: unsupported source mode {mode!r}")
    return _DELIVERY_MODES[mode]


#: `verify_home_files`. The orchestrator's own correction: inferring
#: witnessing from dict membership means a closure regression that drops
#: the gate script would silently skip witnessing instead of refusing -
#: "the same silent-skip shape as the .git revision check." `harness_root`/
#: `harness_path`/the shim itself are HARNESS concerns, never subject
#: facts, so they stay fixed constants here. `_FLOW_CHECK_GATE_SHIM_SOURCE`
#: is read from THIS repository's own tracked copy, the same file
#: `docker/trial/Dockerfile` COPies into the trial image - both are the
#: one tracked source, never two independent copies that could drift
#: (matching `tests/test_gate_overlay_live.py`'s own `_REAL_SHIM_SOURCE`
#: convention).
_FLOW_CHECK_GATE_HARNESS_ROOT = "/opt/skillc-harness"
_FLOW_CHECK_GATE_HARNESS_PATH = "flow-finish-gate.sh"
_FLOW_CHECK_GATE_SHIM_SOURCE = (
    Path(__file__).resolve().parent.parent / "docker" / "trial" / "flow-check-gate-shim.py"
)
#: #287 auto6: the `flow-finish` witness kind - `/flow:auto` Step 6's BARE
#: `flow-finish-gate.sh` call. It reuses #434's closed-map flow-auto shim
#: (`fixture_attempt.FLOW_AUTO_GATE_SHIM`, outside `docker/trial/` so the pinned
#: flow-check runtime's build context is unchanged) and its gate name; the
#: flow-check shim is unchanged. One declared gate, the runner's `finish` plan.
_FLOW_AUTO_GATE_SHIM_SOURCE = (
    Path(__file__).resolve().parent.parent / "docker" / "fixture-service" / "flow-auto-gate-shim.py"
)
_FLOW_FINISH_GATE = "flow-auto-finish"
_FLOW_FINISH_PLAN = "finish"
#: #525: the shim line a bundled-gate copy sets (`docker/fixture-service/
#: flow-auto-gate-shim.py`); a shim without it cannot witness a bundled gate,
#: which is why the flow-check witness of one is deferred and refused.
_SHIM_VIA_LINE = b"_VIA: str | None = None\n"
#: #525: each witnessed bundled gate's root-owned mirror of its skill's whole
#: `scripts/` directory, so the real script's BASH_SOURCE-relative siblings
#: (`gate-lib.sh`, `counter-model-receipt.py`) are the skill's own.
_BUNDLED_GATE_HARNESS_ROOT = f"{_FLOW_CHECK_GATE_HARNESS_ROOT}/bundled"


def bundled_gate_shim(shim_source: bytes, via: str) -> bytes:
    """#525: the flow-auto shim with its one `_VIA` line set to `via`."""
    if shim_source.count(_SHIM_VIA_LINE) != 1:
        raise HomeFileVerificationRefused("this gate shim cannot witness a bundled gate (no _VIA line): the "
                                          "flow-check witness of a bundled gate is deferred (#525)")
    return shim_source.replace(_SHIM_VIA_LINE, f"_VIA: str | None = {via!r}\n".encode())


def _bundled_via(path: str) -> str:
    """`.codex/skills/<skill>/scripts/<gate>` -> `bundled:<skill>`."""
    parts = path.split("/")
    if len(parts) != 5 or parts[:2] != [".codex", "skills"] or parts[3] != "scripts":
        raise HomeFileVerificationRefused(f"bundled gate entrypoint {path!r} is not .codex/skills/<skill>/scripts/<gate>")
    return f"bundled:{parts[2]}"


def _overlay_bundled_gates(
    backend: DockerBackend, handle: object, bundled: Sequence[str], verify_home_files: Mapping[str, str],
    home_files: Mapping[str, bytes], home_modes: Mapping[str, str] | None, shim_source: bytes,
) -> list[dict[str, object]]:
    """#525: witness each skill-bundled gate copy. Mirror the skill's whole
    `scripts/` directory root-owned, move the real gate into the mirror with
    the shim in its place (`gate_overlay`, unchanged), then PROVE the mirror is
    the shipped skill: it must pass `sha256sum -c` against the skill's own
    `SHA256SUMS`, and the in-place directory must fail on exactly the shimmed
    file. Returns the declared treatment deviations; refuses on any doubt."""
    deviations: list[dict[str, object]] = []
    for path in bundled:
        via = _bundled_via(path)
        scripts_dir = posixpath.dirname(path)
        gate_name = posixpath.basename(path)
        mirror = f"{_BUNDLED_GATE_HARNESS_ROOT}/{via.split(':', 1)[1]}/scripts"
        real_digest = verify_home_files.get(path)
        if real_digest is None:
            raise HomeFileVerificationRefused(f"bundled gate entrypoint {path!r} is not in the verified closure")
        siblings = {dest[len(scripts_dir) + 1:]: data for dest, data in home_files.items()
                    if dest.startswith(scripts_dir + "/") and dest != path}
        if "SHA256SUMS" not in siblings:
            raise HomeFileVerificationRefused(f"{scripts_dir} ships no SHA256SUMS: the bundled-gate mirror "
                                              "cannot be proven to be the shipped skill (#525)")
        for rel, data in sorted(siblings.items()):
            dest = f"{scripts_dir}/{rel}"
            if verify_home_files.get(dest) != "sha256:" + hashlib.sha256(data).hexdigest():
                raise HomeFileVerificationRefused(f"{dest} is not a verified closure file; refusing to mirror it")
            mode = 0o755 if (home_modes or {}).get(dest) == "100755" else 0o644
            if not backend.write_root_owned_file_in_attempt(handle, f"{mirror}/{rel}", data, mode=mode):
                raise HomeFileVerificationRefused(f"could not write the root-owned mirror of {dest}")
        shim = bundled_gate_shim(shim_source, via)
        gate_overlay.apply_flow_check_gate_overlay(
            backend, handle, subject_root=CONTAINER_HOME, harness_root=mirror, subject_path=path,
            harness_path=gate_name, expected_real_digest=real_digest[len("sha256:"):],
            expected_shim_digest=hashlib.sha256(shim).hexdigest(), shim_content=shim,
        )
        check = 'cd -- "$1" && sha256sum -c --quiet -- SHA256SUMS'
        if backend.root_output_in_attempt(handle, ["sh", "-c", check, "sh", mirror]) is None:
            raise HomeFileVerificationRefused(f"the mirror of {scripts_dir} does not verify against the skill's own "
                                              "SHA256SUMS: it is not byte-identical to the shipped skill (#525)")
        in_place = backend.root_output_in_attempt(
            handle, ["sh", "-c", 'cd -- "$1" && { sha256sum -c -- SHA256SUMS 2>/dev/null; true; }', "sh",
                     f"{CONTAINER_HOME}/{scripts_dir}"])
        failures = sorted(line.rsplit(":", 1)[0] for line in (in_place or b"").decode("utf-8", "replace").splitlines()
                          if not line.endswith(": OK"))
        if in_place is None or failures != [gate_name]:
            raise HomeFileVerificationRefused(f"the installed {scripts_dir} differs from its SHA256SUMS on {failures}, "
                                              f"not on exactly the declared shim {gate_name!r} (#525)")
        deviations.append({"path": path, "via": via, "real_digest": real_digest,
                           "shim_digest": "sha256:" + hashlib.sha256(shim).hexdigest(), "mirror": mirror,
                           "mirror_verified": True, "in_place_checksum_failures": failures})
    return deviations



def _gate_witness_choice(
    gate_witness: str | None, fixture: AttemptFixture | None, gate_entrypoint: str | None,
) -> tuple[Mapping[str, Sequence[str]] | None, Mapping[str, str] | None, Path]:
    """#287 auto6: `(gate_args, stage_plans, shim source)` for an attempt's
    witness. The fixture route (#434) and the default flow-check witness
    (`gate_witness` absent or `flow-check`) are exactly what they were; only
    `flow-finish` - `/flow:auto` Step 6's bare call - selects the flow-auto
    shim, its one gate and the runner's `finish` plan. Refused: an unknown
    kind, a fixture with a non-default witness, `flow-finish` with no
    `gate_entrypoint` to witness."""
    if gate_witness not in (None, "flow-check", "flow-finish"):
        raise HomeFileVerificationRefused(f"unknown gate_witness {gate_witness!r}")
    if gate_witness == "flow-finish":
        if fixture is not None:
            raise HomeFileVerificationRefused("a fixture attempt uses its own gate map; gate_witness cannot also be set")
        if gate_entrypoint is None:
            raise HomeFileVerificationRefused("gate_witness 'flow-finish' needs a declared gate_entrypoint to witness")
        return {_FLOW_FINISH_GATE: ()}, {_FLOW_FINISH_GATE: _FLOW_FINISH_PLAN}, _FLOW_AUTO_GATE_SHIM_SOURCE
    if fixture is not None:
        return fixture.gates, None, fixture.gate_shim_source
    return None, None, _FLOW_CHECK_GATE_SHIM_SOURCE


@dataclass
class _WitnessSession:
    """One controller-owned holder; the subject can never supply its record."""

    attempt_id: str
    limits: Limits
    #: #434: a fixture task's own gate map (name -> argv after the harness
    #: path). `None` keeps the flow-check gates every earlier caller uses.
    gate_args: Mapping[str, Sequence[str]] | None = None
    #: #287 auto6: with `gate_args`, the runner plan whose stages each named
    #: gate's run carries (`stage_capture.capture_stages(plan=...)`). `None`
    #: or absent keeps a `gate_args` map stage-less, as the fixture route is.
    stage_plans: Mapping[str, str] | None = None
    witness: GateWitness | None = field(default=None, repr=False)
    record: GateWitnessRecord | None = field(default=None, repr=False)
    #: #279 PR-2a: the attempt's ordering counter (a multi-turn attempt only);
    #: with it, each run records its order and the gated tree's SOURCE digest.
    order: Order | None = field(default=None, repr=False)
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    #: #508: the declared project gate, witnessed as `project-check` by the
    #: SAME GateWitness as every other gate, so one `_exec_lock` orders them all.
    project_gate: pg.ProjectGate | None = None
    #: #508 ruling 1: `make` invocations the shim passed through to the real
    #: make, as the SHIM reported them. Subject-reported, never evidence: kept
    #: out of the gate-witness record and of everything grading reads.
    passthrough_log: list[dict[str, object]] = field(default_factory=list, repr=False)
    #: #525: gate -> {via: argv} for each witnessed skill-bundled gate copy,
    #: set by the overlay before `bind_and_check`; empty keeps the witness as it was.
    variants: dict[str, dict[str, list[str]]] = field(default_factory=dict, repr=False)
    nonce: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    ready: bool = False
    finalization_started: bool = False
    failure: str | None = None

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        if self.failure is not None or self.finalization_started:
            raise ChannelRefusal("witness session no longer accepts requests")
        if self.witness is None:
            raise ChannelRefusal("witness session has no bound controller")
        if request.get("op") == "witness_ready":
            if self.ready or set(request) != {"op", "nonce"} or request.get("nonce") != self.nonce:
                raise ChannelRefusal("witness readiness request refused")
            return {"nonce": self.nonce}
        if not self.ready:
            raise ChannelRefusal("witness session is not ready for gates")
        if request.get("op") == pg.PASSTHROUGH_OP:
            return self._log_passthrough(request)
        return self.witness.decide(request)

    def _log_passthrough(self, request: Mapping[str, object]) -> Mapping[str, object]:
        """Record one shim pass-through, bounded; never a gate run."""
        if self.project_gate is None:
            raise ChannelRefusal("this attempt witnesses no project gate")
        if len(self.passthrough_log) >= pg.MAX_PASSTHROUGH_LOG:
            return {"logged": False, "reason": "the pass-through log is full"}
        argv, cwd, code, why = (request.get(k) for k in ("argv", "cwd", "exit_code", "why"))
        if (not isinstance(argv, list) or len(argv) > 64 or not all(isinstance(a, str) and len(a) <= 512 for a in argv)
                or not isinstance(cwd, str) or len(cwd) > 4096 or not isinstance(code, int) or isinstance(code, bool)
                or not isinstance(why, str) or len(why) > 128):
            raise ChannelRefusal("make_passthrough fields are malformed or oversized")
        self.passthrough_log.append({"argv": list(argv), "cwd": cwd, "exit_code": code, "why": why,
                                     "at": time.time(), "subject_reported": True})
        return {"logged": True}

    def gate_environment(self) -> Mapping[str, str]:
        """The measured runtime env plus `PYTHONDONTWRITEBYTECODE=1`, as
        grading's own env sets it (`verify._env`). #400: a gate that imports
        Python otherwise writes `__pycache__/*.pyc` into the tree it is judged
        against, and every honest run's `tree_digest_at_start` reads stale.
        The start digest stays strict: any other edit still differs."""
        return MappingProxyType({**self.environment, "PYTHONDONTWRITEBYTECODE": "1"})

    def bind_and_check(self, backend: DockerBackend, handle: object) -> None:
        def snapshot() -> str:
            with tempfile.TemporaryDirectory(prefix="skillc-gate-export-") as directory:
                backend.export(handle, Path(directory))
                return witness_capture.capture_digest(Path(directory))

        def source_snapshot(cwd: str | None) -> str:
            """#279 PR-2a: the SOURCE digest of the checkout containing the
            gate's working directory, from the controller's own export."""
            rel = sd.workspace_relative(cwd, CONTAINER_WORKSPACE)
            if rel is None:
                return "unreadable: the gate's working directory is outside the workspace"
            with tempfile.TemporaryDirectory(prefix="skillc-gate-source-") as directory:
                backend.export(handle, Path(directory))
                root = sd.repository_root(Path(directory), rel)
                if root is None:
                    return "unreadable: no repository contains the gate's working directory"
                return sd.digest_tree(root)

        if self.witness is not None:
            # #508: the cross-gate order is the single `_exec_lock` of ONE
            # witness per attempt; a second one would break it silently.
            raise HomeFileVerificationRefused("an attempt's gate witness is bound once; a second one is refused")
        harness = f"{_FLOW_CHECK_GATE_HARNESS_ROOT}/{_FLOW_CHECK_GATE_HARNESS_PATH}"
        if self.gate_args is None:
            gates = {"flow-check-plan": ["bash", harness, "--plan", "check", "--evidence", "flow-check"],
                     "flow-check-summary": ["bash", harness, "--check-summary"]}
        else:
            gates = {gate: ["bash", harness, *args] for gate, args in self.gate_args.items()}
        staged: dict[str, pg.StagedRunner] = {}
        if self.project_gate is not None:
            # The argv is the record's statement of the entry; the stages run
            # one controller exec each (`project_gate.StagedRunner`).
            gates[pg.GATE] = [pg.REAL_MAKE, self.project_gate.goal]
            staged[pg.GATE] = pg.StagedRunner(self.project_gate)
        self.witness = GateWitness(
            declared_gates=gates, tree_digest_fn=snapshot, backend=backend, handle=handle, limits=self.limits,
            gate_exclusivity=False, exclusivity_basis="The channel observes prescribed shim calls; bypass is not excluded.",
            declared_env={gate: self.gate_environment() for gate in gates}, workspace_root=CONTAINER_WORKSPACE,
            # #376: the plan run's per-stage outcomes, read from its own
            # controller-held stdout when it resolves - never replayed later.
            # A fixture's own gate map (#434) declares no stage-bearing gate.
            stage_capture={"flow-check-plan": stage_capture.capture_stages} if self.gate_args is None else {
                gate: functools.partial(stage_capture.capture_stages, plan=plan)
                for gate, plan in (self.stage_plans or {}).items()},
            order=self.order, source_digest_fn=source_snapshot if self.order is not None else None,
            staged=staged or None, declared_variants=self.variants or None,
        )
        script = (
            "import json,socket,sys; "
            "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(float(sys.argv[3])); "
            "s.connect(sys.argv[1]); "
            "s.sendall((json.dumps(dict(op='witness_ready',nonce=sys.argv[2]))+'\\n').encode()); "
            "s.shutdown(socket.SHUT_WR); f=s.makefile('rb'); raw=f.readline(4097); "
            "assert len(raw)<=4096 and raw.endswith(b'\\n') and not f.read(1); "
            "sys.stdout.buffer.write(raw); s.close()"
        )
        limits = replace(self.limits, timeout=min(self.limits.timeout, 5), max_captured_stdout_bytes=4096)
        try:
            reply = rs.load_json(backend.controller_output(
                handle, ["/usr/bin/python3", "-c", script, TRIGGER_SOCKET_PATH, self.nonce, str(limits.timeout)], limits,
            ))
            if reply != {"ok": True, "result": {"nonce": self.nonce}}:
                raise HomeFileVerificationRefused("witness readiness reply did not match controller nonce")
        except Exception:
            self.failure = "witness readiness failed"
            self.witness.channel_unavailable = True
            raise
        self.ready = True

    def finish(self, backend: DockerBackend, handle: object, experiment: trial.Experiment) -> None:
        if self.finalization_started:
            if self.failure is not None:
                raise HomeFileVerificationRefused(self.failure)
            return
        self.finalization_started = True
        try:
            stops = [e["event"] for e in experiment.events(self.attempt_id)
                     if e.get("event") in ("stop-confirmed", "stop-unconfirmed")]
            if stops[-1:] != ["stop-confirmed"] or not self.ready or self.witness is None:
                raise HomeFileVerificationRefused("witness finalization requires confirmed stop and readiness")
            # #367: first result is authoritative. The channel now enforces
            # it too: after a failed drain, trigger_log() re-raises that
            # failure on every read, caught below as a refusal.
            if backend.trigger_log(handle) is None:
                raise HomeFileVerificationRefused("witness channel was unavailable at finalization")
            record = self.witness.finalize(self.attempt_id)
            if any(g.coverage == "channel-unavailable" for g in record.gates.values()):
                raise HomeFileVerificationRefused("witness output or channel coverage is unavailable")
            self.record = record
        except Exception:
            self.failure = "witness stop, channel drain or output finalization failed"
            if self.witness is not None:
                self.witness.channel_unavailable = True
            raise

def _workspace_snapshot(backend: DockerBackend, handle: object) -> dict[str, str]:
    """A `{relpath: sha256-hex}` content snapshot of every file currently
    under `CONTAINER_WORKSPACE`, via `export()` - never via an exec, since
    `exec_in_attempt()`'s own write-back tail (#76/#186) would plant an
    `observations` file as a SIDE EFFECT of taking the very snapshot meant
    to prove nothing was planted. Used twice by `_preflight_in_container`
    to prove the workspace ends up byte-identical to
    its state before the preflight ran - not only that the observations
    file specifically is gone, but that nothing else (e.g.
    `exec_in_attempt()`'s own per-call `.skillc-exec-pid-<uuid>` marker)
    was left behind either."""
    with tempfile.TemporaryDirectory() as tmp:
        backend.export(handle, Path(tmp))
        return {
            path.relative_to(tmp).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(tmp).rglob("*") if path.is_file()
        }


def _preflight_in_container(
    backend: DockerBackend, handle: object, limits: Limits,
    verify_home_files: Mapping[str, str], tools: Sequence[Mapping[str, Any]],
    verify_home_modes: Mapping[str, str] | None = None,
) -> None:
    """skillc#334 (orchestrator ruling, probe
    design): read back every closure file's digest FROM
    THE LIVE CONTAINER, and evaluate every declared tool dependency's own
    `probes` IN THE CONTAINER - never trust that delivery alone proves
    arrival, and never check a tool on the HOST (`profile._check_tool`
    does that, for the unrelated `skillc profile install` CLI path - it
    has no meaning for a live attempt). The DECISION logic
    (`profile.evaluate_command_probe`/`evaluate_python_import_probe`/
    `aggregate_probe_results`) is shared with `profile._check_tool`,
    never duplicated - only the FACT-GATHERING differs (host subprocess
    there, one combined container exec here).

    A tool dependency with NO probes is refused outright, naming it -
    unlike `_check_tool`'s host-side "unknown, no probes declared" (an
    informational receipt field), this is the gate that decides whether
    the agent starts at all, so reporting unknown-and-continuing would
    pass every attempt by construction - the same blind instrument that
    let exit 127 through in the first place.

    Witnessed attempts consume the controller's retained stdout, never a
    candidate observations artifact. Ordinary callers retain the existing
    workspace write-back convention. Every check - digests and every probe - shares ONE
    combined exec, regardless of how many files, tools or probes are
    declared. TWO exports are needed, not one: a
    BASELINE snapshot taken before the exec even runs, and one taken
    after it, so the function can prove the workspace it leaves behind is
    byte-identical to the workspace it found - never only that the one
    file this module happens to know about (`observations`) is gone."""
    if not verify_home_files and not tools:
        return
    for dep in tools:
        if not dep.get("probes"):
            raise HomeFileVerificationRefused(
                f"tool dependency {dep.get('id')!r} declares no probes; a profile-opted live attempt "
                f"cannot verify an unchecked tool claim, so it refuses rather than silently passing"
            )

    try:
        baseline = _workspace_snapshot(backend, handle)
    except OSError as exc:
        raise HomeFileVerificationRefused(
            f"could not export the container to take a pre-preflight workspace baseline: {exc}"
        ) from exc

    container_paths = {relpath: f"{CONTAINER_HOME}/{relpath}" for relpath in verify_home_files}
    script_lines = [f"sha256sum {shlex.quote(path)}" for path in container_paths.values()]
    # #505: each verified file's executable bit, read back from the container
    # in the same exec; only when modes are given, so the script is otherwise
    # byte-identical to before.
    mode_checked = {relpath: mode for relpath, mode in (verify_home_modes or {}).items()
                    if relpath in container_paths}
    for relpath in mode_checked:
        path = shlex.quote(container_paths[relpath])
        script_lines.append(f'if test -x {path}; then echo "{_XMODE_PREFIX}1 "{path}; '
                            f'else echo "{_XMODE_PREFIX}0 "{path}; fi')
    script_lines.append(f"echo {shlex.quote(_TOOLS_MARKER)}")

    probe_entries: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = [
        (dep, probe) for dep in tools for probe in dep["probes"]
    ]
    for idx, (_dep, probe) in enumerate(probe_entries):
        kind = probe.get("kind")
        if kind == "command":
            name = str(probe["name"])
            version_args = probe.get("version_args") or ["--version"]
            quoted_args = " ".join(shlex.quote(a) for a in version_args)
            # Counter-model review (codex gpt-6.1-sol, #334): `$?` is
            # captured IMMEDIATELY after the version command itself, in a
            # separate statement - never after piping its output through
            # `head`, which would report `head`'s own exit status instead
            # (always 0) and silently let a nonzero-exiting command that
            # happens to print a matching version string pass as
            # "satisfied". The exit code rides in the wire format
            # (`PRESENT:<rc>:<version text>`) so `evaluate_command_probe`
            # can refuse to certify a version it never confirmed.
            script_lines.append(
                f'if command -v {shlex.quote(name)} >/dev/null 2>&1; then '
                f'out=$({shlex.quote(name)} {quoted_args} 2>&1); rc=$?; '
                f'v=$(printf "%s" "$out" | head -1); '
                f'printf "PROBE:{idx}:PRESENT:%s:%s\\n" "$rc" "$v"; '
                f'else printf "PROBE:{idx}:ABSENT\\n"; fi'
            )
        elif kind == "python-import":
            modules = probe.get("modules") or []
            script_body = "; ".join(f"import {mod}" for mod in modules)
            uv_project = probe.get("uv_project")
            if uv_project is None:
                check_cmd = f'python3 -c {shlex.quote(script_body)}'
            else:
                # Mailbox 5944 fix 1: mirror the real runner's own
                # invocation (flow-finish-gate.sh: `PYTHONPATH="$CPP_DIR:
                # ${PYTHONPATH:-}" uv run --project "$CPP_DIR" python -m
                # lib.cicd ...`) - never a bare `python3`, which checks the
                # trial image's system interpreter rather than the
                # checkout's own isolated venv.
                project_dir = f"{CONTAINER_HOME}/{uv_project}"
                policy = "--offline --locked " if getattr(backend, "runtime_supply", None) is not None else ""
                check_cmd = (
                    f'PYTHONPATH={shlex.quote(project_dir)}:${{PYTHONPATH:-}} '
                    f'uv run {policy}--project {shlex.quote(project_dir)} python -c {shlex.quote(script_body)}'
                )
            script_lines.append(
                f'if {check_cmd} >/dev/null 2>&1; then '
                f'printf "PROBE:{idx}:IMPORT_OK\\n"; '
                f'else printf "PROBE:{idx}:IMPORT_FAIL\\n"; fi'
            )
        else:
            raise HomeFileVerificationRefused(f"unknown probe kind: {kind!r}")

    result = backend.exec_in_attempt(handle, ["sh", "-c", "\n".join(script_lines)], limits)
    if result.exit_code != 0:
        raise HomeFileVerificationRefused(
            f"the in-container preflight script itself failed (exec exit {result.exit_code!r}, "
            f"reason {result.reason!r}) - could not verify closure files or preflight tools"
        )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend.export(handle, Path(tmp))
        except OSError as exc:
            raise HomeFileVerificationRefused(
                f"could not export the container to read back the preflight output: {exc}"
            ) from exc
        tmp_root = Path(tmp)
        observations = tmp_root / "observations"
        if getattr(backend, "witness_io", False):
            if (result.reason != "exited" or result.stdout is None or result.stdout_truncated
                    or result.stdout_incomplete or result.stderr_incomplete):
                raise HomeFileVerificationRefused("preflight retained output is missing or incomplete")
            output = result.stdout.decode("utf-8", errors="strict")
        else:
            output = observations.read_text(encoding="utf-8", errors="replace") if observations.is_file() else ""
        after_exec = {
            path.relative_to(tmp_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in tmp_root.rglob("*") if path.is_file()
        }

    # Mailbox 5944 fixes 2+3: the preflight exec left its digest/probe
    # report sitting in the AGENT's own workspace, at the same
    # `CONTAINER_WORKSPACE/observations` path the agent's own run (and the
    # grader, after it) will see - the preflight's internal verification
    # detail would otherwise show up in the graded tree or diff. Every
    # NEW file the exec left behind (never only the one this module
    # happens to know the name of - e.g. `exec_in_attempt()`'s own
    # per-call `.skillc-exec-pid-<uuid>` marker) is removed via
    # `remove_file_in_attempt`, never a second `exec_in_attempt()` call
    # (that method's own write-back would just recreate an empty file in
    # its place - see that method's docstring). A pre-existing file the
    # script has no business touching must not have changed either -
    # the whole point is a workspace byte-identical to what it was
    # before the preflight ran, not merely "the known file is gone".
    for relpath in sorted(set(after_exec) - set(baseline)):
        if not backend.remove_file_in_attempt(handle, f"{CONTAINER_WORKSPACE}/{relpath}"):
            raise HomeFileVerificationRefused(
                f"could not remove a preflight residue file from the workspace: {relpath}"
            )
    vanished = sorted(set(baseline) - set(after_exec))
    if vanished:
        raise HomeFileVerificationRefused(
            f"the preflight script unexpectedly removed pre-existing workspace file(s): {vanished}"
        )
    changed = sorted(p for p in set(baseline) & set(after_exec) if baseline[p] != after_exec[p])
    if changed:
        raise HomeFileVerificationRefused(
            f"the preflight script unexpectedly modified pre-existing workspace file(s): {changed}"
        )

    digest_section, _, tools_section = output.partition(_TOOLS_MARKER)

    actual_by_path = {}
    executable_by_path: dict[str, bool] = {}
    for line in digest_section.splitlines():
        if line.startswith(_XMODE_PREFIX):
            flag, _, path = line[len(_XMODE_PREFIX):].partition(" ")
            executable_by_path[path] = flag == "1"
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            actual_by_path[parts[1]] = parts[0]
    for relpath, expected_digest in verify_home_files.items():
        container_path = container_paths[relpath]
        actual_hex = actual_by_path.get(container_path)
        if actual_hex is None:
            raise HomeFileVerificationRefused(f"{relpath} was not read back from the container at all")
        if f"sha256:{actual_hex}" != expected_digest:
            raise HomeFileVerificationRefused(
                f"{relpath} verified in-container digest sha256:{actual_hex} disagrees with the "
                f"expected {expected_digest!r} - what was delivered does not match what arrived"
            )
    for relpath, mode in mode_checked.items():
        executable = executable_by_path.get(container_paths[relpath])
        if executable is None:
            raise HomeFileVerificationRefused(f"{relpath}: its executable bit was not read back from the container")
        if executable != (mode == "100755"):
            raise HomeFileVerificationRefused(
                f"{relpath} is {'' if executable else 'not '}executable in the container, but its source mode is "
                f"{mode} - the subject would run a different install than its source (#505)"
            )

    probe_output: dict[int, str] = {}
    for line in tools_section.splitlines():
        if not line.startswith("PROBE:"):
            continue
        rest = line[len("PROBE:"):]
        idx_str, _, detail = rest.partition(":")
        if idx_str.isdigit():
            probe_output[int(idx_str)] = detail

    results_by_dep: dict[int, list[dict[str, Any]]] = {}
    for idx, (dep, probe) in enumerate(probe_entries):
        dep_key = id(dep)
        results_by_dep.setdefault(dep_key, [])
        probe_detail = probe_output.get(idx)
        if probe.get("kind") == "command":
            if probe_detail is None or probe_detail == "ABSENT":
                command_outcome = profile.CommandProbeOutcome(present=False)
            elif probe_detail.startswith("PRESENT:"):
                rc_str, _, version_output = probe_detail[len("PRESENT:"):].partition(":")
                command_outcome = profile.CommandProbeOutcome(
                    present=True, version_output=version_output,
                    version_exit_code=int(rc_str) if rc_str.isdigit() else None,
                )
            else:
                command_outcome = profile.CommandProbeOutcome(present=True, version_output=None)
            results_by_dep[dep_key].append(profile.evaluate_command_probe(probe, command_outcome))
        else:
            succeeded = probe_detail == "IMPORT_OK"
            import_outcome = profile.PythonImportProbeOutcome(
                succeeded=succeeded, error="" if succeeded else "import failed",
            )
            results_by_dep[dep_key].append(profile.evaluate_python_import_probe(probe, import_outcome))

    for dep in tools:
        aggregate = profile.aggregate_probe_results(results_by_dep.get(id(dep), []))
        if aggregate["status"] != "satisfied":
            raise HomeFileVerificationRefused(
                f"tool dependency {dep.get('id')!r} is not satisfied in the container: "
                f"{aggregate['status']} - {aggregate.get('reason', '')}"
            )


def _make_before_execute(
    *, spec: ClientSpec, ctx: _AttemptContext, credential_explicit_path: str | Path | None,
    minimum_credential_seconds: float, delivered_credential_bytes: dict[str, bytes],
    extra_home_files: Mapping[str, bytes], verify_home_files: Mapping[str, str] | None = None,
    preflight_tools: Sequence[Mapping[str, object]] | None = None, limits: Limits | None = None,
    gate_entrypoint: str | None = None,
    runtime_ready: Callable[[DockerBackend, object], None] | None = None,
    gate_shim_source: Path = _FLOW_CHECK_GATE_SHIM_SOURCE,
    extra_home_modes: Mapping[str, str] | None = None,
    bundled_gate_entrypoints: Sequence[str] = (),
    treatment_deviation: list[dict[str, object]] | None = None,
) -> Callable[[ExecutionBackend, object], None]:
    """`delivered_credential_bytes` is an OUT-parameter (a single-entry dict
    the caller reads afterward) - `observe_before_teardown` needs these
    exact bytes later to compute `refresh_observed`, and a hook's own return
    value has nowhere else to go (`before_execute`'s contract returns
    nothing - see `lifecycle.py`'s own docstring).

    `verify_home_files` (#334) names which of `extra_home_files`' own
    destinations get read back from the live container and digest-checked
    after delivery - never every file, only the ones a caller declares
    (today: a profile's installed closure). `preflight_tools` (#334) names
    the profile's own `tool`-kind dependencies (each a dict with at least
    `id` and `version`), checked present in the SAME container at their
    declared constraint - never on the host, which has no bearing on what
    the agent's own container can actually run. `limits` is required
    together with a non-empty `verify_home_files` or `preflight_tools`;
    meaningless (and unused) without either - mirrors `calibration_run.
    build_treatment`'s own subject_profile/root pairing.

    `gate_entrypoint` is the subject's OWN declared fact -
    ultimately `profile.Profile.gate_entrypoint`, threaded through
    `calibration_run.Treatment` - naming which installed path is this
    skill's gate command. `None` means the subject declares none, so the
    overlay never runs, whatever `verify_home_files` happens to contain.
    A real path means witnessing is UNCONDITIONALLY required: it must be
    present in the verified closure or the attempt is refused before any
    spend - never silently un-witnessed because the file happened to be
    missing (the orchestrator's own correction: inferring the need to
    witness from a file's presence has the same silent-skip shape as the
    `.git` revision check's own blind-instrument defect)."""
    resolved_verify_home_files = verify_home_files or {}
    resolved_preflight_tools = preflight_tools or ()
    if (resolved_verify_home_files or resolved_preflight_tools) and limits is None:
        raise HomeFileVerificationRefused(
            "verify_home_files or preflight_tools is given but limits is None; cannot exec to verify"
        )
    if gate_entrypoint is not None and limits is None:
        raise HomeFileVerificationRefused("gate_entrypoint is given but limits is None; cannot exec to witness")

    def hook(backend: ExecutionBackend, handle: object) -> None:
        assert isinstance(backend, DockerBackend)
        cred_path = credential.resolve_path(spec.name, credential_explicit_path)
        cred_bytes = credential.read_fresh(cred_path)
        remaining = credential.check_remaining_life_or_refuse(
            spec.name, cred_bytes, minimum_seconds=minimum_credential_seconds,
        )
        # Recorded, never discarded (issue #106): the remaining life the
        # freshness check actually saw, rounded to the minute - a duration,
        # not a token, and the only evidence a record can carry that the
        # launch cleared the threshold rather than merely not failing.
        delivered_credential_bytes["remaining_seconds"] = str(int(remaining // 60 * 60)).encode("ascii")
        credential_relpath = credential.CLIENT_SPECS[spec.name].container_relpath
        backend.deliver_home_file(handle, credential_relpath, cred_bytes)
        delivered_credential_bytes["bytes"] = cred_bytes
        delivered_credential_bytes["relpath"] = credential_relpath.encode("utf-8")  # type: ignore[assignment]

        for relpath, data in spec.compose_home_files(ctx).items():
            backend.deliver_home_file(handle, relpath, data)
        # Caller-supplied, never spec-derived (issue #11): a declared skill
        # collection to install alongside the credential and seed, into the
        # SAME container the agent runs in - so a skill-free canary run can
        # genuinely observe whether the agent selects one of these on its
        # own, not merely that the harness plumbing works. Delivered last,
        # after the client's own home files, so a colliding path (unlikely -
        # `compose_home_files` never writes under `.codex/skills/`) is
        # decided by the caller's own intent, not by dict ordering luck.
        for relpath, data in extra_home_files.items():
            backend.deliver_home_file(handle, relpath, data, mode=delivery_mode(relpath, extra_home_modes))

        if runtime_ready is not None:
            runtime_ready(backend, handle)

        if resolved_verify_home_files or resolved_preflight_tools:
            assert limits is not None  # checked above, before any delivery happened
            _preflight_in_container(backend, handle, limits, resolved_verify_home_files, resolved_preflight_tools,
                                    verify_home_modes=extra_home_modes)

        # skillc#334 step 4 (#332's own
        # follow-up #342 landed the two-root `install()`/`export()`/
        # `apply_flow_check_gate_overlay()` this needed): the LAST setup
        # step before the agent starts (gate_overlay.py's own ordering
        # requirement - anything that re-reads an installed-file digest
        # after this runs would see the shim's digest where it expects
        # the real script's). Fires whenever `gate_entrypoint` is given -
        # an explicit fact, never inferred from `resolved_verify_home_
        # files`' own membership - and REFUSES if that declared path is
        # not actually in the verified closure, rather than silently
        # skipping witnessing for a reason nothing would ever surface.
        if gate_entrypoint is not None:
            real_digest = resolved_verify_home_files.get(gate_entrypoint)
            if real_digest is None:
                raise HomeFileVerificationRefused(
                    f"gate_entrypoint {gate_entrypoint!r} is declared but not present in the "
                    f"verified closure - witnessing is required whenever a gate_entrypoint is "
                    f"declared, and this attempt cannot honour it"
                )
            assert real_digest.startswith("sha256:")
            shim_content = gate_shim_source.read_bytes()
            gate_overlay.apply_flow_check_gate_overlay(
                backend, handle,
                subject_root=CONTAINER_HOME,
                harness_root=_FLOW_CHECK_GATE_HARNESS_ROOT,
                subject_path=gate_entrypoint,
                harness_path=_FLOW_CHECK_GATE_HARNESS_PATH,
                expected_real_digest=real_digest[len("sha256:"):],
                expected_shim_digest=hashlib.sha256(shim_content).hexdigest(),
                shim_content=shim_content,
            )
            # #525: then each declared skill-bundled copy - the last setup step,
            # after the installed gate, for the same re-read reason. Its
            # deviations are an OUT-parameter, like `delivered_credential_bytes`.
            if bundled_gate_entrypoints:
                deviations = _overlay_bundled_gates(
                    backend, handle, bundled_gate_entrypoints, resolved_verify_home_files, extra_home_files,
                    extra_home_modes, shim_content)
                if treatment_deviation is not None:
                    treatment_deviation.extend(deviations)

    return hook


@dataclass(frozen=True)
class TranscriptObservation:
    """What `observe_before_teardown` concluded about the real transcript -
    recorded verbatim, never a token value anywhere in it (mirrors
    `credential.CredentialUsage`'s own "no field a secret could occupy"
    guarantee)."""

    files_found: int
    prompt_delivered: bool
    prompt_delivery_reason: str | None
    canary_satisfied: bool
    canary_reason: str | None
    #: The names of every `skill_invocation` event in the transcript, in the
    #: order they appear - never only the one `skill_name` a canary was
    #: checked against, and never dropped once parsed (issue #26 review:
    #: `_make_observe_before_teardown` already parses these events to check
    #: the canary, then discarded them - a selection probe needs to know
    #: which skill(s), if any, were invoked, not merely whether one
    #: pre-named skill's own canary fired). Empty when no single transcript
    #: file was found (the same condition that leaves every other field
    #: above at its "could not observe" default).
    skill_invocations: tuple[str, ...] = ()
    #: Whether `skill_invocations` is a STRUCTURAL guarantee for this client
    #: (Claude Code has a dedicated `Skill` tool call) or a best-effort
    #: HEURISTIC (Codex has no `skill_invocation` transcript marker of its
    #: own - `transcript_adapter.py`'s own module docstring - and infers one
    #: from an `exec` call reading a `SKILL.md`). A selection probe's report
    #: must be able to say which, never present a heuristic as structural.
    skill_invocation_detection: str = "structural"
    #: Every skill name the client's own `skill_listing` told the model about,
    #: read from the real transcript (issue #124) - `None` when not observable
    #: (no single transcript file, a client whose transcript carries no
    #: listing, or a transcript with no listing attachment), never `()`
    #: standing in for "could not see". `skills_listed_source` says which.
    skills_listed: tuple[str, ...] | None = None
    skills_listed_source: str = "not observed"

    def to_fields(self) -> dict[str, object]:
        return {
            "transcript_files_found": self.files_found,
            "prompt_delivered": self.prompt_delivered,
            "prompt_delivery_reason": self.prompt_delivery_reason,
            "canary_satisfied": self.canary_satisfied,
            "canary_reason": self.canary_reason,
            "skill_invocations": list(self.skill_invocations),
            "skill_invocation_detection": self.skill_invocation_detection,
            "skills_listed": list(self.skills_listed) if self.skills_listed is not None else None,
            "skills_listed_source": self.skills_listed_source,
            # Computed HERE, once, from the real dataclass fields - never
            # re-derived from the flattened dict `run_one_attempt`'s own
            # grading gate reads (PR #113 review: two separate
            # definitions of "eligible for grading" would drift silently).
            "grading_eligible": self.grading_eligible,
        }

    @property
    def grading_eligible(self) -> bool:
        """Both must hold - #106's own acceptance: "prompt-delivery
        mismatch: the attempt is BLOCKED, not graded." A canary failure is
        the same class of fact: neither is proof the attempt did the real
        work, so neither earns a grade."""
        return self.prompt_delivered and self.canary_satisfied


def skill_invocations_from_events(events: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """Every `skill_invocation` event's skill, in transcript order - the ONE
    definition both the live observation and `recompute_skill_invocations`
    use, so a recomputation checks the heuristic rather than a second copy
    of it."""
    return tuple(
        str(event["skill"]) for event in events
        if event.get("type") == "skill_invocation" and "skill" in event
    )


def _jsonl_string_leaves(text: str) -> Iterator[tuple[int, str]]:
    """`(1-indexed line, decoded string)` for every string key and value of
    every JSONL line that parses. The serialized line escapes the quotes a
    detector such as the OAuth pattern keys on, so a credential the agent
    printed inside a tool result is only visible once decoded (counter-model
    review, #202)."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        stack: list[object] = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                yield lineno, item
            elif isinstance(item, dict):
                stack.extend(item.keys())
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)


#: A field whose JSON string value retention replaces with
#: `leak.REDACTED_VALUE` before a transcript is kept (#225):
#:   - the account identifiers `leak.ACCOUNT_ID_RE` detects, which a Codex
#:     rollout's `session_meta` records for the operator on every attempt -
#:     refusing them instead would refuse every Codex transcript;
#:   - `encrypted_content`, the provider-encrypted reasoning blob on Codex
#:     `reasoning` items. No reader of the evidence can decrypt it, so it is
#:     not evidence; it is session content held by the provider's key, and
#:     publishing it gains nothing;
#:   - `response_id` (#227), the provider-side id of each model response on
#:     a Codex `token_usage_record`, an account-scoped handle.
_REDACTED_FIELD = r"(?:" + leak.ACCOUNT_ID_FIELD + r"|encrypted_content|response_id)"
_REDACTED_FIELD_RE = re.compile(
    (r'("' + _REDACTED_FIELD + r'"\s*:\s*")((?:[^"\\]|\\.)*)(")').encode("ascii")
)
_REDACTED_KEY_RE = re.compile(_REDACTED_FIELD)
_ENCRYPTED_CONTENT_RE = re.compile(r'"encrypted_content"\s*:\s*"((?:[^"\\]|\\.)+)"')


#: A field whose whole value, an object, retention replaces with
#: `leak.REDACTED_VALUE` (#227): `rate_limits` on every Codex `token_count`
#: event holds the operator's plan, credit balance and usage windows.
#:
#: A deny-list, not an allow-list of the fields evidence uses: an allow-list
#: would have to know every payload a client version writes, and would drop
#: evidence-bearing fields silently on a client upgrade. The cost is that a
#: NEW account-scoped field passes until someone names it here, which is why
#: a transcript is still read by hand before it is published.
_REDACTED_OBJECT_KEYS = frozenset({"rate_limits"})


def _finding_class(key: str) -> str:
    if key == "encrypted_content":
        return "encrypted-content"
    if key in _REDACTED_OBJECT_KEYS:
        return "account-usage"
    if key == "response_id":
        return "response-id"
    return "account-id"


def _unredacted_protected_fields(value: object) -> Iterator[str]:
    """The finding class of every `_REDACTED_FIELD` key under `value` whose
    value is populated and not `leak.REDACTED_VALUE` (#225, counter-model
    review). Walks DECODED JSON, so it sees what the serialized-text
    redaction cannot: a key spelled with escapes (`"creator_\\u0075ser_id"`),
    a non-string value (a number, a list), and JSON an agent printed inside
    a string, which is parsed and walked in turn."""
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, inner in item.items():
                if (
                    isinstance(key, str)
                    and (_REDACTED_KEY_RE.fullmatch(key) or key in _REDACTED_OBJECT_KEYS)
                    and inner not in (None, "", leak.REDACTED_VALUE)
                ):
                    yield _finding_class(key)
                stack.append(inner)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and item.lstrip()[:1] in ("{", "["):
            try:
                stack.append(json.loads(item))
            except ValueError:
                pass


def redact_transcript_identities(raw: bytes) -> bytes:
    """`raw` with each `_REDACTED_FIELD_RE` field's value replaced by
    `leak.REDACTED_VALUE` (#225). A substitution on the serialized text, not a
    parse and re-serialize, so every byte outside a redacted value - every
    other line in particular - is exactly what the client wrote.

    `_REDACTED_OBJECT_KEYS` values are objects, so a line carrying one is
    parsed and re-serialized instead (#227, `_redact_object_fields`); every
    other line is still byte-identical.

    Only structural fields are redacted. The same identifier inside an
    escaped string (an agent printing a rollout, say) is left alone, and
    `transcript_leak_findings`' decoded pass refuses the transcript on it."""
    marker = leak.REDACTED_VALUE.encode("utf-8")
    raw = _REDACTED_FIELD_RE.sub(lambda m: m.group(1) + marker + m.group(3), raw)
    return b"".join(_redact_object_fields(line) for line in raw.splitlines(keepends=True))


def _redact_object_fields(line: bytes) -> bytes:
    """`line` with every `_REDACTED_OBJECT_KEYS` value replaced (#227). An
    object value cannot be swapped by a text substitution, so a line naming
    one is parsed and re-serialized, compactly and as ASCII; a line
    that names none is returned as is. A line that does not parse is left
    alone, and the decoded check refuses it if a value is still there."""
    if not any(b'"' + key.encode("ascii") + b'"' in line for key in _REDACTED_OBJECT_KEYS):
        return line
    body = line.rstrip(b"\r\n")
    try:
        value = json.loads(body)
    except ValueError:
        return line
    changed = False
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in item:
                if key in _REDACTED_OBJECT_KEYS and item[key] not in (None, "", leak.REDACTED_VALUE):
                    item[key] = leak.REDACTED_VALUE
                    changed = True
                else:
                    stack.append(item[key])
        elif isinstance(item, list):
            stack.extend(item)
    if not changed:
        return line
    # ASCII, so every escape stays an escape (counter-model review): a decoded
    # U+2028 written back raw would split this record under `splitlines()`
    # and hide the rest of it from the decoded checks, and a lone surrogate
    # cannot be encoded as UTF-8 at all.
    rewritten = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return rewritten + line[len(body):]


def transcript_leak_findings(raw: bytes) -> list[str]:
    """Every reason `raw` may not be retained or published, by CLASS and LINE
    only - never the matched value. Three passes, because each alone is
    blind to something (#202, counter-model review):

      - `leak.scan_text` over the raw text (machine identities, credentials);
      - the same over each JSONL line's DECODED strings, where an escaped
        `{\"access_token\": ...}` becomes matchable again;
      - `trial._secret_content`, the filter artifact capture already applies
        (GitHub/AWS/Slack tokens, private keys), over the raw bytes and each
        decoded string;
      - `_unredacted_protected_fields` over each parsed line, and an
        `encrypted_content` pattern over each decoded string: what
        `redact_transcript_identities` left in place (#225, #227). A
        `rate_limits` or `response_id` in an unparseable line or inside a
        string is caught by `leak.scan_text`'s own classes in the first two
        passes."""
    text = raw.decode("utf-8", errors="replace")
    denylist, host_paths = leak.load_denylist(None), leak.default_host_paths()
    located = {f"{kind} at line {lineno}" for lineno, kind, _detail in leak.scan_text(text, denylist, host_paths)}
    secret = trial._secret_content(raw)
    if secret is not None:
        located.add(secret.removesuffix("; never exported"))
    for lineno, leaf in _jsonl_string_leaves(text):
        located.update(
            f"{kind} at line {lineno}" for _l, kind, _detail in leak.scan_text(leaf, denylist, host_paths)
        )
        # `surrogatepass`: a decoded JSON string may hold an unpaired
        # surrogate (a tool's surrogate-escaped filename), which plain utf-8
        # refuses to encode (counter-model review, #202).
        leaf_secret = trial._secret_content(leaf.encode("utf-8", errors="surrogatepass"))
        if leaf_secret is not None:
            located.add(f"{leaf_secret.removesuffix('; never exported')} at line {lineno}")
        if any(m.group(1) != leak.REDACTED_VALUE for m in _ENCRYPTED_CONTENT_RE.finditer(leaf)):
            located.add(f"encrypted-content at line {lineno}")
    for lineno, line in enumerate(text.splitlines(), start=1):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        located.update(f"{kind} at line {lineno}" for kind in _unredacted_protected_fields(parsed))
    return sorted(located)


def retainable_transcript(raw: bytes) -> trial.TranscriptEvidence:
    """Leak-check a transcript before it may be retained (#202, ADR 0005 rule
    3). A finding refuses retention entirely - never a redacted copy - and the
    reason names each finding's class and line only
    (`transcript_leak_findings`)."""
    try:
        findings = transcript_leak_findings(raw)
    except Exception as exc:  # noqa: BLE001 - retention must never take the transcript observation with it
        return trial.TranscriptEvidence(None, f"transcript leak-check could not run ({type(exc).__name__}); retention refused")
    if findings:
        return trial.TranscriptEvidence(None, f"transcript leak-check found {', '.join(findings)}; retention refused")
    if not raw:
        return trial.TranscriptEvidence(None, "the transcript file was empty")
    return trial.TranscriptEvidence(raw)


def _stored_transcript_entry(experiment: trial.Experiment, attempt_id: str) -> dict[str, object] | None:
    path = experiment.root / f"manifest-{attempt_id}.json"
    if path.is_symlink() or not path.is_file():
        return None
    manifest = json.loads(path.read_bytes())
    for entry in manifest.get("observations") or ():
        if isinstance(entry, dict) and entry.get("stream") == records.CLIENT_TRANSCRIPT:
            return entry
    return None


def transcript_retention(experiment: trial.Experiment, attempt_id: str, disposition: object) -> dict[str, object]:
    """What the store holds of this attempt's transcript, read back from its
    manifest - never from what the hook intended to store. No manifest (the
    attempt was not captured) and no entry are both `missing`, each with its
    own reason, never an absent key."""
    entry = _stored_transcript_entry(experiment, attempt_id)
    if entry is None:
        reason = (
            f"no manifest: the attempt was not captured (disposition {disposition!r})"
            if not (experiment.root / f"manifest-{attempt_id}.json").is_file()
            else "the manifest declares no client-transcript stream"
        )
        return {"coverage": "missing", "digest": None, "size": None, "reason": reason}
    return {
        "coverage": entry.get("coverage"), "digest": entry.get("digest"), "size": entry.get("size"),
        "reason": entry.get("reason"),
    }


def recompute_skill_invocations(experiment: trial.Experiment, attempt_id: str, client: str) -> tuple[str, ...]:
    """`skill_invocations` re-derived from the RETAINED transcript (#202), so
    the heuristic is checkable after the run. The object is re-hashed before
    it is parsed (`trial._read_object`); refused when no transcript was
    retained - there is nothing to recompute from, and an empty tuple would
    read as "nothing was invoked"."""
    if client not in CLIENT_SPECS:
        raise credential.CredentialRefused(f"unknown client {client!r}: expected one of {sorted(CLIENT_SPECS)}")
    entry = _stored_transcript_entry(experiment, attempt_id)
    if entry is None or entry.get("coverage") not in ("complete", "partial") or not entry.get("digest"):
        reason = entry.get("reason") if entry else "no client-transcript observation"
        raise trial.Refused(f"attempt {attempt_id!r} has no retained transcript ({reason})")
    if entry.get("coverage") != "complete":
        # A truncated transcript can drop the output that pairs with a skill
        # read, so a short answer here would read as "not invoked" (#202,
        # counter-model review).
        raise trial.Refused(
            f"attempt {attempt_id!r} retained only a {entry.get('coverage')} transcript; "
            f"a recomputation from it cannot say what was not invoked"
        )
    data = trial._read_object(experiment.root, str(entry["digest"]))
    events = CLIENT_SPECS[client].parse_transcript(data.decode("utf-8", errors="replace"))
    if not events:
        # Nothing the adapter recognizes - an empty answer would read as
        # "inspected, nothing invoked" (counter-model review, #202).
        raise trial.Refused(
            f"attempt {attempt_id!r}'s transcript holds no event the {client} adapter recognizes; "
            f"a recomputation from it cannot say what was not invoked"
        )
    return skill_invocations_from_events(events)


def observe_transcript_bytes(
    spec: ClientSpec, raw: bytes, *, expected_prompt: str, skill_name: str | None,
    local_mcp_servers: frozenset[str] = frozenset(),
) -> tuple[TranscriptObservation, dict[str, object], dict[str, object] | None]:
    """What one transcript's BYTES show: the observation (prompt delivery,
    canary, skill invocations), the census and the run metadata - the exact
    derivation the live teardown hook runs on the one transcript it found.

    Pure, so a retained run can be re-derived with the CURRENT adapter without
    a container (#486's re-grade), by the same code a live attempt runs."""
    run_metadata: dict[str, object] | None = None
    census: dict[str, object] = {
        "transcript_client_version": None, "transcript_model": None,
        "transcript_response_items_inspected": None,
        "transcript_line_types": None, "transcript_unrecognized_types": None,
        "server_side_tool_uses": None,
    }
    text = raw.decode("utf-8", errors="replace")
    try:
        census = transcript_census(spec.name, text)
    except Exception as exc:  # noqa: BLE001 - the census is context; it must never erase the observation
        census = {**census, "transcript_census_error": f"{type(exc).__name__}: {exc}"}
    # #442: from the RAW bytes, before any retention decision - a
    # transcript the leak check refuses to store is still inspected.
    census["server_side_tool_uses"] = server_side_tool_uses(
        raw, census.get("transcript_line_types"), local_mcp_servers)  # type: ignore[arg-type]
    events = spec.parse_transcript(text)
    if spec.run_metadata is not None:
        run_metadata = spec.run_metadata(text)
    prompt_delivered = True
    prompt_reason = None
    try:
        trial_bootstrap.verify_first_user_message(events, expected_prompt)
    except PromptDeliveryError as exc:
        prompt_delivered = False
        prompt_reason = str(exc)
    canary_satisfied = True
    canary_reason = None
    try:
        trial_bootstrap.check_agent_canary(events, skill_name)
    except CanaryNotSatisfied as exc:
        canary_satisfied = False
        canary_reason = str(exc)
    # Every skill_invocation the transcript shows, in order - never
    # only `skill_name`'s own (issue #26 review): `check_agent_canary`
    # above answers "was THIS skill invoked", a different, narrower
    # question than "which skill(s), if any, were invoked at all".
    invocations = skill_invocations_from_events(events)
    if spec.read_skill_listing is None:
        listed, listed_source = None, f"not available: the {spec.name} transcript carries no skill listing"
    else:
        listed = spec.read_skill_listing(raw.decode("utf-8", errors="replace"))
        listed_source = (
            "transcript skill_listing attachment" if listed is not None
            else "not observed: the transcript has no skill_listing attachment"
        )
    observation = TranscriptObservation(
        files_found=1, prompt_delivered=prompt_delivered, prompt_delivery_reason=prompt_reason,
        canary_satisfied=canary_satisfied, canary_reason=canary_reason,
        skill_invocations=invocations, skill_invocation_detection=spec.skill_invocation_detection,
        skills_listed=listed, skills_listed_source=listed_source,
    )
    return observation, census, run_metadata


def _make_observe_before_teardown(
    *, spec: ClientSpec, expected_prompt: str, skill_name: str | None,
    delivered_credential_bytes: dict[str, bytes],
    retained_transcript: dict[str, object] | None = None,
    stored_transcript: dict[str, trial.TranscriptEvidence] | None = None,
    local_mcp_servers: frozenset[str] = frozenset(),
    sessions: list[dict[str, object]] | None = None,
    scan_codex: bool = False,
    credential_reader: Callable[[ExecutionBackend, object], bytes | None] | None = None,
) -> Callable[[ExecutionBackend, object], Mapping[str, object]]:
    """`sessions` (#500), when given, receives EVERY transcript file of an
    attempt that left more than one, redacted and leak-checked, with each
    session's own model and token usage, so the caller can retain them all
    rather than none. `scan_codex` (#500, an attempt under `AttemptGuard`)
    adds `transcript_codex_invocations`: every codex launch the transcript's
    tool-call commands show (`attempt_guard.scan_codex_invocations`). Both
    default off, and then the observation is byte-identical to before."""
    def hook(backend: ExecutionBackend, handle: object) -> dict[str, object]:
        assert isinstance(backend, DockerBackend)
        extra: dict[str, object] = {}

        refresh_observed: bool | None = None
        cred_relpath_bytes = delivered_credential_bytes.get("relpath")
        cred_bytes = delivered_credential_bytes.get("bytes")
        if isinstance(cred_relpath_bytes, bytes) and isinstance(cred_bytes, bytes):
            if credential_reader is not None:
                # #518: the steward withdrew the credential into its vault; the
                # home no longer holds it. An unreadable vault is unknown.
                vaulted = credential_reader(backend, handle)
                refresh_observed = credential.refresh_observed(cred_bytes, vaulted) if vaulted is not None else None
            else:
                current = backend.read_home_file(handle, cred_relpath_bytes.decode("utf-8"))
                refresh_observed = credential.refresh_observed(cred_bytes, current)

        tree = backend.read_home_tree(handle, spec.transcript_container_reldir)
        matches = {path: data for path, data in tree.items() if path.endswith(spec.transcript_suffix)}

        run_metadata: dict[str, object] | None = None
        census: dict[str, object] = {
            "transcript_client_version": None, "transcript_model": None,
            "transcript_response_items_inspected": None,
            "transcript_line_types": None, "transcript_unrecognized_types": None,
            # #442: None until the RAW transcript is read - never [] standing
            # in for "nothing was inspected".
            "server_side_tool_uses": None,
        }
        observation = TranscriptObservation(
            files_found=len(matches), prompt_delivered=False, prompt_delivery_reason=None,
            canary_satisfied=False, canary_reason=None,
            skill_invocation_detection=spec.skill_invocation_detection,
        )
        if len(matches) != 1:
            if stored_transcript is not None:
                stored_transcript["evidence"] = trial.TranscriptEvidence(
                    None, f"expected exactly one transcript file, found {len(matches)}",
                )
            observation = TranscriptObservation(
                files_found=len(matches), prompt_delivered=False,
                prompt_delivery_reason=f"expected exactly one transcript file, found {len(matches)}",
                canary_satisfied=False,
                canary_reason=f"expected exactly one transcript file, found {len(matches)}",
                skill_invocation_detection=spec.skill_invocation_detection,
            )
            if len(matches) > 1 and sessions is not None:
                # #500: a second session is the evidence that matters most, so
                # every file is kept and read - never all of them discarded.
                summary: list[dict[str, object]] = []
                for index, (path, raw_session) in enumerate(sorted(matches.items()), start=1):
                    kept_session = redact_transcript_identities(raw_session)
                    text_session = raw_session.decode("utf-8", errors="replace")
                    evidence = retainable_transcript(kept_session)
                    entry: dict[str, object] = {"index": index, "path": path, "evidence": evidence}
                    try:
                        meta = spec.run_metadata(text_session) if spec.run_metadata is not None else None
                    except Exception as exc:  # noqa: BLE001 - one unreadable session must not lose the rest
                        meta, entry["error"] = None, f"{type(exc).__name__}: {exc}"
                    entry["model"] = meta.get("model") if isinstance(meta, Mapping) else None
                    entry["token_usage"] = meta.get("token_usage") if isinstance(meta, Mapping) else None
                    sessions.append(entry)
                    summary.append({k: entry.get(k) for k in ("index", "path", "model", "token_usage", "error")}
                                   | {"retained": evidence.data is not None,
                                      "reason": evidence.reason})
                extra["multiple_transcripts"] = True
                extra["transcript_sessions"] = summary
                if scan_codex:
                    scans = [ag.scan_transcript_text(raw_session.decode("utf-8", errors="replace"))
                             for _path, raw_session in sorted(matches.items())]
                    # One session the scan could not read leaves the whole scan unknown.
                    extra["transcript_codex_invocations"] = (
                        None if any(scan is None for scan in scans)
                        else [hit for scan in scans if scan is not None for hit in scan])
        else:
            (matched_path, raw), = matches.items()
            # Account identifiers and encrypted reasoning are redacted before
            # anything is kept (#225); the observation below still reads `raw`.
            kept = redact_transcript_identities(raw)
            if stored_transcript is not None:
                stored_transcript["evidence"] = retainable_transcript(kept)
            if retained_transcript is not None:
                # The client's own bytes apart from the redacted values, never
                # a decode/re-encode round trip - retention exists so a run can
                # be re-scanned against what the client actually wrote.
                retained_transcript["path"] = matched_path
                retained_transcript["bytes"] = kept
            observation, census, run_metadata = observe_transcript_bytes(
                spec, raw, expected_prompt=expected_prompt, skill_name=skill_name,
                local_mcp_servers=local_mcp_servers)
            if scan_codex:
                extra["transcript_codex_invocations"] = ag.scan_transcript_text(
                    raw.decode("utf-8", errors="replace"))
        if scan_codex and "transcript_codex_invocations" not in extra:
            # No transcript at all: nothing was scanned, which is not "none found".
            extra["transcript_codex_invocations"] = None

        usage = credential.CredentialUsage(
            client=spec.name, delivered=cred_bytes is not None, refresh_observed_in_container=refresh_observed,
        )
        remaining_raw = delivered_credential_bytes.get("remaining_seconds")
        remaining_at_launch = int(remaining_raw) if isinstance(remaining_raw, bytes) else None
        return {
            **observation.to_fields(), **usage.to_record_fields(),
            "credential_remaining_seconds_at_launch": remaining_at_launch,
            **census,
            "run_metadata": run_metadata,
            **extra,
        }

    return hook


def _frozen_candidate_files(experiment: trial.Experiment, attempt_id: str) -> list[tuple[str, bytes, bool]]:
    """`verify.grade_files`'s own `files` shape, read from the ATTEMPT'S
    FROZEN, CONTENT-ADDRESSED EVIDENCE (`trial.frozen_artifacts`) - never a
    live workspace directory. `run_through_backend` calls
    `trial.cleanup_workspace` unconditionally before returning (this
    module's own docstring, "teardown is unconditional"), so by the time
    `run_one_attempt` can act on its result, the raw exported directory is
    already gone; `trial.capture` already froze its bytes into the
    evidence store before that happened, and `frozen_artifacts` re-verifies
    each one against its own digest before handing it back (issue #9's own
    "gate between capture and grading").

    Executability is NOT recorded in the artifact manifest at all
    (`trial.py`'s own `_export`, checked directly) - a real limitation,
    not an oversight: every artifact here is reported non-executable.
    A grader whose probe depends on a candidate file's own executable bit
    (rather than invoking it through an explicit interpreter) is not yet
    supported through this path."""
    return [
        (str(artifact["path"]), Path(str(artifact["object"])).read_bytes(), False)
        for artifact in trial.frozen_artifacts(experiment, attempt_id)
    ]


def observation_record_name(attempt_id: str) -> str:
    """Beside `trial._lifecycle_name(attempt_id)` in the experiment root - the
    name a stand-in `verified-result` cites (#139), so it has one definition."""
    return verify.observation_record_name(attempt_id)


def _as_list(value: object) -> list[object] | None:
    return list(value) if isinstance(value, (list, tuple)) else None


def build_observation_record(
    record: Mapping[str, object], *, client: str, grader_supplied: bool,
) -> dict[str, object]:
    """The `agent-observation` record (#106, `records.AGENT_OBSERVATION`) for
    one finished attempt, from `run_one_attempt`'s own returned record - every
    path, including an attempt blocked before launch (`not-observed`) and one
    whose transcript hook failed (`unknown`). Copies only the controller's
    derived facts: no transcript text, no credential bytes, and from the grade
    only its status, category and each criterion's id/mandatory/outcome (never
    the grader's free-text detail)."""
    observation = record.get("observation")
    obs = observation if isinstance(observation, dict) else None
    status: str
    reason: str | None = None
    transcript: dict[str, object] | None = None
    if obs is None:
        status = "not-observed"
        reason = str(record.get("reason") or f"no transcript was read; disposition {record.get('disposition')!r}")
    elif obs.get("status") == "unknown":
        status = "unknown"
        reason = str(obs.get("reason") or "the observation hook failed without a reason")
    else:
        status = "observed"
        transcript = {
            "files_found": obs.get("transcript_files_found"),
            "prompt_delivered": obs.get("prompt_delivered"),
            "prompt_delivery_reason": obs.get("prompt_delivery_reason"),
            "canary_satisfied": obs.get("canary_satisfied"),
            "canary_reason": obs.get("canary_reason"),
            "skill_invocations": _as_list(obs.get("skill_invocations")),
            "skill_invocation_detection": obs.get("skill_invocation_detection"),
            "skills_listed": _as_list(obs.get("skills_listed")),
            "skills_listed_source": obs.get("skills_listed_source"),
            "grading_eligible": obs.get("grading_eligible"),
            "census": {
                "client_version": obs.get("transcript_client_version"),
                "model": obs.get("transcript_model"),
                "line_types": obs.get("transcript_line_types"),
                "unrecognized_types": obs.get("transcript_unrecognized_types"),
                "response_items_inspected": obs.get("transcript_response_items_inspected"),
                "error": obs.get("transcript_census_error"),
            },
        }
    src = obs or {}
    graded = record.get("graded")
    graded_d = graded if isinstance(graded, dict) else None
    criteria = graded_d.get("criteria") if graded_d else None
    return {
        "version": 2,
        "kind": records.AGENT_OBSERVATION,
        "producer": "controller",
        "attempt_id": record.get("attempt_id"),
        "trial_id": record.get("trial_id"),
        "client": client,
        "status": status,
        "reason": reason,
        "transcript": transcript,
        "credential": {
            "delivered": src.get("credential_delivered"),
            "source": src.get("credential_source"),
            "remaining_seconds_at_launch": src.get("credential_remaining_seconds_at_launch"),
            "refresh_observed_in_container": src.get("credential_refresh_observed_in_container"),
        },
        "grading": {
            "grader_supplied": grader_supplied,
            "eligible": bool(transcript and transcript.get("grading_eligible") is True),
            "blocked_reason": record.get("grading_blocked_reason"),
            "graded_status": graded_d.get("status") if graded_d else None,
            "category": graded_d.get("category") if graded_d else None,
            "criteria": [
                {"id": c.get("id"), "mandatory": c.get("mandatory"), "outcome": c.get("outcome")}
                for c in criteria if isinstance(c, dict)
            ] if isinstance(criteria, list) else None,
        },
    }


def _string_leaves(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in (*_string_leaves(k), *_string_leaves(v))]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _string_leaves(item)]
    return []


def write_observation_record(experiment: trial.Experiment, attempt_id: str, data: Mapping[str, object]) -> str:
    """Write `data` beside the attempt's lifecycle record. Host paths this
    process knows (home, temp, the repo) are redacted first, exactly as the
    paste-back does - a blocked attempt's reason often names the credential
    path, and refusing THAT record would lose the evidence a blocked attempt
    most needs. Then leak-checked twice: each string as it will read once
    parsed, and the serialized text (#136's review: `json.dumps` escaping hides
    an OAuth-shaped value inside a string from a text-only scan).

    Returns `written`, `refused-leak` (nothing written), or `write-failed`."""
    text = demo.redact_known_host_paths(json.dumps(data, indent=2, sort_keys=True, default=str))
    parsed = json.loads(text)
    findings = [f for leaf in _string_leaves(parsed) for f in demo.leak_check_text(leaf)]
    if findings or demo.leak_check_text(text):
        return "refused-leak"
    try:
        with trial.experiment_lock(experiment.root):
            (experiment.root / observation_record_name(attempt_id)).write_text(text + "\n", encoding="utf-8")
    except OSError:
        return "write-failed"
    return "written"


#: `demo.run_subject_discovery`'s own per-name outcomes - re-exported here
#: rather than re-literalled, so this module and demo.py cannot silently
#: drift on the strings that mean "discovered".
_DISCOVERED, _NOT_DISCOVERED, _UNMEASURED = "discovered", "not-discovered", "UNMEASURED"


def readiness_from_discovery_listings(
    declared: frozenset[str],
    before: tuple[dict[str, str], frozenset[str], str | None],
    after: tuple[dict[str, str], frozenset[str], str | None],
) -> dict[str, object]:
    """Build the agent-trial path's two installation-readiness facts
    (`verify.READINESS_FACTS`) from a codex model-free listing taken before
    and after `extra_home_files` delivery (#150-D, ADR 0005's "yes, narrow
    B1" ruling narrowing #139's own B1: an agent-trial arm that installs a
    declared collection now writes a real installation receipt, built from
    an in-container discovery canary, instead of staying on the
    `AGENT_OBSERVATION_READINESS` stand-in that arms installing nothing
    still use unchanged).

    `before`/`after` are `demo.run_subject_discovery`'s own return shape -
    `({name: "discovered"|"not-discovered"|"UNMEASURED"}, unexpected,
    reason)` for every name in `declared` - taken by calling it once before
    `extra_home_files` is delivered into the container and once after, with
    the SAME `declared` name set both times. `reason` is non-`None` only
    when the listing could not be obtained at all (a launch failure, a
    nonzero exit, or output the shared parser could not read), in which
    case every declared name maps to `"UNMEASURED"` there too and
    `unexpected` is empty - never treated as absence.

    `discovery_canary` (from `after`): `SATISFIED` only if every declared
    skill is `"discovered"` after delivery. `UNKNOWN` if the listing could
    not be obtained, or maps any declared name to `"UNMEASURED"`.
    `VIOLATED` if the listing succeeded but a declared skill is
    `"not-discovered"` - the file copy or the client's own discovery
    failed, whichever it was. `after`'s own `unexpected` plays no part
    here - an undeclared skill appearing alongside a freshly-delivered one
    says nothing about whether delivery worked.

    `baseline_absence` (from `before`): `SATISFIED` only if every declared
    skill was `"not-discovered"` BEFORE delivery AND `before`'s own
    `unexpected` is empty. `UNKNOWN` follows `discovery_canary`'s rule over
    the earlier listing. `VIOLATED` either way round: a declared skill
    already `"discovered"` before delivery is contamination (an earlier
    attempt's leftover state, or a container that did not start clean);
    an UNDECLARED skill already listed is the same hazard from the other
    direction (cross-model review, PR #154's own predecessor: an
    image-shipped or leftover skill unrelated to this trial could make a
    degraded arm pass for the wrong reason - the trial would credit its
    own instructions for behaviour the baseline environment already
    supplied). Both are checked; either alone VIOLATES.

    A degraded arm that mutates a skill's content but leaves the file
    itself in place is STILL discovered after delivery - readiness cannot
    and must not distinguish a mutated skill from an intact one; that is
    the grader's job, not this criterion's. #133 item 4 (per-entry install
    readiness, replacing `DockerBackend.install()`'s current all-or-nothing
    canary) is moot for this path for the same reason: this readiness is
    already per-entry, one listing lookup per declared name, independent
    of whatever `install()` itself reports.

    Only `codex` has a model-free listing (`materialize.SURFACES
    ["codex-skills"].model_free_listing`); a Claude Code arm has no way to
    obtain either listing at all, so a caller must not call this for one -
    `AGENT_OBSERVATION_READINESS` is what a Claude Code arm keeps, exactly
    like an empty baseline arm."""

    after_listed, _after_unexpected, after_reason = after
    if after_reason is not None or any(after_listed.get(name) == _UNMEASURED for name in declared):
        discovery = {
            "outcome": "UNKNOWN",
            "detail": after_reason or "the listing named an UNMEASURED skill",
        }
    elif all(after_listed.get(name) == _DISCOVERED for name in declared):
        discovery = {"outcome": "SATISFIED", "detail": "every declared skill discovered after delivery"}
    else:
        discovery = {
            "outcome": "VIOLATED",
            "detail": f"not every declared skill was discovered after delivery: {after_listed}",
        }

    before_listed, before_unexpected, before_reason = before
    if before_reason is not None or any(before_listed.get(name) == _UNMEASURED for name in declared):
        absence = {
            "outcome": "UNKNOWN",
            "detail": before_reason or "the listing named an UNMEASURED skill",
        }
    elif any(before_listed.get(name) == _DISCOVERED for name in declared):
        absence = {
            "outcome": "VIOLATED",
            "detail": f"a declared skill was already listed before delivery: {before_listed}",
        }
    elif before_unexpected:
        absence = {
            "outcome": "VIOLATED",
            "detail": f"undeclared skill(s) already listed before delivery: {sorted(before_unexpected)}",
        }
    else:
        absence = {"outcome": "SATISFIED", "detail": "no declared or undeclared skill listed before delivery"}

    return {
        "discovery_canary": discovery["outcome"],
        "baseline_absence": absence["outcome"],
        "discovery_canary_detail": discovery["detail"],
        "baseline_absence_detail": absence["detail"],
    }


#: (image digest, delivered-tree digest) - review point 1: baseline_absence
#: is a property of the image alone, and discovery is a property of
#: (image, tree, delivery method), so caching on this key means a run with
#: several attempts sharing one image/tree pays for 2 extra containers total,
#: not 2 per attempt. There is only one delivery method today
#: (`deliver_home_file`), so it is not itself part of the key; a second
#: method would need to become one.
DiscoveryCacheKey = tuple[str, str]

#: A fresh cache dict, one per caller-defined "run" (typically one CLI
#: invocation) - never a module-level global, so tests (and two concurrent
#: runs) never share state by accident.
DiscoveryCache = dict[DiscoveryCacheKey, tuple["_DiscoveryMeasurement", "_DiscoveryMeasurement"]]


@dataclass(frozen=True)
class _DiscoveryMeasurement:
    listing: dict[str, str]
    unexpected: frozenset[str]
    reason: str | None
    image_digest: str | None


def _measure_discovery(
    backend: DockerBackend, id_prefix: str, client_argv: Sequence[str],
    extra_home_files: Mapping[str, bytes], selected: frozenset[str],
    limits: Limits, base: Path,
) -> _DiscoveryMeasurement:
    """Prepare a fresh, dedicated, throwaway container - NEVER the agent's
    own. `DockerBackend.execute()`'s own docstring is explicit: "Intended to
    be called ONCE per handle"; it stops the container before returning. So
    a before-delivery listing, an after-delivery listing and the real agent
    invocation cannot share one container - this mirrors `demo.py`'s own
    install+list+destroy lifecycle for its non-agent subject-discovery leg
    (`install_subject` / `run_subject_discovery` / `destroy`), applied to a
    throwaway container instead.

    Any failure - the container could not be prepared, a file could not be
    delivered, or its absence after teardown could not be confirmed - maps
    to the same UNMEASURED shape `demo.run_subject_discovery` uses for its
    own failures (#150-D review point 3), so it flows into UNKNOWN the same
    way an unobtainable listing does - never SATISFIED."""
    unmeasured = {name: "UNMEASURED" for name in selected}
    attempt_id = f"{id_prefix}-{secrets.token_hex(4)}"
    try:
        handle = backend.prepare(attempt_id)
    except BackendUnavailable as exc:
        return _DiscoveryMeasurement(unmeasured, frozenset(), f"listing container could not be prepared: {exc}", None)

    result = _DiscoveryMeasurement(unmeasured, frozenset(), "measurement did not complete", None)
    try:
        for relpath, data in extra_home_files.items():
            backend.deliver_home_file(handle, relpath, data)
        image_digest = backend.image_id(handle)
        listing, unexpected, reason = demo.run_subject_discovery(
            backend, handle, list(client_argv), set(selected), limits, base,
        )
        result = _DiscoveryMeasurement(listing, unexpected, reason, image_digest)
    except BackendUnavailable as exc:
        result = _DiscoveryMeasurement(
            unmeasured, frozenset(), f"delivery to the listing container failed: {exc}", result.image_digest,
        )
    finally:
        backend.destroy(handle)
        absent = backend.confirm_absent(handle)
    if absent != Confirmation.CONFIRMED:
        # Overrides whatever was measured above (review point 3): an
        # unconfirmed teardown means this container's own state - and so its
        # listing - is no longer something this run can vouch for.
        return _DiscoveryMeasurement(
            unmeasured, frozenset(),
            f"the listing container's absence after teardown could not be confirmed ({absent.value})",
            result.image_digest,
        )
    return result


@dataclass(frozen=True)
class InstallationReceiptContext:
    """Everything `_build_discovery_receipt` needs beyond what
    `run_one_attempt` already has (#150-D, ADR 0005's "yes, narrow B1"
    ruling). Passed only by a caller that has a real acquired collection
    (`collection_conformance.run_collection_agent_attempt`); every other
    caller (`matched_pilot`'s own arms, `selection_probe`) omits it and
    keeps `grade_agent_attempt`'s B1 stand-in exactly as before - this
    receipt path is additive, never a behavior change for an existing
    caller that does not opt in.

    `cache` is caller-owned and caller-scoped (typically one per CLI
    invocation / one per `skillc pilot-run` - "a run" in review point 1's
    sense) - passing the SAME cache across multiple `run_one_attempt` calls
    that share `subject.digest`/`image.digest` is what makes the caching
    real; a fresh `{}` per call defeats it, which is the caller's choice to
    make, not this function's.

    `listing_client_argv` is caller-supplied, exactly as `run_one_attempt`'s
    own `base_argv` already is (see that parameter's docstring for why): a
    bare `[client]` (`["codex"]`) is only resolvable when the real binary is
    on the container's `PATH`, which a real trial image gives it but a test
    fixture does not - `None` (the default) uses `[client]`, correct for a
    real container; a test passes a scripted stand-in's own invocation
    instead (`tests/fixtures/codex-subject/fake_codex.py`'s own `debug
    prompt-input` handling, already shaped for exactly this)."""

    declared: frozenset[str]
    tree_digest: str
    subject_locator: str
    subject_revision: str
    surface_name: str
    cache: DiscoveryCache
    listing_client_argv: Sequence[str] | None = None


#: The exact evidence sentence review point 2 requires, verbatim, so a
#: reader of the receipt (not just this module's docstrings) sees the precise
#: claim: measured in a FRESH container of the same image, never "the
#: agent's own container had it".
_DISCOVERY_RECEIPT_CLAIM = (
    "this delivered tree, delivered by the same method, into a fresh "
    "container of the same image digest, was discovered by the client's "
    "model-free listing"
)


def _build_discovery_receipt(
    *,
    backend: DockerBackend,
    experiment: trial.Experiment,
    attempt_id: str,
    client: str,
    client_version: str,
    client_argv: Sequence[str],
    extra_home_files: Mapping[str, bytes],
    limits: Limits,
    base: Path,
    context: InstallationReceiptContext,
) -> dict[str, object] | None:
    """Measure (or reuse a cached measurement of) discovery before and after
    delivering `extra_home_files` into fresh throwaway containers, and build
    a `records.INSTALLATION_RECEIPT`-shaped dict - the REAL schema
    (`records.py`), through `verify.grade`'s existing default path, not a
    new `readiness_source` (review: the schema's `adapter`/`surface`/
    `layers`/`dependencies`/`allowed_writes` fields are loosely typed enough
    to state honestly here - an empty list is documented as "none", not
    "missing" - and inventing a new readiness_source would mean extending
    `records.py`'s OWN bundle-level validation, the actual "new schema" to
    avoid).

    Returns `None` - never a receipt claiming readiness it does not have -
    when `client` has no model-free listing (only codex does today:
    `materialize.SURFACES["codex-skills"].model_free_listing`); the caller
    keeps the B1 stand-in for a Claude Code arm exactly as for an empty one.
    """
    if client != "codex" or not context.declared:
        return None
    planned = experiment.trial_of(attempt_id)
    trial_id = str(planned["trial_id"])
    planned_image = planned.get("image")
    planned_image_digest = planned_image.get("digest") if isinstance(planned_image, dict) else None
    if not isinstance(planned_image_digest, str) or not planned_image_digest:
        planned_image_digest = "UNKNOWN"
    # The CACHE key uses the ledger's PLANNED image digest, known up front -
    # never a live measurement, which would need a container to already
    # exist to obtain (review point 1: cache on (image, tree), not per
    # attempt). The RECEIPT's own `image.digest` field, below, is the
    # ACTUALLY MEASURED value from the listing container instead - #151's
    # "the image that ran", never the configured tag - and
    # `verify._receipt`'s cross-check is what confirms the two agree, the
    # same discipline `_record_identity`/`backend-identity` already applies
    # to the agent's own container.
    key: DiscoveryCacheKey = (planned_image_digest, context.tree_digest)
    if key not in context.cache:
        baseline = _measure_discovery(
            backend, f"{attempt_id}-baseline", client_argv, {}, context.declared, limits, base,
        )
        discovery = _measure_discovery(
            backend, f"{attempt_id}-discovery", client_argv, extra_home_files, context.declared, limits, base,
        )
        context.cache[key] = (baseline, discovery)
    baseline, discovery = context.cache[key]

    readiness = readiness_from_discovery_listings(
        context.declared,
        (baseline.listing, baseline.unexpected, baseline.reason),
        (discovery.listing, discovery.unexpected, discovery.reason),
    )
    measured_image_digest = discovery.image_digest or baseline.image_digest
    readiness["evidence"] = _DISCOVERY_RECEIPT_CLAIM
    readiness["cache_key"] = {"image_digest": key[0], "tree_digest": key[1]}

    installed = [
        {"path": relpath, "digest": f"sha256:{hashlib.sha256(data).hexdigest()}"}
        for relpath, data in extra_home_files.items()
    ]
    if not installed:
        # installation_receipt's own rule: "an empty list says none, a
        # missing one says unknown" (records.py) - an empty `installed` is
        # REFUSED outright ("an install that recorded nothing is not a ready
        # one"). context.declared is non-empty (checked above), so
        # extra_home_files being empty here would itself be a caller bug;
        # refuse loudly rather than write an invalid receipt.
        raise trial.Refused(
            "declared skill names are non-empty but extra_home_files is empty; "
            "nothing was actually delivered to build a receipt from"
        )

    return {
        "version": 2,
        "kind": records.INSTALLATION_RECEIPT,
        # "subject-adapter" is a ROLE (interfaces.md's producer column,
        # records.AUTHORIZED_PRODUCER), not a module name - the one producer
        # every installation-receipt must declare, whichever code plays it.
        "producer": "subject-adapter",
        "checked_by": records.RECEIPT_CHECKER,
        "attempt_id": attempt_id,
        "trial_id": trial_id,
        "subject": {
            "locator": context.subject_locator, "revision": context.subject_revision,
            "digest": context.tree_digest,
        },
        # No separate adapter component exists on this path - the client
        # itself performs the listing - so `adapter` honestly names the
        # client, matching `client` below exactly.
        "adapter": {"name": client, "version": client_version},
        "client": {"name": client, "version": client_version},
        "surface": context.surface_name,
        "treatment": "agent-trial-discovery-listing",
        # These three are native-adapter concepts (materialize.py's own
        # layering/dependency resolution) that do not apply to this path -
        # an empty list is the schema's OWN documented spelling of "none",
        # not "missing" (records.py's installation_receipt docstring).
        "layers": [],
        "dependencies": [],
        "allowed_writes": [],
        "installed": installed,
        "readiness": readiness,
        "image": {"digest": measured_image_digest or "UNKNOWN"},
    }


def _steward_vault_reader(fixture_session: FixtureSession | None, attempt_guard: ag.AttemptGuard | None
                          ) -> Callable[[ExecutionBackend, object], bytes | None] | None:
    """#518: where the credential is at teardown - the steward's vault."""
    holder = fixture_session or attempt_guard
    if holder is None:
        return None

    def read(backend: ExecutionBackend, handle: object) -> bytes | None:
        driver = holder.steward_driver
        return driver.vault_bytes(backend, handle) if driver is not None else None  # type: ignore[arg-type]
    return read


def _fixture_credit_block(session: FixtureSession, observation: object = None) -> str | None:
    """#434's credit-gate reasons, or `None` when the fixture's evidence lets
    the attempt be graded at all (the judge still decides each criterion).
    #518: the guard's own record is not enough - a nested client that never came
    through it (a login shell's PATH) is read from the transcript too."""
    if session.failure is not None:
        return f"not credited: {session.failure}"
    if session.record is None:
        return "not credited: the fixture service record was never finalized"
    guard = session.guard_record()
    block = cg.credit_block(guard, nested_policy=session.nested_policy)
    if block is None and (bypass := ag.nested_bypass(ag.guard_nested(guard), observation, session.nested_policy)):
        block = "not credited: nested codex past the guard (" + "; ".join(bypass) + ")"
    return block or cs.credit_block(session.steward_record())  # #518


def _fixture_extras(session: FixtureSession | None,
                    stored_transcript: Mapping[str, trial.TranscriptEvidence]) -> dict[str, object] | None:
    """The controller-held evidence beside the gate witness: the final report
    is the agent's last message as the stored transcript recorded it."""
    if session is None:
        return None
    evidence = stored_transcript.get("evidence")
    report: str | None = None
    if evidence is not None and evidence.data is not None:
        message = ta.codex_run_metadata(evidence.data.decode("utf-8", errors="replace")).get("final_agent_message")
        report = message if isinstance(message, str) else None
    return session.extras(report)


def run_one_attempt(
    *,
    backend: DockerBackend,
    experiment: trial.Experiment,
    attempt_id: str,
    client: str,
    base_argv: Sequence[str],
    prompt: str,
    skill_name: str | None,
    surface: Mapping[str, object],
    limits: Limits,
    base: Path,
    workdir: PurePosixPath | None = None,
    mcp_servers: Mapping[str, MCPServerSpec] | None = None,
    credential_explicit_path: str | Path | None = None,
    minimum_credential_seconds: float = credential.MINIMUM_REMAINING_SECONDS,
    cli_version: str | None = None,
    grader: verify.GraderDef | None = None,
    grading_backend: ExecutionBackend | None = None,
    extra_home_files: Mapping[str, bytes] | None = None,
    verify_home_files: Mapping[str, str] | None = None,
    preflight_tools: Sequence[Mapping[str, object]] | None = None,
    gate_entrypoint: str | None = None,
    gate_witness: str | None = None,
    bundled_gate_entrypoints: Sequence[str] = (),
    project_gate: pg.ProjectGate | None = None,
    retain_transcript: bool = False,
    receipt_context: InstallationReceiptContext | None = None,
    fixture: AttemptFixture | None = None,
    turns: ct.Turns | None = None,
    nested_codex_policy: str | None = None,
    codex_guard: bool = False,
    declared_model: str | None = None,
    extra_home_modes: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Drive one real-agent attempt end to end and, only when the real
    transcript confirms both prompt delivery and the liveness canary, grade
    the exported output through `grader` (a SEPARATE backend instance,
    interfaces.md's own step-8 rule - never `backend`, which the agent's own
    attempt already used).

    `receipt_context` (#150-D): when given, and `client` has a model-free
    listing and delivered at least one skill, a REAL installation receipt is
    measured (in fresh throwaway containers - never the agent's own; see
    `_build_discovery_receipt`) and graded through `verify.grade`'s normal
    path. `None` (the default) - or a Claude Code arm, or an empty
    `extra_home_files` - keeps `grade_agent_attempt`'s B1 stand-in exactly as
    before; every existing caller that omits this parameter is unaffected.

    `client` must name one of `CLIENT_SPECS`. `cli_version`, when omitted,
    is read from `docker/trial/pinned-versions.json` via
    `trial_bootstrap.pinned_cli_version` - never guessed.

    `skill_name=None` composes a SKILL-FREE canary instruction (issue #26
    review): the named-skill form ("invoke the '<skill>' skill, then...")
    tells the agent which skill to use, which is exactly the answer a
    SELECTION probe exists to observe rather than supply - every "selected"
    result under that instruction would be an artifact of the prompt, not a
    measurement. With `skill_name=None`, the instruction mentions no skill at
    all (only the tool write of `touched:<nonce>`), `check_agent_canary`
    requires only a confirmed, error-free tool use, and skill selection
    becomes purely what `TranscriptObservation.skill_invocations` observes.
    The named-skill form is unchanged and still the right choice outside a
    selection probe (#106/#107's own liveness proof, where naming the skill
    under test is the point).

    `extra_home_files` (issue #11): additional container-home files delivered
    alongside the credential and the client's own seed - a declared skill
    collection's own surface, keyed by container-relative path, exactly the
    shape `demo.install_subject` already builds for the no-agent `--subject`
    leg. `None` (the default) delivers nothing beyond what `spec` already
    composes, so every existing caller is unaffected.

    `verify_home_files` (#334): a subset of `extra_home_files`' own
    destinations (relpath -> expected `sha256:` digest) to read back from
    the LIVE container and digest-check after delivery, before the agent
    starts - host-side checks prove what was SENT, this proves what
    ARRIVED. A mismatch or an unreadable file raises `HomeFileVerificationRefused`
    inside `before_execute`, which `lifecycle.run_through_backend` turns
    into an unavailable attempt (never dispatched, never a guessed
    outcome) - the same path an unreachable backend already takes.
    `None` (the default) verifies nothing, so every existing caller is
    unaffected.

    `preflight_tools` (#334): a profile's `tool`-kind dependencies, checked
    present in THIS container at their declared version constraint, same
    `before_execute` failure path as `verify_home_files` above - never on
    the host (`profile._check_tool`'s own convention, for the unrelated
    `skillc profile install` CLI). `None` (the default) checks nothing.

    `retain_transcript=True` (issue #26): the ORIGINAL transcript bytes (one
    file, the same one the observation itself reads - never a second read)
    are attached to the returned dict as `result["retained_transcript"]`
    (`{"path": <container-relative path>, "bytes": <raw bytes>}`, or absent
    when no single transcript file was found). Default `False` leaves every
    existing caller's returned shape unchanged; this is deliberately NOT part
    of `build_observation_record` or the stored `agent-observation` record,
    which that function's own docstring already states carries no transcript
    text - leak-checking and persisting what this returns is the CALLER's
    job (`selection_probe.py`'s own retention, not a general capability every
    caller inherits for free).

    `turns` (#279): this case's controller-delivered turns, e.g. the Step-3
    approval (`controller_turns`). After a turn EXITS with code 0, the next
    declared text is sent as `[*turn-1 argv, "resume", <session id>, <text>]`
    in the same container and wall budget. The session id comes only from
    turn 1's own stderr header, and every resume argv passes #442's preflight
    before any container exists. The guard then expects one top-level launch
    per turn, and the result's `controller_turns` says what was delivered.
    `None` or empty: one turn, exactly as before.

    `fixture` (#434): a fixture-service task's per-attempt facts. The
    attempt then also carries `fixture_attempt.FixtureSession`: the `gh` shim
    and the nested-codex guard placed root-owned before the agent starts, the
    service over an in-attempt `ExecGitRemote`, and, after the stop, the
    service finalized and the git state captured from the EXPORTED bytes
    (`git_snapshot`, no git process). Its routes share the one socket with the
    gate witness through `fixture_service.dispatch`, so `gate_entrypoint` is
    required and the witness uses the fixture's own gate map and shim. A
    fixture attempt on #442's egress keeps its default allowlist; a widened
    one is refused before any container exists. The credit gate adds the
    fixture's own reasons (a failed binding or finalization, a missing service
    record, a nested-codex count that is not zero), and grading receives the
    controller-held evidence as `verify`'s `trusted_extras`. `None` (the
    default) changes nothing for any other caller."""
    if nested_codex_policy is not None and nested_codex_policy not in cg.NESTED_POLICIES:
        raise ValueError(f"nested_codex_policy must be one of {cg.NESTED_POLICIES}, not {nested_codex_policy!r}")
    if extra_home_modes is not None:
        # #505: each installed file's SOURCE git mode, checked before any
        # container exists: only a delivered file has one, and only a git mode.
        unknown = sorted(set(extra_home_modes) - set(extra_home_files or {}))
        if unknown:
            raise HomeFileVerificationRefused(f"extra_home_modes names files that are not delivered: {unknown}")
        for relpath in extra_home_modes:
            delivery_mode(relpath, extra_home_modes)
    #: #279 PR-2a: one controller-owned ordering per MULTI-TURN attempt only
    #: (orchestrator ruling R3); every other attempt's records are unchanged.
    attempt_order = Order() if turns is not None and turns.texts else None
    fixture_session = FixtureSession(fixture, attempt_id) if fixture is not None else None
    #: #500: the nested-codex guard on an attempt with no fixture service (a
    #: calibration attempt). A fixture attempt already carries it.
    attempt_guard = (ag.AttemptGuard(attempt_id, nested_policy=nested_codex_policy)
                     if codex_guard and fixture is None else None)
    if attempt_guard is not None and not isinstance(backend, DockerBackend):
        raise HomeFileVerificationRefused("the nested-codex guard requires a supported Docker backend")
    if fixture_session is not None:
        fixture_session.order = attempt_order
        # #279 (ruling G1): the declared nested-codex policy, recorded and
        # honoured only when declared; set before any guard record is read.
        fixture_session.nested_policy = nested_codex_policy
    if fixture is not None:
        if gate_entrypoint is None:
            raise HomeFileVerificationRefused("a fixture attempt witnesses its gate; gate_entrypoint is required")
        if isinstance(backend, DockerBackend) and backend.egress and tuple(backend.egress_hosts) != eg.ALLOWED_HOSTS:
            raise ServerSideChannelRefused(
                "refusing a fixture attempt whose egress allowlist differs from #442's defaults "
                f"({', '.join(backend.egress_hosts)}): a necessity attempt is never widened"
            )
    gate_args, stage_plans, gate_shim_source = _gate_witness_choice(gate_witness, fixture, gate_entrypoint)
    #: #525: the declared treatment deviations the bundled-gate overlay makes.
    treatment_deviation: list[dict[str, object]] = []
    if bundled_gate_entrypoints:
        if gate_entrypoint is None:
            raise HomeFileVerificationRefused("bundled gate entrypoints need the declared gate_entrypoint they copy")
        if gate_shim_source.read_bytes().count(_SHIM_VIA_LINE) != 1:
            raise HomeFileVerificationRefused("this attempt's gate witness cannot see a skill-bundled gate: the "
                                              "flow-check witness of a bundled gate is deferred (#525)")
        if gate_args is None or tuple(gate_args.get(_FLOW_FINISH_GATE, ("missing",))) != ():
            raise HomeFileVerificationRefused(f"a bundled gate is witnessed as {_FLOW_FINISH_GATE!r}, which this "
                                              "attempt does not declare as a bare call (#525)")
    if project_gate is not None:
        if fixture is not None:
            raise HomeFileVerificationRefused("a fixture attempt uses its own gate map; project_gate cannot also be set")
        if gate_entrypoint is None:
            gate_args = {}  # #508: the project gate alone, no CPP gate declared
    witness_session = (_WitnessSession(attempt_id, limits, gate_args=gate_args, stage_plans=stage_plans,
                                       project_gate=project_gate)
                       if gate_entrypoint is not None or project_gate is not None else None)
    #: #508: the agent's own exec PATH (shim directory first), filled in once
    #: the runtime env is measured; a launch before then is refused.
    agent_env: dict[str, str] = {}

    def agent_exec_env() -> Mapping[str, str]:
        if "PATH" not in agent_env:
            raise HomeFileVerificationRefused("the project-gate shim was not placed before the agent launch")
        return dict(agent_env)
    run_gate_keys = frozenset({"op", "gate", "cwd", *(("make_args", "make_env") if project_gate is not None else ())})
    passthrough_route = ({pg.PASSTHROUGH_OP: (witness_session.decide,
                                              frozenset({"op", "argv", "cwd", "exit_code", "why"}))}
                         if project_gate is not None and witness_session is not None else {})
    if witness_session is not None:
        witness_session.order = attempt_order
    selected_supply = backend.runtime_supply if isinstance(backend, DockerBackend) else None
    if witness_session is not None or selected_supply is not None:
        if not isinstance(backend, DockerBackend):
            raise HomeFileVerificationRefused("witnessing requires a supported Docker backend")
        if grading_backend is backend:
            raise ValueError("grading_backend must be a SEPARATE instance from the original agent backend")
        if witness_session is not None and backend.trigger_decide is not None:
            raise HomeFileVerificationRefused("witnessing conflicts with an existing trigger callback")
        trigger = witness_session.decide if witness_session else backend.trigger_decide
        if fixture_session is not None and witness_session is not None:
            # One socket, routed by op alone; a mixed request is refused.
            trigger = fixture_session.watch(fs.dispatch({
                "witness_ready": (witness_session.decide, frozenset({"op", "nonce"})),
                "run_gate": (witness_session.decide, run_gate_keys),
                **passthrough_route,
                **fixture_session.routes(),
            }))
        elif attempt_guard is not None and witness_session is not None:
            # #500: the guard shares the witness's one socket, routed by op.
            trigger = attempt_guard.watch(fs.dispatch({
                "witness_ready": (witness_session.decide, frozenset({"op", "nonce"})),
                "run_gate": (witness_session.decide, run_gate_keys),
                **passthrough_route,
                **attempt_guard.routes(),
            }))
        try:
            backend = replace(backend, witness_io=True, trigger_decide=trigger,
                              agent_exec_env=agent_exec_env if project_gate is not None else backend.agent_exec_env)
        except (TypeError, ValueError) as exc:
            raise HomeFileVerificationRefused("backend cannot preserve its type while enabling witness IO") from exc
    if attempt_guard is not None and witness_session is None:
        # #500: no witness, so the guard's channel is the attempt's only socket.
        assert isinstance(backend, DockerBackend)
        if backend.trigger_decide is not None:
            raise HomeFileVerificationRefused("the nested-codex guard conflicts with an existing trigger callback")
        try:
            backend = replace(backend, witness_io=True,
                              trigger_decide=attempt_guard.watch(fs.dispatch(attempt_guard.routes())))
        except (TypeError, ValueError) as exc:
            raise HomeFileVerificationRefused("backend cannot preserve its type while enabling the guard") from exc

    if client not in CLIENT_SPECS:
        raise credential.CredentialRefused(f"unknown client {client!r}: expected one of {sorted(CLIENT_SPECS)}")
    if client == "codex" and isinstance(backend, DockerBackend):
        # #442 preflight, before any container exists: a live codex attempt
        # runs only with provider-only egress AND every server-side channel
        # pinned off in its own argv. A scripted subject on network "none"
        # (the Level-3 campaigns) reaches nothing and is not checked here.
        if backend.egress:
            missing = eg.missing_server_side_flags(base_argv)
            if missing:
                raise ServerSideChannelRefused(
                    "refusing a live codex attempt with a server-side channel left open: " + "; ".join(missing)
                )
        elif backend.network != "none":
            raise ServerSideChannelRefused(
                f"refusing a live codex attempt on network {backend.network!r} with no provider-only egress "
                "policy (#442): the container could reach the public repository that holds the graders"
            )
    declared_turns = turns.texts if turns is not None else ()
    if declared_turns and client not in ct.CLIENTS:
        raise ct.TurnsRefused(f"controller turns support {list(ct.CLIENTS)} only, not {client!r}")
    if declared_turns and not isinstance(backend, TurnCapableBackend):
        raise ct.TurnsRefused(f"{type(backend).__name__} cannot keep an attempt running between turns")
    spec = CLIENT_SPECS[client]
    resolved_workdir = workdir if workdir is not None else PurePosixPath("/work")
    resolved_mcp_servers: Mapping[str, MCPServerSpec] = mcp_servers if mcp_servers is not None else {}
    resolved_cli_version = cli_version or trial_bootstrap.pinned_cli_version(spec.pinned_version_key)
    # ONE nonce, ONE instruction, ONE artifact (cross-model review: minimize
    # prompt contamination in the very behaviour being measured) - the same
    # nonce lifecycle.run_through_backend plants as its OWN backend-level
    # content canary is passed straight through as this trial's agent-canary
    # nonce too, and the agent is pointed at the SAME result file
    # (docker_backend.CANARY_RESULT_FILENAME) lifecycle already reads back
    # and verifies after export() - never a second, agent_trial-local nonce
    # or a second instruction.
    nonce = trial_bootstrap.new_canary_nonce()
    canary_instruction = trial_bootstrap.compose_canary_instruction(
        skill_name, nonce, result_filename=CANARY_RESULT_FILENAME,
    )
    full_prompt = f"{prompt}\n\n{canary_instruction}"
    invocation = trial_bootstrap.build_invocation(
        attempt_id, base_argv, supports_name=spec.supports_name_flag,
    )
    argv = (*invocation.argv, full_prompt)
    for text in declared_turns:
        # Every resume argv is checked before any container exists: the same
        # #442 preflight as turn 1, on the exact shape that will run.
        probe = ct.resume_argv(client, invocation.argv, "00000000-0000-0000-0000-000000000000", text)
        if isinstance(backend, DockerBackend) and backend.egress and (missing := eg.missing_server_side_flags(probe)):
            raise ServerSideChannelRefused("refusing a controller turn with a server-side channel left open: "
                                           + "; ".join(missing))
    turn_state: dict[str, object] = {"declared": len(declared_turns), "session_id_source": "client-stderr-header",
                                     "session_id_found": None, "stopped": None}

    def next_turn(
        _backend: ExecutionBackend, _handle: object, done: int, previous: ExecuteResult,
    ) -> Sequence[str] | None:
        """#279: the argv of the turn after `done` turns, or `None`."""
        if done == 1:
            turn_state["session_id"] = ct.session_id_from_header(previous.stderr)
            turn_state["session_id_found"] = turn_state["session_id"] is not None
            # #516: why, kept in the record - turn 1's stderr is not retained
            # on an exit-0 attempt, so this is the only trace of a refusal.
            turn_state["header_refusal"] = ct.header_refusal(previous.stderr)
        if done > len(declared_turns):
            turn_state["stopped"] = "every declared turn was delivered"
            return None
        session_id = turn_state.get("session_id")
        if not isinstance(session_id, str):
            turn_state["stopped"] = "no session id in turn 1's client header: no further turn"
            return None
        # #518: the resumed client needs the credential back - for its startup
        # reads only. The steward re-arms first, then the file is restored.
        holder = fixture_session or attempt_guard
        driver = holder.steward_driver if holder is not None else None
        if driver is not None:
            try:
                driver.restore_for_turn(_backend, _handle)  # type: ignore[arg-type]
            except cs.StewardFailed as exc:
                turn_state["stopped"] = f"the credential steward could not cover the resume: {exc}"
                return None
        return ct.resume_argv(client, invocation.argv, session_id, declared_turns[done - 1])

    ctx = _AttemptContext(workdir=resolved_workdir, mcp_servers=resolved_mcp_servers, cli_version=resolved_cli_version)
    delivered_credential_bytes: dict[str, bytes] = {}
    def runtime_ready(measured_backend: DockerBackend, handle: object) -> None:
        if selected_supply is not None:
            env = measured_backend.runtime_environment(handle, limits, verify_home_files or {})
        elif witness_session is not None:
            bounded = replace(limits, timeout=min(limits.timeout, 5), max_captured_stdout_bytes=rs.MAX_JSON + 1)
            env = rs.environment(measured_backend.controller_output(handle, ["env", "-0"], bounded))
        else:
            return
        if witness_session is not None:
            witness_session.environment = MappingProxyType(dict(env))

    before_execute = _make_before_execute(
        spec=spec, ctx=ctx, credential_explicit_path=credential_explicit_path,
        minimum_credential_seconds=minimum_credential_seconds,
        delivered_credential_bytes=delivered_credential_bytes,
        extra_home_files=extra_home_files or {},
        verify_home_files=verify_home_files, preflight_tools=preflight_tools, limits=limits,
        gate_entrypoint=gate_entrypoint,
        runtime_ready=runtime_ready if witness_session is not None or selected_supply is not None else None,
        gate_shim_source=gate_shim_source,
        extra_home_modes=extra_home_modes,
        bundled_gate_entrypoints=tuple(bundled_gate_entrypoints), treatment_deviation=treatment_deviation,
    )
    if witness_session is not None:
        install_and_verify = before_execute

        def before_execute(ready_backend: ExecutionBackend, handle: object) -> None:
            install_and_verify(ready_backend, handle)
            assert isinstance(ready_backend, DockerBackend)
            for deviation in treatment_deviation:  # #525: one declared variant per witnessed bundled copy
                witness_session.variants.setdefault(_FLOW_FINISH_GATE, {})[str(deviation["via"])] = [
                    "bash", f"{deviation['mirror']}/{posixpath.basename(str(deviation['path']))}"]
            witness_session.bind_and_check(ready_backend, handle)
            if fixture_session is not None:
                fixture_session.bind(ready_backend, handle, witness_session.environment)
            if attempt_guard is not None:
                attempt_guard.bind(ready_backend, handle, witness_session.environment)
            if project_gate is not None:
                # #508: placed LAST, so the check below sees every overlay.
                pg.install_make_shim(ready_backend, handle, witness_session.environment)
                pg.verify_agent_path(ready_backend, handle, witness_session.environment,
                                     codex_guard=fo.CODEX_GUARD_PATH if attempt_guard is not None else None)
                agent_env["PATH"] = pg.agent_path(witness_session.environment)
    elif attempt_guard is not None:
        install_without_witness = before_execute

        def before_execute(ready_backend: ExecutionBackend, handle: object) -> None:
            install_without_witness(ready_backend, handle)
            assert isinstance(ready_backend, DockerBackend)
            bounded = replace(limits, timeout=min(limits.timeout, 5), max_captured_stdout_bytes=rs.MAX_JSON + 1)
            env = rs.environment(ready_backend.controller_output(handle, ["env", "-0"], bounded))
            attempt_guard.bind(ready_backend, handle, env)

    retained_transcript: dict[str, object] | None = {} if retain_transcript else None
    # #202: the transcript goes into the attempt's OWN store for every caller,
    # leak-checked first. Empty only when the hook itself failed before it
    # reached the transcript - which the fallback below states as such.
    stored_transcript: dict[str, trial.TranscriptEvidence] = {}
    #: #500: every session of an attempt that left more than one transcript.
    transcript_sessions: list[dict[str, object]] = []
    observe_before_teardown = _make_observe_before_teardown(
        spec=spec, expected_prompt=full_prompt, skill_name=skill_name,
        delivered_credential_bytes=delivered_credential_bytes,
        retained_transcript=retained_transcript, stored_transcript=stored_transcript,
        local_mcp_servers=frozenset(resolved_mcp_servers),
        sessions=transcript_sessions, scan_codex=attempt_guard is not None or fixture_session is not None,
        credential_reader=_steward_vault_reader(fixture_session, attempt_guard),
    )
    if attempt_guard is not None:
        observe_unguarded = observe_before_teardown

        def observe_before_teardown(observed_backend: ExecutionBackend, handle: object) -> Mapping[str, object]:
            try:
                attempt_guard.finish(observed_backend, handle)
            except Exception:  # noqa: BLE001 - the record then reads unknown, never zero
                attempt_guard.guard.channel_unavailable = True
            return observe_unguarded(observed_backend, handle)

    if witness_session is not None:
        observe_transcript = observe_before_teardown

        def observe_before_teardown(observed_backend: ExecutionBackend, handle: object) -> Mapping[str, object]:
            assert isinstance(observed_backend, DockerBackend)
            try:
                witness_session.finish(observed_backend, handle, experiment)
            except Exception:  # noqa: BLE001 - preserve transcript; grading checks this latched failure
                witness_session.failure = witness_session.failure or "witness finalization failed"
            if fixture_session is not None:
                try:
                    fixture_session.finish(observed_backend, handle)
                except Exception as exc:  # noqa: BLE001 - the credit gate checks this latched failure
                    fixture_session.failure = fixture_session.failure or f"fixture finalization failed: {exc}"
            return observe_transcript(observed_backend, handle)

    # #442: the attempt's egress proxy log, read while the proxy still runs
    # (before teardown) and FIRST, so a failing transcript hook cannot lose it.
    # It is captured as the `egress-proxy-log` stream of the attempt's manifest.
    egress_imports: list[trial.Import] = []
    if isinstance(backend, DockerBackend) and backend.egress:
        observe_without_egress = observe_before_teardown

        def observe_before_teardown(observed_backend: ExecutionBackend, handle: object) -> Mapping[str, object]:
            summary: dict[str, object]
            raw = observed_backend.egress_log(handle) if isinstance(observed_backend, DockerBackend) else None
            if raw is None:
                summary = {"status": "unread", "reason": "the egress proxy log could not be read before teardown"}
            else:
                log_path = base / f"{attempt_id}.{eg.PROXY_LOG_STREAM}.jsonl"
                log_path.write_bytes(raw)
                digest = trial.sha256_bytes(raw)
                egress_imports.append(trial.Import(log_path, eg.PROXY_LOG_STREAM, "observed", digest))
                summary = {"status": "read", "digest": digest, **eg.summarize_log(raw)}
            observed = dict(observe_without_egress(observed_backend, handle))
            observed["egress"] = summary
            return observed

    def transcript_for_capture() -> trial.TranscriptEvidence:
        return stored_transcript.get("evidence") or trial.TranscriptEvidence(
            None, "the transcript observation hook did not complete; no transcript was read",
        )

    def imports_for_capture() -> list[trial.Import]:
        """#442's egress log, and (#500) every retained session of an attempt
        that left more than one transcript, each its own stream."""
        imports = list(egress_imports)
        if witness_session is not None and witness_session.project_gate is not None:
            # #508: the shim's pass-through log, its own SUBJECT-REPORTED
            # stream - never in the gate-witness record grading reads.
            raw = b"".join(json.dumps(e, sort_keys=True).encode() + b"\n" for e in witness_session.passthrough_log)
            path = base / f"{attempt_id}.{pg.PASSTHROUGH_STREAM}.jsonl"
            path.write_bytes(raw)
            imports.append(trial.Import(path, pg.PASSTHROUGH_STREAM, "client-reported", trial.sha256_bytes(raw)))
        for entry in transcript_sessions:
            evidence = entry.get("evidence")
            if isinstance(evidence, trial.TranscriptEvidence) and evidence.data is not None:
                stream = f"{records.CLIENT_TRANSCRIPT}-session-{entry['index']}"
                path = base / f"{attempt_id}.{stream}.jsonl"
                path.write_bytes(evidence.data)
                imports.append(trial.Import(path, stream, "client-reported", trial.sha256_bytes(evidence.data)))
        return imports

    stewarded = [h for h in (fixture_session, attempt_guard) if h is not None]

    def before_stop(stopping_backend: ExecutionBackend, handle: object) -> None:
        """#518: the steward reports `stopped` and its vault is read while the
        container still runs; `finish()`, after the stop, cannot reach it."""
        for holder in stewarded:
            if holder.steward_driver is not None:
                holder.steward_driver.stop(stopping_backend, handle)  # type: ignore[arg-type]

    record = run_through_backend(
        backend, experiment, attempt_id, argv, surface, limits, base,
        before_execute=before_execute, observe_before_teardown=observe_before_teardown, nonce=nonce,
        before_stop=before_stop if stewarded else None,
        transcript_for_capture=transcript_for_capture,
        imports_for_capture=imports_for_capture,
        next_turn=next_turn if declared_turns else None,
        order=attempt_order,
    )
    delivered = sum(1 for e in experiment.events(attempt_id)
                    if e.get("event") == "controller-turn" and e.get("delivered") is True)
    if attempt_guard is not None:
        attempt_guard.expected_top_level = ct.expected_top_level(delivered)
    if fixture_session is not None:
        # Each delivered turn is one more legitimate top-level launch (#279).
        fixture_session.expected_top_level = ct.expected_top_level(delivered)
        if attempt_order is not None:
            fixture_session.turn_records = [
                {k: e[k] for k in ("index", "dispatched", "ended", "exit_code", "delivered", "reason", "order")
                 if k in e}
                for e in experiment.events(attempt_id) if e.get("event") == "controller-turn"]

    # #434 (counter-model review, pass 2): the fixture's full evidence is
    # stored on EVERY path, before grading, so an attempt the credit gate
    # blocks keeps the decisions that blocked it. Grading's own envelope is
    # stored separately, and only when grading runs.
    fixture_evidence: str | None = None
    if fixture_session is not None:
        extras = _fixture_extras(fixture_session, stored_transcript)
        fixture_evidence = trial.put_object(experiment, trial.canonical(extras)) if extras is not None else None

    graded: dict[str, object] | None = None
    grading_blocked_reason: str | None = None
    #: Wall-clock of the grading call alone (issue #12's setup/agent/grading
    #: split); `None` when nothing was graded.
    grading_seconds: float | None = None
    observation = record.get("observation")
    if grader is not None:
        grading_blocked_reason = credit_block(
            observation, client=client, disposition=record.get("disposition"),
            witness_failure=(witness_session.failure or "controller witness was never finalized")
            if witness_session is not None and (witness_session.failure or witness_session.record is None) else None,
            fixture_block=(lambda: _fixture_credit_block(fixture_session, observation))
            if fixture_session is not None
            else (lambda: ag.credit_block(attempt_guard.report(observation, declared_model)))
            if attempt_guard is not None else None,
        )
        if grading_blocked_reason is None:
            assert isinstance(observation, dict)  # credit_block passes only an observed dict
            try:
                if grading_backend is None:
                    raise ValueError("grading_backend is required when grader is given - never the agent's own backend")
                if grading_backend is backend:
                    # Cross-model review: the ORIGINAL check only rejected `None`,
                    # so passing the SAME instance the agent already used for
                    # `backend` silently proceeded - interfaces.md's step 8 rule
                    # ("a SEPARATE backend instance") is a structural requirement,
                    # not merely a naming convention, and this is what actually
                    # enforces it rather than trusting a caller to have read the
                    # docstring.
                    raise ValueError(
                        "grading_backend must be a SEPARATE instance from the agent's own backend - "
                        "interfaces.md's step 8 rule, reusing the same instance risks carrying the "
                        "agent attempt's own state into the probe's isolation"
                    )
                grading_started = time.monotonic()
                # Through the verifier's result assembler, never `grade_files`
                # alone (#139): the grade used to live only in this returned
                # dict, so every captured attempt read as "grading is still
                # owed" to attempt-accounting.
                receipt = (
                    _build_discovery_receipt(
                        backend=backend, experiment=experiment, attempt_id=attempt_id,
                        client=client, client_version=resolved_cli_version,
                        client_argv=receipt_context.listing_client_argv or [client],
                        extra_home_files=extra_home_files or {}, limits=limits, base=base,
                        context=receipt_context,
                    ) if receipt_context is not None else None
                )
                if receipt is not None:
                    # A REAL installation receipt (#150-D, narrowing #139's
                    # B1): written through trial.add_receipt, which validates
                    # it against the schema and the bundle before it exists
                    # at all. `_grade_and_store`'s own DEFAULT
                    # readiness_source (records.INSTALLATION_RECEIPT, exactly
                    # what `verify.grade`'s public wrapper also uses) then
                    # reads it back via `verify._receipt`, whose cross-check
                    # (subject.digest, client, and #150-D's own image.digest
                    # addition) refuses it if it does not match this trial's
                    # own ledger pin. Called through the module directly,
                    # like `grade_agent_attempt` itself wraps the same
                    # function - `verify.grade`'s public form discards the
                    # `Graded` half this caller still needs to report.
                    trial.add_receipt(experiment, receipt)
                    stored, graded_result = verify._grade_and_store(
                        experiment, attempt_id, grader, base, backend=grading_backend,
                        gate_witness=witness_session.record if witness_session else None,
                        trusted_extras=_fixture_extras(fixture_session, stored_transcript),
                    )
                else:
                    # The observation stands in for the installation receipt
                    # this path did not write (no receipt_context, a Claude
                    # Code arm, or an empty extra_home_files - B1's stand-in,
                    # unchanged) - accounting only, readiness stays UNKNOWN.
                    stored, graded_result = verify.grade_agent_attempt(
                        experiment, attempt_id, grader, base, observation, backend=grading_backend,
                        gate_witness=witness_session.record if witness_session else None,
                        trusted_extras=_fixture_extras(fixture_session, stored_transcript),
                    )
            except Exception as exc:
                # The attempt ran and was observed; a grading failure (a
                # quarantined verifier, a frozen artifact that no longer
                # verifies, a missing or reused grading backend) must not take
                # its observation with it (codex review, both passes). Persist
                # it with the failure as the blocked reason, then let the
                # failure propagate exactly as before.
                failed = {
                    **record, "graded": None, "grading_seconds": None,
                    "grading_blocked_reason": f"grading raised {type(exc).__name__}: {exc}",
                }
                write_observation_record(
                    experiment, attempt_id, build_observation_record(failed, client=client, grader_supplied=True),
                )
                raise
            grading_seconds = time.monotonic() - grading_started
            # `status` is the TASK grade (the grader's own criteria); the stored
            # result's status adds the verifier's readiness criterion, which
            # is UNKNOWN on this path, and is carried beside it, never merged.
            graded = {
                "status": graded_result.status, "category": graded_result.category,
                "detail": graded_result.detail, "criteria": graded_result.criteria,
                "result_id": stored["result_id"], "result_status": stored["status"],
            }

    result: dict[str, object] = {
        **record, "graded": graded, "grading_blocked_reason": grading_blocked_reason,
        "grading_seconds": grading_seconds,
    }
    if retained_transcript:
        result["retained_transcript"] = retained_transcript
    if fixture_session is not None:
        result["fixture"] = {"case": fixture_session.fixture.case, "failure": fixture_session.failure,
                             "git_unreadable": fixture_session.git_unreadable,
                             "codex_guard": fixture_session.guard_record()["nested"],
                             "credential_steward": fixture_session.steward_record(),
                             "evidence_digest": fixture_evidence}
    if attempt_guard is not None:
        result["codex_guard"] = attempt_guard.report(observation, declared_model)
    if treatment_deviation:
        # #525 (orchestrator): a declared deviation is part of the attempt's own
        # record, never only a detail field; the report's head repeats it.
        result["treatment_deviation"] = [dict(d) for d in treatment_deviation]
    if declared_turns:
        result["controller_turns"] = {
            "declared": len(declared_turns), "delivered": delivered,
            "expected_top_level": ct.expected_top_level(delivered),
            "session_id_source": turn_state["session_id_source"],
            "session_id_found": turn_state["session_id_found"], "stopped": turn_state["stopped"],
            "header_refusal": turn_state.get("header_refusal"),
        }
    result["transcript_retention"] = transcript_retention(experiment, attempt_id, record.get("disposition"))
    # Persisted on EVERY path (#106): the observation used to exist only in
    # this returned dict, so a caller that printed it wrong - or not at all -
    # lost it for good.
    result["observation_record"] = write_observation_record(
        experiment, attempt_id,
        build_observation_record(result, client=client, grader_supplied=grader is not None),
    )
    return result
