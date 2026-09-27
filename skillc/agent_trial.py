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

OWED TO THE OPERATOR'S LIVE RUN, stated plainly rather than assumed: the
exact real argv that launches a real client (this module takes `base_argv`
and `prompt` as caller-supplied parameters, deliberately never inventing
its own - the same layering `run_through_backend` itself already uses for
`argv`); whether a real login still works on the operator's host after a
trial; and the real transcript format drift either CLI might introduce
between the pinned version this was built against and a later one.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import credential, trial, trial_bootstrap, verify
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
    #: Client-specific extra home files beyond the credential - the
    #: onboarding seed dance for Claude Code (#78); nothing at all for Codex,
    #: whose `exec` subcommand needed no seed in every live probe run for
    #: #106/#107 (confirmed empirically, 2026-09-27, not assumed).
    compose_home_files: Callable[[_AttemptContext], dict[str, bytes]]


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


CLIENT_SPECS: dict[str, ClientSpec] = {
    "claude": ClientSpec(
        name="claude",
        pinned_version_key="claude_code",
        transcript_container_reldir=".claude/projects",
        transcript_suffix=".jsonl",
        parse_transcript=ta.parse_claude_code_transcript,
        supports_name_flag=True,
        compose_home_files=_claude_home_files,
    ),
    "codex": ClientSpec(
        name="codex",
        pinned_version_key="codex",
        transcript_container_reldir=".codex/sessions",
        transcript_suffix=".jsonl",
        parse_transcript=ta.parse_codex_transcript,
        supports_name_flag=False,
        compose_home_files=_codex_home_files,
    ),
}


def _make_before_execute(
    *, spec: ClientSpec, ctx: _AttemptContext, credential_explicit_path: str | Path | None,
    minimum_credential_seconds: float, delivered_credential_bytes: dict[str, bytes],
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
        credential.check_remaining_life_or_refuse(spec.name, cred_bytes, minimum_seconds=minimum_credential_seconds)
        credential_relpath = credential.CLIENT_SPECS[spec.name].container_relpath
        backend.deliver_home_file(handle, credential_relpath, cred_bytes)
        delivered_credential_bytes["bytes"] = cred_bytes
        delivered_credential_bytes["relpath"] = credential_relpath.encode("utf-8")  # type: ignore[assignment]

        for relpath, data in spec.compose_home_files(ctx).items():
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

    def to_fields(self) -> dict[str, object]:
        return {
            "transcript_files_found": self.files_found,
            "prompt_delivered": self.prompt_delivered,
            "prompt_delivery_reason": self.prompt_delivery_reason,
            "canary_satisfied": self.canary_satisfied,
            "canary_reason": self.canary_reason,
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
    *, spec: ClientSpec, expected_prompt: str, skill_name: str,
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

        observation = TranscriptObservation(
            files_found=len(matches), prompt_delivered=False, prompt_delivery_reason=None,
            canary_satisfied=False, canary_reason=None,
        )
        if len(matches) != 1:
            observation = TranscriptObservation(
                files_found=len(matches), prompt_delivered=False,
                prompt_delivery_reason=f"expected exactly one transcript file, found {len(matches)}",
                canary_satisfied=False,
                canary_reason=f"expected exactly one transcript file, found {len(matches)}",
            )
        else:
            (_, raw), = matches.items()
            events = spec.parse_transcript(raw.decode("utf-8", errors="replace"))
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
            observation = TranscriptObservation(
                files_found=1, prompt_delivered=prompt_delivered, prompt_delivery_reason=prompt_reason,
                canary_satisfied=canary_satisfied, canary_reason=canary_reason,
            )

        usage = credential.CredentialUsage(
            client=spec.name, delivered=cred_bytes is not None, refresh_observed_in_container=refresh_observed,
        )
        return {**observation.to_fields(), **usage.to_record_fields()}

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


def run_one_attempt(
    *,
    backend: DockerBackend,
    experiment: trial.Experiment,
    attempt_id: str,
    client: str,
    base_argv: Sequence[str],
    prompt: str,
    skill_name: str,
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
) -> dict[str, object]:
    """Drive one real-agent attempt end to end and, only when the real
    transcript confirms both prompt delivery and the liveness canary, grade
    the exported output through `grader` (a SEPARATE backend instance,
    interfaces.md's own step-8 rule - never `backend`, which the agent's own
    attempt already used).

    `client` must name one of `CLIENT_SPECS`. `cli_version`, when omitted,
    is read from `docker/trial/pinned-versions.json` via
    `trial_bootstrap.pinned_cli_version` - never guessed.
    """
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
            graded_result = verify.grade_files(grader, files, base, backend=grading_backend)
            graded = {
                "status": graded_result.status, "category": graded_result.category,
                "detail": graded_result.detail, "criteria": graded_result.criteria,
            }

    return {**record, "graded": graded, "grading_blocked_reason": grading_blocked_reason}
