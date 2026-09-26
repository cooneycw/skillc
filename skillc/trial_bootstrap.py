"""Per-trial live-agent bootstrap (#78, Refs #10): the parts of a Docker
trial that make a real agent actually start and do work inside the
container, independent of which `ExecutionBackend` (#10's seam,
`skillc/backend.py`) runs it.

Every item this module addresses was, at least once on a sibling platform, a
silent no-op that exited 0 and would have been graded (see issue #10's
"Operating lessons" comment, sections A and B, required reading before
changing anything here). For an evaluation harness a silent failure is worse
than a crash: it produces a verdict.

Scope, matching issue #78 exactly:

  - a private, empty, never-shared per-trial HOME/.claude/.codex
    (`build_trial_home`);
  - an onboarding seed that clears exactly the documented gates and never
    auto-answers anything else (`compose_claude_seed`,
    `validate_seed_before_launch`);
  - a per-trial MCP config declared explicitly, never inherited
    (`compose_mcp_config`);
  - prompt delivery verified after the fact against the transcript's first
    user message, never keystrokes (`verify_first_user_message`);
  - an invocation with a unique `--name`, never `--remote-control`, and
    `GIT_TERMINAL_PROMPT=0` (`build_invocation`);
  - a liveness canary that requires the transcript to show BOTH a skill
    invocation and a tool use, tagged with a per-attempt nonce
    (`compose_canary_instruction`, `check_canary`).

Deliberately NOT in this module: `skillc/docker_backend.py` (#77) itself, or
anything that imports it. #78's own instruction was to build the parts that
do not depend on #77's interface names; the pieces here are consumed BY a
backend's `install()`/`execute()`, never the other way around.

WHAT IS TESTABLE HERE VS OWED TO THE LIVE RUN (issue #78's own evidence
rule): every function below is exercised in `tests/test_trial_bootstrap.py`
against synthetic homes, seeds and transcripts. Whether a real Claude Code or
Codex process, started this way inside `docker/trial/Dockerfile`'s image,
actually starts un-wedged is owed to the live run - this module cannot prove
that from a dev machine with no running trial. Translating a specific
client's real on-disk transcript format into the normalized event shape
`verify_first_user_message` and `check_canary` read is likewise a thin
per-client adapter, not delivered here - the same kind of gap
`skillc/backend.py`'s docstring already states for `docker_backend.py`
itself ("skillc will ship its own Docker-backed implementation... it does
not exist at this commit").

Stdlib only (AGENTS.md): `json`, `re`, `secrets`, `dataclasses`, `pathlib`.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: docker/trial/pinned-versions.json is the single source of truth for the
#: trial image's CLI pins (docker/trial/check_pins.py proves the Dockerfile's
#: ARG defaults still match it). This default path assumes a source
#: checkout, not an installed wheel - `docker/` ships with the repository,
#: not with the `skillc` package - so it is a dev/build-time convenience,
#: never something a packaged install depends on at runtime. Callers that
#: need it from another layout pass `manifest_path` explicitly.
_DEFAULT_PINNED_VERSIONS_PATH = Path(__file__).resolve().parent.parent / "docker" / "trial" / "pinned-versions.json"


class PinnedVersionError(Exception):
    """The pinned CLI version manifest is missing, unreadable or incomplete."""


def pinned_cli_version(client: str, manifest_path: Path | None = None) -> str:
    """The exact pinned version for `client` ('claude_code' or 'codex').

    Refuses rather than guessing a version when the manifest is missing,
    malformed, or silent about `client` - an unpinned version defeats the
    point of pinning (issue #10 lesson D14: an auto-updater changing a CLI
    underneath a running session)."""
    path = manifest_path or _DEFAULT_PINNED_VERSIONS_PATH
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinnedVersionError(f"cannot read pinned CLI versions from {path}: {exc}") from exc
    entry = manifest.get(client)
    if not isinstance(entry, dict) or not entry.get("version"):
        raise PinnedVersionError(f"{path} has no pinned version recorded for client '{client}'")
    return str(entry["version"])


# --------------------------------------------------------------------------
# Sandbox decision (issue #10 lesson A3): recorded here because #77's
# ExecutionBackend.describe() is where it should be REPORTED, but #77 has not
# landed yet. Whoever lands #77 should surface this through describe()'s
# isolation/unobserved claims rather than re-deciding it.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxDecision:
    """A deliberate choice about a client's own internal sandboxing, distinct
    from the container's own isolation."""

    sandboxed: bool
    mechanism: str
    rationale: str


