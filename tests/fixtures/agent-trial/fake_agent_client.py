"""A scripted stand-in for a real agent CLI (issue #106's own acceptance:
"a scripted fake client that writes a realistic transcript for each client
format"). Never a real `claude`/`codex` binary - this is what
`tests/test_agent_trial.py` runs the whole driver against, end to end,
through the fake docker CLI.

The fake docker CLI (`tests/fixtures/docker-backend/fake_docker.py`) runs
`execute()`'s subject as a REAL host subprocess with NO chroot - it proves
the LIFECYCLE state machine, never a containment boundary (its own module
docstring). So this script cannot write to `/home/candidate/...` and expect
that to land anywhere meaningful; the caller must tell it, via `--home`,
exactly which HOST directory the fake CLI has mapped `CONTAINER_HOME` to for
this attempt - the same "white-box, known fixture convention"
`tests/test_docker_backend.py`'s own `deliver_home_file` tests already use.
A REAL client obviously needs no such flag; it just writes to its own home.

Writes a transcript matching the REAL on-disk shape documented in
`tests/fixtures/transcripts/{claude-code,codex}/README.md` (#107) - the
skill-invocation + tool-use canary, and the first user message, in the
exact normalized-adapter-facing shape `skillc/transcript_adapter.py`
already parses.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def _claude_transcript(prompt: str, skills: tuple[str, ...], nonce: str, fail_canary: bool) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = [
        {"type": "user", "message": {"role": "user", "content": prompt}},
    ]
    if fail_canary:
        lines.append({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Here is a plain-prose answer."}]},
        })
        return lines
    for index, skill in enumerate(skills):
        lines.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"toolu_skill{index:04d}", "name": "Skill", "input": {"skill": skill}}],
            },
        })
        lines.append({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": f"toolu_skill{index:04d}", "content": "loaded", "is_error": False}],
            },
        })
    lines.append({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_bash0001", "name": "Bash",
                         "input": {"command": f"echo 'touched:{nonce}' | tee canary.txt"}}],
        },
    })
    lines.append({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_bash0001",
                         "content": f"touched:{nonce}\n", "is_error": False}],
        },
    })
    return lines


def _codex_transcript(prompt: str, skills: tuple[str, ...], nonce: str, fail_canary: bool) -> list[dict[str, object]]:
    def message(role: str, text: str) -> dict[str, object]:
        return {"type": "response_item", "payload": {"type": "message", "role": role,
                                                       "content": [{"type": "input_text", "text": text}]}}

    def exec_call(call_id: str, command: str) -> dict[str, object]:
        return {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": call_id,
                                                       "name": "exec", "input": command}}

    def exec_output(call_id: str, exit_code: int, output_text: str) -> dict[str, object]:
        chunk = json.dumps({"chunk_id": "x", "exit_code": exit_code, "output": output_text})
        return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id,
                                                       "output": [{"type": "input_text", "text": chunk}]}}

    lines: list[dict[str, object]] = [
        message("user", "<environment_context>\n  <cwd>/work</cwd>\n</environment_context>"),
        message("user", prompt),
    ]
    if fail_canary:
        lines.append(message("assistant", "Here is a plain-prose answer."))
        return lines
    for index, skill in enumerate(skills):
        call_id = f"call_skill{index:04d}"
        lines.append(exec_call(call_id, f"cat .codex/skills/{skill}/SKILL.md"))
        lines.append(exec_output(call_id, 0, "# skill\n"))
    lines.append(exec_call("call_write", f"echo 'touched:{nonce}' | tee canary.txt"))
    lines.append(exec_output("call_write", 0, f"touched:{nonce}\n"))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    # "claude-fake"/"codex-fake", never the bare real names: lifecycle.py's
    # own _refuse_real_agent scans EVERY argv element's basename for "claude"
    # or "codex" (deliberately, to catch a wrapped real launch) - a bare
    # "--format codex" value would trip that same guard, which is a sign the
    # guard works, not something to route around by disabling it.
    parser.add_argument("--format", choices=("claude-fake", "codex-fake"), required=True)
    parser.add_argument("--home", required=True, help="host path the fake docker CLI maps CONTAINER_HOME to")
    parser.add_argument("--transcript-relpath", required=True, help="where to write, relative to --home")
    parser.add_argument("--name", help="accepted and ignored - mirrors the real Claude Code CLI's own --name flag, "
                                        "which trial_bootstrap.build_invocation appends for a client that supports it")
    parser.add_argument("--fail-canary", action="store_true")
    parser.add_argument("--mismatched-prompt", action="store_true",
                         help="record a DIFFERENT prompt than the one delivered - simulates a real prompt-delivery mismatch")
    parser.add_argument("--copy-solution", help="a directory whose contents to copy into the CWD (/work) - "
                                                 "simulates the agent having produced this as its own solution")
    parser.add_argument("--plant-leak", action="store_true",
                         help="append an obviously-fake credential-shaped value to the transcript - "
                              "for #106's own leak-check acceptance, proving the scan catches a real one")
    parser.add_argument("--plant-skill", action="append", default=[],
                         help="a skill_invocation event to write into the transcript, independent of the prompt's "
                              "own named skill - repeatable. Issue #26's skill-free canary mode names no skill in "
                              "the prompt at all, so a test simulating 'the agent selected X anyway' (or nothing) "
                              "needs a way to control this directly. Defaults (when omitted) to the prompt's own "
                              "named skill in named-canary mode, and to none at all in skill-free mode - every "
                              "existing named-mode test is unaffected.")
    parser.add_argument("--no-skill-listing", action="store_true",
                         help="claude-fake only: write no skill_listing attachment at all - a client version "
                              "that stopped emitting one (issue #124: must read as UNMEASURED, never as empty)")
    parser.add_argument("--omit-listed", action="append", default=[],
                         help="claude-fake only: leave this installed skill OUT of the skill_listing attachment - "
                              "a client that did not tell the model about a skill it was given (repeatable)")
    # Issue #141: the real codex's own launch pins. `-m` and `-c
    # model_reasoning_effort=...` are what `matched_pilot.launch_argv` appends;
    # the fake writes them back as a codex `turn_context`, exactly where the
    # real client records the model it actually ran - so a test proves the
    # declared pin REACHES the client rather than asserting an argv shape.
    parser.add_argument("-m", "--model", help="codex-fake only: the model to record in a turn_context")
    parser.add_argument("-c", "--config", action="append", default=[],
                         help="codex-fake only: key=value; model_reasoning_effort is recorded in the turn_context")
    parser.add_argument("--observed-model",
                         help="codex-fake only: record THIS model instead of -m - a client that ignored the pin")
    parser.add_argument("--no-turn-context", action="store_true",
                         help="codex-fake only: write no turn_context at all - the model is unobserved")
    parser.add_argument("prompt")
    args = parser.parse_args()

    # `lifecycle.run_through_backend`'s OWN liveness check (independent of
    # this whole module's transcript-based canary) compares a workspace
    # snapshot before and after execute() - since this script only ever
    # writes into HOME, never into its own CWD (/work), that check would
    # otherwise always see "no observable change" and mark the attempt
    # inconclusive before agent_trial.py's own checks ever get a chance to
    # matter. A real agent naturally writes into its own CWD; this is the
    # scripted stand-in for that.
    Path("agent-touched.txt").write_text("the agent ran\n")
    if args.copy_solution:
        shutil.copytree(args.copy_solution, ".", dirs_exist_ok=True)

    # The skill name and nonce are never passed as separate flags - a real
    # agent has no such flags either. Both are read out of the PROMPT text
    # itself, exactly as `trial_bootstrap.compose_canary_instruction`
    # composes it: "invoke the '<skill>' skill... write the exact text
    # 'touched:<nonce>'...". A real agent reads its own instructions the
    # same way. The skill clause is OPTIONAL (issue #26's skill-free canary
    # mode composes no skill clause at all) - only the nonce/result-file
    # clauses are required for this to be a canary instruction at all.
    skill_match = re.search(r"invoke the '([^']+)' skill", args.prompt)
    nonce_match = re.search(r"touched:([0-9a-f]+)", args.prompt)
    result_file_match = re.search(r"named '([^']+)' in the working directory", args.prompt)
    if nonce_match is None or result_file_match is None:
        print("fake_agent_client: could not find the canary instruction in the prompt", file=sys.stderr)
        return 2
    nonce = nonce_match.group(1)
    result_filename = result_file_match.group(1)
    # Default: the prompt's own named skill in named-canary mode (every
    # existing test's own behaviour, unchanged), nothing at all in
    # skill-free mode - `--plant-skill` overrides either default explicitly.
    default_skills = [skill_match.group(1)] if skill_match is not None else []
    skills = tuple(args.plant_skill) if args.plant_skill else tuple(default_skills)

    # lifecycle.run_through_backend's OWN backend-planted content canary
    # (independent of the transcript-based one below) reads THIS file back
    # after export() and requires it to read exactly 'touched:<nonce>' - a
    # real agent does this as an ordinary consequence of following the
    # canary instruction in its own prompt; this is the scripted stand-in.
    # Written UNCONDITIONALLY, even in --fail-canary mode: that flag exists
    # to simulate the named red case where the backend file IS written
    # correctly but the TRANSCRIPT never shows a confirmed skill+tool touch
    # - proving the transcript proof (check_agent_canary) still refuses on
    # its own, never merely piggybacking on the backend check's own verdict.
    Path(result_filename).write_text(f"touched:{nonce}")

    recorded_prompt = "a completely different prompt, never the one delivered" if args.mismatched_prompt else args.prompt
    builder = _claude_transcript if args.format == "claude-fake" else _codex_transcript
    lines = builder(recorded_prompt, skills, nonce, args.fail_canary)
    recorded_model = args.observed_model or args.model
    if args.format == "codex-fake" and recorded_model and not args.no_turn_context:
        effort = None
        for item in args.config:
            key, _, value = item.partition("=")
            if key == "model_reasoning_effort":
                effort = value.strip('"')
        context: dict[str, object] = {"model": recorded_model}
        if effort is not None:
            context["effort"] = effort
        lines.insert(0, {"type": "turn_context", "payload": context})
    if args.format == "claude-fake" and not args.no_skill_listing:
        # Issue #124: the real client lists the skills it FOUND under
        # ~/.claude/skills/ - so this reads the installed directories off disk
        # rather than being told which ones to list. A skill whose files never
        # reached the home is therefore missing here exactly as it would be
        # from a real listing; `--omit-listed` drops one that IS installed.
        skills_dir = Path(args.home) / ".claude" / "skills"
        found = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []
        names = [n for n in found if n not in args.omit_listed]
        # The real attachment shape (skillc/transcript_adapter.py,
        # `_CLAUDE_SKILL_LISTING_TYPE`), inserted before the first turn as the
        # real client does.
        lines.insert(0, {"type": "attachment", "attachment": {
            "type": "skill_listing", "names": names, "skillCount": len(names), "isInitial": True,
            "content": "".join(f"- {n}: a skill\n" for n in names),
        }})

    if args.plant_leak:
        # An API-key-SHAPED value, not an OAuth key:value pair: the latter's
        # detector pattern requires literal, unescaped quotes around the key
        # and value, which a JSON-encoded message's own text field always
        # escapes away (the exact bug #98's own first fixture attempt found
        # and fixed) - an API-key-shaped bare token has no such quote
        # dependency, so it survives JSON round-tripping and still matches.
        #
        # Built from fragments on purpose, exactly as tests/test_demo.py's
        # own _seeded_leak_text does: this file is not on the repo-wide
        # `leak-check .` CI gate's exclude list, so a single literal here
        # would make this fixture script itself the leak.
        planted_value = "sk-ant-api03-" + "planted" + "0" * 29
        planted_text = "found a stray credential: " + planted_value
        leak_line: dict[str, object] = (
            {"type": "user", "message": {"role": "user", "content": planted_text}}
            if args.format == "claude-fake" else
            {"type": "response_item", "payload": {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": planted_text}]}}
        )
        lines.append(leak_line)

    dest = Path(args.home) / args.transcript_relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj))
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
