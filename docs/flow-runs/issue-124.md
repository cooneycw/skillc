# Flow run record - issue #124

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #124
- Base SHA:          ab04c6c536de8c8ce8df2de261f85ebbb8f93d89
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the operator (cooneycw), in the flow:auto session ("approved")
- Recorded at:       2026-09-27T13:40:00Z

## Section B evidence
Commits since filing: ab04c6c (#126), fd144d1 (#123), 28af6b6 (#125) - all Codex
collection-run completion, none adds a Claude surface. Merged PRs inspected: #126,
#125, #123, #121, #120, #117, #113, #111, #107, #105. Duplicates/superseding
issues considered: #11 (closed; names #124 for the Claude arm), #55, #50, #53 -
none overlapping. Correction: the issue's `skillc demo --subject --agent --client
claude` shipped under #11 as `skillc collection-run <subject>`; this run reuses
that. Open overlap: PR #128 (issue-127) touches collection-run printing.

## Section C - the approved plan
1. `skillc/materialize.py` - surface table (codex-skills->codex .codex/skills, claude-code-skills->claude .claude/skills); Subject carries surface+client; mismatch refused; host materialize stays codex-only and refuses claude-code-skills by name
2. `skillc/transcript_adapter.py` - claude_code_skill_listing(raw): union of skill_listing attachment names, None when absent
3. `skillc/agent_trial.py` - ClientSpec.read_skill_listing; observation records skills_listed (None = not observable)
4. `skillc/demo.py` - subject files land under the subject surface's skills dir; discovery NOT EXERCISED for a surface with no no-model listing
5. `skillc/collection_conformance.py` - client from the subject, per-client default argv, transcript-observed discovery map (listed/not-listed/UNMEASURED) in the paste-back
6. `skillc/cli.py` - collection-run default argv by subject client; exit 1 when any selected skill is not-listed
7. `evals/subjects/cpp-claude-code/subject.json` - CPP at the same pin, skills_root .claude/skills, client claude 2.1.283
8. `evals/subjects/cpp-claude-code/SUBJECT.md` - selection and scope
9. `evals/subjects/mattpocock-skills-claude-code/subject.json` - tdd + diagnosing-bugs, client claude
10. `evals/subjects/mattpocock-skills-claude-code/SUBJECT.md` - selection, disable-model-invocation note
11. `tests/test_materialize.py` - surface table, mismatch refusal, genericity guard
12. `tests/test_transcript_adapter.py` - listing parse; absent listing -> None
13. `tests/test_agent_trial.py` - skills_listed on the observation
14. `tests/test_collection_conformance.py` - claude subject installs under .claude/skills; listing omission turns discovery red; no listing -> UNMEASURED
15. `tests/fixtures/agent-trial/fake_agent_client.py` - writes a skill_listing attachment for claude
16. `evals/claude-code-agent-arm/README.md` - evidence summary and bounded statement
17. `evals/claude-code-agent-arm/evidence/README.md` - live output
18. `evals/claude-code-agent-arm/run-manifest.json` - cited lines
19. `tests/test_claude_code_agent_arm.py` - every cited line exists in the evidence
20. `docs/specs/evaluation-facility/support-matrix.md` - Claude Code arm row
21. `docs/specs/evaluation-facility/materialization.md` - the second surface
22. `evals/second-collection-conformance/README.md` - point "Claude Code" at #124's evidence
23. `CHANGELOG.md` - entry

Scope: large, ~21 files, ~900-1200 lines. Live runs on the operator's normal
Claude subscription login (ADR 0005 rule 6): collection-run per Claude subject,
a missing-credential control, and the #98 host-login check.

Risks: first real Claude Code 2.1.283 launch in the trial container (argv, seed,
--name, a subagent writing a second transcript file); skill_listing may be
absent in 2.1.283 (then UNMEASURED); real subscription usage; PR #128 overlap
in cli.py.