#: Codex is run unsandboxed inside the trial container. Bubblewrap needs
#: user namespaces, commonly unavailable or double-nested inside a container
#: runtime's own container (measured on a sibling platform: the same prompt
#: wrote its file under danger-full-access and wrote nothing under
#: workspace-write without bwrap - issue #10 lesson A3). The trial container
#: is already the isolation boundary (skillc/backend.py's neutral-identity
#: rule: a fixed unprivileged user, no host filesystem or credential in
#: reach), so a missing nested sandbox does not widen what the trial can
#: reach - it only removes a mechanism that silently swallows every shell
#: command when misconfigured. docker/trial/Dockerfile does not install
#: bubblewrap; this constant is the recorded reason.
BWRAP_DECISION = SandboxDecision(
    sandboxed=False,
    mechanism="none - codex exec --sandbox danger-full-access",
    rationale=(
        "The trial container is the isolation boundary; bubblewrap needs "
        "user namespaces that are commonly unavailable or double-nested "
        "inside a container runtime's own container, and a trial has no "
        "host filesystem or credential in reach to sandbox further "
        "against. See docker/trial/Dockerfile and issue #10 lesson A3."
    ),
)


# --------------------------------------------------------------------------
# Per-trial home
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialHome:
    """A fresh, private, empty home tree for exactly one trial attempt."""

    home: Path
    claude_home: Path
    codex_home: Path


class TrialHomeError(Exception):
    """A trial home could not be built as a fresh, private, empty tree."""


def build_trial_home(root: Path) -> TrialHome:
    """Create a `home` directory under `root`, and inside it `.claude` and
    `.codex`, all freshly created and empty.

    Refuses if any of the three already exists - a trial home is never
    reused and never shared across trials (the generalization of issue #10
    lesson B5: a shared or long-lived home is exactly what let a rotated
    credential go silently stale under every session sharing it). Never
    touches the operator's own `$HOME` or `$CODEX_HOME` - `root` must be a
    trial-scoped directory the caller allocated."""
    home = root / "home"
    claude_home = home / ".claude"
    codex_home = home / ".codex"
    for path in (home, claude_home, codex_home):
        if path.exists():
            raise TrialHomeError(f"{path} already exists - a trial home must be built fresh, never reused or shared")
    home.mkdir(parents=True)
    claude_home.mkdir()
    codex_home.mkdir()
    return TrialHome(home=home, claude_home=claude_home, codex_home=codex_home)


# --------------------------------------------------------------------------
# Onboarding seed (issue #10 lesson A1)
# --------------------------------------------------------------------------

#: The exact top-level keys this module's seed ever sets. Closed on purpose
#: (issue #78's own control: "a seed that auto-answers... produces a
#: refusal"): a key outside this set is something ELSE deciding a prompt on
#: the agent's behalf, which is refused rather than silently accepted -
#: matching this repo's closed-schema convention elsewhere (e.g. the Docker
#: backend's composed argv, #77's own scope).
ALLOWED_SEED_KEYS = frozenset({
    "hasCompletedOnboarding",
    "bypassPermissionsModeAccepted",
    "projects",
    "_skillc_seed_cli_version",
})

