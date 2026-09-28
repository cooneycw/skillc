#!/usr/bin/env python3
"""Judge for the Level 1 finish-close-ref task. The agent never sees this file.

Grading is split in two (skillc.verify, docs/specs/evaluation-facility/verification.md):

  - `probe.py` reads `src/commit_message.txt` from the candidate and reports its
    raw text. It never sees the rule this file grades against.
  - this file, the JUDGE, holds the rule. skillc runs it as `grade_ref.py
    --judge`, with the probe's report on stdin, in a fresh directory, and only
    after every process the probe started is confirmed gone. So no candidate
    code is alive to write on its stdout, the success channel.

The judge prints one JSON object - one criterion per requirement, each
SATISFIED/VIOLATED/UNKNOWN with evidence - and exits 0. Any other exit, or no
output, is a grader failure, not a verdict on the candidate: INCONCLUSIVE.

The probe's report is untrusted: candidate code shares the probe's process and
can write it. Anything that is not a well-formed report of the named file's
text is read as an interface failure, never as a verdict.

THE RULE THIS JUDGES (skillc #150, acceptance item 1): GitHub's issue-closing
matcher recognizes a literal closing keyword (close/closes/closed/fix/fixes/
fixed/resolve/resolves/resolved), an optional colon, then an issue reference
- case-insensitively, ANYWHERE in the text, with no regard for surrounding
grammar or negation. A negated disclaimer ("this does not close #N") closes
the issue exactly as a bare closing trailer does. Modeled on GitHub's own
docs ("Linking a pull request to an issue using a keyword", docs.github.com,
read 2026-09-28) and cross-checked against claude-power-pack's own merge
guard at the pinned revision (`scripts/gh-pr-merge.sh`,
`guard_negated_close_keywords`'s `keyword_re`, commit 85e9b03a) - see
PROVENANCE.md for the full citation. GitHub's documented grammar also
accepts a cross-repo `OWNER/REPOSITORY#N` reference; this judge deliberately
does NOT model it (see KEYWORD_RE's comment below for why). The flow-finish
skill states the consequence: never print a closing keyword beside an issue
number, even to explain that the issue is NOT closed.
"""

from __future__ import annotations

import json
import re
import sys

GRADER = {"id": "finish-close-ref", "revision": "1"}

#: The issue this task's fixture is about. Fixed, not derived from the
#: candidate's text: a candidate that closes a DIFFERENT issue number must not
#: be read as satisfying (or violating) this one's rule.
ISSUE_NUMBER = "42"

#: GitHub's nine closing keywords (case-insensitive), an optional colon, then
#: optional whitespace, then `#<digits>`. See the module docstring for the
#: citation. Deliberately NOT anchored to sentence or clause boundaries -
#: unlike claude-power-pack's own guard, this judge does not need to separate
#: "negated" from "incidental" overrides (that split exists there only to
#: pick which escape-hatch flag an operator consciously passes); it only
#: needs to know whether GitHub's own matcher would fire, and GitHub's
#: matcher does not parse grammar at all.
#:
#: Deliberately bare-`#N` only, with no `OWNER/REPOSITORY#N` form, even
#: though GitHub's documented grammar recognizes that form too (module
#: docstring). This fixture never declares which repository its own issue
#: #42 lives in, so a candidate referencing `some-owner/some-repo#42` names
#: an issue this judge cannot know is - or is not - the fixture's own; a
#: verdict that depended on that undeclared fact would not be a certified
#: outcome. Grading only the bare form loses nothing the task needs: the
#: discriminating case (a negated disclaimer still closes an issue) holds
#: identically for the bare form. See README.md, "What this task does not
#: grade".
KEYWORD_RE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s*#(\d+)\b")

#: A bare reference to issue #42 itself - see KEYWORD_RE's comment for why
#: this deliberately does not also recognize an `OWNER/REPOSITORY#42` form.
#: The negative lookbehind is load-bearing, not decorative: without it,
#: "#42" still substring-matches inside "some-owner/some-repo#42", crediting
#: a reference to a DIFFERENT repository's issue 42 as if it named this
#: fixture's own #42 - the same undeclared-repository problem KEYWORD_RE's
#: comment explains, just on the issue-ref criterion instead of
#: no-closing-match.
ISSUE_REF_RE = re.compile(r"(?<![\w/])#" + ISSUE_NUMBER + r"\b")

#: Deliberately generous (design-review requirement for this task, 2026-09-28):
#: any one of these words is enough to credit the candidate with conveying
#: that the issue stays open. It must not fail either reference answer.
STAYS_OPEN_RE = re.compile(
    r"(?i)\b(open|remains?|remaining|incomplete|unfinished|outstanding|pending|left)\b"
)

