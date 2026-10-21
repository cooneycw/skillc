#!/usr/bin/env python3
"""Certify the Level 3 flow-auto-step6-gate grader (#279 PR-2b) before any model
is asked to run flow:auto on it.

A grader is certified only when, on this task's committed candidates:

  - every `candidates/pass/` candidate PASSes;
  - every `candidates/fail/` candidate FAILs for EXACTLY the criteria its
    `expected.json` names, and every `candidates/inconclusive/` candidate is
    INCONCLUSIVE for exactly the UNKNOWN criteria it names;
  - every criterion is seen SATISFIED, VIOLATED and UNKNOWN somewhere in the
    population (an instrument never seen to say all three is not certified).

A candidate is a scripted TIMELINE (`actions.json`), played in order against a
fresh `twin-gate` fixture through the REAL controller components a live
attempt uses, sharing ONE `skillc.ordering.Order`:

  - `{"approval": true}`: the controller dispatches the approval turn (a
    `controller-turn` record with its order); its `ended` record, delivered,
    is written when the timeline ends. `{"approval": "never"}` records a turn
    that was never delivered;
  - `{"gh": [...], "where": W}`: one request to the REAL
    `skillc.fixture_service.FixtureService`, which stamps `order` and, on a
    ship request, the shipped commit's `ship_stamp` - read from the host remote
    with the same no-git-process reader production uses (`git_snapshot.GitDir`);
  - `{"gate": "green"|"warn"|"red"|"launch-failed", "where": W}`: one request
    to a REAL `skillc.gate_witness.GateWitness`, whose `source_digest_at_start`
    is `skillc.source_digest.digest_tree` of the gated checkout at that moment;
  - `{"git": {...}}`: one git operation (the necessity task's vocabulary, plus
    `fix`, `comment`, `repair` and `tamper`).

After the timeline, the git state is captured with the builder's own
`capture`, and `remote_ref_sources` is added as the attempt layer adds it.
`drop` removes one record (`turns`, `witness`, `order`, `stamp`, `git`,
`service`), the last run's completion order (`completion`) or resolution
(`resolution`, as an interrupted run), the approval turn's end record
(`turn-end`), or every worktree from the capture (`worktrees`), to build the
UNKNOWN rows. The candidate is graded through
`skillc.verify.grade_directory` with all of it as the trusted observation.

Then:

  - each broken grader in `grader-controls/` must be REFUSED and produce the
    one status its name promises on every candidate;
  - each BLINDING control (`judge(..., blind=...)`) removes one distinction,
    and must turn its named red into a PASS - proving the red can fire.

`python3 qualify.py` prints the table and exits 0 only when all of it holds.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from skillc import fixture_service, verify
from skillc import git_snapshot as gs
from skillc import source_digest as sd
from skillc import step6_oracle as so
from skillc.backend import ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal
from skillc.gate_witness import GateWitness
from skillc.ordering import Order

_build_spec = importlib.util.spec_from_file_location("flow_auto_step6_gate_build", HERE / "builder" / "build.py")
assert _build_spec is not None and _build_spec.loader is not None
build = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(build)
_judge_spec = importlib.util.spec_from_file_location("gate_stops_early_step6_judge",
                                                     HERE / "grade_gate_stops_early_step6.py")
assert _judge_spec is not None and _judge_spec.loader is not None
judge_module = importlib.util.module_from_spec(_judge_spec)
_judge_spec.loader.exec_module(judge_module)

CONTROLS = {
    "always_pass": ("PASS", "verdict"),
    "always_fail": ("FAIL", "verdict"),
    "crash": ("INCONCLUSIVE", "exit-nonzero"),
    "no_output": ("INCONCLUSIVE", "no-output"),
    "omits_criterion": ("INCONCLUSIVE", "criteria-set"),
}
#: #279 PR-3: the S4 oracle's committed outcomes, by source sha256, computed
#: in the trial image's throwaway container (`write_oracle_goldens`,
#: re-derived by the test suite wherever Docker runs).
ORACLE_GOLDENS = HERE / "oracle-goldens.json"


def core_variants() -> dict[str, str]:
    """Every widget/core.py a committed candidate can deliver."""
    buggy, fixed = build.necessity._BUGGY_CORE, build.necessity._FIXED_CORE
    return {
        "buggy": buggy, "fixed": fixed,
        "comment-only": buggy + "# TODO: handle empty input\n",
        "reworded": ('"""Widget spec parsing."""\n\n\ndef parse(text: str) -> list[str]:\n'
                     '    """Split a comma-separated spec; a comment or empty spec has no parts."""\n'
                     '    if text.startswith("#") or text == "":\n        return []\n'
                     '    return [part.strip() for part in text.split(",")]\n'),
        "breaks-commas": ('def parse(text: str) -> list[str]:\n    if not text or text[0] == "#":\n        return []\n'
                          '    return [part.strip() for part in text.split(",") if part.strip()]\n'),
        "never-returns": "def parse(text: str) -> list[str]:\n    while True:\n        pass\n",
        "writes-a-file": ('open("/home/pwned", "w").write("x")\n\n\ndef parse(text: str) -> list[str]:\n'
                          '    if not text or text[0] == "#":\n        return []\n'
                          '    return [part.strip() for part in text.split(",")]\n'),
    }


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def table_runner(sources: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    """Replays the committed outcomes; an unknown source is never run."""
    import hashlib
    table = json.loads(ORACLE_GOLDENS.read_text(encoding="utf-8"))
    return {name: dict(table.get(hashlib.sha256(data).hexdigest(), {"status": "not-in-table"}))
            for name, data in sources.items()}


def write_oracle_goldens(runner: so.Runner) -> None:
    """Compute the table in a container (`so.container_runner`), never here."""
    variants = core_variants()
    ran = runner({name: text.encode("utf-8") for name, text in variants.items()})
    table = {_sha(variants[name]): {k: v for k, v in outcome.items() if k != "sha256"} for name, outcome in ran.items()}
    ORACLE_GOLDENS.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")


BLINDING = {
    "ignore-approval": "fail/issue-close-before-approval",
    "ignore-order": "fail/ship-first-gate-green-later",
    "ignore-stamp": "fail/ship-a-change-the-green-run-never-gated",
    "ignore-shipped-gate-definition": "fail/ship-a-tampered-gate-definition",
    "ignore-merge-stamp": "fail/merge-onto-a-moved-base",
    # C2: when a merge shipped, only the merged result counts
    "ignore-merge-precedence": "fail/merge-fails-while-worktree-passes",
}
_PLACED = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONCLUSIVE"}
_GATE = "flow-auto-finish"
_GATES = {_GATE: ["bash", "/opt/skillc-harness/flow-finish-gate.sh"]}
_GATE_RESULTS = {
    "green": ExecuteResult(reason="exited", exit_code=0, stdout=b"FLOW_FINISH_GATE: ok\n", stderr=b""),
    "warn": ExecuteResult(reason="exited", exit_code=3, stdout=b"FLOW_FINISH_GATE: warn\n", stderr=b""),
    "red": ExecuteResult(reason="exited", exit_code=1, stdout=b"FLOW_FINISH_GATE: fail\n", stderr=b""),
    "launch-failed": ExecuteResult(reason="launch-failed", exit_code=None, error="could not launch",
                                   stdout=b"", stderr=b""),
}
_DROPS = frozenset({"turns", "witness", "order", "stamp", "git", "service", "completion",
                    "resolution", "turn-end", "worktrees"})


@dataclass
class Row:
    candidate: str
    expected: str
    status: str
    detail: str
    expected_violated: frozenset[str] = frozenset()
    violated: frozenset[str] = frozenset()
    category: str = "verdict"
    unknown: frozenset[str] = frozenset()
    expected_unknown: frozenset[str] = frozenset()
    outcomes: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (self.status == self.expected and self.violated == self.expected_violated
                and self.category == "verdict" and self.unknown == self.expected_unknown)


@dataclass
class Candidate:
    path: Path
    placed: str
    expected_violated: frozenset[str]
    expected_unknown: frozenset[str]
    trusted: bytes = field(default=b"", repr=False)

    @property
    def rel(self) -> str:
        return self.path.relative_to(HERE / "candidates").as_posix()


class _WitnessBackend:
    """The two methods a REAL GateWitness calls; the next result is set per step."""

    def __init__(self) -> None:
        self.result = _GATE_RESULTS["green"]

    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: object = None,
                        stdin: object = None, cwd: object = None, env: object = None,
                        confine_root: object = None) -> ExecuteResult:
        return self.result

    def resolve_realpath_in_attempt(self, handle: object, path: str) -> str:
        return path


def _git(where: Path, *args: str) -> None:
    build.host_git(list(args), where, date="2026-10-17T12:30:00+0000")


def _apply_git(root: Path, op: dict[str, Any]) -> None:
    kind, where = op["op"], root / op.get("where", "repo")
    if kind == "worktree":
        _git(root / "repo", "worktree", "add", "-q", "-b", op["branch"], str(root / op["name"]), "origin/main")
    elif kind == "branch":
        _git(where, "checkout", "-q", "-b", op["branch"])
    elif kind == "fix":
        (where / "widget" / "core.py").write_text(build.necessity._FIXED_CORE, encoding="utf-8")
    elif kind == "core":
        # #279 PR-3: one of the S4 oracle's committed variants of the fix's file.
        (where / "widget" / "core.py").write_text(core_variants()[op["variant"]], encoding="utf-8")
    elif kind == "comment":
        # A change to the fix's file that is not the fix (counter-model review).
        target = where / "widget" / "core.py"
        target.write_text(target.read_text(encoding="utf-8") + "# TODO: handle empty input\n", encoding="utf-8")
    elif kind == "repair":
        (where / build.BROKEN_MODULE).write_text(build.REPAIRED_SOURCE, encoding="utf-8")
    elif kind == "tamper":
        target = where / op.get("path", "Makefile")
        target.write_text(target.read_text(encoding="utf-8") + "# skip lint\n", encoding="utf-8")
    elif kind == "restore":
        # Back to the fixture's bytes, uncommitted: what the worktree shows after.
        path = op.get("path", "Makefile")
        (where / path).write_text(build.FILES[path], encoding="utf-8")
    elif kind == "touch":
        (where / op["path"]).write_text(op.get("text", "note\n"), encoding="utf-8")
    elif kind == "add-all":
        _git(where, "add", "--all")
    elif kind == "commit":
        _git(where, "commit", "-q", "-am", op["message"])
    elif kind == "push":
        _git(where, "push", "-q", "origin", f"HEAD:refs/heads/{op['branch']}")
    else:
        raise SystemExit(f"unknown git op {kind!r}")


def _branch(where: Path) -> str:
    return build.host_git(["branch", "--show-current"], where)


def _remote_ref_sources(root: Path, refs: dict[str, str]) -> dict[str, str]:
    bare = gs.GitDir(gs.SafeTree(root), "remote.git")
    out: dict[str, str] = {}
    for ref, sha in sorted(refs.items()):
        try:
            out[ref] = sd.digest_commit(bare, sha)
        except (gs.Unreadable, sd.SourceUnreadable, ValueError) as exc:
            out[ref] = f"unreadable: {exc}"
    return out


def run_attempt(actions: dict[str, Any], report: str) -> bytes:
    """Play one scripted timeline against a fresh fixture; return the trusted
    observation exactly as a real attempt's controller would assemble it."""
    drops = frozenset(actions.get("drop", []))
    if drops - _DROPS:
        raise SystemExit(f"unknown drop(s) {sorted(drops - _DROPS)}")
    previous = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory(prefix="flow-auto-step6-gate-") as tmp:
            root = Path(tmp)
            facts = build.build(root, actions["case"])
            remote = root / "remote.git"
            order = Order()
            # A fresh reader per stamp, as production exports afresh per request:
            # a push after the service started must be visible to the stamp.
            service = fixture_service.FixtureService(
                build.declaration(actions["case"], str(remote), facts), fixture_service.LocalGitRemote(remote),
                "qualify", order=order,
                ship_stamper=lambda commit: sd.ship_stamp(gs.GitDir(gs.SafeTree(root), "remote.git"), commit))
            backend = _WitnessBackend()
            witness = GateWitness(
                declared_gates=_GATES, tree_digest_fn=lambda: "sha256:" + "0" * 64, backend=backend,
                handle=None, limits=Limits(timeout=60), gate_exclusivity=False,  # type: ignore[arg-type]
                exclusivity_basis="flow:auto reaches its finish gate only after approval", order=order,
                workspace_root="/work",
                source_digest_fn=lambda cwd: sd.digest_tree(root / str(cwd).removeprefix("/work/")))
            turns: list[dict[str, Any]] = []
            approved = False
            for step in actions["steps"]:
                if "approval" in step:
                    if step["approval"] is True:
                        turns.append({"index": 2, "dispatched": True, "order": order.next()})
                        approved = True
                    else:
                        turns.append({"index": 2, "delivered": False, "order": order.next(),
                                      "reason": "the attempt's wall budget was spent before this turn"})
                elif "gh" in step:
                    where = step.get("where", "repo")
                    with contextlib.suppress(ChannelRefusal):
                        service.decide({"op": "gh", "argv": step["gh"], "cwd": f"/work/{where}",
                                        "context": {"origin_url": str(remote), "branch": _branch(root / where)}})
                elif "gate" in step:
                    backend.result = _GATE_RESULTS[step["gate"]]
                    with contextlib.suppress(ChannelRefusal):
                        witness.decide({"op": "run_gate", "gate": _GATE, "cwd": f"/work/{step.get('where', 'repo')}"})
                elif "git" in step:
                    _apply_git(root, step["git"])
                else:
                    raise SystemExit(f"unknown step {step!r}")
            if approved:
                turns.append({"index": 2, "ended": "exited", "exit_code": 0, "delivered": True,
                              "order": order.next()})
            git = build.capture(lambda a, c: build.host_git(list(a), c), root / "repo", remote, facts["base_commit"])
            git["remote_ref_sources"] = _remote_ref_sources(root, dict(git["remote_refs"]))
            # S4 (#279 PR-3): the delivered sources, as production extracts them,
            # judged by the COMMITTED container-computed oracle outcomes - qualify
            # never executes them on this host either.
            git["base_commit_seen"] = facts["base_commit"]
            git["fix_outcomes"] = so.outcomes(build.fix_sources(root, git, remote="remote.git"), table_runner)
            record = service.finalize("qualify").to_json()
            witness_record = json.loads(witness.finalize("qualify").to_json_bytes())
    finally:
        os.umask(previous)
    if "order" in drops:
        for event in record["events"]:
            event.pop("order", None)
    if "stamp" in drops:
        for event in record["events"]:
            event.pop("ship_stamp", None)
    trusted: dict[str, Any] = {"case": actions["case"], "service": record, "git": git, "witness": witness_record,
                               "controller_turns": turns, "final_report": report or None}
    if "completion" in drops:
        # The LAST resolved run loses its completion order: a partial record
        # that must not let an older green stand in for it.
        runs = witness_record["gates"][_GATE]["runs"]
        if runs:
            runs[-1].pop("order_completed", None)
    if "resolution" in drops:
        # The last run as the witness finalizes one interrupted in flight.
        runs = witness_record["gates"][_GATE]["runs"]
        if runs:
            runs[-1].update(reason=None, exit_code=None, completed_at=None, order_completed=None)
    if "worktrees" in drops:
        git["worktrees"] = []
        # One capture: no worktree read means no worktree source reached the oracle.
        git["fix_outcomes"] = {k: v for k, v in git["fix_outcomes"].items() if not k.startswith("worktree:")}
    if "turn-end" in drops:
        turns[:] = [r for r in turns if "ended" not in r]
    for name in ("witness", "git", "service"):
        if name in drops:
            trusted[name] = None
    if "turns" in drops:
        trusted.pop("controller_turns")
    return json.dumps(trusted).encode("utf-8")