#: The exact keys allowed inside `projects.<workdir>`.
ALLOWED_SEED_PROJECT_KEYS = frozenset({
    "hasTrustDialogAccepted",
    "enabledMcpjsonServers",
})


class SeedError(Exception):
    """A composed or loaded onboarding seed is invalid, incomplete, or would
    auto-answer a prompt this module has not deliberately decided."""


def compose_claude_seed(
    workdir: PurePosixPath,
    mcp_server_names: Sequence[str],
    cli_version: str,
) -> dict[str, object]:
    """The per-trial `~/.claude.json` seed content.

    Clears exactly the four interactive gates issue #10 lesson A1 names:
    onboarding, trust for `workdir`, the declared MCP servers, and the
    bypass-permissions warning. Nothing else - a fresh home otherwise wedges
    on the first gate it hits, and the container looks healthy while nothing
    runs.

    `cli_version` pins the seed to the exact CLI build it was measured
    against - Claude Code rewrites this file on first start and has been
    observed to drop acceptance keys across versions, so an unpinned seed
    silently stops working under a CLI upgrade. Refused when empty."""
    if not workdir.is_absolute():
        raise SeedError(f"workdir must be absolute, got {workdir}")
    if not cli_version:
        raise SeedError("cli_version must be pinned, not empty - an unpinned seed cannot be trusted across a CLI upgrade")
    return {
        "hasCompletedOnboarding": True,
        "bypassPermissionsModeAccepted": True,
        "projects": {
            str(workdir): {
                "hasTrustDialogAccepted": True,
                "enabledMcpjsonServers": list(mcp_server_names),
            },
        },
        "_skillc_seed_cli_version": cli_version,
    }


def write_claude_seed(claude_home: Path, seed: Mapping[str, object]) -> Path:
    """Write `seed` to `<claude_home's parent>/.claude.json` - the CLI reads
    onboarding state from `$HOME`, not from `~/.claude/`. Takes `claude_home`
    (not the bare home) so callers can reuse the same `TrialHome` value used
    everywhere else without re-deriving the relationship."""
    seed_path = claude_home.parent / ".claude.json"
    seed_path.write_text(json.dumps(dict(seed), indent=2, sort_keys=True), encoding="utf-8")
    return seed_path


