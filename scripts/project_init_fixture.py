#!/usr/bin/env python3
"""Replay claude-power-pack's real /project:init for one Python project (skillc#281).

Everything runs from a pinned export of CPP (`git archive <pin>`), never a
working tree:

1. Step 2: CPP's own engine, `scripts/project-init.py --framework python`
   (template rendering, `uv sync`, git init + initial commit).
2. Step 4a: `lib.cicd.makefile.generate_makefile('.')` > Makefile, and
   `templates/cicd.yml.example` > `.claude/cicd.yml`, exactly as
   `codex/skills/project-init/reference.md` runs them.
3. The cicd-pipeline skill's documented `pipeline --write`, after setting
   `pipeline.provider` in `.claude/cicd.yml` as that skill says to.

Declared patches (`evals/level3/cicd-pipeline/patches/*.json`) are exact
replacements applied to CPP's OWN template at the pin before the engine runs.
Each names the CPP issue it pre-applies. A patch whose `old` text is not
found exactly `count` times refuses: CPP fixed that issue, so the patch must
be dropped deliberately rather than outlive its reason.

Resolution is reproducible: `UV_EXCLUDE_NEWER` is fixed, so a scenario
regenerated later resolves the same tool versions. That date is a generation
input, not project content: uv records it as the lock's `[options]
exclude-newer`, and a lock carrying it reads as outdated to any `uv sync
--locked` without the same setting (the trial runtime's included). So the
committed lock drops that one block and keeps every resolved package. The output keeps the
project's source, `uv.lock` and the generated artifacts; `.git`, `.venv` and
the engine's timestamped checkpoint are not fixture content.

    python3 scripts/project_init_fixture.py generate dev --cpp ~/Projects/claude-power-pack --stage full --dest DIR
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "cicd-pipeline"
PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"
#: Fixed resolution date: the same tool versions for every scenario, every time.
EXCLUDE_NEWER = "2026-10-17T00:00:00Z"
PATCHES = ("cpp-1477.json", "cpp-1478.json")
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_AUTHOR_DATE": "2026-10-17T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-17T00:00:00Z"}

#: scenario -> (project name, pipeline provider, post-generation edits).
#: The held-out project adds a second module and a `[tool.mypy] files` scope,
#: which drives the generated typecheck target's OTHER branch.
SCENARIOS: dict[str, tuple[str, str, dict[str, str]]] = {
    "dev": ("calc-demo", "both", {}),
    "heldout": ("ledger-tool", "woodpecker", {
        "src/ledger_tool/entries.py": (
            '"""Ledger entries."""\n\n\ndef total(amounts: list[int]) -> int:\n'
            '    """Sum a list of amounts."""\n    return sum(amounts)\n'),
        "tests/test_entries.py": (
            '"""Entry totals."""\n\nfrom ledger_tool.entries import total\n\n\n'
            'def test_total() -> None:\n    """Totals add up."""\n    assert total([1, 2, 3]) == 6\n'),
        "+pyproject.toml": '\n[tool.mypy]\nfiles = ["src"]\n',
    }),
}
DROPPED = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
DROPPED_FILES = {".claude/project-init-checkpoint.json"}


class PatchNoLongerApplies(RuntimeError):
    """CPP changed the patched text: the issue was fixed, or the file moved."""


def apply_patches(cpp_tree: Path, names: tuple[str, ...] = PATCHES) -> list[str]:
    applied = []
    for name in names:
        patch = json.loads((TASK / "patches" / name).read_text(encoding="utf-8"))
        for edit in patch["edits"]:
            path = cpp_tree / edit["file"]
            text = path.read_text(encoding="utf-8")
            found = text.count(edit["old"])
            if found != edit["count"]:
                number = patch["issue"].rsplit("#", 1)[-1]
                raise PatchNoLongerApplies(
                    f"{name}: expected {edit['count']} occurrence(s) in {edit['file']}, found {found} - "
                    f"CPP fixed #{number}; drop the patch deliberately")
            path.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")
        applied.append(patch["issue"])
    return applied


def _run(argv: list[str], cwd: Path, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=check, timeout=600)


def generate(scenario: str, cpp: Path, dest: Path, *, stage: str, patched: bool = True) -> dict[str, object]:
    """Write the scenario's project into `dest`; return the provenance record."""
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    name, provider, edits = SCENARIOS[scenario]
    record: dict[str, object] = {"scenario": scenario, "stage": stage, "pin": PIN, "patched": patched,
                                 "exclude_newer": EXCLUDE_NEWER, "steps": []}
    with tempfile.TemporaryDirectory(prefix="skillc-281-gen-") as temp:
        work = Path(temp)
        tree = work / "cpp"
        tree.mkdir()
        archive = subprocess.run(["git", "-C", str(cpp), "archive", PIN], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
        record["patches"] = apply_patches(tree) if patched else []
        env = {**os.environ, **GIT_IDENTITY, "UV_EXCLUDE_NEWER": EXCLUDE_NEWER, "PYTHONPATH": str(tree)}
        env.pop("VIRTUAL_ENV", None)
        target = work / "project"
        engine = _run([sys.executable, str(tree / "scripts" / "project-init.py"), "--project-name", name,
                       "--framework", "python", "--target-dir", str(target)], work, env, check=False)
        record["steps"].append({"step": "2-engine", "exit": engine.returncode,  # type: ignore[union-attr]
                                "tail": (engine.stdout + engine.stderr).strip().splitlines()[-1:]})
        for rel, text in edits.items():
            if rel.startswith("+"):
                with (target / rel[1:]).open("a", encoding="utf-8") as handle:
                    handle.write(text)
            else:
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).write_text(text, encoding="utf-8")
        if edits:
            _run(["uv", "lock"], target, env, check=patched)
        if stage == "full":
            cpp_env = {**env, "PYTHONPATH": f"{tree}:{env.get('PYTHONPATH', '')}"}
            makefile = _run(["uv", "run", "--project", str(tree), "python", "-c",
                             "from lib.cicd.makefile import generate_makefile; print(generate_makefile('.'))"],
                            target, cpp_env)
            (target / "Makefile").write_text(makefile.stdout, encoding="utf-8")
            (target / ".claude").mkdir(exist_ok=True)
            config = (tree / "templates" / "cicd.yml.example").read_text(encoding="utf-8")
            config += f"\n# Set by the cicd-pipeline skill's step 1 (skillc#281 fixture).\npipeline:\n  provider: {provider}\n"
            (target / ".claude" / "cicd.yml").write_text(config, encoding="utf-8")
            record["steps"].append({"step": "4a-makefile+cicd.yml", "exit": 0})  # type: ignore[union-attr]
            pipeline = _run(["uv", "run", "--project", str(tree), "python", "-m", "lib.cicd", "pipeline", "--write"],
                            target, {**cpp_env, "PYTHONPATH": f"{target}:{tree}"})
            record["steps"].append({"step": "pipeline-write", "exit": pipeline.returncode,  # type: ignore[union-attr]
                                    "wrote": [line.split(": ", 1)[1] for line in pipeline.stdout.splitlines()
                                              if line.startswith("Wrote: ")]})
        _copy_clean(target, dest)
        lock = dest / "uv.lock"
        if lock.is_file():
            lock.write_text(normalize_lock(lock.read_text(encoding="utf-8")), encoding="utf-8")
    record["files"] = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    return record


def normalize_lock(text: str) -> str:
    """Drop the generation-time `[options] exclude-newer` block, nothing else."""
    block = f'[options]\nexclude-newer = "{EXCLUDE_NEWER}"\n\n'
    if text.count(block) != 1:
        raise RuntimeError("uv.lock does not carry exactly one generation-time exclude-newer block")
    return text.replace(block, "")


def _copy_clean(src: Path, dest: Path) -> None:
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if DROPPED.intersection(rel.parts) or rel.as_posix() in DROPPED_FILES or not path.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("generate",))
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--cpp", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--stage", choices=("scaffold", "full"), required=True)
    parser.add_argument("--unpatched", action="store_true", help="the real, unpatched output (known-bad control)")
    args = parser.parse_args(argv)
    try:
        record = generate(args.scenario, args.cpp, args.dest, stage=args.stage, patched=not args.unpatched)
    except PatchNoLongerApplies as exc:
        print(f"project_init_fixture: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
