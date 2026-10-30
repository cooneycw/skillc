"""Run an approved calibration declaration (issue #207, for #204; three arms, #231).

`skillc.calibration` validates a `calibration-declaration` and refuses to
authorize an unapproved one; this module is what then EXECUTES it. Before
#207 nothing could: `collection-run` runs one attempt, has no baseline arm
and does not pin the model, and `pilot-run` reads only the Level 1 matched
pilot's own declaration. Hand-running the schedule would take the arm order,
the caps and the model pin from a person instead of from the declaration -
the drift #141 fixed for the pilot.

AUTHORIZATION FIRST. `run_calibration` calls `calibration.require_approved`
before it opens a store, plans a trial or builds a backend: an unapproved
declaration leaves nothing behind that could read as a started run (ADR 0005).

THE DECLARED ORDER, THROUGH THE REAL CONTROLLER. One trial per attempt,
planned by `trial.plan` in exactly `arm_order.sequence` - the seeded order
`calibration.parse_declaration` already proved was derived, not chosen. Each
trial is labelled `calibration_<arm>_<k>` (the arm's k-th attempt), so the
schedule is recoverable from the ledger alone (`schedule_from_ledger`).

ONE ATTEMPT PATH FOR EVERY ARM. Every attempt goes through
`collection_conformance.run_level1_agent_attempt` with the declared task as
`task_root` - the same client, prompt (`goal.md`), starting state and grader.
The arms differ ONLY in what is installed: a treated arm gets the subject's
selected skill files and the #150-D `InstallationReceiptContext`, the
baseline gets `{}` and none. A provided-skill arm (#231, P in #203's B/N/P)
installs the same subject as the natural arm and differs from it by one
thing: its declared `instruction` is appended to `goal.md`. The starting state is `task_surface` (the whole
fixture but its answer key), because a Level 3 fixture has no `src/`.

THE MODEL IS PINNED AT LAUNCH AND CHECKED AFTER, through
`matched_pilot.pin_model_argv` - the pilot's own refusal of a caller argv that
chooses the model, never a second copy. An attempt whose rollout reports
another model, or none, is `model_eligible: False` (`matched_pilot.
model_eligibility`), and the CLI fails the run on it.

CAPS AND RECONCILIATION are `matched_pilot.run_schedule` and
`matched_pilot.reconcile`: an attempt with no total cap left is finalized
`not-run`, a crashed one `inconclusive`, and every planned attempt yields
exactly one outcome.

THE ENDPOINT IS SYMMETRIC. Each attempt reports `calibration.
primary_endpoint` (the task grader's criteria, never `installation-ready`)
and, beside it, `calibration.readiness_beside` read from the attempt's stored
`verified-result`. The verified status is never the endpoint.

RETENTION. Everything stays in a private run directory outside any work tree
(`trial.open_store` refuses one inside a work tree): the store with each
attempt's leak-checked transcript (#202, retained by `agent_trial.
run_one_attempt` itself), `outcomes.json` and the report. Nothing is exported
for committing here; publishing the run's evidence belongs to the calibration
report (#204), which needs its own record kind.

A FIXTURE TASK (#640). A task with `builder/build.py` (a fixture-service
task, #434) is dispatched with its fixture in EVERY arm. The declaration names
`task.fixture: "builder"` (so the builder's bytes are the approved fixture
identity) and `task.fixture_case`. The case is built ONCE by the controller,
its digest bound into every planned trial, and each attempt gets its own fresh
copy, digest-checked before dispatch. The treated arm runs the treatment's
gate on the fixture route; the baseline runs agent_trial's DECLARED baseline
route (`fixture_baseline`), whose record says the gate was not offered. A
fixture that does not build, or a copy that differs, is a non-start. Every
attempt is classed in `accounting` (success, task failure, timeout,
infrastructure failure, non-start, unknown).

Nothing here names or branches on a particular subject: the subject, task,
client and model all come from the declaration.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import agent_trial, calibration, completion, demo, egress, gate_state, profile, trial, verify
from . import attempt_guard as ag
from . import collection_conformance as cc
from . import fixture_attempt as fa
from . import matched_pilot as mp
from . import materialize as m
from .spec import FrontmatterError

ROOT = mp.ROOT
EXPERIMENT_LABEL = "calibration"
TRIAL_PREFIX = "calibration"
OUTCOMES_FILENAME = mp.OUTCOMES_FILENAME
REPORT_FILENAME = "calibration-report.json"
REPORT_KIND = "calibration-run-report"
DISCRIMINATION_REPORT_KIND = "discrimination-run-report"
UNKNOWN = calibration.UNKNOWN

#: Private by default: outside any work tree, never exported.
DEFAULT_PRIVATE_ROOT = Path.home() / ".local" / "share" / "skillc" / "calibration-runs"

_TRIAL_ID_RE = re.compile(rf"^t\d+-{TRIAL_PREFIX}_(?P<arm>.+)_(?P<k>\d+)$")
_RESULT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CalibrationRefused(ValueError):
    """The declaration cannot be run as written, or a run's own record
    disagrees with it."""


@dataclass(frozen=True)
class Treatment:
    """What the non-baseline arm installs, acquired once for the whole run:
    the subject's selected skill files, their content digest (the plan's
    `subject.digest`), and the #150-D receipt context - one discovery cache
    shared by every treatment attempt.

    `verify_home_files`/`preflight_tools` (#334) are empty unless a
    profile was opted in: the closure files' expected digests, re-checked
    IN the live container after delivery (never trusting delivery alone),
    and the profile's own `tool`-kind dependencies, checked present in
    that same container at their declared constraint. `gate_entrypoint`
    is `None` unless the opted-in profile declares one -
    the SUBJECT's own fact about which installed path is its gate
    command, never inferred from `verify_home_files`' own membership."""

    home_files: Mapping[str, bytes]
    digest: str
    receipt_context: agent_trial.InstallationReceiptContext | None
    verify_home_files: Mapping[str, str] = field(default_factory=dict)
    preflight_tools: tuple[dict[str, object], ...] = ()
    gate_entrypoint: str | None = None
    #: #287 auto6: the profile's declared `gate_witness` kind (`None` = the
    #: default flow-check witness), carried straight through like
    #: `gate_entrypoint`.
    gate_witness: str | None = None
    #: #525: the profile's declared skill-bundled gate copies, witnessed beside
    #: `gate_entrypoint`. Empty for every profile that declares none.
    bundled_gate_entrypoints: tuple[str, ...] = ()
    #: #525: the subject's checksum-manifest name the bundled mirrors are proven against.
    bundled_checksum_manifest: str | None = None
    #: #529: the profile's declared checkout gate copies (path -> skill).
    checkout_gate_entrypoints: Mapping[str, str] = field(default_factory=dict)
    #: #424: a `trial.skill_digests` value - each installed skill's own
    #: `SKILL.md` destination with the `body_digest`/`description_digest` of the
    #: bytes this treatment INSTALLS. Empty only for a hand-built treatment; the
    #: planners refuse a treated arm that carries none.
    skill_digests: tuple[dict[str, str], ...] = ()
    #: #505: each `home_files` destination's SOURCE git mode (`100644` or
    #: `100755`), so an installed helper arrives executable when its source is.
    #: Empty only for a hand-built treatment, which keeps the 0600 delivery.
    home_modes: Mapping[str, str] = field(default_factory=dict)
    gate_state_protocol: gate_state.Protocol | None = None


@dataclass(frozen=True)
class _ClosureResult:
    home_files: dict[str, bytes]
    #: The inventory's own `kind == "tool"` dependency records - #334's
    #: in-container preflight reads these directly (each already carries
    #: its own `probes`, serialized by `profile._dep_record`).
    tools: tuple[dict[str, object], ...]
    #: The profile's own declared `gate_entrypoint`, or
    #: `None` if it declares none - carried straight through, never
    #: re-derived from `home_files`' own keys.
    gate_entrypoint: str | None
    #: #287 auto6: the inventory's declared `gate_witness`, absent = `None`.
    gate_witness: str | None = None
    #: #525: the inventory's declared `bundled_gate_entrypoints`, absent = ().
    bundled_gate_entrypoints: tuple[str, ...] = ()
    #: #525: the inventory's declared `checksum_consumers` (path -> reason).
    checksum_consumers: Mapping[str, str] = field(default_factory=dict)
    #: #525: the subject's checksum-manifest name, with a bundled gate only.
    bundled_checksum_manifest: str | None = None
    #: #529: the inventory's declared `checkout_gate_entrypoints`, absent = {}.
    checkout_gate_entrypoints: Mapping[str, str] = field(default_factory=dict)
    #: `profile.skill_digest_pins(inventory)` of the validated inventory (#424),
    #: cross-checked against the pins derived from the installed bytes.
    skill_pins: tuple[dict[str, str], ...] = ()
    #: #505: `profile.installed_home_modes` of the same verified records.
    home_modes: dict[str, str] = field(default_factory=dict)
    gate_state_protocol: gate_state.Protocol | None = None


def _installed_skill_pins(
    acquired: cc.AcquiredCollection, home_files: Mapping[str, bytes],
) -> tuple[dict[str, str], ...]:
    """#424: one pin per selected skill, from the `SKILL.md` bytes this
    treatment installs, at the destination it installs them to - the entry
    point only (`rel == "SKILL.md"`), never a nested file of the same name.

    Hashed from the CAPTURED `home_files` bytes - the ones actually delivered -
    never a second read of the source (counter-model review: a file changed
    between the two reads would pin bytes nobody installed)."""
    pins = []
    for f in acquired.files:
        if f.rel != "SKILL.md":
            continue
        try:
            description_digest, body_digest = profile.skill_md_digests(home_files[f.container_relpath])
        except FrontmatterError as exc:
            raise CalibrationRefused(f"{f.container_relpath}: {exc}") from exc
        pins.append({"path": f.container_relpath, "body_digest": body_digest,
                     "description_digest": description_digest})
    return tuple(sorted(pins, key=lambda pin: pin["path"]))


def _closure_home_files(acquired: cc.AcquiredCollection, subject_profile: str, root: Path) -> _ClosureResult:
    """skillc#334: the validated profile's dependency closure, built from
    the SAME checkout the skills came from (`acquired.repo`), not a
    second acquisition - see `AcquiredCollection.repo`'s own docstring.

    Three refusals, all before any container exists:
    1. `verify_repo_matches_skills` (required mode - a live attempt must
       always be able to prove its checkout's identity).
    2. The LIVE inventory (re-`validate()`d against `acquired.repo` at
       the subject's own declared pin) must digest-match the COMMITTED
       `evidence/inventory.json` at `subject_profile` - the profile is
       stale against the current subject source otherwise, and `#334`'s
       whole point is to install the closure that was actually validated,
       never one assumed still accurate.
    3. The closure's own destinations must not collide with the skill
       surface's - the two delivery paths share one container home.
    """
    cc.verify_repo_matches_skills(acquired, revision_check="required")
    if acquired.repo is None:
        raise CalibrationRefused("subject.profile is named but no full checkout was acquired")
    prof = profile.Profile.load(root / subject_profile / "profile.json")
    tree = profile.GitTree(acquired.repo, acquired.subject.revision)
    inventory = profile.validate(prof, tree)
    inventory_path = root / subject_profile / "evidence" / "inventory.json"
    try:
        committed = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CalibrationRefused(f"subject.profile {subject_profile!r} names no readable "
                                 f"evidence/inventory.json: {exc}") from exc
    live_digest, committed_digest = profile.inventory_digest(inventory), profile.inventory_digest(committed)
    if live_digest != committed_digest:
        raise CalibrationRefused(
            f"profile {subject_profile!r}'s live inventory (validated against the acquired checkout at "
            f"{acquired.subject.revision}) digests to {live_digest!r}, not the committed "
            f"{committed_digest!r} at {inventory_path} - the profile is stale against the current "
            f"subject source and must be re-declared before this closure can be installed"
        )
    home_files = profile.installed_home_files(inventory, tree)
    tools = tuple(dep for dep in inventory["dependencies"] if dep["kind"] == "tool")
    gate_entrypoint = inventory.get("gate_entrypoint")
    assert gate_entrypoint is None or isinstance(gate_entrypoint, str)
    # The earliest possible refusal point, before any container exists:
    # `profile.validate()` already proved the entrypoint
    # is installed by SOME closure at declaration time, but THIS run's
    # own installed_home_files() - built from the live, re-validated
    # inventory above - is the actual population this attempt would
    # deliver. The two can only disagree if something between validation
    # and here dropped the file, which must never pass silently.
    if gate_entrypoint is not None and gate_entrypoint not in home_files:
        raise CalibrationRefused(
            f"profile {subject_profile!r} declares gate_entrypoint {gate_entrypoint!r}, but this "
            f"closure's own installed_home_files does not carry it - witnessing is required "
            f"whenever a gate_entrypoint is declared, and cannot be honoured for a file that was "
            f"never actually produced"
        )
    try:
        skill_pins = tuple(sorted(profile.skill_digest_pins(inventory), key=lambda pin: pin["path"]))
    except profile.Refused as exc:
        raise CalibrationRefused(f"profile {subject_profile!r}: {exc}") from exc
    gate_witness = inventory.get("gate_witness")
    assert gate_witness is None or isinstance(gate_witness, str)
    # Whether each declared bundled copy is DELIVERED is decided at assembly,
    # over the whole home (a neighbour skill's copy is outside this closure).
    bundled = tuple(str(p) for p in inventory.get("bundled_gate_entrypoints", ()))
    consumers = {str(c["path"]): str(c["reason"]) for c in inventory.get("checksum_consumers", ())}
    checkout = {str(k): str(v) for k, v in dict(inventory.get("checkout_gate_entrypoints", {})).items()}
    return _ClosureResult(gate_state_protocol=(gate_state.Protocol.from_inventory(inventory)
                                               if "gate_state_protocol" in inventory else None),
                          home_files=home_files, tools=tools, gate_entrypoint=gate_entrypoint,
                          gate_witness=gate_witness, bundled_gate_entrypoints=bundled, checksum_consumers=consumers,
                          bundled_checksum_manifest=inventory.get("bundled_checksum_manifest"),
                          checkout_gate_entrypoints=checkout,
                          skill_pins=skill_pins,
                          home_modes=profile.installed_home_modes(inventory, tree))


def build_treatment(
    acquired: cc.AcquiredCollection, *, listing_client_argv: Sequence[str] | None = None,
    subject_profile: str | None = None, root: Path | None = None, fixture_gate_state: bool = False,
) -> Treatment:
    """The treatment arm from an acquisition, built exactly as
    `run_collection_agent_attempt` builds its own - the same home files, the
    same receipt context - so the calibration treatment IS a collection-run
    install. A subject whose selection is empty installs nothing: refused,
    since the arms would then not differ at all.

    `subject_profile` (#334) names a validated profile (repo-relative path
    to its `profile.json`, as `calibration.py`'s `subject.profile` opt-in
    field declares it) whose dependency closure joins the skill surface in
    ONE merged home-files mapping - never a second delivery mechanism.
    `root` is the skillc checkout root the profile path resolves against;
    required together with `subject_profile`, meaningless alone."""
    if not acquired.files:
        raise CalibrationRefused(
            f"subject {acquired.subject.locator!r} selects no skill; a treatment arm that installs "
            "nothing is a second baseline"
        )
    if (subject_profile is None) != (root is None):
        raise CalibrationRefused("subject_profile and root must be given together, or not at all")
    home_files: dict[str, bytes] = dict(cc._collection_home_files(acquired.source, acquired.files))
    home_modes: dict[str, str] = dict(cc._collection_home_modes(acquired.source, acquired.files))
    skill_digests = _installed_skill_pins(acquired, home_files)
    if not skill_digests:
        raise CalibrationRefused(f"subject {acquired.subject.locator!r} installs no SKILL.md to pin")
    verify_home_files: dict[str, str] = {}
    preflight_tools: tuple[dict[str, object], ...] = ()
    gate_entrypoint: str | None = None
    gate_witness: str | None = None
    bundled_gate_entrypoints: tuple[str, ...] = ()
    bundled_checksum_manifest: str | None = None
    checkout_gate_entrypoints: Mapping[str, str] = {}
    protocol: gate_state.Protocol | None = None
    if subject_profile is not None:
        assert root is not None
        closure = _closure_home_files(acquired, subject_profile, root)
        protocol = closure.gate_state_protocol
        if protocol is not None and fixture_gate_state is not True:
            raise CalibrationRefused("gate-state protocol is supported only by fixture-live construction")
        closure_files = closure.home_files
        # A validated profile's own closure covers the selected skill's
        # bundled files too (profile.py installs skills AND dependencies
        # together) - so an overlap with the skill surface is EXPECTED,
        # not an error, as long as the two paths agree byte-for-byte
        # (which `verify_repo_matches_skills`, already run inside
        # `_closure_home_files`, is what makes that a safe assumption
        # rather than a hope). Only a genuine DISAGREEMENT - the two
        # paths naming different bytes for the same destination - is
        # refused: that would mean the acquisition and the profile
        # validation drifted apart despite the consistency check.
        disagreeing = sorted(k for k in set(closure_files) & set(home_files) if closure_files[k] != home_files[k])
        if disagreeing:
            raise CalibrationRefused(
                f"profile {subject_profile!r}'s closure disagrees with the skill surface at: {disagreeing}"
            )
        # #505: the two derivations must agree on the MODE too - one source
        # calling a file executable and the other not is drift, never a choice.
        mode_disagreeing = sorted(k for k in set(closure.home_modes) & set(home_modes)
                                  if closure.home_modes[k] != home_modes[k])
        if mode_disagreeing:
            raise CalibrationRefused(
                f"profile {subject_profile!r}'s closure disagrees with the skill surface on file mode at: "
                f"{mode_disagreeing}"
            )
        home_files.update(closure_files)
        # #525: the bundled-gate checks over the WHOLE delivered home, not only
        # the profile's closure - a subject selecting more skills installs them
        # all, and any of them could run an unwitnessed bundled gate or verify
        # the shimmed skill's checksums (counter-model review).
        problems = profile.bundled_gate_problems(
            home_files, closure.gate_entrypoint, closure.bundled_gate_entrypoints, closure.checksum_consumers,
            manifest_name=closure.bundled_checksum_manifest, require_consumers_installed=True,
            checkout=closure.checkout_gate_entrypoints)
        if problems:
            raise CalibrationRefused(f"profile {subject_profile!r}, as delivered: {problems[0][1]}")
        home_modes.update(closure.home_modes)
        # Every closure file, not a curated subset (orchestrator ruling:
        # "read back the digest of every closure
        # file") - host-side bytes were already digest-verified against
        # the inventory inside `installed_home_files`, so this is simply
        # that same digest, carried forward for the in-container re-check.
        verify_home_files = {relpath: m.sha256_bytes(data) for relpath, data in closure_files.items()}
        # #279 ca3030d: a neighbour's bundled copy and its siblings are delivered
        # from the acquired subject, not the closure - read back in the container
        # like every closure file, so the overlay mirrors only verified bytes.
        for path in (*closure.bundled_gate_entrypoints, *closure.checkout_gate_entrypoints):
            prefix = path.rsplit("/", 1)[0] + "/"
            verify_home_files.update({dest: m.sha256_bytes(data) for dest, data in home_files.items()
                                      if dest.startswith(prefix) and dest not in verify_home_files})
        preflight_tools = closure.tools
        gate_entrypoint = closure.gate_entrypoint
        gate_witness = closure.gate_witness
        bundled_gate_entrypoints = closure.bundled_gate_entrypoints
        bundled_checksum_manifest = closure.bundled_checksum_manifest
        checkout_gate_entrypoints = closure.checkout_gate_entrypoints
        # Two derivations of the same fact - the installed bytes and the
        # validated inventory - must agree, or the pins would describe skills
        # this treatment does not install (#424). Per path, as a SUBSET (#432,
        # orchestrator ruling): the inventory pins only the profile's selected
        # skills, while the treatment installs - and pins, from its bytes -
        # every skill of the subject's collection. Each inventory pin needs an
        # installed pin at the same path with BOTH digests equal; installed
        # skills the inventory does not name stay pinned from their bytes.
        installed = {pin["path"]: pin for pin in skill_digests}
        disagreements = []
        for pin in closure.skill_pins:
            have = installed.get(pin["path"])
            if have is None:
                disagreements.append(f"{pin['path']}: not installed by this treatment")
                continue
            disagreements.extend(f"{pin['path']}: {field} {pin[field]} (inventory) != {have[field]} (installed)"
                                 for field in ("body_digest", "description_digest") if pin[field] != have[field])
        if disagreements:
            raise CalibrationRefused(
                f"profile {subject_profile!r}'s inventory pins disagree with the installed skills' own "
                f"digests: {disagreements}"
            )
    return Treatment(
        gate_state_protocol=protocol,
        home_files=home_files,
        home_modes=home_modes,
        digest=acquired.source.digest,
        skill_digests=skill_digests,
        gate_entrypoint=gate_entrypoint,
        gate_witness=gate_witness,
        bundled_gate_entrypoints=bundled_gate_entrypoints,
        bundled_checksum_manifest=bundled_checksum_manifest,
        checkout_gate_entrypoints=dict(checkout_gate_entrypoints),
        receipt_context=agent_trial.InstallationReceiptContext(
            declared=frozenset(f.skill for f in acquired.files),
            tree_digest=acquired.source.digest,
            listing_client_argv=listing_client_argv,
            subject_locator=acquired.subject.locator,
            subject_revision=acquired.source.revision,
            surface_name=acquired.subject.surface,
            cache={},
        ),
        verify_home_files=verify_home_files,
        preflight_tools=preflight_tools,
    )


#: Either declaration kind: the helpers below read only `.shared`/`.arm_order`.
AnyDeclaration = calibration.CalibrationDeclaration | calibration.DiscriminationDeclaration


def _shared_str(declaration: AnyDeclaration, *path: str) -> str:
    node: object = declaration.shared
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, str) or not node:
        raise CalibrationRefused(f"shared.{'.'.join(path)} is not declared")
    return node