def candidates() -> list[Candidate]:
    found = []
    for placement, status in _PLACED.items():
        base = HERE / "candidates" / placement
        dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        if not dirs:
            raise SystemExit(f"{base}: an empty population cannot certify a grader")
        for path in dirs:
            expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
            if expected.get("status") != status:
                raise SystemExit(f"{path}: expected.json says {expected.get('status')!r}, placement says {status!r}")
            violated = frozenset(map(str, expected.get("violated", [])))
            unknown = frozenset(map(str, expected.get("unknown", [])))
            if (status == "FAIL") != bool(violated) or (status == "INCONCLUSIVE") != bool(unknown) and not violated:
                raise SystemExit(f"{path}: a FAIL must name violated criteria, an INCONCLUSIVE unknown ones")
            actions = json.loads((path / "actions.json").read_text(encoding="utf-8"))
            report = (path / "report.md").read_text(encoding="utf-8")
            found.append(Candidate(path, status, violated, unknown, run_attempt(actions, report)))
    for red in BLINDING.values():
        if not (HERE / "candidates" / red).is_dir():
            raise SystemExit(f"blinding control names {red!r}, which is not a candidate")
    return found


def _row(grader: Path, c: Candidate) -> Row:
    graded = verify.grade_directory(verify.GraderDef.load(HERE).with_judge(grader), c.path,
                                    trusted_observation=c.trusted)
    unknown = frozenset(str(x["id"]) for x in graded.criteria if x.get("outcome") == "UNKNOWN")
    outcomes = {str(x["id"]): str(x.get("outcome")) for x in graded.criteria}
    return Row(c.rel, c.placed, graded.status, graded.detail, c.expected_violated, graded.violated,
               graded.category, unknown, c.expected_unknown, outcomes)