def validate_seed_before_launch(
    seed_path: Path, workdir: PurePosixPath, expected_cli_version: str
) -> dict[str, object]:
    """Refuse to launch rather than hang on a bad seed (issue #78's own
    control: "a seed that auto-answers, or a missing seed, produces a
    refusal rather than a hang").

    `expected_cli_version` is required, not optional: a Codex code-review
    finding on issue #78 caught an earlier version of this function that
    only checked `_skillc_seed_cli_version` was non-empty, so a seed
    measured against `1.0.0` would pass even when the CLI about to launch is
    the pinned `2.1.283` - exactly the silent-drift scenario this field
    exists to catch (Claude Code has been observed to drop acceptance keys
    across versions). The caller must supply the version it is actually
    about to launch; an empty string is refused the same as any mismatch.

    Raises `SeedError` - never returns silently - when: the file is missing;
    its JSON is invalid or not an object; it carries a key outside
    `ALLOWED_SEED_KEYS`/`ALLOWED_SEED_PROJECT_KEYS` (an undeclared key is
    something else deciding a prompt on the agent's behalf); the onboarding
    or bypass-permissions gates are not accepted; the seed's recorded CLI
    version does not exactly match `expected_cli_version`; or `projects`
    contains anything other than EXACTLY one entry, for `workdir`, complete
    and accepted. A per-trial seed has no legitimate reason to carry a
    second project - a Codex code-review finding on issue #78 caught an
    earlier version of this function that validated only the `workdir`
    entry and ignored any OTHER project a seed might carry, so undeclared
    acceptance settings for a different project could ride along unnoticed.
    Returns the parsed seed on success."""
    if not seed_path.is_file():
        raise SeedError(f"{seed_path} is missing - refusing to launch rather than hang on the trust-dialog prompt")
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedError(f"{seed_path} is not valid JSON: {exc}") from exc
    if not isinstance(seed, dict):
        raise SeedError(f"{seed_path} must contain a JSON object")

    unknown = set(seed) - ALLOWED_SEED_KEYS
    if unknown:
        raise SeedError(
            f"{seed_path} carries undeclared key(s) {sorted(unknown)} - "
            "a seed may only clear the gates this module deliberately decided"
        )
    if seed.get("hasCompletedOnboarding") is not True:
        raise SeedError(f"{seed_path} does not clear the onboarding gate")
    if seed.get("bypassPermissionsModeAccepted") is not True:
        raise SeedError(f"{seed_path} does not clear the bypass-permissions gate")
    if not expected_cli_version or seed.get("_skillc_seed_cli_version") != expected_cli_version:
        raise SeedError(
            f"{seed_path} is pinned to CLI version {seed.get('_skillc_seed_cli_version')!r}, "
            f"but the launch expects {expected_cli_version!r}"
        )

    projects = seed.get("projects")
    if not isinstance(projects, dict):
        raise SeedError(f"{seed_path} has no 'projects' entry")
    if set(projects) != {str(workdir)}:
        raise SeedError(
            f"{seed_path}'s 'projects' must contain EXACTLY the one entry for "
            f"{workdir}, found {sorted(projects)}"
        )
    entry = projects[str(workdir)]
    if not isinstance(entry, dict):
        raise SeedError(f"{seed_path} has no project entry for {workdir}")
    unknown_project_keys = set(entry) - ALLOWED_SEED_PROJECT_KEYS
    if unknown_project_keys:
        raise SeedError(
            f"{seed_path}'s project entry for {workdir} carries undeclared "
            f"key(s) {sorted(unknown_project_keys)}"
        )
    if entry.get("hasTrustDialogAccepted") is not True:
        raise SeedError(f"{seed_path} does not accept the trust dialog for {workdir}")
    if not isinstance(entry.get("enabledMcpjsonServers"), list):
        raise SeedError(f"{seed_path}'s project entry for {workdir} has no enabledMcpjsonServers list")
    return seed


# --------------------------------------------------------------------------
# Per-trial MCP config
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MCPServerSpec:
    """One declared MCP server for a trial. `env` is exactly what the server
    process receives - never the controller's or the operator's own
    environment (issue #10 lesson B7's allowlist principle, applied to MCP
    the same way `skillc/materialize.py` already applies it to a client's
    `PATH`/`HOME`/`LANG`)."""

    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)


def compose_mcp_config(servers: Mapping[str, MCPServerSpec]) -> dict[str, object]:
    """A per-trial MCP config built from `servers` alone - never read from,
    or merged with, the operator's own global MCP config. A pure function:
    the same `servers` mapping always produces the same config, so a caller
    cannot accidentally inherit ambient state by forgetting to pass
    something explicit."""
    return {
        "mcpServers": {
            name: {"command": spec.command, "args": list(spec.args), "env": dict(spec.env)}
            for name, spec in servers.items()
        }
    }