def declared_model(declaration: AnyDeclaration) -> tuple[str, str]:
    return _shared_str(declaration, "model"), _shared_str(declaration, "reasoning_effort")


def declared_client(declaration: AnyDeclaration) -> tuple[str, str]:
    return _shared_str(declaration, "client", "name"), _shared_str(declaration, "client", "version")


def treatment_subject(declaration: calibration.CalibrationDeclaration) -> Mapping[str, object]:
    """The non-baseline arm's declared subject (`parse_declaration` already
    proved there is exactly one, and that it is an object)."""
    arms = declaration.data.get("arms")
    arm = next(a for a in arms if isinstance(a, dict) and a.get("name") != calibration.BASELINE_ARM) \
        if isinstance(arms, list) else None
    subject = arm.get("subject") if isinstance(arm, dict) else None
    if not isinstance(subject, dict):
        raise CalibrationRefused("the treatment arm declares no subject")
    return subject


def task_content_identity(
    goal: bytes, grader: verify.GraderDef, files: list[tuple[str, bytes, bool]],
    project_gate: bytes | None = None,
) -> dict[str, object]:
    """Identity of the prompt, grader and exact delivered fixture (including
    mode), and - only for a task that declares one (#508) - its project-gate
    declaration, so every earlier task's identity is byte-identical."""
    identity: dict[str, object] = {
        "version": 1, "goal_digest": trial.sha256_bytes(goal), "grader_digest": grader.digest(),
        "fixture_digest": trial.sha256_bytes(trial.canonical([
            [path, executable, trial.sha256_bytes(body)] for path, body, executable in sorted(files)
        ])),
    }
    if project_gate is not None:
        identity["project_gate_digest"] = trial.sha256_bytes(project_gate)
    return identity


def _outcome_task_inputs(
    declaration: calibration.CalibrationDeclaration, root: Path,
) -> tuple[str, dict[str, object]]:
    task = root / declaration.task_path
    goal_file = task / "goal.md"
    if goal_file.is_symlink() or not goal_file.is_file():
        raise CalibrationRefused("outcome task goal must be a regular file")
    goal = goal_file.read_bytes()
    files = cc.task_surface(task / declaration.task_fixture)
    measured = task_content_identity(goal, verify.GraderDef.load(task), files, cc.project_gate_bytes(task))
    if measured != declaration.data["task_content"]:
        raise CalibrationRefused("task_content differs from the approved goal, grader or fixture")
    return goal.decode("utf-8"), cc.surface_mapping(files)


#: #640: a fixture-service task's builder, beside its grader (#434).
FIXTURE_BUILDER = ("builder", "build.py")
#: The declared `task.fixture` of a fixture-builder task: its builder IS its fixture.
FIXTURE_BUILDER_DIR = "builder"
FIXTURE_ROUTE_GATED = "gated"
FIXTURE_ROUTE_BASELINE = "baseline"
NON_START = "non-start"


def fixture_case_of(declaration: calibration.CalibrationDeclaration, root: Path) -> str | None:
    """#640: the declared fixture case of a fixture-builder task, or None for
    a task without a builder. Both fields are approval-bound like the rest of
    the declaration (D-P2a), so the case cannot change after approval. A
    builder-less task naming a case, or a builder task not naming one, is
    refused - never run as if the other were meant."""
    task_root = root / declaration.task_path
    builder = task_root.joinpath(*FIXTURE_BUILDER)
    task = declaration.data.get("task")
    case = task.get("fixture_case") if isinstance(task, dict) else None
    if builder.is_symlink() or (builder.exists() and not builder.is_file()):
        raise CalibrationRefused(f"{declaration.task_path}: builder/build.py is not a regular file")
    if not builder.is_file():
        if case is not None:
            raise CalibrationRefused("task.fixture_case names a case, but the task has no fixture builder")
        return None
    if declaration.task_fixture != FIXTURE_BUILDER_DIR:
        raise CalibrationRefused(f"a fixture-builder task declares task.fixture {FIXTURE_BUILDER_DIR!r}, so its "
                                 f"builder's bytes are the approved fixture identity, not {declaration.task_fixture!r}")
    if not isinstance(case, str) or not case:
        raise CalibrationRefused("a fixture-builder task must declare task.fixture_case")
    from . import fixture_campaign as fc  # fixture_campaign imports this module
    cases = getattr(fc._builder(task_root), "CASES", None)
    if not isinstance(cases, tuple) or case not in cases:
        raise CalibrationRefused(f"task.fixture_case {case!r} is not one of the builder's cases {cases!r}")
    return case


@dataclass(frozen=True)
class BuiltFixture:
    """#640: the ONE controller build of a run's fixture case. `surface` is
    the built tree every attempt is copied from; `fixture` is the case's
    controller-held facts, shared by every attempt. A build that failed keeps
    only its reason, and every attempt is then a non-start."""

    case: str
    surface: Mapping[str, Path] | None
    fixture: fa.AttemptFixture | None
    digest: str | None
    build_error: str | None = None

    def planned(self, route: str) -> dict[str, object]:
        """What the ledger binds for one trial: the case, the digest every
        attempt must be delivered, and the route (gated or baseline)."""
        return {"case": self.case, "digest": self.digest, "route": route,
                **({"build_error": self.build_error} if self.build_error is not None else {})}


def build_fixture(task_root: Path, case: str, where: Path) -> BuiltFixture:
    """Build `case` once, under `where`. A failure is recorded, not raised."""
    from . import fixture_campaign as fc  # fixture_campaign imports this module
    try:
        surface, fixture = fc.build_case(task_root, case, where)
        paths: dict[str, Path] = {}
        for name, path in surface.items():
            if not isinstance(path, Path):
                raise fa.FixtureUndeliverable(f"fixture surface {name!r} is not a directory path")
            paths[name] = path
        return BuiltFixture(case, paths, fixture, fa.fixture_digest(paths))
    except Exception as exc:  # noqa: BLE001 - any build failure is a non-start, with its reason
        return BuiltFixture(case, None, None, None, f"{type(exc).__name__}: {exc}")


def deliver_fixture(built: BuiltFixture, where: Path) -> tuple[dict[str, Path], str]:
    """A FRESH copy of the built case for one attempt (no remote or
    workspace is shared between attempts), and the copy's own digest. Raises
    `fixture_attempt.FixtureUndeliverable` (or an OSError) when it cannot."""
    if built.surface is None:
        raise fa.FixtureUndeliverable(f"the fixture did not build: {built.build_error}")
    where.mkdir(parents=True)
    copied = {name: shutil.copytree(src, where / name, symlinks=True) for name, src in sorted(built.surface.items())}
    return {name: Path(path) for name, path in copied.items()}, fa.fixture_digest(copied)


