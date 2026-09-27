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
itself refuses to call `verify.grade_files` unless the observation shows
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

import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import credential, demo, records, trial, trial_bootstrap, verify
from . import transcript_adapter as ta
from .backend import ExecutionBackend, Limits
from .docker_backend import CANARY_RESULT_FILENAME, DockerBackend
from .lifecycle import run_through_backend
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
CODEX_KNOWN_RESPONSE_ITEM_TYPES = frozenset({"message", "custom_tool_call", "custom_tool_call_output", "reasoning"})


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


def _make_before_execute(
    *, spec: ClientSpec, ctx: _AttemptContext, credential_explicit_path: str | Path | None,
    minimum_credential_seconds: float, delivered_credential_bytes: dict[str, bytes],
    extra_home_files: Mapping[str, bytes],
) -> Callable[[ExecutionBackend, object], None]:
    """`delivered_credential_bytes` is an OUT-parameter (a single-entry dict
    the caller reads afterward) - `observe_before_teardown` needs these
    exact bytes later to compute `refresh_observed`, and a hook's own return
    value has nowhere else to go (`before_execute`'s contract returns
    nothing - see `lifecycle.py`'s own docstring)."""

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
            backend.deliver_home_file(handle, relpath, data)

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


def _make_observe_before_teardown(
    *, spec: ClientSpec, expected_prompt: str, skill_name: str | None,
    delivered_credential_bytes: dict[str, bytes],
) -> Callable[[ExecutionBackend, object], Mapping[str, object]]:
    def hook(backend: ExecutionBackend, handle: object) -> dict[str, object]:
        assert isinstance(backend, DockerBackend)

        refresh_observed: bool | None = None
        cred_relpath_bytes = delivered_credential_bytes.get("relpath")
        cred_bytes = delivered_credential_bytes.get("bytes")
        if isinstance(cred_relpath_bytes, bytes) and isinstance(cred_bytes, bytes):
            current = backend.read_home_file(handle, cred_relpath_bytes.decode("utf-8"))
            refresh_observed = credential.refresh_observed(cred_bytes, current)

        tree = backend.read_home_tree(handle, spec.transcript_container_reldir)
        matches = {path: data for path, data in tree.items() if path.endswith(spec.transcript_suffix)}

        run_metadata: dict[str, object] | None = None
        census: dict[str, object] = {
            "transcript_client_version": None, "transcript_model": None,
            "transcript_response_items_inspected": None,
            "transcript_line_types": None, "transcript_unrecognized_types": None,
        }
        observation = TranscriptObservation(
            files_found=len(matches), prompt_delivered=False, prompt_delivery_reason=None,
            canary_satisfied=False, canary_reason=None,
            skill_invocation_detection=spec.skill_invocation_detection,
        )
        if len(matches) != 1:
            observation = TranscriptObservation(
                files_found=len(matches), prompt_delivered=False,
                prompt_delivery_reason=f"expected exactly one transcript file, found {len(matches)}",
                canary_satisfied=False,
                canary_reason=f"expected exactly one transcript file, found {len(matches)}",
                skill_invocation_detection=spec.skill_invocation_detection,
            )
        else:
            (_, raw), = matches.items()
            text = raw.decode("utf-8", errors="replace")
            try:
                census = transcript_census(spec.name, text)
            except Exception as exc:  # noqa: BLE001 - the census is context; it must never erase the observation
                census = {**census, "transcript_census_error": f"{type(exc).__name__}: {exc}"}
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
            invocations = tuple(
                str(event["skill"]) for event in events
                if event.get("type") == "skill_invocation" and "skill" in event
            )
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
    """Beside `trial._lifecycle_name(attempt_id)` in the experiment root."""
    return f"observation-{attempt_id}.json"


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
        (experiment.root / observation_record_name(attempt_id)).write_text(text + "\n", encoding="utf-8")
    except OSError:
        return "write-failed"
    return "written"


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
) -> dict[str, object]:
    """Drive one real-agent attempt end to end and, only when the real
    transcript confirms both prompt delivery and the liveness canary, grade
    the exported output through `grader` (a SEPARATE backend instance,
    interfaces.md's own step-8 rule - never `backend`, which the agent's own
    attempt already used).

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
    composes, so every existing caller is unaffected."""
    if client not in CLIENT_SPECS:
        raise credential.CredentialRefused(f"unknown client {client!r}: expected one of {sorted(CLIENT_SPECS)}")
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

    ctx = _AttemptContext(workdir=resolved_workdir, mcp_servers=resolved_mcp_servers, cli_version=resolved_cli_version)
    delivered_credential_bytes: dict[str, bytes] = {}
    before_execute = _make_before_execute(
        spec=spec, ctx=ctx, credential_explicit_path=credential_explicit_path,
        minimum_credential_seconds=minimum_credential_seconds,
        delivered_credential_bytes=delivered_credential_bytes,
        extra_home_files=extra_home_files or {},
    )
    observe_before_teardown = _make_observe_before_teardown(
        spec=spec, expected_prompt=full_prompt, skill_name=skill_name,
        delivered_credential_bytes=delivered_credential_bytes,
    )

    record = run_through_backend(
        backend, experiment, attempt_id, argv, surface, limits, base,
        before_execute=before_execute, observe_before_teardown=observe_before_teardown, nonce=nonce,
    )

    graded: dict[str, object] | None = None
    grading_blocked_reason: str | None = None
    #: Wall-clock of the grading call alone (issue #12's setup/agent/grading
    #: split); `None` when nothing was graded.
    grading_seconds: float | None = None
    observation = record.get("observation")
    if grader is not None:
        if record.get("disposition") != "captured":
            grading_blocked_reason = f"attempt disposition is {record.get('disposition')!r}, not captured"
        elif not isinstance(observation, dict) or observation.get("status") == "unknown":
            grading_blocked_reason = "the transcript observation is unknown - never graded on an unconfirmed attempt"
        elif not observation.get("grading_eligible"):
            grading_blocked_reason = (
                f"prompt_delivered={observation.get('prompt_delivered')!r}, "
                f"canary_satisfied={observation.get('canary_satisfied')!r} - "
                "never graded without both confirmed against the real transcript"
            )
        else:
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
                files = _frozen_candidate_files(experiment, attempt_id)
                grading_started = time.monotonic()
                graded_result = verify.grade_files(grader, files, base, backend=grading_backend)
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
            graded = {
                "status": graded_result.status, "category": graded_result.category,
                "detail": graded_result.detail, "criteria": graded_result.criteria,
            }

    result: dict[str, object] = {
        **record, "graded": graded, "grading_blocked_reason": grading_blocked_reason,
        "grading_seconds": grading_seconds,
    }
    # Persisted on EVERY path (#106): the observation used to exist only in
    # this returned dict, so a caller that printed it wrong - or not at all -
    # lost it for good.
    result["observation_record"] = write_observation_record(
        experiment, attempt_id,
        build_observation_record(result, client=client, grader_supplied=grader is not None),
    )
    return result
