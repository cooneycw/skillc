#!/usr/bin/env python3
"""Apply or check GitHub branch protection for skillc's `main` (issue #73).

**Operator tool. Never run in CI.** It needs a GitHub token - `gh`'s own
auth - and the apply path is a real, hard-to-reverse change to shared repo
settings. `--check` is read-only (a single GET) and safe to run any time; the
apply path (no flag, or `--apply`) should be run deliberately, by a human.

Owner instruction, 2026-09-26: `main` requires the `ci/woodpecker/pr/ci`
status check, strict (the branch must be up to date with `main` before
merging), no required reviews, `enforce_admins=false`, and blocks force-push
and branch deletion. **Never merge a protected PR with `--admin`** - that
bypasses every one of these checks rather than satisfying them, and defeats
the reason this script exists.

`EXPECTED_CONTEXTS` is the one thing likely to change (a renamed or added
required check); everything else is a fixed policy decision. Update it there,
not by hand-editing what `--check` compares against.
"""

from __future__ import annotations

import json
import subprocess
import sys

REPO = "cooneycw/skillc"
BRANCH = "main"

#: The one required status check. A second one would need review: strict mode
#: means EVERY required check must be green and up to date before merge.
EXPECTED_CONTEXTS = ["ci/woodpecker/pr/ci"]

#: The PUT body per GitHub's branch-protection API. `required_pull_request_
#: reviews` and `restrictions` must be explicit `null` in a PUT - omitting them
#: is not the same as clearing them.
APPLY_BODY: dict[str, object] = {
    "required_status_checks": {"strict": True, "contexts": EXPECTED_CONTEXTS},
    "enforce_admins": False,
    "required_pull_request_reviews": None,
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def drift(actual: dict[str, object], expected_contexts: list[str] = EXPECTED_CONTEXTS) -> list[str]:
    """Human-readable differences between `actual` (a GET response) and the
    policy, or `[]` when `actual` already satisfies it.

    Reads the GET response's own shape (`{"enabled": bool}` for the simple
    toggles), which differs from `APPLY_BODY`'s PUT shape (bare booleans) -
    GitHub's API is asymmetric between the two verbs for the same settings.
    """
    problems: list[str] = []
    rsc = actual.get("required_status_checks")
    rsc = rsc if isinstance(rsc, dict) else {}
    if rsc.get("strict") is not True:
        problems.append(f"required_status_checks.strict is {rsc.get('strict')!r}, want True")
    contexts = rsc.get("contexts")
    if contexts != expected_contexts:
        problems.append(f"required_status_checks.contexts is {contexts!r}, want {expected_contexts!r}")
    for key in ("enforce_admins", "allow_force_pushes", "allow_deletions"):
        value = actual.get(key)
        enabled = value.get("enabled") if isinstance(value, dict) else value
        want = False
        if enabled is not want:
            problems.append(f"{key}.enabled is {enabled!r}, want {want!r}")
    if actual.get("required_pull_request_reviews") is not None:
        problems.append("required_pull_request_reviews is set, want none required")
    if actual.get("restrictions") is not None:
        problems.append("restrictions is set, want none")
    return problems


def _gh(*args: str, input_json: dict[str, object] | None = None) -> str:
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(input_json) if input_json is not None else None,
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"branch-protection: gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def current_protection(repo: str = REPO, branch: str = BRANCH) -> dict[str, object]:
    out = _gh("api", f"repos/{repo}/branches/{branch}/protection")
    data = json.loads(out)
    assert isinstance(data, dict)
    return data


def apply_protection(repo: str = REPO, branch: str = BRANCH) -> None:
    _gh(
        "api", "-X", "PUT", f"repos/{repo}/branches/{branch}/protection",
        "--input", "-",
        input_json=APPLY_BODY,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    check = "--check" in args
    apply = "--apply" in args
    if check == apply:
        print(
            "branch-protection: pass exactly one of --check (read-only) or "
            "--apply (writes; a real, hard-to-reverse change)",
            file=sys.stderr,
        )
        return 2
    if apply:
        print(f"branch-protection: applying policy to {REPO}@{BRANCH}", file=sys.stderr)
        apply_protection()
        print("branch-protection: applied")
        return 0
    problems = drift(current_protection())
    if problems:
        print(f"branch-protection: DRIFT on {REPO}@{BRANCH}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"branch-protection: ok - {REPO}@{BRANCH} matches policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