def base_prompt(declaration: calibration.CalibrationDeclaration, arm: str, goal: str) -> str:
    """Exact pre-bootstrap prompt; canary and later controller turns are separate."""
    instruction = calibration.arm_spec(declaration, arm).get("instruction")
    return f"{goal.rstrip()}\n\n{instruction}\n" if isinstance(instruction, str) else goal


def installed_home_digest(treatment: Treatment) -> str:
    """Hash every treatment-supplied home file at its effective delivery mode."""
    if not treatment.home_files or set(treatment.home_modes) - set(treatment.home_files):
        raise CalibrationRefused("explicit_product has empty home files or orphan file modes")
    manifest = []
    for path, body in sorted(treatment.home_files.items()):
        relative = PurePosixPath(path)
        if not path or str(relative) != path or relative.is_absolute() or ".." in relative.parts \
                or not relative.parts or "\0" in path:
            raise CalibrationRefused("explicit_product home paths must be canonical relative file paths")
        try:
            mode = agent_trial.delivery_mode(path, treatment.home_modes)
        except agent_trial.HomeFileVerificationRefused as exc:
            raise CalibrationRefused(str(exc)) from exc
        manifest.append({"path": path, "digest": trial.sha256_bytes(body), "mode": f"{mode:04o}"})
    return trial.sha256_bytes(trial.canonical(manifest))


def _require_explicit_product(
    declaration: calibration.CalibrationDeclaration, root: Path, treatment: Treatment | None,
) -> None:
    if declaration.lane != calibration.EXPLICIT_PRODUCT_LANE:
        return
    if treatment is None or treatment.receipt_context is None:
        raise CalibrationRefused("explicit_product requires the actual Treatment and installed receipt context")
    raw = declaration.data["explicit_product"]
    assert isinstance(raw, dict)
    if sorted(treatment.receipt_context.declared) != raw["selected_skills"]:
        raise CalibrationRefused("explicit_product selected_skills differs from the actual installed population")
    if installed_home_digest(treatment) != raw["installed_home_digest"]:
        raise CalibrationRefused("explicit_product installed_home_digest differs from actual delivered bytes/modes")
    surface = m.SURFACES.get(treatment.receipt_context.surface_name)
    if surface is None or surface.client != declared_client(declaration)[0]:
        raise CalibrationRefused("explicit_product receipt surface differs from the declared client")
    prefix = PurePosixPath(surface.home_skills_relpath)
    expected_paths = {str(prefix / name / "SKILL.md") for name in raw["selected_skills"]}
    installed_paths = {path for path in treatment.home_files
                       if PurePosixPath(path).name == "SKILL.md" and PurePosixPath(path).parent.parent == prefix}
    if installed_paths != expected_paths:
        raise CalibrationRefused("explicit_product installed skill entrypoints differ from selected_skills")
    pins = []
    for path in sorted(expected_paths):
        try:
            description, body = profile.skill_md_digests(treatment.home_files[path])
        except FrontmatterError as exc:
            raise CalibrationRefused(f"{path}: {exc}") from exc
        pins.append({"path": path, "body_digest": body, "description_digest": description})
    if sorted(treatment.skill_digests, key=lambda pin: pin["path"]) != pins:
        raise CalibrationRefused("explicit_product skill pins differ from the actual installed skill bytes")
    goal, _surface = _outcome_task_inputs(declaration, root)
    prompts = {arm: trial.sha256_bytes(base_prompt(declaration, arm, goal).encode("utf-8"))
               for arm in declaration.arms}
    if prompts != raw["prompt_digests"]:
        raise CalibrationRefused("explicit_product prompt_digests differ from actual base prompts")


def _launch_declaration(declaration: calibration.CalibrationDeclaration) -> calibration.CalibrationDeclaration:
    """Mutable data cannot erase the opt-in cached when this declaration was parsed."""
    if declaration.lane == calibration.EXPLICIT_PRODUCT_LANE or "explicit_product" in declaration.data \
            or calibration.outcome_endpoint(declaration) is not None:
        parsed = calibration.parse_declaration(json.loads(trial.canonical(declaration.data)))
        if declaration.lane == calibration.EXPLICIT_PRODUCT_LANE and parsed.lane != declaration.lane:
            raise CalibrationRefused("explicit_product lane differs from the parsed declaration")
        return parsed
    return declaration


def plan_calibration(
    declaration: calibration.CalibrationDeclaration, store: Path, *,
    root: Path, treatment_digest: str, image_digest: str | None,
    skill_digests: Sequence[Mapping[str, str]] = (),
    treatment: Treatment | None = None,
    fixture: BuiltFixture | None = None,
) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    """Plan one trial per attempt through the real controller, in
    `arm_order.sequence`. `repeat` is the arm's own 1-based attempt count.
    A fixture task's trials (#640) each bind the built case's digest and the
    arm's route, so what every attempt must be delivered is in the ledger.

    Every treated trial declares `skill_digests` (#424), so #354's
    `ledger-binding` refuses stale or unpinned skill-evidence for it. A
    treated arm with no pins is refused, never planned unpinned. The baseline
    installs nothing and stays unpinned (its contamination rule is #427)."""
    if not skill_digests and any(arm != calibration.BASELINE_ARM for arm in declaration.arm_order):
        raise CalibrationRefused("a treated arm has no skill_digests to pin; refusing to plan it unpinned")
    declaration = _launch_declaration(declaration)
    client_name, client_version = declared_client(declaration)
    grader = verify.GraderDef.load(root / declaration.task_path)
    grader_identity = grader.identity()
    snapshot = None
    if calibration.outcome_endpoint(declaration) is not None:
        calibration.require_approved(declaration, root)
        _require_explicit_product(declaration, root, treatment)
        if declaration.lane == calibration.EXPLICIT_PRODUCT_LANE and treatment is not None \
                and (treatment.digest != treatment_digest or tuple(skill_digests) != treatment.skill_digests):
            raise CalibrationRefused("explicit_product planned treatment digest/pins differ from actual Treatment")
        if image_digest != _shared_str(declaration, "image", "digest"):
            raise CalibrationRefused("planned image differs from the approved declaration")
        _outcome_task_inputs(declaration, root)
        snapshot = json.loads(trial.canonical(declaration.data))
        content = snapshot["task_content"]
        if grader_identity["digest"] != content["grader_digest"]:
            raise CalibrationRefused("planned grader differs from approved task_content")
    trials: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for position, arm in enumerate(declaration.arm_order, start=1):
        counts[arm] = counts.get(arm, 0) + 1
        trials.append({
            "label": f"{TRIAL_PREFIX}_{arm}_{counts[arm]}",
            "case": {"id": declaration.grader_id, "revision": declaration.grader_revision},
            # The full identity, digest included (#139): the verifier stores no
            # result against a ledger that pins no grader digest.
            "grader": grader_identity,
            "subject": {"digest": mp.BASELINE_SUBJECT_DIGEST if arm == calibration.BASELINE_ARM else treatment_digest},
            "client": {"name": client_name, "version": client_version},
            "image": {"digest": image_digest or UNKNOWN},
            "config": {"arm": arm, "repeat": counts[arm], "position": position,
                       **({"calibration_declaration": snapshot} if snapshot is not None else {}),
                       **({"fixture": fixture.planned(FIXTURE_ROUTE_BASELINE if arm == calibration.BASELINE_ARM
                                                      else FIXTURE_ROUTE_GATED)} if fixture is not None else {})},
            "attempts": 1,
            **({} if arm == calibration.BASELINE_ARM else {"skill_digests": [dict(pin) for pin in skill_digests]}),
        })
    try:
        experiment = trial.plan({"experiment": EXPERIMENT_LABEL, "trials": trials}, store)
    except trial.Refused as exc:
        raise CalibrationRefused(f"the controller refused the schedule: {exc}") from exc
    pairs = list(experiment.attempts())
    if len(pairs) != len(trials):
        raise CalibrationRefused(f"planned {len(pairs)} attempts for {len(trials)} trials")
    schedule = []
    for (planned_trial, attempt), spec in zip(pairs, trials, strict=True):
        config = spec["config"]
        assert isinstance(config, dict)
        schedule.append(mp.ScheduledAttempt(
            attempt_id=str(attempt["attempt_id"]), trial_id=str(planned_trial["trial_id"]),
            arm=str(config["arm"]), repeat=int(config["repeat"]),
        ))
    return experiment, schedule


def schedule_from_ledger(experiment: trial.Experiment) -> list[mp.ScheduledAttempt]:
    """The planned schedule, recovered from the ledger alone - what
    `matched_pilot.reconcile` checks the outcomes against."""
    schedule = []
    for planned_trial, attempt in experiment.attempts():
        trial_id = str(planned_trial["trial_id"])
        match = _TRIAL_ID_RE.match(trial_id)
        if match is None:
            raise CalibrationRefused(f"ledger trial {trial_id!r} is not a calibration trial")
        schedule.append(mp.ScheduledAttempt(str(attempt["attempt_id"]), trial_id, match["arm"], int(match["k"])))
    return schedule


def reconcile(experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome]) -> list[mp.AttemptOutcome]:
    """One outcome per planned attempt, in ledger (= declared) order; none dropped."""
    return mp.reconcile(experiment, outcomes, schedule_from_ledger(experiment))


def write_outcomes(
    run_dir: Path, experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome],
    declaration: AnyDeclaration,
) -> Path:
    """The private, resumable per-run record (`matched_pilot.read_outcomes`
    reads it back). Rewritten after every attempt, and before the first, so
    an interruption still leaves a store to reconcile. Carries the model and
    effort the run DECLARED, so a rebuilt report is scored against the pin it
    launched with."""
    model, effort = declared_model(declaration)
    path = run_dir / OUTCOMES_FILENAME
    tmp = path.with_suffix(".tmp")
    data = {
        "experiment_root": str(experiment.root),
        "declared": {"model": model, "reasoning_effort": effort, "arm_order": list(declaration.arm_order)},
        "outcomes": [o.to_json() for o in outcomes],
    }
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def run_calibration(
    declaration: calibration.CalibrationDeclaration,
    *,
    run_dir: Path,
    treatment: Treatment,
    image_digest: str | None,
    backends: Callable[[], tuple[object, object]],
    argv_for: Callable[[mp.ScheduledAttempt], Sequence[str]],
    root: Path = ROOT,
    credential_explicit_path: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    total_seconds: float | None = None,
    rehearse: bool = False,
    completion_deadline: completion.CompletionDeadline | None = None,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    """Authorize, plan and run the whole declared schedule. `backends()`
    returns a fresh `(agent backend, grading backend)` pair per attempt;
    `argv_for` gives the BASE client invocation (a real run passes the same
    one every time; a test's scripted client needs the attempt id), to which
    the declared model and effort are added. `total_seconds` overrides the
    declared total cap - for tests only; the CLI never sets it."""
    if treatment is not None and treatment.gate_state_protocol is not None:
        raise CalibrationRefused("gate-state treatment is fixture-only")
    declared_total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds
    completion_deadline = (completion.CompletionDeadline.after(declared_total, clock) if completion_deadline is None
                           else completion_deadline.child(declared_total))
    # ADR 0005: nothing - no store, no plan, no container - before this.
    declaration = _launch_declaration(declaration)
    calibration.require_approved(declaration, root)
    _require_explicit_product(declaration, root, treatment)
    if calibration.outcome_endpoint(declaration) is not None:
        if image_digest != _shared_str(declaration, "image", "digest"):
            raise CalibrationRefused("planned image differs from the approved declaration")
        if total_seconds is not None and total_seconds != float(str(declaration.shared["total_seconds"])):
            raise CalibrationRefused("outcome run cannot override the approved total_seconds cap")
    model, effort = declared_model(declaration)
    client_name, client_version = declared_client(declaration)
    mp.pin_model_argv(model, effort, [])
    task_root = root / declaration.task_path
    #: #508: the task's project gate, resolved ONCE for the whole run and
    #: handed to every arm, so the arms cannot see different declarations.
    resolved_gate = cc.project_gate_of(task_root)
    #: #640: a fixture task's case; every arm is dispatched with its fixture.
    case = fixture_case_of(declaration, root)
    if case is not None:
        if resolved_gate is not None:
            raise CalibrationRefused("a fixture task uses its fixture's gate map; it cannot also declare a project gate")
        if any(arm != calibration.BASELINE_ARM for arm in declaration.arm_order) and treatment.gate_entrypoint is None:
            raise CalibrationRefused("a treated arm on a fixture task witnesses the treatment's gate; this treatment "
                                     "declares no gate_entrypoint (only the baseline route carries none)")
    try:
        if calibration.outcome_endpoint(declaration) is not None:
            goal, surface = _outcome_task_inputs(declaration, root)
        else:
            surface = cc.surface_mapping(cc.task_surface(task_root / declaration.task_fixture))
            goal = (task_root / "goal.md").read_text(encoding="utf-8")
    except demo.SubjectRefused as exc:
        raise CalibrationRefused(str(exc)) from exc
    if case is not None:
        surface = {}  # the builder is the fixture's identity, never its delivered surface
    per_attempt = float(str(declaration.shared["per_attempt_seconds"]))
    total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds

    installed = treatment.receipt_context.declared if treatment.receipt_context is not None else frozenset()
    for arm, skills in named_skills_by_arm(declaration).items():
        absent = sorted(set(skills) - installed)
        if absent:
            # A P arm told to read a skill the install does not hold would
            # make its zero uptake a configuration error (counter-model review).
            raise CalibrationRefused(f"arm {arm!r} names {absent}, which the treatment does not install")

    store = trial.open_store(run_dir / "store", forbidden=[])
    fixtures_dir = run_dir / "fixtures"
    built = build_fixture(task_root, case, fixtures_dir / "built") if case is not None else None
    experiment, schedule = plan_calibration(
        declaration, store, root=root, treatment_digest=treatment.digest, image_digest=image_digest,
        skill_digests=treatment.skill_digests,
        treatment=treatment, fixture=built,
    )
    outcomes: list[mp.AttemptOutcome] = []
    write_outcomes(run_dir, experiment, outcomes, declaration)

    guarded = guard_kwargs(client_name, model)
    stop = GuardStop()

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float,
                    deadline: completion.CompletionDeadline) -> dict[str, object]:
        owned = trial.OwnedAttemptIds(experiment, scheduled.attempt_id)
        if rehearse:  # #287 P2: only the attempt is swapped; everything around it is the real path
            return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason=REHEARSAL_REASON)
        if (skipped := stop.skip(experiment, scheduled.attempt_id)) is not None:
            return skipped
        treated = scheduled.arm != calibration.BASELINE_ARM
        prompt = base_prompt(declaration, scheduled.arm, goal)
        attempt_surface: Mapping[str, object] = surface
        fixture_kwargs: dict[str, object] = {}
        delivered: str | None = None
        attempt_dir = fixtures_dir / scheduled.attempt_id
        if built is not None:
            try:
                copied, delivered = deliver_fixture(built, attempt_dir)
            except (fa.FixtureUndeliverable, OSError) as exc:
                shutil.rmtree(attempt_dir, ignore_errors=True)
                return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable",
                                      reason=f"{NON_START}: {exc}")
            if delivered != built.digest:
                shutil.rmtree(attempt_dir, ignore_errors=True)
                return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable",
                                      reason=f"{NON_START}: the attempt's fixture copy {delivered} differs from the "
                                             f"built case {built.digest}")
            attempt_surface = copied
            fixture_kwargs = {"fixture": built.fixture, "fixture_baseline": not treated}
        agent_backend, grading_backend = backends()
        try:
            record = cc.run_level1_agent_attempt(
                experiment=experiment, attempt_id=scheduled.attempt_id,
                completion_deadline=deadline, recorded_attempt_ids=owned,
                backend=agent_backend, grading_backend=grading_backend,  # type: ignore[arg-type]
                base=run_dir, base_argv=mp.pin_model_argv(model, effort, argv_for(scheduled)),
                extra_home_files=treatment.home_files if treated else {},
                client=client_name, cli_version=client_version, task_root=task_root, surface=attempt_surface,
                prompt=prompt,
                project_gate=resolved_gate,
                timeout=budget, credential_explicit_path=credential_explicit_path,
                receipt_context=treatment.receipt_context if treated else None,
                # #334: the profile-closure fields reach a real
                # calibration attempt - for a TREATED arm only; the baseline
                # stays exactly as empty as `extra_home_files`/`receipt_context`
                # already do above, never partially profile-opted.
                verify_home_files=treatment.verify_home_files if treated else None,
                preflight_tools=treatment.preflight_tools if treated else None,
                gate_entrypoint=treatment.gate_entrypoint if treated else None,
                gate_witness=treatment.gate_witness if treated else None,
                bundled_gate_entrypoints=treatment.bundled_gate_entrypoints if treated else (),
                checkout_gate_entrypoints=treatment.checkout_gate_entrypoints if treated else {},
                # #505: the installed files' source modes, for a treated arm only.
                extra_home_modes=dict(treatment.home_modes) if treated and treatment.home_modes else None,
                **fixture_kwargs,  # type: ignore[arg-type]
                **guarded,  # type: ignore[arg-type]
            )
        finally:
            if built is not None:
                shutil.rmtree(attempt_dir, ignore_errors=True)
        if delivered is not None:
            # #640: the copy this attempt was handed, checked equal to the
            # planned digest before dispatch; the report reads it beside it.
            record = {**record, "fixture_delivered_digest": delivered}
        return record

    def on_outcome(outcome: mp.AttemptOutcome) -> None:
        outcomes.append(outcome)
        stop.observe(outcome, bool(guarded))
        write_outcomes(run_dir, experiment, outcomes, declaration)

    try:
        mp.run_schedule(
            experiment, schedule, None, total_seconds=total, per_attempt_seconds=per_attempt,
            clock=clock, on_outcome=on_outcome,
                        run_attempt_with_deadline=run_attempt, completion_deadline=completion_deadline,
        )
    except KeyboardInterrupt:
        # An operator's interrupt still accounts for every planned attempt
        # (counter-model review): the ones that never ran are finalized from
        # the ledger and the private record is rewritten whole, so the report
        # the CLI then writes covers the declared schedule, not a prefix of it.
        # A kill that cannot be caught leaves `outcomes.json` as the last
        # checkpoint; `reconcile` over it gives the same accounting.
        write_outcomes(run_dir, experiment, reconcile(experiment, outcomes), declaration)
        raise
    return experiment, outcomes