def write_mcp_config(path: Path, config: Mapping[str, object]) -> Path:
    """Write `config` to `path`. Deliberately takes an explicit path rather
    than a fixed filename: which file a given client CLI actually consumes
    (a project-local `.mcp.json`, a `--mcp-config` flag, or a key inside the
    onboarding seed) is client-specific wiring owed to the live run, exactly
    like `verify_first_user_message`'s transcript-shape caveat below - this
    function only composes and writes the CONTENT."""
    path.write_text(json.dumps(dict(config), indent=2, sort_keys=True), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Invocation: unique --name, never --remote-control, GIT_TERMINAL_PROMPT=0
# --------------------------------------------------------------------------


class InvocationError(Exception):
    """A composed invocation would violate issue #78's own launch rules."""


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    env: Mapping[str, str]


def build_invocation(
    attempt_id: str,
    base_argv: Sequence[str],
    *,
    supports_name: bool,
    extra_env: Mapping[str, str] | None = None,
) -> Invocation:
    """Compose the argv/env for one trial's agent process.

    `supports_name` is required, not defaulted, because `--name` is real for
    ONE pinned client, not both: Claude Code's own binary documents `--name
    <name>` ("Name for the session (shown in claude.ai/code)"), confirmed by
    extracting the pinned 2.1.283 tarball, while the pinned Codex release's
    `exec` subcommand parser accepts no such flag (confirmed against its
    source, `codex-rs/exec/src/cli.rs` and `shared_options.rs` at
    `rust-v0.157.1`) - a Codex code-review finding on issue #78 caught an
    earlier version of this function appending `--name` unconditionally,
    which would have made every Codex invocation fail argument parsing
    before the trial even started. When `supports_name` is False, attempt
    identity still lives in the container name #77's backend derives from
    `attempt_id` - this function adds nothing extra for such a client.

    When `supports_name` is True, appends a unique `--name` derived from
    `attempt_id` alone (the same neutral-identity rule `skillc/backend.py`
    already states for a container name: never host-identifying). Refuses
    `base_argv` containing `--remote-control` regardless of client - a
    disposable trial must never be left attachable. Sets
    `GIT_TERMINAL_PROMPT=0` so a `git` credential prompt cannot hang the
    trial exactly like the onboarding gates in issue #10 lesson A1, and
    refuses an `extra_env` that tries to override it away from `'0'` rather
    than silently letting the override win - a caller passing a conflicting
    value made a mistake that should surface, not vanish."""
    if not attempt_id:
        raise InvocationError("attempt_id must be non-empty - a --name derived from nothing is not unique")
    if "--remote-control" in base_argv:
        raise InvocationError("--remote-control must never be passed to a trial invocation - it would leave the session attachable")
    if extra_env and extra_env.get("GIT_TERMINAL_PROMPT", "0") != "0":
        raise InvocationError("GIT_TERMINAL_PROMPT must not be overridden away from '0' - a git credential prompt would hang the trial exactly like the onboarding gates it exists to prevent")
    if supports_name:
        argv = (*base_argv, "--name", f"skillc-trial-{attempt_id}")
    else:
        argv = tuple(base_argv)
    env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
    if extra_env:
        env.update(extra_env)
    return Invocation(argv=argv, env=env)


# --------------------------------------------------------------------------
# Prompt delivery, verified against the transcript
# --------------------------------------------------------------------------


class PromptDeliveryError(Exception):
    """The transcript does not confirm the prompt was delivered as sent."""


def verify_first_user_message(
    transcript_events: Sequence[Mapping[str, object]],
    expected_prompt: str,
) -> None:
    """Refuse when the transcript's first user-role message does not match
    the prompt actually sent (issue #78's own control).

    This is what makes "delivered by argv or stdin, never keystrokes"
    verifiable after the fact: a prompt typed interactively, retried, or
    silently altered by a wrapper shows up here as a mismatch, not as a
    passing trial.

    `transcript_events` is skillc's own normalized shape - each event at
    least `{"role": ..., "content": ...}` for a message. Translating a
    specific client's real on-disk transcript into this shape is a thin
    per-client adapter, owed to the live run - the same kind of gap
    `skillc/backend.py`'s docstring already states for `docker_backend.py`
    itself."""
    for event in transcript_events:
        if event.get("role") == "user":
            content = event.get("content")
            if content != expected_prompt:
                raise PromptDeliveryError(
                    f"transcript's first user message does not match the prompt sent: "
                    f"expected {expected_prompt!r}, got {content!r}"
                )
            return
    raise PromptDeliveryError("transcript has no user message at all - the prompt was never observed as delivered")


# --------------------------------------------------------------------------
# Liveness canary: skill invocation AND a tool, tagged with a per-attempt nonce
# --------------------------------------------------------------------------

#: Distinct from `skillc/lifecycle.py`'s `CANARY_NONCE_KEY`: that one is a
#: BACKEND-planted, content-diff canary with no transcript involved at all.
#: This one is an AGENT-observed canary - it proves the agent itself invoked
#: a real skill and a real tool, which a backend-side content diff cannot
#: distinguish from the agent's own unrelated file writes.
AGENT_CANARY_NONCE_KEY = "_skillc_agent_liveness_nonce"


class CanaryNotSatisfied(Exception):
    """The transcript does not show the skill+tool canary being touched.

    Issue #78's own controls: a fake client that exits 0 having done
    nothing, and one that answers in prose without touching the skill, are
    both refused here as not-live, never captured as success."""


def new_canary_nonce() -> str:
    """A fresh per-attempt nonce. Never reused across attempts - a canary
    satisfied once proves nothing about a different attempt."""
    return secrets.token_hex(16)


def compose_canary_instruction(skill_name: str, nonce: str) -> str:
    """A prompt fragment appended to the trial's real goal, instructing the
    agent to invoke `skill_name` and then use a tool to prove it, tagged
    with `nonce`."""
    return (
        f"Before doing anything else, invoke the '{skill_name}' skill, then "
        f"use a tool to write the exact text 'touched:{nonce}' to a file "
        f"named 'skillc-canary-{nonce}.txt' in the working directory."
    )


def check_canary(
    transcript_events: Sequence[Mapping[str, object]],
    skill_name: str,
    nonce: str,
) -> None:
    """Raise `CanaryNotSatisfied` unless the transcript shows BOTH a skill
    invocation naming `skill_name` and a tool-use event whose CONFIRMED
    OUTPUT carries `nonce` (issue #78: "a canary that invokes the skill and
    a tool").

    Checks the event's `output` specifically, and requires no `error` - never
    its `input`/request. A Codex code-review finding on issue #78 caught an
    earlier version of this function searching the whole serialized event,
    which a REQUESTED-but-denied-or-failed tool call satisfies just as well
    as a completed one: the nonce a caller asks a tool to write is present in
    the *request* whether or not the tool ever ran. Matching only a
    successful, error-free `output` is what makes this an OBSERVED liveness
    proof rather than a restated intention.

    Deliberately two independent existence checks rather than requiring one
    event to satisfy both: a client may model "invoke a skill" and "use a
    tool" as separate transcript events, and requiring them to be the SAME
    event would make this brittle to a client whose skill invocation is not
    itself a tool call.

    Normalized event shapes this checks for (a per-client adapter's job to
    produce - see `verify_first_user_message`'s caveat, which applies here
    identically):
      - a skill invocation: `{"type": "skill_invocation", "skill": <name>}`
      - a tool use: `{"type": "tool_use", "output": ..., "error": ...}`, with
        `nonce` appearing in `output` once JSON-serialized, and `error`
        absent or falsy.
    """
    skill_invoked = any(
        event.get("type") == "skill_invocation" and event.get("skill") == skill_name
        for event in transcript_events
    )
    if not skill_invoked:
        raise CanaryNotSatisfied(f"no skill_invocation event for '{skill_name}' in the transcript - not live")

    nonce_marker = f"touched:{nonce}"
    tool_touched = any(
        event.get("type") == "tool_use"
        and not event.get("error")
        and nonce_marker in _stringify(event.get("output"))
        for event in transcript_events
    )
    if not tool_touched:
        raise CanaryNotSatisfied(
            f"no tool_use event's confirmed, error-free output carries the canary "
            f"marker {nonce_marker!r} - the agent answered, or the tool call "
            "failed, without a confirmed touch of the canary"
        )


def _stringify(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)
