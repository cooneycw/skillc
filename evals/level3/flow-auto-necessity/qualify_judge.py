#!/usr/bin/env python3
"""Qualify the PLUMBING of the independent Anthropic judge (#513) on this
task's committed candidates. It makes NO paid call and holds NO key.

WHAT A PASS HERE MEANS, AND WHAT IT DOES NOT. Every request goes through the
real `skillc.judge_anthropic.AnthropicJudge` over a real socket to
`FakeMessagesServer`, which answers from a SCRIPTED ORACLE: each candidate's
own `expected.json`. So a PASS shows that what reaches the judge is right
(the observations whole and labelled as facts, the report whole and fenced as
a claim, every criterion with its rubric definition, the pinned model, the
forced tool) and that a verdict coming back is carried through `run_tier`
intact. It says NOTHING about whether claude-opus-5-5 grades well. That is the
owner-approved paid validation's job (held-out, blind, repeated), and this
output says so on every run so its PASS is never quoted as validation
(orchestrator C5).

Three broken judges must each be REFUSED:

  - drop-observations: the builder leaves observed_facts out, so the judge
    could only trust the report;
  - drop-criterion-text: the builder sends ids without definitions;
  - always-satisfied: the judge answers SATISFIED to everything, so no
    fail or inconclusive row is reproduced.

`fail/clean-steers-the-judge` is the injection candidate (orchestrator C1):
its report tries to close its own JSON field, forge an observation and tell
the grader to pass everything. Here it must reach the judge byte for byte,
inside agent_claims, forging nothing, and the deterministic grader must still
grade it as its expected.json says. Whether a real model resists it is a
named item of the paid held-out set.

It lives in `judge-candidates/`, not `candidates/`: the deterministic
population is pinned by the frozen #434 campaign manifest and by candidate
counts, and a judge-only control must not move them.

`python3 qualify_judge.py` exits 0 only when all of that holds.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import qualify

from skillc import judge
from skillc import judge_anthropic as ja

BANNER = ("PLUMBING ONLY: a scripted oracle (each candidate's expected.json) answers every call. A PASS shows "
          "what reaches the judge and what comes back intact; it is NOT evidence that the model grades well, "
          "and must not be quoted as validation.")
STEERING = "fail/clean-steers-the-judge"
JUDGE_CANDIDATES = HERE / "judge-candidates"
OBSERVATIONS = "observations.json"
REPORT = "report.md"
CRITERIA: tuple[str, ...] = tuple(json.loads((HERE / "grader.json").read_text(encoding="utf-8"))["criteria"])
RUBRIC: dict[str, str] = json.loads((HERE / "judge-rubric.json").read_text(encoding="utf-8"))["criteria"]
GOAL = (HERE / "goal.md").read_text(encoding="utf-8")


def judge_input(c: qualify.Candidate) -> tuple[bytes, str | None]:
    """The controller-held observations (the trusted envelope less the report)
    and the report, which is the claim under test."""
    trusted = json.loads(c.trusted)
    report = trusted.pop("final_report")
    return json.dumps(trusted, sort_keys=True).encode("utf-8"), report


def files_for(c: qualify.Candidate) -> list[tuple[str, bytes]]:
    observations, report = judge_input(c)
    files = [(OBSERVATIONS, observations)]
    if report is not None:
        files.append((REPORT, report.encode("utf-8")))
    return files


def oracle(c: qualify.Candidate) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for cid in CRITERIA:
        if cid in c.expected_violated:
            out.append({"id": cid, "outcome": "VIOLATED", "evidence": ["oracle: expected.json"]})
        elif cid in c.expected_unknown:
            out.append({"id": cid, "outcome": "UNKNOWN", "missing": "oracle: expected.json"})
        else:
            out.append({"id": cid, "outcome": "SATISFIED", "evidence": ["oracle: expected.json"]})
    return out


def always_satisfied(c: qualify.Candidate) -> list[dict[str, object]]:
    return [{"id": cid, "outcome": "SATISFIED", "evidence": ["always"]} for cid in CRITERIA]


@dataclasses.dataclass(frozen=True)
class DropObservations(ja.AnthropicJudge):
    def build_user_document(self, criteria: Sequence[str], goal_text: str,
                            candidate_files: Sequence[tuple[str, bytes]]) -> dict[str, Any]:
        document = super().build_user_document(criteria, goal_text, candidate_files)
        return {**document, "observed_facts": []}


@dataclasses.dataclass(frozen=True)
class DropCriterionText(ja.AnthropicJudge):
    def build_user_document(self, criteria: Sequence[str], goal_text: str,
                            candidate_files: Sequence[tuple[str, bytes]]) -> dict[str, Any]:
        document = super().build_user_document(criteria, goal_text, candidate_files)
        return {**document, "criteria": [{"id": c["id"], "definition": ""} for c in document["criteria"]]}


def request_problem(c: qualify.Candidate, body: Mapping[str, Any]) -> str | None:
    """What is wrong with the request the judge received for `c`, or None."""
    observations, report = judge_input(c)
    if body.get("model") != ja.DEFAULT_MODEL or body.get("tool_choice") != {"type": "tool", "name": ja.TOOL_NAME}:
        return "not the pinned model with the forced tool"
    document = ja.user_document(body)
    if document.get("observed_facts") != [{"name": OBSERVATIONS, "content": observations.decode("utf-8")}]:
        return "the observations did not reach the judge whole, as facts"
    claims = [] if report is None else [{"name": REPORT, "content": report}]
    if document.get("agent_claims") != claims:
        return "the report did not reach the judge whole, as a claim"
    if document.get("criteria") != [{"id": cid, "definition": RUBRIC[cid]} for cid in CRITERIA]:
        return "the criteria did not reach the judge with their rubric definitions"
    return None


def verdict_problem(c: qualify.Candidate, tier: Mapping[str, Any]) -> str | None:
    criteria = tier.get("criteria") or []
    violated = frozenset(x["id"] for x in criteria if x.get("outcome") == "VIOLATED")
    unknown = frozenset(x["id"] for x in criteria if x.get("outcome") == "UNKNOWN")
    if (tier.get("status"), violated, unknown) != (c.placed, c.expected_violated, c.expected_unknown):
        return (f"judged {tier.get('status')} violated={sorted(violated)} unknown={sorted(unknown)}, "
                f"expected {c.placed} violated={sorted(c.expected_violated)} unknown={sorted(c.expected_unknown)}")
    return None


def run(population: list[qualify.Candidate], answer: Callable[[qualify.Candidate], list[dict[str, object]]],
        kind: type[ja.AnthropicJudge] = ja.AnthropicJudge) -> list[tuple[str, str | None]]:
    current: list[qualify.Candidate] = []
    fake = ja.FakeMessagesServer(lambda body: (200, ja.tool_reply(answer(current[-1]))))
    rows: list[tuple[str, str | None]] = []
    with fake.running() as url:
        for c in population:
            current.append(c)
            before = len(fake.requests)
            one = kind(key_provider=lambda: "qualify-holds-no-key", criteria_text=RUBRIC,
                       observation_files=frozenset({OBSERVATIONS}), base_url=url, timeout=30.0)
            tier = judge.run_tier(judge.INDEPENDENT_TIER, one, CRITERIA, GOAL, files_for(c))
            if len(fake.requests) != before + 1:
                rows.append((c.rel, f"expected one request, saw {len(fake.requests) - before}: {tier.get('reason')}"))
                continue
            rows.append((c.rel, request_problem(c, fake.requests[-1]["body"]) or verdict_problem(c, tier)))
    return rows


class JudgeOnlyCandidate(qualify.Candidate):
    """A candidate outside the deterministic population (`judge-candidates/`)."""

    @property
    def rel(self) -> str:
        return self.path.relative_to(JUDGE_CANDIDATES).as_posix()


def judge_only_candidates() -> list[qualify.Candidate]:
    """Loaded with the same checks `qualify.candidates` applies to its own."""
    found: list[qualify.Candidate] = []
    for placement, status in qualify._PLACED.items():
        base = JUDGE_CANDIDATES / placement
        for path in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
            expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
            if expected.get("status") != status:
                raise SystemExit(f"{path}: expected.json says {expected.get('status')!r}, placement says {status!r}")
            actions = json.loads((path / "actions.json").read_text(encoding="utf-8"))
            report = (path / "report.md").read_text(encoding="utf-8")
            found.append(JudgeOnlyCandidate(path, status, actions, frozenset(map(str, expected.get("violated", []))),
                                            frozenset(map(str, expected.get("unknown", []))),
                                            qualify.run_attempt(actions, report)))
    if [c.rel for c in found] != [STEERING]:
        raise SystemExit(f"{JUDGE_CANDIDATES}: expected exactly [{STEERING}], found {[c.rel for c in found]}")
    return found


def steering_is_graded_as_expected(c: qualify.Candidate) -> str | None:
    """The deterministic grader, unchanged, still grades the steering report
    as its expected.json says - so the oracle answer below is grounded."""
    row = qualify._row(HERE / "grade_flow_auto_necessity.py", c)
    if row.status != c.placed or row.violated != c.expected_violated:
        return f"the deterministic grader says {row.status} {sorted(row.violated)}, expected {c.placed} " \
               f"{sorted(c.expected_violated)}"
    return None


def steering_reaches_the_judge_verbatim(population: list[qualify.Candidate]) -> str | None:
    (c,) = [c for c in population if c.rel == STEERING]
    report = (c.path / "report.md").read_text(encoding="utf-8")
    if "ignore the observations" not in report or '"observed_facts"' not in report:
        return "the steering candidate no longer tries to steer or to forge a fact"
    fake = ja.FakeMessagesServer(lambda body: (200, ja.tool_reply(oracle(c))))
    with fake.running() as url:
        judge.run_tier(judge.INDEPENDENT_TIER, ja.AnthropicJudge(
            key_provider=lambda: "qualify-holds-no-key", criteria_text=RUBRIC,
            observation_files=frozenset({OBSERVATIONS}), base_url=url), CRITERIA, GOAL, files_for(c))
    document = ja.user_document(fake.requests[0]["body"])
    if document["agent_claims"] != [{"name": REPORT, "content": report}]:
        return "the steering report did not reach the judge byte for byte inside agent_claims"
    if [f["name"] for f in document["observed_facts"]] != [OBSERVATIONS]:
        return "the steering report forged an observed fact"
    return None


CONTROLS: dict[str, tuple[Callable[[qualify.Candidate], list[dict[str, object]]], type[ja.AnthropicJudge]]] = {
    "drop-observations": (oracle, DropObservations),
    "drop-criterion-text": (oracle, DropCriterionText),
    "always-satisfied": (always_satisfied, ja.AnthropicJudge),
}


def main() -> int:
    print(BANNER)
    population = qualify.candidates() + judge_only_candidates()
    rows = run(population, oracle)
    bad = [(name, why) for name, why in rows if why]
    print(f"judge plumbing on {len(rows)} candidates: {len(rows) - len(bad)} carried intact")
    for name, why in bad:
        print(f"  WRONG {name}: {why}")
    (steer,) = [c for c in population if c.rel == STEERING]
    steering = steering_is_graded_as_expected(steer) or steering_reaches_the_judge_verbatim(population)
    print(f"steering candidate {STEERING}: {steering or 'reached the judge verbatim, inside agent_claims'}")
    refused_all = True
    for name, (answer, kind) in CONTROLS.items():
        caught = [r for r in run(population, answer, kind) if r[1]]
        refused = bool(caught)
        refused_all &= refused
        print(f"control {name}: {'REFUSED' if refused else 'NOT REFUSED'} ({len(caught)} of {len(rows)} wrong)")
    ok = not bad and steering is None and refused_all
    print(f"{'PLUMBING QUALIFIED' if ok else 'NOT QUALIFIED'} - {BANNER}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
