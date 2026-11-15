<!-- flow-run n=1 id=eaea2f51bf7644ebb886bdd084758afc -->
## Run 1 - issue #763 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #763
- Read at:      2026-11-15T14:34:22Z
- updatedAt:    2026-11-15T14:33:28Z   (context only - moves on comments and labels)
- Body digest:  6965fdd9bd4189892eaeac1e442b2e9b115661f64b3a44919390db2315c760ec   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2109 of 2109 (cap 16384)

### Body as read
## Why

The owner (2026-11-15): "I can't use the skill yet". #754 ships `/skill-gauntlet` as `.claude/skills/skill-gauntlet/` inside skillc, and Claude Code loads project skills only for sessions opened in that repo. The owner works mostly in other repos (CPP, Kyle), so even after #754 merges, typing `/skill-gauntlet` in their normal session does nothing. The skill also calls the `skillc` CLI, which must resolve from any working directory.

## What

1. **`make install-skill`** (and `make uninstall-skill`) in skillc:
   - installs `/skill-gauntlet` for the USER by symlinking `~/.claude/skills/skill-gauntlet` to the main checkout's `.claude/skills/skill-gauntlet`, the same user-level skill directory the owner's other skills use;
   - refuses to overwrite an existing non-symlink entry, or a symlink pointing elsewhere, and names it;
   - is idempotent.
2. **CLI resolution from any directory.** The SKILL.md invokes the engine in a way that works outside skillc's tree, for example `uv run --project <skillc main checkout> skillc gauntlet run ...`, with the checkout path resolved once at install time or from a documented variable. No hard-coded `/home/<account>` path in committed files.
3. **Docs:** README install section, plus how to update (it's a symlink, so a pull updates it) and how to remove.
4. **Registration through CPP** (so CPP-managed installs ship it) is a separate CPP coordination issue and not part of this.

## Acceptance

- [ ] From a fresh Claude Code session opened in **another repo** (e.g. claude-power-pack), `/skill-gauntlet` is listed, and running it on a CPP command reaches the same verdicts as #754's headless run. Quote that session's output in the PR.
- [ ] Negative controls: `make install-skill` refuses when `~/.claude/skills/skill-gauntlet` is a real directory or a foreign symlink; `uninstall-skill` removes only the symlink it owns.
- [ ] With skillc's checkout moved or missing, the skill reports that it can't find skillc and stops, never a verdict.
- [ ] No host account path in any committed file (leak-check stays clean).

Depends on #754. Part of #738.


<!-- end of body -->
