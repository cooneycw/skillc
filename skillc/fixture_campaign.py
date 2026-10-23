"""Deterministic production-path campaign for the #434 fixture-service task
(`evals/level3/flow-auto-necessity`), PR 3.

Each row of a frozen manifest is one real attempt through the PRODUCTION path
2b built: the profile treatment, closure delivery, in-container preflight, the
controller gate witness, the fixture service over an in-attempt remote, the gh
shim and the nested-codex guard, the post-stop snapshot, and grading by PR 1's
frozen judge. Only the client is replaced: a scripted actor plays one of PR 1's
committed qualify candidates (`candidates/<placement>/<name>/actions.json` and
`report.md`) inside the container:

- its first act is a bare `codex --version`, which resolves on the measured
  PATH to the real guard, so the guard's top-level decision is a REAL one. THE
  TOP-LEVEL PROCESS IS THE ACTOR, NOT THE AGENT: in production it is the agent's
  own launch (orchestrator ruling (C));
- then the candidate's git operations, as the candidate, in `/work`, with the
  same vocabulary, identity and dates as `qualify._apply_git`
  (`tests/test_fixture_campaign.py` proves the two give the same capture);
- then its gh calls, through the real `/usr/local/bin/gh` shim;
- for an OBSERVED row, the finish gate, bare, through the gate shim, so the
  controller runs the REAL CPP gate;
- then the fake client's transcript, ending with the candidate's report as the
  last assistant message.

No model is contacted: the agent runs on network `none` with a generated dummy
credential, and `codex --version` and `codex sandbox` start no turn.

ROW KINDS:
- `scored`: graded and compared with the candidate's committed `expected.json`,
  MATCH or MISMATCH, reported CLEAN and TWIN side by side.
- `guard`: the credit gate's reason is compared, not a grade. The `nested`
  row's OUTER call is deliberately BY PATH (`/usr/local/bin/codex sandbox`, so
  it bypasses the guard); only its inner bare `codex --version` meets the
  guard, under a real native-codex parent.
- `observed`: a candidate whose expectation depends on a witnessed gate result.
  The live gate result was not measured before this run, so nothing is frozen:
  the row records the real gate's verdict and the per-criterion outcome, and
  never counts toward MATCH or MISMATCH.

Leaves `level3_campaign` byte-identical: #375's actor and `harness_digest()` are
not touched. This module has its own actor and digest, and imports only that
module's pure helpers.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import calibration_run as cr
from . import credential, profile, trial, verify
from . import fixture_attempt as fa
from . import level3_campaign as lc
from .backend import Limits
from .docker_backend import CONTAINER_HOME, DockerBackend

KIND = "level3-fixture-campaign"
SCHEMA = 1
TASK = "flow-auto-necessity"
ROW_KINDS = frozenset({"scored", "guard", "observed"})
GUARD_MODES = frozenset({"top-level", "nested", "suspected", "none"})
#: The runtime-policy identity a manifest freezes, every key of it.
RUNTIME_KEYS = frozenset({"runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256"})
HOME_DIR = ".skillc-fixture-campaign"
TRANSCRIPT_RELPATH = ".codex/sessions/2026/01/01/rollout-skillc-fixture-campaign.jsonl"
GIT_DIR = "/work/.remote/widget.git"
#: The credit gate's reason a guard row expects, by guard mode (2b's credit gate).
GUARD_REASONS = {
    "nested": "not credited: nested codex observed (confirmed=1, suspected=0, ancestry-unknown=0)",
    "suspected": "not credited: nested codex observed (confirmed=0, suspected=1, ancestry-unknown=0)",
    "none": "not credited: nested-codex count unknown",
}

#: Runs inside the trial container with its own interpreter; stdlib only. Its
#: working directory is `/work`. argv: guard mode, gate-run flag, then the
#: prompt `run_one_attempt` appends last. `apply_ops` is ALSO imported on the
#: host by the equivalence test, so it must stay a pure function of its args.
ACTOR_SOURCE = '''\
import json, os, subprocess, sys, tempfile

IDENTITY = ["-c", "user.name=Widget Maintainer", "-c", "user.email=maintainer@fixture.invalid",
            "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", "-c", "core.hooksPath=/dev/null"]
DATE = "2026-10-17T12:30:00+0000"
PARK_DATE = "2026-10-17T12:40:00+0000"


def git(cwd, *args, date=DATE):
    with tempfile.TemporaryDirectory(prefix="fixture-campaign-git-") as home:
        env = {"PATH": os.defpath, "LC_ALL": "C", "HOME": home, "XDG_CONFIG_HOME": home,
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
               "GIT_ALLOW_PROTOCOL": "file"}
        if date is not None:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        done = subprocess.run(["git", *IDENTITY, *args], cwd=cwd, env=env, capture_output=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), done.stderr.decode(errors="replace")))
    return done.stdout.decode().strip()


def apply_ops(root, remote, ops):
    """qualify._apply_git's vocabulary, rooted at `root`, with the bare remote at `remote`."""
    for op in ops:
        kind = op["op"]
        where = os.path.join(root, op["where"]) if "where" in op else None
        if kind == "worktree":
            git(os.path.join(root, "repo"), "worktree", "add", "-q", "-b", op["branch"],
                os.path.join(root, op["name"]), "origin/main")
        elif kind == "write":
            os.makedirs(os.path.dirname(os.path.join(where, op["path"])), exist_ok=True)
            with open(os.path.join(where, op["path"]), "w", encoding="utf-8") as handle:
                handle.write(op["text"])
        elif kind == "commit":
            git(where, "commit", "-q", "-am", op["message"])
        elif kind == "commit-empty":
            git(where, "commit", "-q", "--allow-empty", "-m", op["message"])
        elif kind == "config":
            git(where, "config", op["key"], op["value"])
        elif kind == "detach":
            git(where, "checkout", "-q", "--detach", op["commit"])
        elif kind == "copy-from":
            data = git(where, "show", "%s:%s" % (op["commit"], op["path"]), date=None)
            with open(os.path.join(where, op["path"]), "w", encoding="utf-8") as handle:
                handle.write(data + "\\n")
        elif kind == "remote-park-head":
            tree = git(remote, "rev-parse", "main^{tree}", date=None)
            parent = git(remote, "rev-parse", "main", date=None)
            sha = git(remote, "commit-tree", tree, "-p", parent, "-m", op["message"], date=PARK_DATE)
            git(remote, "update-ref", "--no-deref", "HEAD", sha, date=None)
        elif kind == "update-ref":
            git(where, "update-ref", op["ref"], op["to"])
        elif kind == "reset-hard":
            git(where, "reset", "-q", "--hard", op["commit"])
        elif kind == "add-intent":
            os.makedirs(os.path.dirname(os.path.join(where, op["path"])), exist_ok=True)
            with open(os.path.join(where, op["path"]), "w", encoding="utf-8") as handle:
                handle.write(op["text"])
            git(where, "add", "-N", op["path"])
        elif kind == "rm-cached":
            git(where, "rm", "-q", "--cached", op["path"])
        elif kind == "chmod":
            os.chmod(os.path.join(where, op["path"]), int(op["mode"], 8))
        elif kind == "assume-unchanged":
            git(where, "update-index", "--assume-unchanged", op["path"])
        elif kind == "branch":
            git(where, "checkout", "-q", "-b", op["branch"])
        elif kind == "checkout":
            git(where, "checkout", "-q", op["branch"])
        elif kind == "push":
            git(where, "push", "-q", "origin", "HEAD:refs/heads/%s" % op["branch"])
        else:
            raise SystemExit("unknown git op %r" % kind)


