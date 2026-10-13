"""Per-stage outcomes of one witnessed gate run, read by the controller (#376).

A gate-witness run records that a declared gate executed, its exit code and
the tree it ran against. That is whole-gate evidence: an aggregate gate that
exits 0 says nothing about what each of its stages did, and one that exits 1
says nothing about which stages never ran. A grader that needs per-stage facts
used to assume them (#270 comment 6134180009: both #270 judges assumed
typecheck was skipped whatever the attempt actually did).

`capture_stages()` reads them from the CPP runner's own report. The pinned
runner (`lib/cicd/runner.py`, `RunResult.to_dict`) prints one pretty-printed
JSON document on stdout carrying `step_details` - each step's id and status -
followed by the `FLOW_FINISH_GATE:` verdict line. The controller calls this
on the stdout IT captured from `exec_in_attempt()`, at the moment that run
resolved, so the result is bound to that run's exit code and
`tree_digest_at_start`. Replaying a gate later produces a different run; it
never rewrites this one.

STATES. A stage's `outcome` is one of:

  - `passed`  - runner status `success`, or `subsumed` (executed inside an
    aggregate that succeeded, CPP #1152);
  - `failed`  - runner status `failed`;
  - `skipped` - runner status `skipped`: the step's `skip_if` applicability
    fired (for example no `typecheck:` target), so it was never applicable;
  - `not-run` - runner status `not-run` (deferred to an aggregate that then
    failed, CPP #1152), or `pending` in a run that stopped at an EARLIER
    failed step. The pinned `check` plan aborts at the first failure and
    leaves later steps `pending` - it emits `not-run` only for an aggregate
    deferral - so both mean "applicable, but never reached";
  - `null`    - unattributable, with a `reason`: a step carried from an
    earlier invocation (not executed in this run), a `pending` step with no
    earlier failure, or a status this reader does not know.

STRICT, NEVER GUESSED. The whole capture is `unavailable` (with a reason) when
the stdout is absent or not UTF-8, carries anything other than exactly one
column-0 JSON document, does not end in a verdict line, names another plan,
repeats a step id, or contradicts itself or the exit code (a successful run
with a failed stage or a `failed_step`; a failed run whose `failed_step` did
not fail). An
unavailable capture establishes nothing about any stage.

BOUND. Stage commands are the candidate's own (its Makefile), and the runner
streams their output to stderr, not stdout. A candidate process could still
write to the gate's stdout through other means; the single-document rule
makes a second, forged document an `unavailable` capture, not a credited one.
This is a bounded reading of the runner's report, not proof against a
coordinated forgery of the whole stream.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import json

#: The plan `reference.md` prescribes (`--plan check`).
DEFAULT_PLAN = "check"

_VERDICT_PREFIX = "FLOW_FINISH_GATE: "

#: Runner status -> stage outcome, for statuses that map without context.
_DIRECT = {"success": "passed", "subsumed": "passed", "failed": "failed",
           "skipped": "skipped", "not-run": "not-run"}

#: Verdict word -> the exit code the pinned `flow-finish-gate.sh` gives it.
_VERDICT_EXIT = {"ok": 0, "fail": 1, "warn": 3, "skipped": 4}


def unavailable(reason: str) -> dict[str, object]:
    return {"status": "unavailable", "reason": reason}


def _document(text: str) -> tuple[dict[str, object] | None, str, str | None]:
    """`(document, verdict_word, None)` or `(None, "", why)`."""
    lines = text.split("\n")
    opens = [i for i, line in enumerate(lines) if line == "{"]
    closes = [i for i, line in enumerate(lines) if line == "}"]
    if len(opens) != 1 or len(closes) != 1 or closes[0] < opens[0]:
        return None, "", f"expected exactly one column-0 JSON document, found {len(opens)} open/{len(closes)} close"
    try:
        document = json.loads("\n".join(lines[opens[0]:closes[0] + 1]))
    except json.JSONDecodeError as exc:
        return None, "", f"runner JSON does not parse ({exc.msg})"
    if not isinstance(document, dict):
        return None, "", "runner JSON is not an object"
    trailing = [line for line in lines[closes[0] + 1:] if line.strip()]
    if not trailing or not trailing[-1].startswith(_VERDICT_PREFIX):
        return None, "", "no FLOW_FINISH_GATE verdict line after the runner JSON"
    word = trailing[-1][len(_VERDICT_PREFIX):].split(" ", 1)[0]
    if word not in _VERDICT_EXIT:
        return None, "", f"unknown verdict {word!r}"
    return document, word, None


def capture_stages(stdout: bytes | None, exit_code: int | None, *,
                   plan: str = DEFAULT_PLAN) -> dict[str, object]:
    """The per-stage capture for one resolved run. Never raises for bad
    input; every defect becomes an `unavailable` capture."""
    if stdout is None:
        return unavailable("no stdout was captured for this run")
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return unavailable("stdout is not UTF-8")
    document, verdict, why = _document(text)
    if document is None:
        return unavailable(str(why))
    if document.get("plan") != plan:
        return unavailable(f"runner plan is {document.get('plan')!r}, not {plan!r}")
    success = document.get("success")
    failed_step = document.get("failed_step")
    details = document.get("step_details")
    if not isinstance(success, bool) or not isinstance(details, list) or not details:
        return unavailable("runner JSON lacks a boolean success or a non-empty step_details list")
    if failed_step is not None and not isinstance(failed_step, str):
        return unavailable("runner failed_step is not a string")
    if exit_code != _VERDICT_EXIT[verdict]:
        return unavailable(f"exit code {exit_code!r} contradicts verdict {verdict!r}")
    if success != (verdict in ("ok", "warn")):
        return unavailable(f"runner success={success} contradicts verdict {verdict!r}")
    ids: list[str] = []
    for entry in details:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) \
                or not isinstance(entry.get("status"), str):
            return unavailable("a step_details entry lacks a string id or status")
        ids.append(entry["id"])
    if len(set(ids)) != len(ids):
        return unavailable("step_details repeats a step id")
    statuses = {entry["id"]: entry["status"] for entry in details}
    if success and failed_step is not None:
        return unavailable(f"a successful run names failed_step {failed_step!r}")
    if success and any(s == "failed" for s in statuses.values()):
        return unavailable("a successful run reports a failed stage")
    if not success and (failed_step is None or statuses.get(failed_step) != "failed"):
        return unavailable(f"a failed run whose failed_step {failed_step!r} is not a failed stage")
    stages: dict[str, dict[str, object]] = {}
    failure_seen: str | None = None
    for entry in details:
        status = entry["status"]
        record: dict[str, object] = {"outcome": None, "runner_status": status, "reason": None}
        if entry.get("carried_from_previous_run") is True or entry.get("executed_in_this_run") is False:
            record["reason"] = "carried from an earlier invocation; not executed in this run"
        elif status in _DIRECT:
            record["outcome"] = _DIRECT[status]
            if status == "not-run":
                reason = entry.get("not_run_reason")
                record["reason"] = reason if isinstance(reason, str) and reason else "deferred to an aggregate that did not complete"
        elif status == "pending" and failure_seen is not None:
            record["outcome"] = "not-run"
            record["reason"] = f"never reached: the run stopped after {failure_seen} failed"
        elif status == "pending":
            record["reason"] = "pending with no earlier failed stage"
        else:
            record["reason"] = f"runner status {status!r} is not a resolved outcome"
        if status == "failed" and failure_seen is None:
            failure_seen = entry["id"]
        stages[entry["id"]] = record
    return {"status": "captured", "plan": plan, "runner_success": success,
            "failed_step": failed_step, "stages": stages}
