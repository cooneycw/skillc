# Subject: claude-power-pack, native Claude Code skills (#124)

- Declaration: [subject.json](subject.json) - the machine form; this page explains it
- Surface: `claude-code-skills` - installed into the container's `~/.claude/skills/<name>/`
  (`materialize.SURFACES`, issue #124)
- Client: Claude Code 2.1.283, the version `docker/trial/pinned-versions.json` pins
- Evidence: [the Claude Code agent arm](../../claude-code-agent-arm/README.md)

The same repository and pin as [cpp-codex](../cpp-codex/SUBJECT.md), but CPP's
**native Claude Code surface**, not its generated Codex copy. CPP ships two
skill roots at `85e9b03a`: `codex/skills` (74 generated Codex skills, which
cpp-codex declares) and `.claude/skills` (18 hand-authored Claude Code
skills). Installing the Codex copy into Claude Code's home would measure a
surface CPP never ships to Claude Code, so this subject declares the one it
does.

## Selection

- **All 18 skills** (`select: "all"`). None declares
  `disable-model-invocation`, so every one is eligible for the model's skill
  listing - the discovery route this arm observes.
- **No `checksum_manifest`.** `.claude/skills` carries no `SHA256SUMS`; that
  convention belongs to the generated `codex/skills` tree.
- **No relative Markdown links.** Each skill is a single `SKILL.md`. The
  mentions of repository files (`docs/skills/<topic>.md`,
  `PROGRESSIVE_DISCLOSURE_GUIDE.md`, `scripts/c4-mermaid.py`) are backticked
  paths, so `materialize.inventory` records them as static findings: files of
  the repository these skills document, not bundled with the skill, and never
  readiness in either direction.
- **Not included:** CPP's `.claude/commands/**` (slash commands) and its
  plugin manifest. They are a different Claude Code surface, not skills, and
  no adapter installs them.

## Discovery, stated honestly

Claude Code has no model-free listing command (`skillc/exposure.py` states the
same limit), so `skillc demo --subject cpp-claude-code` installs the skills
and re-hashes them in the container but reports discovery **NOT EXERCISED**.
Discovery is observed instead from the real agent transcript of
`skillc collection-run cpp-claude-code`: the client's own `skill_listing`
attachment, the skills Claude Code told the model it had. It is labelled
`source=transcript skill_listing`, and it is never a Codex canary result.
