"""A stand-in Codex client for skillc exposure's own tests (#55) - distinct
from materialize.py's own fixture (`tests/fixtures/codex-subject/fake_codex.py`)
because exposure needs to simulate AGENTS.md-shaped always-loaded content and
a configurable truncation boundary, neither of which that fixture models.

Answers the same two calls `run_client` ever makes: `--version` and
`debug prompt-input PROMPT`. Configuration comes from a sidecar file next to
this script's own copy: `<script>.mode`, one JSON object (file-based fault
injection, never environment-based - `DockerBackend`'s own fixture documents
why: the adapter runs clients with a controlled environment, so an
environment toggle would not reliably reach every subprocess this fixture's
caller launches).

Sidecar fields:
  mode            "normal" (default) | "crash" | "hang" | "empty" (exit 0,
                  nothing on stdout - its own blind case, distinct from a
                  crash) | "textless" (exit 0, well-formed JSON, but no
                  extractable text - distinct from "empty": no output at all)
  expose_paths    workspace-relative paths to read and wrap as a
                  `user`-role AGENTS.md-shaped message, in this order -
                  a path NOT listed here is never exposed at all, exactly
                  as real codex-cli 0.157.1 does not surface an arbitrary
                  declared file it was never told to load (verified
                  empirically while building #55: only AGENTS.md is
                  auto-loaded; a sibling "index" file is not)
  truncate        {relative_path: max_bytes} - simulates a real client
                  cutting a file's own rendered block at max_bytes; a path
                  present in expose_paths but absent here is exposed whole

A skill whose `agents/openai.yaml` sets `policy.allow_implicit_invocation:
false` is excluded from the listing entirely - matches codex-cli 0.157.1's
real behavior, verified empirically while building #55, not merely assumed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

VERSION = "0.157.1-fake"
MODE_FILE = Path(__file__).with_suffix(".mode")


def _config() -> dict[str, object]:
    if MODE_FILE.is_file():
        data = json.loads(MODE_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data
    return {}


def _name(skill_md: Path) -> str | None:
    match = re.search(r'^name:\s*"?([^"\n]+)"?\s*$', skill_md.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else None


def _policy_hides(skill_dir: Path) -> bool:
    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        return False
    return "allow_implicit_invocation: false" in openai_yaml.read_text(encoding="utf-8")


def _skills(root: Path) -> list[tuple[str, str]]:
    found = []
    if root.is_dir():
        for child in sorted(p for p in root.iterdir() if p.is_dir()):
            skill_md = child / "SKILL.md"
            if not skill_md.is_file() or _policy_hides(child):
                continue
            name = _name(skill_md)
            if name is not None:
                found.append((name, child.name))
    return found


def main(argv: list[str]) -> int:
    config = _config()
    mode = config.get("mode", "normal")
    if argv[:1] == ["--version"]:
        print(f"codex-cli {VERSION}")
        return 0
    if argv[:2] != ["debug", "prompt-input"]:
        print(f"fake_codex_exposure: unsupported call {argv}", file=sys.stderr)
        return 2
    if mode == "crash":
        print("fake_codex_exposure: crashing on purpose", file=sys.stderr)
        return 3
    if mode == "hang":
        time.sleep(3600)
    if mode == "empty":
        # Exit 0, nothing on stdout - its own blind case, distinct from a
        # crash: named explicitly by #55's acceptance criteria.
        return 0
    if mode == "textless":
        # Exit 0, well-formed JSON, but nothing extractable - distinct from
        # "empty" (no output at all). Cross-model review, PR #90.
        print(json.dumps([{"role": "developer", "content": []}]))
        return 0

    codex_home = Path(os.environ["CODEX_HOME"])
    items: list[dict[str, object]] = []

    skills_dir = codex_home / "skills"
    found = _skills(skills_dir)
    lines = [f"- {name}: A skill. (file: r0/{directory}/SKILL.md)" for name, directory in found]
    block = (
        "<skills_instructions>\n## Skills\n### Skill roots\n"
        f"- `r0` = `{skills_dir}`\n### Available skills\n" + "\n".join(lines) + "\n</skills_instructions>"
    )
    items.append({"role": "developer", "content": [{"type": "input_text", "text": block}]})

    expose_paths = config.get("expose_paths", [])
    truncate = config.get("truncate", {})
    assert isinstance(expose_paths, list)
    assert isinstance(truncate, dict)
    workdir = Path(os.getcwd())
    for rel in expose_paths:
        path = workdir / str(rel)
        if not path.is_file():
            continue
        content = path.read_bytes()
        limit = truncate.get(rel)
        if isinstance(limit, int):
            content = content[:limit]
        text = (
            f"# {rel} instructions for {workdir}\n\n<INSTRUCTIONS>\n"
            f"{content.decode(errors='replace')}\n\n</INSTRUCTIONS>"
        )
        items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})

    items.append({"role": "user", "content": [{"type": "input_text", "text": argv[2] if len(argv) > 2 else ""}]})
    print(json.dumps(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