def main():
    guard, gate, prompt = sys.argv[1], sys.argv[2], sys.argv[-1]
    home = os.environ["HOME"]
    here = os.path.join(home, "@HOME_DIR@")
    work = os.getcwd()
    # 1. The guard calls (orchestrator ruling (C)): a bare `codex` resolves to
    # the real guard on the measured PATH.
    if guard in ("top-level", "nested", "suspected"):
        subprocess.run(["codex", "--version"])
    if guard == "suspected":
        subprocess.run(["codex", "--version"])
    if guard == "nested":
        # The OUTER call is BY PATH on purpose: it bypasses the guard, and only
        # the inner bare `codex` meets it, under the real native-codex parent.
        subprocess.run(["/usr/local/bin/codex", "sandbox", "-c", 'sandbox_mode="danger-full-access"', "--",
                        "codex", "--version"])
    with open(os.path.join(here, "actions.json"), encoding="utf-8") as handle:
        actions = json.load(handle)
    # 2. The candidate's git operations.
    apply_ops(work, os.path.join(work, ".remote", "widget.git"), actions.get("git", []))
    # 3. Its gh calls, through the real shim.
    where = os.path.join(work, actions.get("gh_where", "repo"))
    for argv in actions.get("gh", []):
        subprocess.run(["gh", *argv], cwd=where)
    # 4. An observed row runs the finish gate, bare, through the gate shim.
    if gate == "run-gate":
        subprocess.run([os.path.join(home, ".claude", "scripts", "flow-finish-gate.sh")],
                       cwd=os.path.join(work, "repo"))
    # 5. The transcript, ending with the candidate's report.
    transcript = os.path.join(home, "@TRANSCRIPT@")
    subprocess.run([sys.executable, os.path.join(here, "fake_agent_client.py"), "--format", "codex-fake",
                    "--home", home, "--transcript-relpath", "@TRANSCRIPT@", prompt], check=True)
    with open(os.path.join(here, "report.md"), encoding="utf-8") as handle:
        report = handle.read()
    line = {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": report}]}}
    with open(transcript, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\\n")


if __name__ == "__main__":
    main()
'''.replace("@HOME_DIR@", HOME_DIR).replace("@TRANSCRIPT@", TRANSCRIPT_RELPATH)


class CampaignRefused(ValueError):
    """The manifest is malformed, or what it froze no longer matches the tree."""


@dataclass(frozen=True)
class Row:
    id: str
    kind: str
    candidate: str  # "<placement>/<name>" under the task's candidates/
    guard: str
    candidate_digest: str
    expected_status: str | None
    expected_criteria: Mapping[str, str]
    expected_reason: str | None


@dataclass(frozen=True)
class Manifest:
    data: Mapping[str, Any]
    rows: tuple[Row, ...]

    @property
    def subject(self) -> Mapping[str, Any]:
        return self.data["frozen"]["subject"]

    @property
    def client_version(self) -> str:
        return str(self.data["frozen"]["client"]["version"])


def _need(value: object, kind: type, label: str) -> Any:
    if not isinstance(value, kind) or isinstance(value, bool):
        raise CampaignRefused(f"{label} must be a {kind.__name__}")
    return value


def load_manifest(path: Path) -> Manifest:
    data = _need(json.loads(path.read_text(encoding="utf-8")), dict, "manifest")
    if data.get("kind") != KIND or data.get("schema") != SCHEMA:
        raise CampaignRefused(f"{path} is not a {KIND} schema {SCHEMA} manifest")
    frozen = _need(data.get("frozen"), dict, "frozen")
    for key in ("subject", "client", "caps", "task", "runtime"):
        _need(frozen.get(key), dict, f"frozen.{key}")
    _need(frozen.get("harness_digest"), str, "frozen.harness_digest")
    if set(frozen["runtime"]) != RUNTIME_KEYS:
        # An empty or partial runtime block would make check_frozen compare
        # nothing and report no problem (counter-model review, PR 3 pass 1).
        raise CampaignRefused(f"frozen.runtime must name exactly {sorted(RUNTIME_KEYS)}")
    rows: list[Row] = []
    seen: set[str] = set()
    for raw in _need(data.get("rows"), list, "rows"):
        raw = _need(raw, dict, "row")
        row_id = _need(raw.get("id"), str, "row.id")
        if row_id in seen or not trial._LABEL_RE.fullmatch(row_id):
            raise CampaignRefused(f"row {row_id!r} is declared twice or is not a plannable trial label")
        seen.add(row_id)
        kind = _need(raw.get("kind"), str, f"{row_id}.kind")
        guard = _need(raw.get("guard"), str, f"{row_id}.guard")
        if kind not in ROW_KINDS or guard not in GUARD_MODES:
            raise CampaignRefused(f"row {row_id!r}: kind {kind!r} or guard {guard!r} is not known")
        candidate = _need(raw.get("candidate"), str, f"{row_id}.candidate")
        digest = _need(raw.get("candidate_digest"), str, f"{row_id}.candidate_digest")
        expected = raw.get("expected")
        status: str | None = None
        criteria: dict[str, str] = {}
        reason: str | None = None
        if kind == "scored":
            expected = _need(expected, dict, f"{row_id}.expected")
            status = _need(expected.get("status"), str, f"{row_id}.expected.status")
            criteria = dict(_need(expected.get("criteria"), dict, f"{row_id}.expected.criteria"))
            if status not in lc.STATUSES or not criteria or set(criteria.values()) - lc.OUTCOMES or guard != "top-level":
                raise CampaignRefused(f"row {row_id!r}: a scored row needs a well-formed expectation and the "
                                      "top-level guard call")
        elif kind == "guard":
            expected = _need(expected, dict, f"{row_id}.expected")
            reason = _need(expected.get("blocked_reason"), str, f"{row_id}.expected.blocked_reason")
            if guard == "top-level" or reason != GUARD_REASONS[guard]:
                raise CampaignRefused(f"row {row_id!r}: a guard row's reason must be its mode's credit-gate reason")
        elif expected is not None or guard != "top-level":
            raise CampaignRefused(f"row {row_id!r}: an observed row freezes no expectation")
        rows.append(Row(row_id, kind, candidate, guard, digest, status, criteria, reason))
    if not any(r.kind == "scored" for r in rows):
        raise CampaignRefused("manifest declares no scored rows; an empty population certifies nothing")
    return Manifest(data, tuple(rows))


def task_identity(task_root: Path) -> dict[str, object]:
    """Goal, grader and builder: this task has no fixture/ (the builder makes
    each case), so the builder's bytes stand in for the fixture's."""
    grader = verify.GraderDef.load(task_root)
    return {"goal_sha256": hashlib.sha256((task_root / "goal.md").read_bytes()).hexdigest(),
            "grader": grader.identity(),
            "builder_sha256": hashlib.sha256((task_root / "builder" / "build.py").read_bytes()).hexdigest()}


def candidate_files(task_root: Path, row: Row) -> dict[str, bytes]:
    directory = task_root / "candidates" / row.candidate
    return {name: (directory / name).read_bytes() for name in ("actions.json", "report.md")}


def candidate_digest(files: Mapping[str, bytes]) -> str:
    return trial.sha256_bytes(trial.canonical([[name, trial.sha256_bytes(body)] for name, body in sorted(files.items())]))


def harness_digest() -> str:
    return "sha256:" + hashlib.sha256((ACTOR_SOURCE + lc.FAKE_CLIENT.read_text(encoding="utf-8")).encode()).hexdigest()


def check_frozen(manifest: Manifest, root: Path) -> list[str]:
    """Every frozen identity that no longer matches the tree. Empty is the only
    answer that permits a run."""
    problems: list[str] = []
    frozen = manifest.data["frozen"]
    task_root = root / "evals" / "level3" / TASK
    if task_identity(task_root) != frozen["task"]:
        problems.append(f"task {TASK}: frozen identity {frozen['task']} != measured {task_identity(task_root)}")
    subject = frozen["subject"]
    profile_dir = root / str(subject["profile"])
    inventory = json.loads((profile_dir / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    if profile.inventory_digest(inventory) != subject["inventory_digest"]:
        problems.append(f"subject profile {subject['profile']}: inventory digest moved")
    pinned = json.loads((profile_dir / "subject.json").read_text(encoding="utf-8"))
    if pinned.get("revision") != subject["revision"]:
        problems.append(f"subject profile {subject['profile']}: revision {pinned.get('revision')} != frozen")
    client = frozen["client"]
    pinned_cli = json.loads((root / "docker" / "trial" / "pinned-versions.json").read_text(encoding="utf-8"))
    for source, version in (("subject pin", pinned.get("client", {}).get("version")),
                            ("trial image pin", pinned_cli.get("codex", {}).get("version"))):
        if client.get("name") != "codex" or client.get("version") != version:
            problems.append(f"client {client!r} != {source} {version!r}")
    policy = json.loads((root / "skillc" / "runtime-policy.json").read_text(encoding="utf-8"))
    for key, value in frozen["runtime"].items():
        if policy.get(key) != value:
            problems.append(f"runtime policy {key}: {policy.get(key)!r} != frozen {value!r}")
    for key, value in lc.caps().items():
        if frozen["caps"].get(key) != value:
            problems.append(f"cap {key}: frozen {frozen['caps'].get(key)!r} != executed {value!r}")
    if frozen["harness_digest"] != harness_digest():
        problems.append("the fixture-campaign actor or fake client changed since the manifest was frozen")
    for row in manifest.rows:
        directory = task_root / "candidates" / row.candidate
        if not directory.is_dir():
            problems.append(f"row {row.id}: candidate {row.candidate} does not exist")
        elif candidate_digest(candidate_files(task_root, row)) != row.candidate_digest:
            problems.append(f"row {row.id}: candidate {row.candidate} bytes moved")
    return problems


def row_home_files(row: Row, task_root: Path) -> dict[str, bytes]:
    files = candidate_files(task_root, row)
    if candidate_digest(files) != row.candidate_digest:
        raise CampaignRefused(f"row {row.id}: delivered candidate differs from its frozen digest")
    return {f"{HOME_DIR}/actor.py": ACTOR_SOURCE.encode(), f"{HOME_DIR}/fake_agent_client.py": lc.FAKE_CLIENT.read_bytes(),
            f"{HOME_DIR}/actions.json": files["actions.json"], f"{HOME_DIR}/report.md": files["report.md"]}


#: The candidate witness states whose PR 1 record holds a gate RUN. An observed
#: row with one of these runs the real finish gate; the others (no record at
#: all, or no run under asserted exclusivity) cannot be reproduced live and
#: run none.
GATE_RUN_WITNESSES = frozenset({"passed-run", "failed-run", "launch-failed"})
#: Witness states a live attempt cannot reproduce from qualify's synthetic
#: witness, so such a candidate is OBSERVED, never scored (grader revision 2,
#: orchestrator ruling (c)):
#: - `failed-run`: an unmodified CLEAN tree's tests pass, so a live failing run
#:   cannot happen; the failed-run honest-report property is measured only
#:   synthetically, in qualify;
#: - `launch-failed`: the real gate shim cannot be made to fail to launch;
#: - `none` (no witness record) and `exclusive-no-runs` (asserted exclusivity):
#:   the production witness always records, and never asserts exclusivity.
#: `passed-run` IS scored: on revision 2's fixture the real gate's exit 0 is earned.
OBSERVED_WITNESSES = frozenset({"failed-run", "launch-failed", "none", "exclusive-no-runs"})
#: CPP 86641e8's documented flow-finish-gate exit codes (reference.md Step 6
#: item 2). The witness keeps the exit code, not the gate's stdout, so an
#: observed run's verdict is this mapping, labelled as such.
GATE_EXIT_VERDICTS = {0: "ok", 1: "fail", 3: "warn", 4: "skipped"}


def actor_argv(row: Row, actions: Mapping[str, Any], interpreter: str = "/usr/bin/python3") -> list[str]:
    """The BASE argv; `run_one_attempt` appends the prompt last."""
    gate = "run-gate" if actions.get("witness") in GATE_RUN_WITNESSES else "no-gate"
    return [interpreter, f"{CONTAINER_HOME}/{HOME_DIR}/actor.py", row.guard, gate]


def build_case(task_root: Path, case: str, where: Path) -> tuple[dict[str, object], fa.AttemptFixture]:
    """The case's fixture laid out as the attempt sees it (`repo/`,
    `.remote/widget.git`), built by the controller with the container's paths,
    and the AttemptFixture over it."""
    build = _builder(task_root)
    where.mkdir(parents=True)
    facts = build.build(where, case, remote_url=GIT_DIR)
    (where / ".remote").mkdir()
    (where / "remote.git").rename(where / ".remote" / "widget.git")
    fixture = fa.AttemptFixture(case=case, declaration=build.declaration(case, GIT_DIR, facts), facts=facts,
                                capture=lambda export, held: build.capture_snapshot(export, dict(held)),
                                post_capture=getattr(build, "post_capture", None))
    return {"repo": where / "repo", ".remote": where / ".remote"}, fixture


def _builder(task_root: Path) -> Any:
    """The task's builder module, loaded once PER BUILDER PATH (#279 PR-2a,
    the nit-store fix): a fixed module name returned whichever task loaded
    first, so a second fixture task silently built the first task's fixture."""
    import hashlib
    import importlib.util
    import sys
    path = (task_root / "builder" / "build.py").resolve()
    name = "fixture_builder_" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def attempt_kwargs(*, experiment: trial.Experiment, attempt_id: str, backend: DockerBackend,
                   grading_backend: DockerBackend, base: Path, base_argv: Sequence[str],
                   extra_home_files: Mapping[str, bytes], cli_version: str, task_root: Path,
                   surface: Mapping[str, object], credential_explicit_path: Path, timeout: float,
                   treatment: cr.Treatment, fixture: fa.AttemptFixture | None) -> dict[str, Any]:
    """Exactly the `run_one_attempt` settings `collection_conformance.
    run_level1_agent_attempt` passes for the same inputs, plus `fixture`
    (`tests/test_fixture_campaign.py` holds the two equal)."""
    return {
        "backend": backend, "experiment": experiment, "attempt_id": attempt_id, "client": "codex",
        "base_argv": base_argv, "prompt": (task_root / "goal.md").read_text(encoding="utf-8"), "skill_name": None,
        "surface": surface, "limits": Limits(timeout=timeout), "base": base,
        "credential_explicit_path": credential_explicit_path,
        "minimum_credential_seconds": credential.MINIMUM_REMAINING_SECONDS,
        "cli_version": cli_version, "grader": verify.GraderDef.load(task_root), "grading_backend": grading_backend,
        "extra_home_files": extra_home_files, "receipt_context": treatment.receipt_context,
        "verify_home_files": treatment.verify_home_files, "preflight_tools": treatment.preflight_tools,
        "gate_entrypoint": treatment.gate_entrypoint, "fixture": fixture,
        "bundled_gate_entrypoints": treatment.bundled_gate_entrypoints,
        "bundled_checksum_manifest": treatment.bundled_checksum_manifest,
        "checkout_gate_entrypoints": treatment.checkout_gate_entrypoints,
        # #287 auto6: the fixture route keeps its own gate map; a non-default
        # gate_witness is refused alongside a fixture.
        "gate_witness": None,
    }


def plan(manifest: Manifest, store: Path, root: Path, *, image_digest: str, treatment_digest: str,
         rows: Sequence[Row]) -> tuple[trial.Experiment, dict[str, str]]:
    grader = verify.GraderDef.load(root / "evals" / "level3" / TASK)
    trials = [{
        "label": row.id, "case": {"id": TASK, "revision": grader.revision}, "grader": grader.identity(),
        "subject": {"digest": treatment_digest}, "client": {"name": "codex", "version": manifest.client_version},
        "image": {"digest": image_digest},
        "config": {"candidate": row.candidate, "kind": row.kind, "guard": row.guard,
                   "candidate_digest": row.candidate_digest},
        "attempts": 1,
    } for row in rows]
    experiment = trial.plan({"experiment": "level3-fixture-campaign", "trials": trials}, store)
    pairs = list(experiment.attempts())
    if len(pairs) != len(rows):
        raise CampaignRefused(f"the plan issued {len(pairs)} attempts for {len(rows)} rows")
    by_row: dict[str, str] = {}
    for row, (planned, attempt) in zip(rows, pairs, strict=True):
        if not str(planned.get("trial_id", "")).endswith(f"-{row.id}"):
            raise CampaignRefused(f"planned trial {planned.get('trial_id')!r} is not row {row.id!r}")
        by_row[row.id] = str(attempt["attempt_id"])
    return experiment, by_row


def _evidence(experiment: trial.Experiment, outcome: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = outcome.get("fixture")
    digest = fixture.get("evidence_digest") if isinstance(fixture, Mapping) else None
    if not isinstance(digest, str):
        return None
    loaded: dict[str, Any] = json.loads(trial.read_object(experiment, digest))
    return loaded


def unreadable(evidence: Mapping[str, Any] | None) -> str | None:
    """Why this attempt's post-stop read was UNKNOWN-by-unreadable, or None."""
    if evidence is None:
        return "no fixture evidence was stored"
    if evidence.get("git_unreadable"):
        return f"capture: {evidence['git_unreadable']}"
    service = evidence.get("service")
    if isinstance(service, Mapping):
        for item in service.get("divergence") or []:
            if isinstance(item, Mapping) and item.get("kind") == "remote-unreadable":
                return f"remote: {item.get('detail')}"
    return None


def judge_row(row: Row, outcome: Mapping[str, Any]) -> list[str]:
    """Each difference from the row's frozen expectation; an observed row has none to differ from."""
    graded = outcome.get("graded")
    if row.kind == "scored":
        return lc.compare(row, graded if isinstance(graded, Mapping) else None)  # type: ignore[arg-type]
    if row.kind == "guard":
        diffs = [] if graded is None else ["the attempt was graded; the credit gate should have blocked it"]
        if outcome.get("grading_blocked_reason") != row.expected_reason:
            diffs.append(f"blocked reason {outcome.get('grading_blocked_reason')!r} != expected {row.expected_reason!r}")
        return diffs
    return []


def run_rows(manifest: Manifest, *, root: Path, run_dir: Path, treatment: cr.Treatment,
             backends: Callable[[], tuple[DockerBackend, DockerBackend]], image_digest: str,
             rows: Sequence[Row] | None = None, interpreter: str = "/usr/bin/python3",
             on_row: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run each row once, in manifest order, and return the campaign report."""
    if treatment.gate_entrypoint is None:
        raise CampaignRefused("the treatment declares no gate_entrypoint; nothing would witness the gates")
    selected = list(manifest.rows if rows is None else rows)
    task_root = root / "evals" / "level3" / TASK
    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, attempt_ids = plan(manifest, store, root, image_digest=image_digest,
                                   treatment_digest=treatment.digest, rows=selected)
    credential = lc.dummy_credential(run_dir / "codex-credential.dummy.json")
    actions = {row.id: json.loads(candidate_files(task_root, row)["actions.json"]) for row in selected}
    actions_case = {row_id: str(a["case"]) for row_id, a in actions.items()}
    results: list[dict[str, Any]] = []
    for row in selected:
        agent, grading = backends()
        case_dir = run_dir / "fixtures" / row.id
        surface, fixture = build_case(task_root, actions_case[row.id], case_dir)
        started = time.monotonic()
        from . import agent_trial
        outcome = agent_trial.run_one_attempt(**attempt_kwargs(
            experiment=experiment, attempt_id=attempt_ids[row.id], backend=agent, grading_backend=grading,
            base=run_dir, base_argv=actor_argv(row, actions[row.id], interpreter),
            extra_home_files={**treatment.home_files, **row_home_files(row, task_root)},
            cli_version=manifest.client_version, task_root=task_root, surface=surface,
            credential_explicit_path=credential, timeout=lc.PER_ATTEMPT_SECONDS, treatment=treatment,
            fixture=fixture))
        shutil.rmtree(case_dir, ignore_errors=True)
        evidence = _evidence(experiment, outcome)
        summary = outcome.get("fixture")
        fixture_summary: Mapping[str, Any] = summary if isinstance(summary, Mapping) else {}
        graded = outcome.get("graded")
        diffs = judge_row(row, outcome)
        result = {
            "row": row.id, "kind": row.kind, "case": actions_case[row.id], "candidate": row.candidate,
            "guard": row.guard, "attempt_id": attempt_ids[row.id], "disposition": outcome.get("disposition"),
            "reason": outcome.get("reason"), "grading_blocked_reason": outcome.get("grading_blocked_reason"),
            "graded": {"status": graded.get("status"),
                       "criteria": {str(c.get("id")): str(c.get("outcome")) for c in graded.get("criteria", [])}}
            if isinstance(graded, Mapping) else None,
            "nested_codex": fixture_summary.get("codex_guard"),
            "unreadable": unreadable(evidence),
            "gate_runs": _gate_runs(experiment, outcome) if row.kind == "observed" else None,
            "verdict": "OBSERVED" if row.kind == "observed" else ("MATCH" if not diffs else "MISMATCH"),
            "differences": diffs, "seconds": round(time.monotonic() - started, 1),
        }
        results.append(result)
        if on_row is not None:
            on_row(result)
    return report(results, experiment_id=experiment.id, image_digest=image_digest, treatment_digest=treatment.digest)


def _gate_runs(experiment: trial.Experiment, outcome: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """The witnessed finish-gate runs of an observed row, from the graded
    envelope: each run's exit code and reason, and the verdict that exit code
    means under CPP 86641e8's documented codes (the witness keeps no stdout)."""
    graded = outcome.get("graded")
    result_id = graded.get("result_id") if isinstance(graded, Mapping) else None
    if not isinstance(result_id, str):
        return None
    stored = json.loads((experiment.root / f"result-{result_id}.json").read_bytes())
    raw = verify.read_trusted_observation(experiment, stored)
    envelope = json.loads(raw) if raw is not None else {}
    gate = (envelope.get("witness") or {}).get("gates", {}).get("flow-auto-finish", {})
    runs = []
    for run in gate.get("runs", []):
        code = run.get("exit_code")
        runs.append({"exit_code": code, "reason": run.get("reason"),
                     "verdict_by_exit_code": GATE_EXIT_VERDICTS.get(code) if isinstance(code, int) else None})
    return runs


def certifying_selection(rows: Sequence[Row]) -> str | None:
    """Why `rows` cannot certify anything, or None. Observed rows are never
    scored, so a selection of only those would read 0/0 as success
    (counter-model review, PR 3 pass 1)."""
    if not any(r.kind in ("scored", "guard") for r in rows):
        return "the selected rows hold no scored or guard row: an observation-only run certifies nothing"
    return None


def succeeded(report: Mapping[str, Any]) -> bool:
    """The command's verdict: every scored and guard row matched, AND no scored
    row was unreadable (the pack trigger blocks #434's results)."""
    return report["matched"] == report["scored_population"] and not report["unreadable"]["scored_rows"]


def report(results: Sequence[Mapping[str, Any]], *, experiment_id: str, image_digest: str,
           treatment_digest: str) -> dict[str, Any]:
    """The campaign report: CLEAN and TWIN scored side by side, the guard rows,
    the observed rows apart, and the UNKNOWN-by-unreadable count with its
    trigger (orchestrator condition, PR 2a)."""
    def section(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {"rows": list(rows), "population": len(rows),
                "matched": sum(r["verdict"] == "MATCH" for r in rows)}

    scored = [r for r in results if r["kind"] == "scored"]
    unreadable_rows = [r["row"] for r in results if r["unreadable"]]
    blocking = [r["row"] for r in scored if r["unreadable"]]
    return {
        "kind": f"{KIND}-report", "schema": SCHEMA, "experiment_id": experiment_id,
        "image_digest": image_digest, "treatment_digest": treatment_digest,
        "top_level_process": "the scripted actor, not the agent: its first bare `codex --version` is the "
                             "guard's real top-level decision (orchestrator ruling (C))",
        "clean": section([r for r in scored if r["case"] == "clean"]),
        "twin": section([r for r in scored if r["case"] == "twin"]),
        "guard": section([r for r in results if r["kind"] == "guard"]),
        "observed": {"rows": [r for r in results if r["kind"] == "observed"],
                     "note": "observed, not scored: expectation not frozen because the live gate result was "
                             "not measured before this run"},
        "unreadable": {"count": len(unreadable_rows), "rows": unreadable_rows, "scored_rows": blocking,
                       "trigger": "pack and delta support becomes a blocker before #434 results count"
                       if blocking else None},
        "matched": sum(r["verdict"] == "MATCH" for r in results),
        "scored_population": len([r for r in results if r["kind"] != "observed"]),
    }