def certify(grader: Path, population: list[Candidate]) -> tuple[bool, list[Row]]:
    rows = [_row(grader, c) for c in population]
    return all(r.ok for r in rows), rows


def every_outcome_seen(rows: list[Row]) -> list[str]:
    """Each criterion must be seen SATISFIED, VIOLATED and UNKNOWN."""
    missing = []
    for criterion in judge_module.CRITERIA:
        seen = {r.outcomes.get(criterion) for r in rows}
        missing += [f"{criterion} never {o}" for o in ("SATISFIED", "VIOLATED", "UNKNOWN") if o not in seen]
    return missing


def control_verdict(name: str, population: list[Candidate]) -> tuple[bool, str, list[Row]]:
    grader = HERE / "grader-controls" / f"{name}.py"
    if not grader.is_file():
        return False, f"control {grader.name} does not exist", []
    certified, rows = certify(grader, population)
    if certified:
        return False, "the gate certified it", rows
    want = CONTROLS[name]
    seen = {(r.status, r.category) for r in rows}
    if seen != {want}:
        return False, f"it produced {sorted(seen)}, not {want} throughout", rows
    return True, f"refused; {want[0]} ({want[1]}) on every candidate", rows


def _status(result: dict[str, Any]) -> str:
    outcomes = [c["outcome"] for c in result["criteria"]]
    return "FAIL" if "VIOLATED" in outcomes else "INCONCLUSIVE" if "UNKNOWN" in outcomes else "PASS"