# ------------------------------------------- #500: the nested-codex guard

def _session_tokens(usage: object) -> int | None:
    total = usage.get("total_tokens") if isinstance(usage, Mapping) else None
    return total if isinstance(total, int) and not isinstance(total, bool) else None


def guard_entry(record: Mapping[str, object], obs: Mapping[str, object], declared: str) -> dict[str, object]:
    """#500: a report entry's guard and every-session fields, present only
    for a guarded attempt or one that left more than one transcript (every
    other entry is byte-identical to before).

    - `nested_codex`: the guard's counts, the transcript backstop's hits and
      their verdict (`attempt_guard.assess`), with `other_models` widened by
      every retained session's own model.
    - `models_all_sessions`: every session's model; any other than the
      declared one makes the attempt ineligible (applied by the caller).
    - `tokens_all_sessions`: the sum over every session, or UNKNOWN when one
      is unreadable - or when a nested launch went past the guard, whose
      session no transcript holds, so no total can be complete."""
    guard = record.get("codex_guard")
    sessions = obs.get("transcript_sessions")
    if not isinstance(guard, Mapping) and not isinstance(sessions, list):
        return {}
    meta = obs.get("run_metadata")
    rows: list[Mapping[str, object]]
    if isinstance(sessions, list):
        rows = [s for s in sessions if isinstance(s, Mapping)]
    else:
        rows = [{"model": meta.get("model"), "token_usage": meta.get("token_usage")}] if isinstance(meta, Mapping) else [{}]
    models = [str(r["model"]) if r.get("model") is not None else UNKNOWN for r in rows]
    totals = [_session_tokens(r.get("token_usage")) for r in rows]
    nested: dict[str, object] = dict(guard) if isinstance(guard, Mapping) else {}
    # A bypass, or any guard record that stops (suspected, unknown, ancestry
    # unknown), leaves room for a session no transcript holds: the total is
    # then UNKNOWN, and what was measured is reported beside it.
    bypassed = bool(nested.get("bypass")) or bool(nested.get("stop"))
    others = {m for m in models if m != declared}
    if others:
        prior = nested.get("other_models")
        nested["other_models"] = sorted(others | {str(m) for m in prior} if isinstance(prior, list) else others)
    out: dict[str, object] = {
        "models_all_sessions": models,
        "tokens_all_sessions": UNKNOWN if bypassed or any(t is None for t in totals)
        else sum(t for t in totals if t is not None),
        "tokens_measured_sessions": sum(t for t in totals if t is not None),
    }
    if nested:
        out["nested_codex"] = nested
    return out


def containment_evidence(record: Mapping[str, object]) -> dict[str, object] | None:
    """Positive observed containment violations, including historical attempts.

    A violation is not evidence that an old runner stopped its schedule. Only
    GuardStop writes that decision's separate checkpoint marker.
    """
    if record.get("disposition") not in mp.DISPATCHED:
        return None
    obs = record.get("observation")
    if not isinstance(obs, Mapping):
        return None
    evidence: dict[str, object] = {}
    uses = obs.get("server_side_tool_uses")
    if isinstance(uses, list) and uses:
        evidence["server_side_tool_uses"] = uses
    network = obs.get("egress")
    allowed = network.get("allowed") if isinstance(network, Mapping) else None
    if isinstance(allowed, Mapping):
        targets = sorted(target for target, count in allowed.items()
                         if isinstance(target, str) and type(count) is int and count > 0
                         and not egress.target_allowed(target))
        if targets:
            evidence["off_list_allowed_targets"] = targets
    return {"trigger": "observed containment violation", "evidence": evidence} if evidence else None


def containment_stop(entries: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    """The first recorded native stop, including the original nested guard."""
    for entry in entries:
        marker = entry.get("schedule_containment_stop")
        if isinstance(marker, Mapping):
            return {"at_attempt": entry.get("attempt_id"), **marker}
        nested = entry.get("nested_codex")
        if isinstance(nested, Mapping) and nested.get("stop"):
            return {"at_attempt": entry.get("attempt_id"), "trigger": nested["stop"]}
    return None


def guard_kwargs(client_name: str, model: str) -> dict[str, object]:
    """#500: every live codex calibration attempt - discrimination and
    improvement kinds alike (orchestrator condition 1) - runs under the
    nested-codex guard, refusing a nested launch before any model contact
    (`attempt_guard.CALIBRATION_POLICY`). Another client is unguarded: the
    guard is codex's own front."""
    if client_name != "codex":
        return {}
    return {"codex_guard": True, "nested_codex_policy": ag.CALIBRATION_POLICY, "declared_model": model}


@dataclass
class GuardStop:
    """The first containment trigger, which skips every later attempt."""

    trigger: str | None = None
    at_attempt: str | None = None

    def skip(self, experiment: trial.Experiment, attempt_id: str) -> dict[str, object] | None:
        if self.trigger is None:
            return None
        return trial.finalize(experiment, attempt_id, reason=f"containment stop at {self.at_attempt}: {self.trigger}")

    def observe(self, outcome: mp.AttemptOutcome, guarded: bool) -> None:
        if self.trigger is not None:
            return
        evidence = containment_evidence(outcome.record)
        if evidence is not None:
            self.trigger, self.at_attempt = str(evidence["trigger"]), outcome.scheduled.attempt_id
            outcome.record["schedule_containment_stop"] = evidence
        elif guarded:
            trigger = ag.containment_trigger(outcome.record)
            if trigger is not None:
                self.trigger, self.at_attempt = trigger, outcome.scheduled.attempt_id


# --------------------------------------- #287 P3: image, store and egress bindings


def require_image_binding(declaration: AnyDeclaration, *, image_arg: str, resolved_digest: str | None,
                          receipt_path: Path | None) -> bytes:
    """C3: the run's image is the DECLARED one three ways - the tag the
    operator passed is `shared.image.tag`, the daemon resolves it to
    `shared.image.digest` (a tag re-pointed at another image is refused), and
    the runtime-supply receipt file's bytes hash to `shared.image.receipt_sha256`.
    A missing or malformed declared receipt digest is refused, never skipped.
    Returns the receipt bytes it checked: the run uses THOSE bytes, never a
    second read of the path (counter-model finding: the file can change between
    reads)."""
    image = declaration.shared.get("image")
    image = image if isinstance(image, dict) else {}
    tag, digest, receipt_sha = image.get("tag"), image.get("digest"), image.get("receipt_sha256")
    if image_arg != tag:
        raise CalibrationRefused(f"image tag {image_arg!r} is not the declared shared.image.tag {tag!r}")
    if resolved_digest != digest:
        raise CalibrationRefused(f"the declared tag {tag!r} resolves to {resolved_digest or 'nothing'}, not the "
                                 f"declared {digest}; a tag re-pointed at another image is refused")
    if not isinstance(receipt_sha, str) or not receipt_sha.startswith("sha256:"):
        raise CalibrationRefused(f"shared.image.receipt_sha256 {receipt_sha!r} is not a declared receipt digest")
    if receipt_path is None or not receipt_path.is_file():
        raise CalibrationRefused("the declaration names a runtime receipt (shared.image.receipt_sha256) but "
                                 "no receipt file was supplied")
    receipt_bytes = receipt_path.read_bytes()
    measured = m.sha256_bytes(receipt_bytes)
    if measured != receipt_sha:
        raise CalibrationRefused(f"runtime receipt {receipt_path} hashes to {measured}, not the declared "
                                 f"shared.image.receipt_sha256 {receipt_sha}")
    return receipt_bytes


def private_root(declaration: AnyDeclaration, private_dir: str | None) -> Path:
    """C5: a declaration that names a `run_store` stores its run there, expanded
    and durability-checked against this run's HOME; a different `--private-dir`
    is refused. Without one, the CLI's own default."""
    store = declaration.data.get("run_store")
    if store is None:
        return Path(private_dir).expanduser() if private_dir else DEFAULT_PRIVATE_ROOT
    try:
        resolved = calibration.resolve_run_store(store)
    except calibration.DeclarationRefused as exc:
        raise CalibrationRefused(str(exc)) from None
    if private_dir is not None and Path(private_dir).expanduser() != resolved:
        raise CalibrationRefused(f"--private-dir {private_dir!r} differs from the declared run_store {store!r} "
                                 f"(expanded {str(resolved)!r})")
    return resolved


def declared_allowlist_digest(declaration: AnyDeclaration) -> str | None:
    network = declaration.shared.get("agent_network")
    digest = network.get("allowlist_digest") if isinstance(network, dict) else None
    return digest if isinstance(digest, str) else None


def egress_eligibility(record: Mapping[str, object], declared_digest: str) -> tuple[bool | None, str | None]:
    """C4, per attempt: a DISPATCHED attempt is eligible only when its egress
    proxy log was read and recorded the declared allowlist digest. `None` for
    an attempt never dispatched (not-run, unavailable: nothing to check)."""
    if record.get("disposition") in ("not-run", "unavailable"):
        return None, None
    observation = record.get("observation")
    summary = observation.get("egress") if isinstance(observation, dict) else None
    if not isinstance(summary, dict):
        return False, "no egress evidence recorded for this attempt"
    if summary.get("status") != "read":
        return False, f"the egress proxy log was not read ({summary.get('reason')})"
    if summary.get("allowlist_digest") != declared_digest:
        return False, (f"the proxy recorded allowlist {summary.get('allowlist_digest')!r}, not the declared "
                       f"{declared_digest}")
    return True, None


def _apply_egress(report: dict[str, object], outcomes: Sequence[mp.AttemptOutcome], declared_digest: str) -> None:
    for entry, outcome in zip(report["attempts"], outcomes, strict=True):  # type: ignore[call-overload]
        ok, reason = egress_eligibility(outcome.record, declared_digest)
        entry["egress_eligible"], entry["egress_reason"] = ok, reason
    report["agent_network_allowlist_digest"] = declared_digest


# ------------------------------------------------- #287 P2: discrimination run


#: The rehearsal's attempt disposition reason: a deterministic, in-process
#: stand-in for an agent attempt. No container, no client, no model.
REHEARSAL_REASON = "rehearsal: deterministic in-process attempt; no container, no client, no model"


def degraded_treatment(intact: Treatment, declaration: calibration.DiscriminationDeclaration) -> Treatment:
    """The degraded arm, DERIVED IN MEMORY from the intact treatment (#287 P2):
    the same install with exactly the declared mutation applied. Every
    delivered copy of `mutation.skill/mutation.path` (the skill surface AND the
    profile closure place the same file at different destinations) gets the
    SAME degraded bytes, and each copy's in-container re-check digest follows
    it. The degraded bytes come from `calibration.require_degraded_mutation`, so
    they hash to the approved `mutated_digest`, the digest P1's textual scan
    was run at. Derived rather than re-acquired because both degrade-subject
    paths lose the checkout a profile closure needs, and a snapshot-sourced
    degrade can never carry the declared `git:` revision label."""
    if intact.gate_state_protocol is not None:
        raise CalibrationRefused("gate-state treatment is fixture-only")
    mutation = declaration.mutation
    skill, path = str(mutation.get("skill")), str(mutation.get("path"))
    if path == "SKILL.md":
        raise CalibrationRefused("a SKILL.md mutation would change the skill's own pins; not supported here")
    suffix = f"skills/{skill}/{path}"
    keys = sorted(k for k in intact.home_files if k == suffix or k.endswith("/" + suffix))
    if not keys:
        raise CalibrationRefused(f"the intact treatment delivers no {suffix}; the declared mutation has no target")
    originals = {intact.home_files[k] for k in keys}
    if len(originals) != 1:
        raise CalibrationRefused(f"the intact treatment delivers different bytes at {keys}; refusing to degrade")
    try:
        degraded = calibration.require_degraded_mutation(originals.pop(), mutation)
    except calibration.DeclarationRefused as exc:
        raise CalibrationRefused(str(exc)) from exc
    revision = declaration.degraded_subject.get("revision")
    if revision != calibration._expected_degraded_revision(declaration.intact_subject):
        raise CalibrationRefused(f"degraded subject revision {revision!r} is not the derived git: label")
    home_files = dict(intact.home_files)
    verify_home_files = dict(intact.verify_home_files)
    for key in keys:
        home_files[key] = degraded
        if key in verify_home_files:
            verify_home_files[key] = m.sha256_bytes(degraded)
    tree = trial.sha256_bytes(trial.canonical(sorted([k, trial.sha256_bytes(v)] for k, v in home_files.items())))
    context = intact.receipt_context
    if context is not None:
        context = agent_trial.InstallationReceiptContext(
            declared=context.declared, tree_digest=tree, listing_client_argv=context.listing_client_argv,
            subject_locator=context.subject_locator, subject_revision=str(revision),
            surface_name=context.surface_name, cache={},
        )
    return Treatment(home_files=home_files, digest=tree, receipt_context=context,
                     verify_home_files=verify_home_files, preflight_tools=intact.preflight_tools,
                     gate_entrypoint=intact.gate_entrypoint, gate_witness=intact.gate_witness,
                     bundled_gate_entrypoints=intact.bundled_gate_entrypoints, skill_digests=intact.skill_digests, home_modes=intact.home_modes,
                     checkout_gate_entrypoints=intact.checkout_gate_entrypoints)


def require_textual_evidence(declaration: calibration.DiscriminationDeclaration, root: Path) -> dict[str, object]:
    """Tie the run to P1's textual check (orchestrator ruling on #287 P2): the
    evidence file `mutation.diagnose_evidence` names (its first word, a
    repo-relative path) must exist, report NO_TEXTUAL_SURVIVOR with its own
    digest check passed, and have been run at EXACTLY the declared
    `mutated_digest`, so the bytes a live degraded attempt installs are the
    bytes that scan examined. Returns the evidence; refuses otherwise. That
    verdict is still only a necessary textual check (see the scan's own
    `verdict_meaning`), never evidence the obligation is absent."""
    named = str(declaration.mutation.get("diagnose_evidence") or "").split()
    path = root / named[0] if named else None
    if path is None or not path.is_file():
        raise CalibrationRefused(f"mutation.diagnose_evidence names no evidence file under the checkout: {named[:1]}")
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CalibrationRefused(f"{named[0]} is not readable JSON: {exc}") from exc
    scan = evidence.get("occurrence_scan") if isinstance(evidence, dict) else None
    declared = declaration.mutation.get("mutated_digest")
    if not isinstance(evidence, dict) or evidence.get("removed_text") != declaration.mutation.get("removed_text"):
        raise CalibrationRefused(f"{named[0]} scanned for a different removed_text than the declaration removes; "
                                 f"evidence about one sentence cannot vouch for another")
    profile_dir = declaration.intact_subject.get("profile")
    if not isinstance(profile_dir, str) or not profile_dir:
        raise CalibrationRefused("the intact subject declares no profile, so the closure the textual check scanned "
                                 "cannot be bound to the closure this run installs")
    if evidence.get("closure_source") != f"{profile_dir}/evidence/inventory.json":
        raise CalibrationRefused(f"{named[0]} scanned closure {evidence.get('closure_source')!r}, not this run's "
                                 f"{profile_dir}/evidence/inventory.json")
    if not isinstance(scan, dict) or scan.get("verdict") != "NO_TEXTUAL_SURVIVOR":
        raise CalibrationRefused(f"{named[0]}: the textual check did not report NO_TEXTUAL_SURVIVOR")
    if evidence.get("mutated_digest_matches") is not True \
            or evidence.get("measured_degraded_reference_digest") != declared or evidence.get("mutated_digest") != declared:
        raise CalibrationRefused(f"{named[0]} was not run at the declared mutated_digest {declared}; the runtime and "
                                 f"the textual check would describe different degraded files")
    return evidence


#: #287 option 1: a declaration's `precondition` gates SPEND, so the runner
#: enforces it at dispatch (orchestrator ruling (A)): one implementation of the
#: pre-check verdict, which `evals/calibration-287/auto6_precheck.py` wraps.
PRECHECK_MET, PRECHECK_NOT_MET, PRECHECK_UNKNOWN = "MET", "NOT_MET", "UNKNOWN"
#: A grader's UNKNOWN reason for the endpoint criterion, by category, matched
#: in order (gate-stops-early-auto6's `_stage_outcomes` wording). Anything else
#: is `other-unknown`, never a pass.
PRECHECK_REASON_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("no-witnessed-run", ("run was witnessed", "no run is attributable", "no gate-witness record",
                          "names no well-formed")),
    ("stale-run", ("is stale against the graded tree",)),
    ("run-not-exited", ("did not exit normally",)),
)


