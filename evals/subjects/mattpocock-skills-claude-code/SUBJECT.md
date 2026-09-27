# Subject: mattpocock/skills on Claude Code (select: tdd, diagnosing-bugs) (#124)

- Declaration: [subject.json](subject.json) - the machine form; this page explains it
- Surface: `claude-code-skills` - installed into the container's `~/.claude/skills/<name>/`
  (`materialize.SURFACES`, issue #124)
- Client: Claude Code 2.1.283, the version `docker/trial/pinned-versions.json` pins
- Evidence: [the Claude Code agent arm](../../claude-code-agent-arm/README.md)

The same collection, pin, root and selection as
[mattpocock-skills](../mattpocock-skills/SUBJECT.md), declared for Claude Code
instead of Codex. The collection is authored for Claude Code first: it ships a
`.claude-plugin/plugin.json`, and its skills are plain `SKILL.md` directories,
the layout Claude Code reads from `~/.claude/skills/`.

## Compatibility, reported before selection

- **Selected: `tdd` and `diagnosing-bugs`.** Both are model-invoked: neither
  declares `disable-model-invocation`, so both are eligible for the model's
  skill listing. That is the discovery route this arm observes.
- **Not compatible with this arm's discovery check, and not selected:** the 14
  manifest skills that declare `disable-model-invocation: true` (counted on
  [mattpocock-skills](../mattpocock-skills/SUBJECT.md)). Claude Code keeps
  those out of the model's listing by design, so a transcript-observed
  discovery check would report them `not-listed`, and that would be a correct
  reading of the policy, not a broken install. The listing is not
  policy-aware in the other direction either; the gap is in the Nit Store
  (#20).
- **Unshipped drafts** (`skills/in-progress/*`, `skills/misc/*`): excluded
  because the manifest does not ship them, as on the Codex subject.

## Discovery, stated honestly

As for [cpp-claude-code](../cpp-claude-code/SUBJECT.md): discovery is
observed from the real `skillc collection-run` transcript's `skill_listing`
attachment and labelled so. `skillc demo --subject` reports it NOT EXERCISED,
because Claude Code has no model-free listing.