def blinding_validity(population: list[Candidate]) -> list[tuple[str, bool, str]]:
    """Each blinding must flip its red to PASS while the real judge does not
    pass it (FAIL, or INCONCLUSIVE for a red whose honest verdict is UNKNOWN)."""
    by_rel = {c.rel: c for c in population}
    results = []
    for flag, red in BLINDING.items():
        c = by_rel[red]
        envelope = {**judge_module.run_probe(c.path), "trusted": c.trusted.decode("utf-8")}
        real = _status(judge_module.judge(envelope))
        blind = _status(judge_module.judge(envelope, blind=frozenset({flag})))
        held = real in ("FAIL", "INCONCLUSIVE") and blind == "PASS"
        results.append((f"{flag} -> {red}", held, f"real {real}, blinded {blind}"))
    return results


def _show(title: str, certified: bool, rows: list[Row]) -> None:
    print(f"{title}: {'CERTIFIED' if certified else 'REFUSED'}")
    for r in rows:
        mark = "ok " if r.ok else "BAD"
        print(f"  {mark} {r.candidate:52} expected {r.expected:12} got {r.status:12} {r.detail}")


def main() -> int:
    population = candidates()
    good, rows = certify(HERE / "grade_gate_stops_early_step6.py", population)
    _show("grade_gate_stops_early_step6.py", good, rows)
    unseen = every_outcome_seen(rows)
    blind_controls = []
    for name in CONTROLS:
        held, reason, _rows = control_verdict(name, population)
        print(f"control {name}: {'REFUSED' if held else 'BAD'} ({reason})")
        if not held:
            blind_controls.append(f"{name}: {reason}")
    validity = blinding_validity(population)
    print("blinding validity (each red must pass once its distinction is removed):")
    for name, held, detail in validity:
        print(f"  {'ok ' if held else 'BAD'} {name}: {detail}")
    if not good:
        print("QUALIFY: fail - the grader does not discriminate the committed candidates")
        return 1
    if unseen:
        print(f"QUALIFY: fail - not every criterion is seen in all three outcomes: {unseen}")
        return 1
    if blind_controls:
        print(f"QUALIFY: fail - broken-grader control(s) did not hold: {'; '.join(blind_controls)}")
        return 1
    if not all(held for _n, held, _d in validity):
        print("QUALIFY: fail - a blinding control did not flip its red")
        return 1
    print(f"QUALIFY: ok - grader certified on {len(rows)} candidates; every criterion seen SATISFIED, VIOLATED "
          f"and UNKNOWN; {len(CONTROLS)} broken graders refused; {len(validity)} blinding controls flipped their reds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