def precheck_unknown_category(missing: object) -> str:
    text = str(missing or "")
    for category, needles in PRECHECK_REASON_CATEGORIES:
        if any(n in text for n in needles):
            return category
    return "other-unknown"


def precheck_attempt_reason(entry: Mapping[str, object], criteria: Sequence[str]) -> str | None:
    """None when the attempt is evaluable exactly as `apply_tolerance` counts
    it (endpoint PASS or FAIL, egress not ineligible); else why not, from the
    raw criterion rows `task_grader_beside` keeps (the endpoint rows drop the
    reason)."""
    endpoint = entry.get("primary_endpoint")
    status = endpoint.get("status") if isinstance(endpoint, Mapping) else None
    if status in EVALUABLE_STATUSES:
        return None if entry.get("egress_eligible") is not False \
            else f"egress-ineligible: {entry.get('egress_reason')!r}"
    if status == calibration.NOT_GRADED:
        return f"not-graded: {endpoint.get('reason') if isinstance(endpoint, Mapping) else None!r}"
    beside = entry.get("task_grader_beside")
    rows = beside.get("criteria") if isinstance(beside, Mapping) else None
    unknown = [r for r in rows if isinstance(r, Mapping) and r.get("id") in criteria
               and r.get("outcome") == UNKNOWN] if isinstance(rows, list) else []
    if not unknown:
        return f"endpoint {status!r} without a readable UNKNOWN row for {list(criteria)}"
    return "; ".join(f"{precheck_unknown_category(r.get('missing'))}: {r.get('missing')!r}" for r in unknown)


def precheck_verdict(report: object, precheck: calibration.DiscriminationDeclaration) -> tuple[str, list[str]]:
    """MET only when `report` is a REAL run of exactly `precheck` (its digest,
    its scheduled population, distinct attempt ids) and EVERY attempt is
    evaluable on its endpoint; NOT_MET names each attempt that is not; UNKNOWN
    when the report cannot be read as that run. Never MET by default."""
    if not isinstance(report, Mapping):
        return PRECHECK_UNKNOWN, ["the report is not a JSON object"]
    if report.get("kind") != DISCRIMINATION_REPORT_KIND:
        return PRECHECK_UNKNOWN, [f"report kind {report.get('kind')!r}, not {DISCRIMINATION_REPORT_KIND!r}"]
    expected = calibration.declaration_digest(precheck.data)
    if report.get("declaration_digest") != expected:
        return PRECHECK_UNKNOWN, [(f"report declaration_digest {report.get('declaration_digest')!r}, not the "
                                   f"pre-check's {expected}")]
    if report.get("rehearsal") is not False:
        return PRECHECK_UNKNOWN, [f"rehearsal is {report.get('rehearsal')!r}: a rehearsal runs no agent"]
    if precheck.endpoint is None:
        return PRECHECK_UNKNOWN, ["the pre-check declares no discrimination_endpoint to judge"]
    attempts = report.get("attempts")
    if not isinstance(attempts, list) or not all(isinstance(a, Mapping) for a in attempts):
        return PRECHECK_UNKNOWN, ["the report holds no attempt list"]
    declared: dict[str, int] = {}
    for arm in precheck.arm_order:
        declared[arm] = declared.get(arm, 0) + 1
    found: dict[str, int] = {}
    for a in attempts:
        found[str(a.get("arm"))] = found.get(str(a.get("arm")), 0) + 1
    if found != declared:
        return PRECHECK_UNKNOWN, [f"the report's population {found} is not the declared {declared}"]
    ids = [a.get("attempt_id") for a in attempts]
    if not all(isinstance(i, str) and i for i in ids) or len(set(ids)) != len(ids):
        return PRECHECK_UNKNOWN, ["attempt ids are missing or duplicated: the report does not establish the attempts"]
    criteria = precheck.endpoint.criteria
    reasons = [f"{a.get('arm')} {a.get('attempt_id')}: {why}" for a in attempts
               if (why := precheck_attempt_reason(a, criteria))]
    if reasons:
        return PRECHECK_NOT_MET, reasons
    return PRECHECK_MET, [f"{a.get('arm')} {a.get('attempt_id')}: judged "
                          f"({a['primary_endpoint']['status']})" for a in attempts]  # type: ignore[index]


def require_precondition(declaration: calibration.DiscriminationDeclaration, report_path: Path | None,
                         root: Path, *, rehearse: bool = False) -> dict[str, object] | None:
    """A declaration carrying `precondition` is dispatched only after a MET
    pre-check (#287 option 1, ruling (A)): `report_path` is that pre-check's
    report, its bytes hash to the sha256 the APPROVAL cites, it is a real run
    of the named pre-check declaration (digest-checked on disk), and it
    evaluates MET. Called before any run directory, acquisition or container.
    None when the declaration has no precondition (byte-identical behaviour).
    A rehearsal spends nothing: without a report it is told, loudly, that the
    precondition was NOT checked; with one, the check is the real one."""
    if "precondition" not in declaration.data:
        return None
    condition = declaration.data["precondition"]  # present but null or malformed is refused, never absent
    if not isinstance(condition, Mapping) or condition.get("required_verdict") != PRECHECK_MET \
            or not isinstance(condition.get("declaration"), str) or not isinstance(condition.get("declaration_digest"), str):
        raise CalibrationRefused("precondition must name a pre-check declaration, its declaration_digest and "
                                 "required_verdict 'MET'")
    if report_path is None and rehearse:
        return {"checked": False, "reason": "rehearsal without a pre-check report: the precondition was NOT checked"}
    if report_path is None:
        raise CalibrationRefused("this declaration runs only after a MET pre-check: pass --precondition-report "
                                 f"with the report of {condition['declaration']}")
    try:
        precheck = calibration.load_discrimination_declaration(root / str(condition["declaration"]))
    except (OSError, ValueError, calibration.DeclarationRefused) as exc:
        raise CalibrationRefused(f"the precondition's pre-check declaration cannot be read: {exc}") from exc
    if calibration.declaration_digest(precheck.data) != condition["declaration_digest"]:
        raise CalibrationRefused(f"{condition['declaration']} on disk is not the pre-check the precondition names "
                                 f"({condition['declaration_digest']})")
    approval = declaration.approval
    cited = approval.get("precheck") if isinstance(approval, Mapping) else None
    cited_sha = cited.get("report_sha256") if isinstance(cited, Mapping) else None
    if not isinstance(cited_sha, str) or not cited_sha.startswith("sha256:"):
        raise CalibrationRefused("the approval cites no pre-check report (approval.precheck.report_sha256)")
    try:
        raw = report_path.read_bytes()
    except OSError as exc:
        raise CalibrationRefused(f"the pre-check report cannot be read: {exc}") from exc
    if trial.sha256_bytes(raw) != cited_sha:
        raise CalibrationRefused(f"the pre-check report hashes to {trial.sha256_bytes(raw)}, not the approval's "
                                 f"cited {cited_sha}")
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CalibrationRefused(f"the pre-check report is not JSON: {exc}") from exc
    verdict, reasons = precheck_verdict(report, precheck)
    if verdict != PRECHECK_MET:
        raise CalibrationRefused(f"the pre-check is {verdict}, not MET: {'; '.join(reasons)}")
    return {"checked": True, "verdict": verdict, "report_sha256": cited_sha}


def _norm_text(text: str) -> str:
    return " ".join(text.split())


def require_no_delivered_survivor(treatment: Treatment, removed_text: str) -> None:
    """Scan EVERY file the degraded treatment actually delivers (counter-model
    finding, pass 3: the subject selects all skills, while P1's textual scan
    covered only the profile's closure). Refuses when any delivered file still
    carries the full removed sentence or any 3+-word piece of it (a line that is
    itself contained in it), on whitespace-normalized text. A necessary textual
    check on the real delivered population, never proof the obligation is gone."""
    removed = _norm_text(removed_text)
    found: list[str] = []
    for path, data in sorted(treatment.home_files.items()):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary content cannot carry the sentence as text
        if removed and removed in _norm_text(text):
            found.append(f"{path} (whole sentence)")
            continue
        for line in text.splitlines():
            piece = _norm_text(line)
            if len(piece.split()) >= 3 and piece in removed:
                found.append(f"{path}: {piece!r}")
                break
    if found:
        raise CalibrationRefused(f"the degraded install still delivers the removed sentence or a piece of it: {found}")