TARGET_FILE = "commit_message.txt"

REQUIRED_CRITERIA = ("artifact-present", "issue-ref", "stays-open", "no-closing-match")


def read_report(envelope: dict[str, object]) -> dict[str, object]:
    """The probe's report, or why there is nothing to judge."""
    if envelope.get("timed_out") is True:
        return {"import_error": "the probe did not finish within its time limit"}
    text = envelope.get("observations")
    if not isinstance(text, str) or not text.strip():
        return {"import_error": "the probe produced no report"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"import_error": "the probe report is not JSON"}
    if not isinstance(data, dict) or set(data) != {"files"} or not isinstance(data["files"], dict):
        return {"import_error": "the probe report is malformed"}
    files = data["files"]
    if set(files) != {TARGET_FILE}:
        return {"import_error": f"the probe report does not name exactly {TARGET_FILE!r}"}
    entry = files[TARGET_FILE]
    if not isinstance(entry, dict) or len(entry) != 1 or next(iter(entry)) not in ("text", "read_error"):
        return {"import_error": "the probe's file entry is malformed"}
    return {"entry": entry}


def judge(envelope: dict[str, object]) -> dict[str, object]:
    """The criteria for one probe report. No candidate code runs here."""
    data = read_report(envelope)

    if "import_error" in data:
        reason = str(data["import_error"])
        criteria: list[dict[str, object]] = [
            {"id": "artifact-present", "mandatory": True, "outcome": "VIOLATED", "evidence": [reason]},
        ]
        for cid in ("issue-ref", "stays-open", "no-closing-match"):
            criteria.append({"id": cid, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no readable {TARGET_FILE} to judge: {reason}"})
        return {"grader": GRADER, "criteria": criteria}

    entry = data["entry"]
    assert isinstance(entry, dict)
    if "read_error" in entry:
        reason = f"{TARGET_FILE}: {entry['read_error']}"
        criteria = [
            {"id": "artifact-present", "mandatory": True, "outcome": "VIOLATED", "evidence": [reason]},
        ]
        for cid in ("issue-ref", "stays-open", "no-closing-match"):
            criteria.append({"id": cid, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"no readable {TARGET_FILE} to judge: {reason}"})
        return {"grader": GRADER, "criteria": criteria}

    text = entry["text"]
    assert isinstance(text, str)
    if not text.strip():
        criteria = [
            {"id": "artifact-present", "mandatory": True, "outcome": "VIOLATED",
             "evidence": [f"{TARGET_FILE} exists but is empty"]},
        ]
        for cid in ("issue-ref", "stays-open", "no-closing-match"):
            criteria.append({"id": cid, "mandatory": True, "outcome": "UNKNOWN",
                             "missing": f"{TARGET_FILE} is empty, nothing to judge"})
        return {"grader": GRADER, "criteria": criteria}

    criteria = [
        {"id": "artifact-present", "mandatory": True, "outcome": "SATISFIED",
         "evidence": [f"{TARGET_FILE} is present and non-empty"]},
    ]

    if ISSUE_REF_RE.search(text):
        criteria.append({"id": "issue-ref", "mandatory": True, "outcome": "SATISFIED",
                         "evidence": [f"references #{ISSUE_NUMBER}"]})
    else:
        criteria.append({"id": "issue-ref", "mandatory": True, "outcome": "VIOLATED",
                         "evidence": [f"no reference to #{ISSUE_NUMBER} found"]})

    if STAYS_OPEN_RE.search(text):
        criteria.append({"id": "stays-open", "mandatory": True, "outcome": "SATISFIED",
                         "evidence": ["states the issue stays open or work remains"]})
    else:
        criteria.append({"id": "stays-open", "mandatory": True, "outcome": "VIOLATED",
                         "evidence": ["does not state that the issue stays open or what remains"]})

    matches = [m for m in KEYWORD_RE.finditer(text) if m.group(1) == ISSUE_NUMBER]
    if matches:
        evidence = [f"{m.group(0)!r} at offset {m.start()}" for m in matches]
        criteria.append({"id": "no-closing-match", "mandatory": True, "outcome": "VIOLATED",
                         "evidence": evidence})
    else:
        criteria.append({"id": "no-closing-match", "mandatory": True, "outcome": "SATISFIED",
                         "evidence": ["no closing keyword adjacent to #" + ISSUE_NUMBER]})

    return {"grader": GRADER, "criteria": criteria}


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    print("usage: grade_ref.py --judge < ENVELOPE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
