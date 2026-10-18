#!/usr/bin/env python3
"""Regenerate every fixture-SHA reference in this task from the builder (#434, grader revision 2).

The fixture's commits and trees are hard-coded in the judge's constants, in candidates'
`actions.json` (a `detach` or `reset-hard` target) and in their `report.md` (a cited
commit prefix), and in the tests that replay candidates. A fixture change moves them
all. This script is the ONE place they are rewritten, so none is hand-edited:

- the OLD objects are revision 1's fixture, recorded below as measured;
- the NEW objects are what `builder/build.py` produces now, for both cases;
- each old object maps to its counterpart (the initial commit, the fix commit, and each
  case's base tree);
- a hex token (7 to 40 characters) is rewritten ONLY when it is a prefix of a real old
  object, and then to the same-length prefix of the new one;
- any other token is left alone. That covers a deliberately fabricated SHA a candidate
  cites (`deadbeef12`) and an unrelated external SHA.

    python3 evals/level3/flow-auto-necessity/regenerate.py           # rewrite in place
    python3 evals/level3/flow-auto-necessity/regenerate.py --check   # exit 1 if anything would change

Running it twice changes nothing: after the first run no old object remains.
`tests/test_flow_auto_necessity_task.py` asserts that, and that every cited token
resolves under the new fixture exactly when it resolved under the old one.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

#: Revision 1's fixture objects, as `builder/build.py` produced them before revision 2.
REVISION_1 = {
    "initial": "a65d6b3bbb57cf04478712f84299eb4b301d8142",
    "fix": "970ffd0266624752509568367994a399d74d12db",
    "clean_tree": "a3f624196a8b25d7ed43a44c697e13381ec28ae8",
    "twin_tree": "afa4d4451f9329e98435eec1af9925fcd160303f",
}

#: Every file whose hex tokens may name a fixture object.
TARGETS = [
    HERE / "grade_flow_auto_necessity.py",
    HERE / "PROVENANCE.md",
    *sorted((HERE / "candidates").glob("*/*/actions.json")),
    *sorted((HERE / "candidates").glob("*/*/report.md")),
    ROOT / "tests" / "test_git_snapshot.py",
    ROOT / "tests" / "test_flow_auto_necessity_task.py",
    ROOT / "tests" / "test_agent_trial_fixture.py",
]

_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")


def _builder():
    spec = importlib.util.spec_from_file_location("flow_auto_necessity_build_regen", HERE / "builder" / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def current() -> dict[str, str]:
    """The builder's objects now, by the same keys as REVISION_1."""
    build = _builder()
    found: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="flow-auto-necessity-regen-") as tmp:
        for case in ("clean", "twin"):
            root = Path(tmp) / case
            root.mkdir()
            facts = build.build(root, case)
            found[f"{case}_tree"] = facts["base_tree"]
            found["initial"] = facts["commits"][0]
            if case == "clean":
                found["fix"] = facts["fix_commit"]
    return found


def mapping(new: dict[str, str]) -> dict[str, str]:
    return {REVISION_1[key]: new[key] for key in REVISION_1}


def rewrite(text: str, old_to_new: dict[str, str]) -> str:
    """Rewrite each token that is a prefix of a real old object; leave every other token alone."""
    def one(match: re.Match[str]) -> str:
        token = match.group(0)
        hits = [old for old in old_to_new if old.startswith(token)]
        if len(hits) != 1:
            return token  # not an old object (or ambiguous, which a 7+ prefix of these four is not)
        return old_to_new[hits[0]][: len(token)]
    return _TOKEN.sub(one, text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    old_to_new = mapping(current())
    changed = []
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        out = rewrite(text, old_to_new)
        if out != text:
            changed.append(path.relative_to(ROOT).as_posix())
            if not check:
                path.write_text(out, encoding="utf-8")
    for name in changed:
        print(("would rewrite " if check else "rewrote ") + name)
    return 1 if check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