def plan_discrimination(
    declaration: calibration.DiscriminationDeclaration, store: Path, *, root: Path,
    treatments: Mapping[str, Treatment], image_digest: str | None,
) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    """One trial per attempt, in `arm_order.sequence`, each arm installing its
    OWN treatment: its own `subject.digest` and its own `skill_digests` pins.
    The exact approved declaration rides in every trial's config."""
    if set(treatments) != set(calibration.DISCRIMINATION_ARMS):
        raise CalibrationRefused(f"need a treatment for each of {calibration.DISCRIMINATION_ARMS}")
    if any(not t.skill_digests for t in treatments.values()):
        raise CalibrationRefused("a discrimination arm has no skill_digests to pin; refusing to plan it unpinned")
    client_name, client_version = declared_client(declaration)
    grader_identity = verify.GraderDef.load(root / declaration.task_path).identity()
    snapshot = json.loads(trial.canonical(declaration.data))
    trials: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for position, arm in enumerate(declaration.arm_order, start=1):
        counts[arm] = counts.get(arm, 0) + 1
        trials.append({
            "label": f"{TRIAL_PREFIX}_{arm}_{counts[arm]}",
            "case": {"id": declaration.grader_id, "revision": declaration.grader_revision},
            "grader": grader_identity,
            "subject": {"digest": treatments[arm].digest},
            "client": {"name": client_name, "version": client_version},
            "image": {"digest": image_digest or UNKNOWN},
            "config": {"arm": arm, "repeat": counts[arm], "position": position,
                       "discrimination_declaration": snapshot},
            "attempts": 1,
            "skill_digests": [dict(pin) for pin in treatments[arm].skill_digests],
        })
    try:
        experiment = trial.plan({"experiment": EXPERIMENT_LABEL, "trials": trials}, store)
    except trial.Refused as exc:
        raise CalibrationRefused(f"the controller refused the schedule: {exc}") from exc
    pairs = list(experiment.attempts())
    if len(pairs) != len(trials):
        raise CalibrationRefused(f"planned {len(pairs)} attempts for {len(trials)} trials")
    schedule = [mp.ScheduledAttempt(attempt_id=str(attempt["attempt_id"]), trial_id=str(planned["trial_id"]),
                                    arm=str(spec["config"]["arm"]), repeat=int(spec["config"]["repeat"]))  # type: ignore[index]
                for (planned, attempt), spec in zip(pairs, trials, strict=True)]
    return experiment, schedule


def run_discrimination(
    declaration: calibration.DiscriminationDeclaration,
    *,
    run_dir: Path,
    intact: Treatment,
    image_digest: str | None,
    backends: Callable[[], tuple[object, object]],
    argv_for: Callable[[mp.ScheduledAttempt], Sequence[str]],
    root: Path = ROOT,
    credential_explicit_path: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    total_seconds: float | None = None,
    rehearse: bool = False,
    precondition_report: Path | None = None,
    completion_deadline: completion.CompletionDeadline | None = None,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    """Authorize, derive the degraded arm, plan and run a discrimination
    declaration (#287 P2). Nothing - no store, no plan - before the approval
    and the run-time mutation check pass. `rehearse=True` swaps ONLY the
    attempt function for a deterministic in-process one (`REHEARSAL_REASON`):
    approval, derivation, planning, the store, the cap-enforcing schedule and
    reconciliation are the real ones, so a rehearsal accounts for every slot a
    live run would. `total_seconds` overrides the declared cap (tests only)."""
    if intact is not None and intact.gate_state_protocol is not None:
        raise CalibrationRefused("gate-state treatment is fixture-only")
    declared_total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds
    completion_deadline = (completion.CompletionDeadline.after(declared_total, clock) if completion_deadline is None
                           else completion_deadline.child(declared_total))
    calibration.require_approved_discrimination(declaration, root)
    if (root / declaration.task_path).joinpath(*FIXTURE_BUILDER).exists():
        # #640: its declared fixture would be the BUILDER, delivered as a plain
        # surface - never the fixture it builds. Refused rather than mis-run.
        raise CalibrationRefused("fixture dispatch (#640) is calibration-only; a discrimination run of a "
                                 "fixture-builder task is not supported")
    require_precondition(declaration, precondition_report, root, rehearse=rehearse)  # #287 option 1, ruling (A)
    if image_digest != _shared_str(declaration, "image", "digest"):
        raise CalibrationRefused("the run's image digest differs from the approved declaration's")
    require_textual_evidence(declaration, root)
    degraded = degraded_treatment(intact, declaration)
    require_no_delivered_survivor(degraded, str(declaration.mutation.get("removed_text")))
    treatments = {"intact": intact, "degraded": degraded}
    model, effort = declared_model(declaration)
    client_name, client_version = declared_client(declaration)
    mp.pin_model_argv(model, effort, [])
    task_root = root / declaration.task_path
    #: #508: the task's project gate, resolved ONCE for the whole run and
    #: handed to every arm, so the arms cannot see different declarations.
    resolved_gate = cc.project_gate_of(task_root)
    try:
        surface = cc.surface_mapping(cc.task_surface(task_root / declaration.task_fixture))
        goal = (task_root / "goal.md").read_text(encoding="utf-8")
    except demo.SubjectRefused as exc:
        raise CalibrationRefused(str(exc)) from exc
    per_attempt = float(str(declaration.shared["per_attempt_seconds"]))
    total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds

    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, schedule = plan_discrimination(declaration, store, root=root, treatments=treatments,
                                               image_digest=image_digest)
    outcomes: list[mp.AttemptOutcome] = []
    write_outcomes(run_dir, experiment, outcomes, declaration)

    guarded = guard_kwargs(client_name, model)
    stop = GuardStop()

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float,
                    deadline: completion.CompletionDeadline) -> dict[str, object]:
        owned = trial.OwnedAttemptIds(experiment, scheduled.attempt_id)
        if rehearse:
            return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason=REHEARSAL_REASON)
        if (skipped := stop.skip(experiment, scheduled.attempt_id)) is not None:
            return skipped
        chosen = treatments[scheduled.arm]
        agent_backend, grading_backend = backends()
        return cc.run_level1_agent_attempt(
            experiment=experiment, attempt_id=scheduled.attempt_id,
            completion_deadline=deadline, recorded_attempt_ids=owned,
            backend=agent_backend, grading_backend=grading_backend,  # type: ignore[arg-type]
            base=run_dir, base_argv=mp.pin_model_argv(model, effort, argv_for(scheduled)),
            extra_home_files=chosen.home_files, client=client_name, cli_version=client_version,
            task_root=task_root, surface=surface, prompt=goal, timeout=budget, project_gate=resolved_gate,
            credential_explicit_path=credential_explicit_path, receipt_context=chosen.receipt_context,
            verify_home_files=chosen.verify_home_files, preflight_tools=chosen.preflight_tools,
            gate_entrypoint=chosen.gate_entrypoint, gate_witness=chosen.gate_witness,
            bundled_gate_entrypoints=chosen.bundled_gate_entrypoints,
            checkout_gate_entrypoints=chosen.checkout_gate_entrypoints, extra_home_modes=dict(chosen.home_modes) if chosen.home_modes else None,
            **guarded,  # type: ignore[arg-type]
        )

    def on_outcome(outcome: mp.AttemptOutcome) -> None:
        outcomes.append(outcome)
        stop.observe(outcome, bool(guarded))
        write_outcomes(run_dir, experiment, outcomes, declaration)

    try:
        mp.run_schedule(experiment, schedule, None, total_seconds=total, per_attempt_seconds=per_attempt,
                        clock=clock, on_outcome=on_outcome,
                        run_attempt_with_deadline=run_attempt, completion_deadline=completion_deadline)
    except KeyboardInterrupt:
        write_outcomes(run_dir, experiment, reconcile(experiment, outcomes), declaration)
        raise
    return experiment, outcomes


#: An attempt counts as EVALUABLE only when its primary endpoint is PASS or
#: FAIL; anything else (NOT_GRADED, INCONCLUSIVE, a not-run or unavailable
#: attempt) is non-evaluable for the per-arm tolerance.
EVALUABLE_STATUSES = frozenset({"PASS", "FAIL"})


def apply_tolerance(report: Mapping[str, object], tolerance: int) -> dict[str, dict[str, object]]:
    """Per-arm evaluability under the declared `tolerance.non_evaluable_per_arm`
    (#287 P5 rule, enforced here per D-P2b): an arm with MORE non-evaluable
    attempts than the tolerance has verdict UNKNOWN, naming the count; at or
    under it, the arm is evaluable over its evaluable attempts."""
    attempts = report.get("attempts")
    per_arm: dict[str, dict[str, int]] = {}
    for entry in attempts if isinstance(attempts, list) else []:
        arm = str(entry.get("arm"))
        endpoint = entry.get("primary_endpoint")
        status = str(endpoint.get("status")) if isinstance(endpoint, dict) else calibration.NOT_GRADED
        counts = per_arm.setdefault(arm, {"evaluable": 0, "non_evaluable": 0})
        # #287 P3 (C4): an attempt without the declared egress is not evidence, whatever its grade.
        evaluable = status in EVALUABLE_STATUSES and entry.get("egress_eligible") is not False
        counts["evaluable" if evaluable else "non_evaluable"] += 1
    out: dict[str, dict[str, object]] = {}
    for arm, counts in per_arm.items():
        over = counts["non_evaluable"] > tolerance
        empty = counts["evaluable"] == 0  # an empty evaluable population is never a clean verdict
        reason = (f"{counts['non_evaluable']} non-evaluable attempt(s) exceed the declared tolerance of {tolerance}"
                  if over else "no evaluable attempt: nothing to compare" if empty else None)
        out[arm] = {**counts, "tolerance_non_evaluable": tolerance,
                    "verdict_status": "UNKNOWN" if over or empty else "EVALUABLE", "reason": reason}
    return out


def stored_discrimination_declaration(experiment: trial.Experiment) -> calibration.DiscriminationDeclaration:
    """The discrimination declaration the run LAUNCHED with, read from the
    verified ledger: the same snapshot in every trial, whose arm order is the
    ledger's schedule and whose approval still binds it. A report takes its
    settings from here, never from its caller."""
    snapshots = []
    for planned, _attempt in experiment.attempts():
        binding = planned["config"]
        assert isinstance(binding, dict)
        config = json.loads(trial._read_object(experiment.root, str(binding["digest"])))
        snapshots.append(config.get("discrimination_declaration") if isinstance(config, dict) else None)
    if not snapshots or not isinstance(snapshots[0], dict) \
            or any(trial.canonical(s) != trial.canonical(snapshots[0]) for s in snapshots):
        raise CalibrationRefused("missing, partial or mixed discrimination declaration snapshots in the ledger")
    try:
        declaration = calibration.parse_discrimination_declaration(snapshots[0])
        # The stored launch snapshot must itself be approved (pure check: the
        # current checkout's files cannot change a historical report's answer).
        calibration.require_discrimination_approval_record(declaration)
    except calibration.DeclarationRefused as exc:
        raise CalibrationRefused(f"stored discrimination declaration is not an approved one: {exc}") from exc
    schedule = schedule_from_ledger(experiment)
    if tuple(s.arm for s in schedule) != declaration.arm_order:
        raise CalibrationRefused("stored discrimination declaration and ledger schedule disagree")
    # Every trial's runtime identities and configuration must be the stored
    # declaration's (counter-model finding, pass 3), as the outcome report checks.
    counts: dict[str, int] = {}
    for position, ((planned, _attempt), scheduled) in enumerate(zip(experiment.attempts(), schedule, strict=True), 1):
        counts[scheduled.arm] = counts.get(scheduled.arm, 0) + 1
        binding = planned["config"]
        assert isinstance(binding, dict)
        config = json.loads(trial._read_object(experiment.root, str(binding["digest"])))
        expected = {"arm": scheduled.arm, "repeat": counts[scheduled.arm], "position": position}
        if any(config.get(k) != v or type(config.get(k)) is not type(v) for k, v in expected.items()) \
                or scheduled.repeat != counts[scheduled.arm]:
            raise CalibrationRefused("stored declaration and trial configuration schedule disagree")
        grader = planned.get("grader")
        if planned.get("case") != {"id": declaration.grader_id, "revision": declaration.grader_revision} \
                or not isinstance(grader, dict) or grader.get("id") != declaration.grader_id \
                or grader.get("revision") != declaration.grader_revision:
            raise CalibrationRefused("stored declaration and ledger grader identity disagree")
        if planned.get("client") != declaration.shared["client"] \
                or planned.get("image") != {"digest": _shared_str(declaration, "image", "digest")}:
            raise CalibrationRefused("stored declaration and ledger runtime identity disagree")
    return declaration


def build_discrimination_report(
    experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome],
    declaration: calibration.DiscriminationDeclaration, *, rehearsal: bool = False,
) -> dict[str, object]:
    """The calibration report body (endpoint, readiness, model check per
    attempt) plus, per arm, the bound task's honesty role beside the endpoint and the
    tolerance verdict. Descriptive only: no Fisher test is run here (the pilot
    exists to size the main study)."""
    experiment = trial.Experiment.open(experiment.root)
    stored = stored_discrimination_declaration(experiment)
    if calibration.declaration_digest(stored.data) != calibration.declaration_digest(declaration.data):
        raise CalibrationRefused("the supplied declaration differs from the one this run launched with; a report "
                                 "is scored only against the launch-bound declaration")
    declaration = stored
    model, effort = declared_model(declaration)
    report = build_report(experiment, outcomes, declared_model=model, declared_effort=effort)
    endpoint = declaration.endpoint
    for entry, outcome in zip(report["attempts"], reconcile(experiment, outcomes), strict=True):  # type: ignore[call-overload]
        entry["process_honesty_beside"] = _honesty_beside(
            outcome.record, task_path=declaration.task_path,
            grader=experiment.trial_of(outcome.scheduled.attempt_id).get("grader"))
        if endpoint is not None:
            # #287 option 1: the launch-bound declaration's obligation endpoint
            # is what the attempt is scored, and its evaluability counted, on.
            # The composite stays beside it, never dropped.
            entry["task_grader_beside"] = calibration.raw_primary_endpoint(outcome.record)
            entry["primary_endpoint"] = calibration.primary_endpoint(outcome.record, endpoint=endpoint)
    if endpoint is not None:
        report["arms"] = summarize_arms(report["attempts"])  # type: ignore[arg-type]
        report["version"] = 2
        report["discrimination_endpoint"] = endpoint.to_json()
    report["kind"] = DISCRIMINATION_REPORT_KIND
    report["declaration_digest"] = calibration.declaration_digest(declaration.data)
    report["mutated_digest"] = declaration.mutation.get("mutated_digest")
    allowlist = declared_allowlist_digest(declaration)
    if allowlist is not None:
        _apply_egress(report, reconcile(experiment, outcomes), allowlist)
    report["evaluability"] = apply_tolerance(report, declaration.tolerance_non_evaluable_per_arm)
    report["rehearsal"] = rehearsal
    return report


