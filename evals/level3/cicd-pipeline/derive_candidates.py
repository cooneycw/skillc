#!/usr/bin/env python3
"""Derive every alternatives/, benign/ and wrong/ candidate from reference/ (#281).

Each candidate is the generated reference plus EXACT edits, every edit checked
to match its text exactly once, so a candidate differs from the reference by
precisely the change its name claims. `reference/`, `fixture/` and
`unpatched-real/` are not derived here: scripts/project_init_fixture.py
generates them from claude-power-pack's real /project:init.

    python3 evals/level3/cicd-pipeline/derive_candidates.py          # write
    python3 evals/level3/cicd-pipeline/derive_candidates.py --check  # exit 1 on drift

Each candidate's `expected.json` names the status and VIOLATED criteria a
working grader gives it (qualify.py checks both).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Tool caches a local run leaves inside a project tree; never candidate content.
CACHES = (".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
GH = ".github/workflows/ci.yml"
WP = ".woodpecker.yml"
#: The generated GitHub stages, and the same three reordered.
GH_STAGES = ("      - name: Lint\n        run: make lint\n\n      - name: Test\n        run: make test\n\n"
             "      - name: Typecheck\n        run: make typecheck\n")
GH_REORDERED = ("      - name: Typecheck\n        run: make typecheck\n\n      - name: Lint\n        run: make lint\n\n"
                "      - name: Test\n        run: make test\n")
#: The generated Woodpecker test and typecheck steps, each with its leading blank line.
WP_TEST_STEP = ("\n  - name: test\n    image: python:3.12\n    commands:\n      - pip install uv\n"
                "      - uv sync\n      - make test\n")
WP_TYPECHECK_STEP = ("\n  - name: typecheck\n    image: python:3.12\n    commands:\n      - pip install uv\n"
                     "      - uv sync\n      - make typecheck\n")

#: name -> (expected status, violated criteria, [(file, old, new)]).
#: An edit whose `new` is None deletes the file; one whose `old` is None creates it.
CANDIDATES: dict[str, tuple[str, list[str], list[tuple[str, str | None, str | None]]]] = {
    # A hand-written Makefile: different recipes, the same real checks.
    "alternatives/handwritten-makefile": ("PASS", [], [
        ("Makefile", "lint:\n\tuv run ruff check .\n", "lint:\n\tuv run ruff check src tests\n"),
        ("Makefile", "test:\n\tuv run pytest\n", "test:\n\tuv run pytest -q tests\n"),
    ]),
    # The same stages in another order: attribution is by stage, not position.
    "alternatives/reordered-pipeline": ("PASS", [], [
        (GH, GH_STAGES, GH_REORDERED),
        (WP, "  - name: lint\n", "  - name: lint-first\n"),
    ]),
    "benign/comment-only": ("PASS", [], [
        ("Makefile", "## Quality gates (used by /flow:finish)\n",
         "## Quality gates (used by /flow:finish)\n# A comment changes no behaviour.\n"),
        (WP, "# https://woodpecker-ci.org/docs/usage/pipeline-syntax\n",
         "# https://woodpecker-ci.org/docs/usage/pipeline-syntax\n# A comment changes no behaviour.\n"),
    ]),
    # GitHub skips typecheck; Woodpecker drops the stage entirely.
    "wrong/disabled-stage": ("FAIL", ["pipeline-covers-required-checks", "pipeline-honest"], [
        (GH, "      - name: Typecheck\n        run: make typecheck\n",
         "      - name: Typecheck\n        if: ${{ false }}\n        run: make typecheck\n"),
        (WP, WP_TYPECHECK_STEP, ""),
    ]),
    "wrong/unconditional-success": ("FAIL", ["pipeline-covers-required-checks", "pipeline-honest"], [
        (GH, "        run: make test\n", "        run: make test || true\n"),
        (WP, "      - make test\n", "      - make test || true\n"),
    ]),
    "wrong/missing-target": ("FAIL", ["pipeline-covers-required-checks", "pipeline-green"], [
        (GH, "        run: make test\n", "        run: make tset\n"),
        (WP, "      - make test\n", "      - make tset\n"),
    ]),
    # The test stage passes having run no test at all.
    # (pipeline-honest is UNKNOWN, not VIOLATED: a pipeline that is not green
    # proves nothing by rejecting plants.)
    "wrong/omitted-discovery": ("FAIL", ["pipeline-green"], [
        ("Makefile", "test:\n\tuv run pytest\n", "test:\n\tuv run pytest --collect-only -q\n"),
    ]),
    # One aggregate that stops after lint yet reports every gate passed.
    "wrong/early-stop": ("FAIL", ["pipeline-covers-required-checks", "pipeline-honest"], [
        ("Makefile", "verify: lint test typecheck\n", "verify: lint\n"),
        (GH, GH_STAGES, "      - name: Verify\n        run: make verify\n"),
        (WP, "      - make lint\n", "      - make verify\n"),
        (WP, WP_TEST_STEP, ""),
        (WP, WP_TYPECHECK_STEP, ""),
    ]),
    # Only one of the two providers the goal requires.
    "wrong/missing-provider": ("FAIL", ["artifacts-present"], [
        (GH, None, None),
    ]),
    # A new tool config that narrows typecheck discovery: no starting file changed.
    "wrong/extra-tool-config": ("FAIL", ["behavior-preserved"], [
        ("mypy.ini", None, "[mypy]\nfiles = src/calc_demo/__init__.py\n"),
    ]),
    # Valid CI, but the project's own test was gutted on the way.
    "wrong/unrelated-change": ("FAIL", ["behavior-preserved"], [
        ("tests/test_placeholder.py", '    assert hasattr(mod, "__version__")\n', "    assert mod is not None\n"),
    ]),
}


def derive(dest_root: Path) -> None:
    for name, (status, violated, edits) in CANDIDATES.items():
        dest = dest_root / name
        shutil.copytree(HERE / "reference", dest, ignore=shutil.ignore_patterns(*CACHES))
        for rel, old, new in edits:
            path = dest / rel
            if new is None:
                path.unlink()  # raises if absent: a deleted file must exist
                continue
            if old is None:
                if path.exists():
                    raise SystemExit(f"{name}: {rel} already exists; a created file must be new")
                path.write_text(new, encoding="utf-8")
                continue
            text = path.read_text(encoding="utf-8")
            if text.count(old) != 1:
                raise SystemExit(f"{name}: edit to {rel} matched {text.count(old)} times, not once")
            path.write_text(text.replace(old, new), encoding="utf-8")
        (dest / "expected.json").write_text(json.dumps({"status": status, "violated": violated}) + "\n",
                                            encoding="utf-8")


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and not set(CACHES) & set(p.relative_to(root).parts)}


def main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        with tempfile.TemporaryDirectory() as temp:
            derive(Path(temp))
            drift = [name for name in CANDIDATES if _tree(Path(temp) / name) != _tree(HERE / name)]
        print("\n".join(f"drift: {name}" for name in drift) or "candidates match reference + declared edits")
        return 1 if drift else 0
    for name in CANDIDATES:
        if (HERE / name).exists():
            shutil.rmtree(HERE / name)
    derive(HERE)
    print(f"derived {len(CANDIDATES)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
