"""A stand-in for the Codex client, for tests that must run where Codex is absent.

It answers the two calls the adapter makes - `--version` and
`debug prompt-input PROMPT` - in the shape codex-cli 0.157.1 was observed to
use: a JSON list of messages, one holding a `<skills_instructions>` block with a
skill-roots table and one line per skill. Like the real client it seeds a
`.system` skill into every CODEX_HOME it is pointed at.

The adapter runs clients with an empty environment, so the failure mode cannot
come from an environment variable. It comes from a sidecar file next to this
script's copy: `<script>.mode`, one JSON object, e.g. {"mode": "blind"}.

Modes:
  normal       list every skill under $CODEX_HOME/skills, like the real client
  blind        list only the client's own .system skills
  noblock      emit messages with no skills listing at all
  crash        exit 3
  hang         sleep until killed
  version      report a different client version
  leak         also list skills from {"dir": ...}, in every arm (host leak)
  skew         when no treatment is installed, list one extra system skill
  context      when no treatment is installed, change the environment text
  block-extra  when no treatment is installed, add text inside and after the listing
  desc         when no treatment is installed, describe the client's skill differently
  badrow       list the client's skill in a row shape the adapter does not know
  mutate       rewrite every installed SKILL.md it finds
  write-host   append to {"path": ...} (a stand-in for the host's client state)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

VERSION = "9.9.9"
MODE_FILE = Path(__file__).with_suffix(".mode")


def _mode() -> dict[str, str]:
    if MODE_FILE.is_file():
        data = json.loads(MODE_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return {str(k): str(v) for k, v in data.items()}
    return {"mode": "normal"}


def _name(skill_md: Path) -> str | None:
    match = re.search(r"^name:\s*\"?([^\"\n]+)\"?\s*$", skill_md.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else None


def _skills(root: Path) -> list[tuple[str, str]]:
    found = []
    if root.is_dir():
        for child in sorted(p for p in root.iterdir() if p.is_dir() and p.name != ".system"):
            skill_md = child / "SKILL.md"
            name = _name(skill_md) if skill_md.is_file() else None
            if name:
                found.append((name, child.name))
    return found


def main(argv: list[str]) -> int:
    config = _mode()
    mode = config.get("mode", "normal")
    if argv[:1] == ["--version"]:
        print(f"codex-cli {'0.0.1' if mode == 'version' else VERSION}")
        return 0
    if argv[:2] != ["debug", "prompt-input"]:
        print(f"fake_codex: unsupported call {argv}", file=sys.stderr)
        return 2
    if mode == "crash":
        print("fake_codex: crashing on purpose", file=sys.stderr)
        return 3
    if mode == "hang":
        time.sleep(3600)

    codex_home = Path(os.environ["CODEX_HOME"])
    skills = codex_home / "skills"
    system = skills / ".system"
    (system / "fake-system").mkdir(parents=True, exist_ok=True)
    (system / "fake-system" / "SKILL.md").write_text(
        "---\nname: fake-system\ndescription: The client's own skill.\n---\n", encoding="utf-8"
    )
    treatment = _skills(skills)

    if mode == "mutate":
        for _, directory in treatment:
            with open(skills / directory / "SKILL.md", "a", encoding="utf-8") as fh:
                fh.write("\ntampered\n")
    if mode == "write-host":
        with open(config["path"], "a", encoding="utf-8") as fh:
            fh.write("touched\n")

    roots = []
    lines = []
    if treatment and mode != "blind":
        roots.append(str(skills))
    roots.append(str(system))
    system_root = f"r{len(roots) - 1}"
    described = "Described differently." if mode == "desc" and not treatment else "The client's own skill."
    if mode == "badrow":
        lines.append(f"- fake-system: {described} [file: {system_root}/fake-system/SKILL.md]")
    else:
        lines.append(f"- fake-system: {described} (file: {system_root}/fake-system/SKILL.md)")
    if mode == "skew" and not treatment:
        lines.append(f"- fake-extra: Only in one arm. (file: {system_root}/fake-extra/SKILL.md)")
    if treatment and mode != "blind":
        for name, directory in treatment:
            lines.append(f"- {name}: A skill. (file: r0/{directory}/SKILL.md)")
    if mode == "leak":
        roots.append(config["dir"])
        leak_root = f"r{len(roots) - 1}"
        for name, directory in _skills(Path(config["dir"])):
            lines.append(f"- {name}: Leaked. (file: {leak_root}/{directory}/SKILL.md)")

    table = "\n".join(f"- `r{i}` = `{r}`" for i, r in enumerate(roots))
    extra = mode == "block-extra" and not treatment
    block = (
        "<skills_instructions>\n## Skills\n"
        + ("Prefer Ruby.\n" if extra else "")
        + "### Skill roots\n"
        f"{table}\n### Available skills\n" + "\n".join(lines) + "\n</skills_instructions>"
        + ("\nUse Ruby for everything." if extra else "")
    )
    context = f"<environment_context>\n  <cwd>{os.getcwd()}</cwd>\n</environment_context>"
    if mode == "context" and not treatment:
        context += "\n<extra>only in the baseline</extra>"
    developer: dict[str, object] = {"role": "developer", "content": [{"type": "input_text", "text": block}]}
    items: list[dict[str, object]] = [] if mode == "noblock" else [developer]
    items.append({"role": "user", "content": [{"type": "input_text", "text": context}]})
    items.append({"role": "user", "content": [{"type": "input_text", "text": argv[2] if len(argv) > 2 else ""}]})
    print(json.dumps(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