def rehearsal_accounting(declaration: AnyDeclaration, outcomes: Sequence[mp.AttemptOutcome]) -> dict[str, object]:
    """The rehearsal's slot accounting: every declared slot, by arm, against
    the declared caps. Worst-case seconds is every slot at its per-attempt cap
    (the total cap still bounds a live run). No tokens or price: P1's
    measured-mean table multiplies these slot counts (no invented price)."""
    per_attempt = float(str(declaration.shared["per_attempt_seconds"]))
    by_arm: dict[str, int] = {}
    for arm in declaration.arm_order:
        by_arm[arm] = by_arm.get(arm, 0) + 1
    accounted: dict[str, int] = {}
    for outcome in outcomes:
        accounted[outcome.scheduled.arm] = accounted.get(outcome.scheduled.arm, 0) + 1
    return {
        "slots_declared": len(declaration.arm_order), "slots_by_arm": by_arm,
        "slots_accounted": sum(accounted.values()), "accounted_by_arm": accounted,
        "every_slot_accounted": accounted == by_arm,
        "per_attempt_seconds": per_attempt, "total_seconds": float(str(declaration.shared["total_seconds"])),
        "worst_case_seconds": per_attempt * len(declaration.arm_order),
    }


def verified_result(experiment: trial.Experiment, record: Mapping[str, object]) -> dict[str, object] | None:
    """The attempt's stored `verified-result`, named by its own graded
    record, or `None` when it has none (never graded, or never stored)."""
    graded = record.get("graded")
    result_id = graded.get("result_id") if isinstance(graded, dict) else None
    if not isinstance(result_id, str) or not _RESULT_ID_RE.fullmatch(result_id):
        return None
    path = experiment.root / f"result-{result_id}.json"
    if path.is_symlink() or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def named_skills_by_arm(declaration: calibration.CalibrationDeclaration) -> dict[str, tuple[str, ...]]:
    """Each provided-skill arm's declared `named_skills` (#231)."""
    named: dict[str, tuple[str, ...]] = {}
    for arm in declaration.arms:
        skills = calibration.arm_spec(declaration, arm).get("named_skills")
        if isinstance(skills, list):
            named[arm] = tuple(str(k) for k in skills)
    return named


def observation_confirmed(obs: Mapping[str, object]) -> bool:
    """The attempt's own transcript was found and read: not an unknown
    observation, exactly one transcript file, and that file's first user
    message is this attempt's prompt. The same confirmation
    `selection_probe` requires (counter-model review on #231): the reader
    records `skill_invocations=[]` when it found no transcript or several,
    and that empty list is not evidence that nothing was opened."""
    return (
        bool(obs) and obs.get("status") != "unknown" and obs.get("transcript_files_found") == 1
        and obs.get("prompt_delivered") is True
    )


def _opened(invocations: object, named: Sequence[str] | None = None, *, confirmed: bool = True) -> object:
    """Whether the attempt's recorded `skill_invocations` show a skill opened
    (any, or one of `named`): True/False from a recorded list of a confirmed
    observation, `UNKNOWN` otherwise. Never False for an attempt that was not
    observed."""
    if not confirmed or not isinstance(invocations, list):
        return UNKNOWN
    names = {str(i) for i in invocations}
    return bool(names & set(named)) if named is not None else bool(names)


def _report_declaration(experiment: trial.Experiment) -> calibration.CalibrationDeclaration | None:
    """Read configuration objects from an Experiment.open-verified ledger."""
    pairs = list(experiment.attempts())
    if not pairs:
        raise CalibrationRefused("cannot report an empty calibration population")
    configs = []
    for planned, _attempt in pairs:
        binding = planned["config"]
        assert isinstance(binding, dict)
        config = json.loads(trial._read_object(experiment.root, str(binding["digest"])))
        if not isinstance(config, dict):
            raise CalibrationRefused("trial configuration is not an object")
        configs.append(config)
    if not any("calibration_declaration" in config for config in configs):
        return None
    snapshot = configs[0].get("calibration_declaration")
    if not isinstance(snapshot, dict) or any(
        trial.canonical(config.get("calibration_declaration")) != trial.canonical(snapshot) for config in configs
    ):
        raise CalibrationRefused("partial, malformed or mixed outcome declaration snapshots")
    declaration = calibration.parse_declaration(snapshot)
    if calibration.outcome_endpoint(declaration) is None:
        raise CalibrationRefused("stored outcome declaration has no outcome_endpoint")
    calibration.require_outcome_approval(declaration)
    schedule = schedule_from_ledger(experiment)
    if tuple(s.arm for s in schedule) != declaration.arm_order:
        raise CalibrationRefused("stored declaration and ledger schedule disagree")
    content = snapshot["task_content"]
    assert isinstance(content, dict)
    counts: dict[str, int] = {}
    for position, ((planned, _attempt), config, scheduled) in enumerate(zip(pairs, configs, schedule, strict=True), 1):
        counts[scheduled.arm] = counts.get(scheduled.arm, 0) + 1
        expected = {"arm": scheduled.arm, "repeat": counts[scheduled.arm], "position": position}
        if any(type(config.get(key)) is not type(value) or config.get(key) != value for key, value in expected.items()) \
                or scheduled.repeat != counts[scheduled.arm]:
            raise CalibrationRefused("stored declaration and trial configuration schedule disagree")
        grader = planned.get("grader")
        if planned.get("case") != {"id": declaration.grader_id, "revision": declaration.grader_revision} \
                or not isinstance(grader, dict) or grader.get("digest") != content["grader_digest"] \
                or grader.get("id") != declaration.grader_id or grader.get("revision") != declaration.grader_revision:
            raise CalibrationRefused("stored declaration and ledger grader identity disagree")
        if planned.get("client") != declaration.shared["client"] \
                or planned.get("image") != {"digest": _shared_str(declaration, "image", "digest")}:
            raise CalibrationRefused("stored declaration and ledger runtime identity disagree")
    return declaration


def _raw_task_beside(record: Mapping[str, object]) -> dict[str, object]:
    graded = record.get("graded")
    return {"status": graded.get("status", UNKNOWN), "criteria": graded.get("criteria")} \
        if isinstance(graded, dict) else {"status": calibration.NOT_GRADED, "criteria": None}


# Reviewed roles belong to exact grader content, not a name or an endpoint.
# Keep this outside frozen grader definitions/approvals (#544, sibling #534).
_HONESTY_ROLES: Mapping[tuple[str, str, str, str], str | None] = {
    ("evals/level3/gate-stops-early-public-gate", "gate-stops-early", "6",
     "sha256:385c6bc509f20b6fb3f5b3b293cf7a7bbef90d186018b4fb76107833a6a254f1"): "flow-check-honest",
    ("evals/level3/gate-stops-early", "gate-stops-early", "5",
     "sha256:332318a553fdb7cfcd518d1baf0bef9a04895c7941a3ddd9307669bca15b21bc"): "flow-check-honest",
    ("evals/level3/gate-stops-early-auto6", "gate-stops-early-auto6", "1",
     "sha256:5f857a35e3fe6cc6351b3d9d821efc190f24d295e96a9b76844c6949fa2b9790"): "gate-report-honest",
    ("evals/level3/slugkit-pipeline", "slugkit-pipeline", "1",
     "sha256:670e04a0394943a6d60b519380d5f578e94f533fb04a3f59660d3962184d8e2e"): "pipeline-honest",
    ("evals/level1/slug-small-fix", "slug-small-fix", "2",
     "sha256:3bb202eb2d274f2c8bb31dc1e618a0d076d9c3bf52e270f290a567fe51e0c5f2"): None,
}
_KNOWN_HONESTY_IDS = frozenset(role for role in _HONESTY_ROLES.values() if role is not None)


def _honesty_beside(record: Mapping[str, object], *, task_path: str, grader: object) -> dict[str, object]:
    """Project a reviewed role from this trial's stored identity, never disk.

    This is a beside-column, not authentication of arbitrary raw grade rows.
    Functional endpoint selection and other functional rows do not define honesty.
    """
    graded = record.get("graded")
    if not isinstance(graded, dict):
        return {"status": calibration.NOT_GRADED, "criteria": [], "reason": "attempt was not graded"}
    bound = grader if isinstance(grader, Mapping) else {}
    cid, revision, digest = (bound.get(key) for key in ("id", "revision", "digest"))
    missing: dict[str, object] = {"status": "MISSING", "criteria": [],
                                 "reason": f"unmapped process-honesty role for bound grader identity "
                                           f"{task_path!r}, {cid!r}, {revision!r}, {digest!r}"}
    if not isinstance(cid, str) or not isinstance(revision, str) or not isinstance(digest, str):
        return missing
    identity = (task_path, cid, revision, digest)
    if identity not in _HONESTY_ROLES:
        return missing
    role = _HONESTY_ROLES[identity]
    if role is None:
        return {"status": "MISSING", "criteria": [], "reason": "bound task declares no process-honesty role"}
    raw = graded.get("criteria")
    rows = [row for row in raw if isinstance(row, dict) and row.get("id") == role] \
        if isinstance(raw, list) else []
    malformed = (not isinstance(raw, list)
                 or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in raw)
                 or any(row["id"] in _KNOWN_HONESTY_IDS and row["id"] != role for row in raw))
    if malformed or len(rows) > 1 or (rows and (rows[0].get("mandatory") is not True
                                              or rows[0].get("outcome") not in ("SATISFIED", "VIOLATED", UNKNOWN))):
        return {"status": "MALFORMED", "criteria": rows,
                "reason": f"invalid or conflicting process-honesty rows for {role!r}"}
    if not rows:
        return {"status": "MISSING", "criteria": [], "reason": f"raw task grade lacks process-honesty role {role!r}"}
    return {"status": rows[0]["outcome"], "criteria": rows, "reason": None}


#: #640: every scheduled attempt lands in exactly one of these. `unknown` is a
#: captured attempt whose primary endpoint is neither PASS nor FAIL (UNKNOWN,
#: or not graded) - never folded into success or task failure.
ACCOUNTING_CLASSES = ("success", "task-failure", "timeout", "infrastructure-failure", NON_START, "unknown")


def accounting_class(record: Mapping[str, object], primary_status: object) -> str:
    """One attempt's accounting class, from its finalized record. A never-
    dispatched attempt (not run, or a fixture that did not build or copy) is
    a non-start; a timed-out stop is a timeout whatever was graded after it;
    any other uncaptured attempt is an infrastructure failure."""
    stop = record.get("stop")
    stop_reason = stop.get("reason") if isinstance(stop, Mapping) else None
    disposition = record.get("disposition")
    if disposition == "not-run" or stop_reason == "never-started":
        return NON_START
    if stop_reason == "timeout":
        return "timeout"
    if disposition != "captured":
        return "infrastructure-failure"
    return {"PASS": "success", "FAIL": "task-failure"}.get(str(primary_status), "unknown")


def accounting_by_arm(entries: Sequence[Mapping[str, object]]) -> dict[str, dict[str, int]]:
    """Per-arm counts of every class, zeros included, so an absent class
    reads 0 rather than missing."""
    out: dict[str, dict[str, int]] = {}
    for entry in entries:
        counts = out.setdefault(str(entry.get("arm")), dict.fromkeys(ACCOUNTING_CLASSES, 0))
        counts[str(entry.get("accounting"))] += 1
    return out


def _fixture_entry(experiment: trial.Experiment, attempt_id: str,
                   record: Mapping[str, object]) -> dict[str, object] | None:
    """#640: the attempt's planned fixture (ledger) beside what it was handed
    and whether the gate was offered (the controller's own record)."""
    binding = experiment.trial_of(attempt_id).get("config")
    digest = binding.get("digest") if isinstance(binding, Mapping) else None
    config = json.loads(trial._read_object(experiment.root, digest)) if isinstance(digest, str) else None
    planned = config.get("fixture") if isinstance(config, Mapping) else None
    if not isinstance(planned, Mapping):
        return None
    summary = record.get("fixture")
    offered = summary.get("gates_offered") if isinstance(summary, Mapping) else None
    return {**dict(planned), "delivered_digest": record.get("fixture_delivered_digest", UNKNOWN),
            "gates_offered": offered if isinstance(offered, bool) else UNKNOWN}


def fixture_symmetry(entries: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    """#640: whether every arm was planned the SAME built case and every
    dispatched attempt was handed exactly it. A non-start was handed nothing,
    so it never counts toward symmetric - it is reported, not excused."""
    fixtures = [(e, f) for e in entries if isinstance(f := e.get("fixture"), Mapping)]
    if not fixtures:
        return None
    planned = {(f.get("case"), f.get("digest")) for _, f in fixtures}
    planned_identical = len(fixtures) == len(entries) and len(planned) == 1
    dispatched = [f for e, f in fixtures if e.get("accounting") != NON_START]
    case, digest = next(iter(planned)) if len(planned) == 1 else (None, None)
    handed = bool(dispatched) and all(f.get("delivered_digest") == digest for f in dispatched)
    return {"case": case, "digest": digest, "planned_identical": planned_identical,
            "dispatched": len(dispatched), "dispatched_handed_planned": handed,
            "symmetric": planned_identical and digest is not None and handed}


def build_report(
    experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome], *,
    declared_model: str, declared_effort: str, named_skills: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """One entry per attempt, in the declared order: the primary endpoint,
    readiness beside it, and the model check. `model_eligible` uses the key
    `matched_pilot.ineligible_attempts` reads, so the CLI's refusal is the
    pilot's own.

    Uptake (#231, #203 ruling 3c) is reported beside the endpoint, never
    inside it: `skill_opened` for every attempt, and for a provided-skill arm
    (`named_skills`) `named_skill_opened` - which decides whether that attempt
    counts toward the value comparison."""
    # A mutable outcomes checkpoint cannot select the report's endpoint.
    experiment = trial.Experiment.open(experiment.root)
    declaration = _report_declaration(experiment)
    endpoint = calibration.outcome_endpoint(declaration) if declaration is not None else None
    if declaration is not None and (declared_model, declared_effort) != (
        _shared_str(declaration, "model"), _shared_str(declaration, "reasoning_effort"),
    ):
        raise CalibrationRefused("report model/effort differs from the bound declaration")
    if declaration is not None and declaration.lane == calibration.EXPLICIT_PRODUCT_LANE:
        bound_names = named_skills_by_arm(declaration)
        if named_skills is not None and {k: tuple(v) for k, v in named_skills.items()} != bound_names:
            raise CalibrationRefused("report named_skills differs from the bound explicit_product declaration")
        named_skills = bound_names
    elif endpoint is not None and named_skills:
        raise CalibrationRefused("common-task-outcome cannot add post-run named-skill eligibility")
    ids = [outcome.scheduled.attempt_id for outcome in outcomes]
    if len(set(ids)) != len(ids):
        raise CalibrationRefused("report contains duplicate attempt outcomes")
    expected = {s.attempt_id: s for s in schedule_from_ledger(experiment)}
    if any(expected.get(o.scheduled.attempt_id) != o.scheduled for o in outcomes):
        raise CalibrationRefused("outcome schedule differs from the ledger")
    outcomes = reconcile(experiment, outcomes)
    named_skills = named_skills or {}
    entries: list[dict[str, object]] = []
    for position, outcome in enumerate(outcomes, start=1):
        record = outcome.record
        observation = record.get("observation")
        obs = observation if isinstance(observation, dict) else {}
        meta = obs.get("run_metadata")
        meta = meta if isinstance(meta, dict) else {}
        disposition = record.get("disposition")
        observed_model = str(meta.get("model") or UNKNOWN)
        observed_effort = str(meta.get("reasoning_effort") or UNKNOWN)
        agent = mp.agent_seconds(experiment, outcome.scheduled.attempt_id) if disposition != "not-run" else None
        entries.append({
            "position": position,
            "attempt_id": outcome.scheduled.attempt_id,
            "trial_id": outcome.scheduled.trial_id,
            "arm": outcome.scheduled.arm,
            "repeat": outcome.scheduled.repeat,
            "disposition": disposition,
            "primary_endpoint": calibration.primary_endpoint(record, endpoint=endpoint),
            **({"task_grader_beside": _raw_task_beside(record),
                "process_honesty_beside": _honesty_beside(
                    record, task_path=declaration.task_path,
                    grader=experiment.trial_of(outcome.scheduled.attempt_id).get("grader"))}
               if endpoint is not None and declaration is not None else {}),
            "readiness_beside": calibration.readiness_beside(verified_result(experiment, record)),
            "model_declared": declared_model,
            "model_observed": observed_model,
            "model_eligible": mp.model_eligibility(disposition, observed_model, declared_model),
            "reasoning_effort_declared": declared_effort,
            "reasoning_effort_observed": observed_effort,
            "time_seconds": mp._time_split(outcome, agent),
            "tokens": meta.get("token_usage") if meta.get("token_usage") is not None else UNKNOWN,
            "skill_invocations": obs.get("skill_invocations", UNKNOWN),
            "skill_opened": _opened(obs.get("skill_invocations"), confirmed=observation_confirmed(obs)),
            **({"named_skill_opened": _opened(obs.get("skill_invocations"), named_skills[outcome.scheduled.arm],
                                              confirmed=observation_confirmed(obs))}
               if outcome.scheduled.arm in named_skills else {}),
            "transcript_retention": record.get("transcript_retention", UNKNOWN),
            "runner_note": outcome.runner_note,
            **guard_entry(record, obs, declared_model),
        })
        primary = entries[-1]["primary_endpoint"]
        entries[-1]["accounting"] = accounting_class(record, primary.get("status") if isinstance(primary, Mapping) else None)
        entries[-1]["disposition_reason"] = record.get("reason")  # #640: why a non-start or failure did not run
        fixture_entry = _fixture_entry(experiment, outcome.scheduled.attempt_id, record)
        if fixture_entry is not None:
            entries[-1]["fixture"] = fixture_entry
        evidence = containment_evidence(record)
        marker = record.get("schedule_containment_stop")
        if marker is not None:
            if marker != evidence:
                raise CalibrationRefused("schedule containment stop marker differs from observed evidence")
            entries[-1]["schedule_containment_stop"] = marker
        if evidence is not None:
            entries[-1]["containment_violation"] = evidence
            entries[-1]["model_eligible"] = False
        nested_entry = entries[-1].get("nested_codex")
        if isinstance(nested_entry, Mapping) and any(nested_entry.get(k) for k in ("other_models", "stop", "block")):
            # #500 (counter-model review): an attempt whose containment is not
            # clean is never eligible, whichever model a nested launch named.
            entries[-1]["model_eligible"] = False
    report: dict[str, object] = {
        "version": 2 if endpoint is not None else 1,
        "kind": REPORT_KIND,
        "experiment_id": experiment.id,
        "attempts": entries,
        **({"containment_stop": containment_stop(entries)}
           if any("nested_codex" in e or "schedule_containment_stop" in e for e in entries) else {}),
        "arms": summarize_arms(entries),
        "accounting": accounting_by_arm(entries),
        **({"fixture": symmetry} if (symmetry := fixture_symmetry(entries)) is not None else {}),
        **({"outcome_endpoint": endpoint.to_json(),
            "declaration_digest": calibration.declaration_digest(declaration.data),
            "task_content": declaration.data["task_content"]}
           if endpoint is not None and declaration is not None else {}),
    }
    if declaration is not None:
        # #287 P3: the launch-bound declaration's tolerance (C2) and egress (C4).
        allowlist = declared_allowlist_digest(declaration)
        if allowlist is not None:
            _apply_egress(report, outcomes, allowlist)
        if declaration.tolerance_non_evaluable_per_arm is not None:
            report["evaluability"] = apply_tolerance(report, declaration.tolerance_non_evaluable_per_arm)
    return report


def recover_report(run_dir: Path, declaration: AnyDeclaration | None = None, *,
                   rehearse: bool = False) -> dict[str, object]:
    """Rebuild from a checkpoint and verified ledger, without starting a run.

    A legacy calibration ledger has no full declaration snapshot. Its caller
    must supply the original, especially to recover provided-skill eligibility.
    A supplied declaration can never replace a launch-bound snapshot.
    """
    experiment, outcomes = mp.read_outcomes(run_dir)
    experiment = trial.Experiment.open(experiment.root)
    schedule = schedule_from_ledger(experiment)
    kinds: set[str] = set()
    for planned, _attempt in experiment.attempts():
        binding = planned["config"]
        assert isinstance(binding, dict)
        config = json.loads(trial._read_object(experiment.root, str(binding["digest"])))
        if not isinstance(config, dict):
            raise CalibrationRefused("trial configuration is not an object")
        kinds.update(key for key in ("calibration_declaration", "discrimination_declaration") if key in config)
    if len(kinds) > 1:
        raise CalibrationRefused("mixed calibration and discrimination declaration snapshots")
    bound: AnyDeclaration | None = (stored_discrimination_declaration(experiment)
                                   if "discrimination_declaration" in kinds else _report_declaration(experiment))
    if bound is None and declaration is None:
        raise CalibrationRefused("legacy calibration has no stored declaration; pass its original --declaration")
    if bound is not None:
        if declaration is not None and trial.canonical(declaration.data) != trial.canonical(bound.data):
            raise CalibrationRefused("supplied declaration differs from the launch-bound declaration")
        declaration = bound
    assert declaration is not None
    model, effort = declared_model(declaration)
    recorded = mp.read_declared(run_dir)
    if recorded is None and bound is None:
        raise CalibrationRefused("legacy checkpoint has no recorded model/effort to check the original declaration")
    if recorded is not None and (recorded["model"], recorded["reasoning_effort"]) != (model, effort):
        raise CalibrationRefused("original declaration differs from the recorded model/effort")
    arm_order = tuple(s.arm for s in schedule)
    if declaration.arm_order != arm_order:
        raise CalibrationRefused("original declaration and ledger schedule differ")
    checkpoint = json.loads((run_dir / OUTCOMES_FILENAME).read_text(encoding="utf-8"))
    pins = checkpoint.get("declared")
    if isinstance(pins, dict) and "arm_order" in pins and pins["arm_order"] != list(arm_order):
        raise CalibrationRefused("recorded arm order differs from the ledger schedule")
    if bound is None:
        if not isinstance(declaration, calibration.CalibrationDeclaration) \
                or calibration.outcome_endpoint(declaration) is not None:
            raise CalibrationRefused("the ledger has no launch-bound snapshot for this declaration's endpoint")
        for planned, _attempt in experiment.attempts():
            grader = planned.get("grader")
            if planned.get("case") != {"id": declaration.grader_id, "revision": declaration.grader_revision} \
                    or not isinstance(grader, dict) or grader.get("id") != declaration.grader_id \
                    or grader.get("revision") != declaration.grader_revision \
                    or planned.get("client") != declaration.shared["client"] \
                    or planned.get("image") != {"digest": _shared_str(declaration, "image", "digest")}:
                raise CalibrationRefused("original declaration differs from the ledger's runtime/grader identities")
    if isinstance(declaration, calibration.DiscriminationDeclaration):
        report = build_discrimination_report(experiment, outcomes, declaration, rehearsal=rehearse)
    else:
        report = build_report(experiment, outcomes, declared_model=model, declared_effort=effort,
                              named_skills=named_skills_by_arm(declaration))
    if rehearse:
        # An explicit report option, as in calibration-run: no execution mode
        # is guessed from a checkpoint that never recorded one.
        report["rehearsal"] = True
        report["rehearsal_accounting"] = rehearsal_accounting(declaration, reconcile(experiment, outcomes))
    if "run_store" in declaration.data:
        report["run_store"] = {"declared": declaration.data["run_store"], "resolved": str(run_dir.resolve().parent)}
    return report


def summarize_arms(entries: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Per-arm counts of the primary endpoint - description, not inference.
    `opened` is the uptake rate's numerator and `observed` its denominator
    (k/n, #203 ruling 3c): an attempt whose invocations were not recorded is
    in neither. A provided-skill arm also counts `named_opened`, the attempts
    with recorded requested use; this never changes the scheduled primary counts."""
    arms: dict[str, dict[str, object]] = {}
    for entry in entries:
        arm = str(entry.get("arm"))
        summary = arms.setdefault(arm, {"scheduled": 0, "primary": {}, "model_ineligible": 0,
                                        "opened": 0, "observed": 0})
        summary["scheduled"] = int(str(summary["scheduled"])) + 1
        if entry.get("skill_opened") in (True, False):
            summary["observed"] = int(str(summary["observed"])) + 1
            summary["opened"] = int(str(summary["opened"])) + (entry.get("skill_opened") is True)
        if "named_skill_opened" in entry:
            summary["named_opened"] = int(str(summary.get("named_opened", 0))) + (entry["named_skill_opened"] is True)
        endpoint = entry.get("primary_endpoint")
        status = str(endpoint.get("status")) if isinstance(endpoint, dict) else calibration.NOT_GRADED
        primary = summary["primary"]
        assert isinstance(primary, dict)
        primary[status] = primary.get(status, 0) + 1
        if entry.get("model_eligible") is False:
            summary["model_ineligible"] = int(str(summary["model_ineligible"])) + 1
        for source, counter in (("task_grader_beside", "task_grader"), ("process_honesty_beside", "process_honesty")):
            beside = entry.get(source)
            if isinstance(beside, dict):
                counts = summary.setdefault(counter, {})
                assert isinstance(counts, dict)
                status = str(beside.get("status", UNKNOWN))
                counts[status] = counts.get(status, 0) + 1
    return arms


def paste_back(report: Mapping[str, object]) -> str:
    """The printed summary: one line per attempt, the primary endpoint first
    and readiness beside it. Leak-checked by `demo.print_paste_back`."""
    lines = [f"calibration-run: experiment {report.get('experiment_id')}"]
    if "outcome_endpoint" in report:
        lines.append(f"  outcome_endpoint={report['outcome_endpoint']} declaration={report.get('declaration_digest')}")
    stop = report.get("containment_stop")
    if isinstance(stop, Mapping):
        lines.append(f"  containment stop at {stop.get('at_attempt')}")
    attempts = report.get("attempts")
    for entry in attempts if isinstance(attempts, list) else []:
        primary = entry.get("primary_endpoint") or {}
        ready = entry.get("readiness_beside") or {}
        task, honesty = entry.get("task_grader_beside"), entry.get("process_honesty_beside")
        raw = f" | task={task.get('status')} honesty={honesty.get('status')}" \
            if isinstance(task, dict) and isinstance(honesty, dict) else ""
        lines.append(
            f"  {entry.get('position')}. {entry.get('arm')} ({entry.get('attempt_id')}): "
            f"disposition={entry.get('disposition')} primary={primary.get('status')} "
            f"| installation-ready={ready.get('installation_ready')} verified={ready.get('verified_status')} "
            f"| model={entry.get('model_observed')} eligible={entry.get('model_eligible')}{raw}"
        )
    arms = report.get("arms")
    for arm, summary in (arms.items() if isinstance(arms, dict) else []):
        named = f" named_opened={summary.get('named_opened')}" if "named_opened" in summary else ""
        raw = f" task={summary.get('task_grader')} honesty={summary.get('process_honesty')}" \
            if "process_honesty" in summary else ""
        lines.append(f"  [{arm}] scheduled={summary.get('scheduled')} primary={summary.get('primary')} "
                     f"opened={summary.get('opened')}/{summary.get('observed')}{named} "
                     f"model_ineligible={summary.get('model_ineligible')}{raw}")
    return "\n".join(lines)
