<!-- flow-run n=1 id=4929476c45b64bd2af776b8225288364 -->
## Run 1 - issue #774 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #774
- Read at:      2026-11-15T17:49:17Z
- updatedAt:    2026-11-15T17:46:55Z   (context only - moves on comments and labels)
- Body digest:  0cec28b943141fb716089d6484ce535045754cbd6c261f16c6f755917bea7ff7   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3055 of 3055 (cap 16384)

### Body as read
## Why

#763 (PR #768) installed `/skill-gauntlet` as a SYMLINK at `~/.claude/skills/skill-gauntlet`. Kyle's deploy copies the owner's `~/.claude/skills` into its session image and deliberately refuses symlinks (cooneycw/kyle `deploy/operator_config.py:404`), so every Kyle deploy failed: Kyle pipeline 5215, and barrier 53 held the shared main-merge lock. The owner chose (2026-11-15) to replace the link with a **real copy**. kyle-cli-helper applies that copy now.

The launcher (`.claude/skills/skill-gauntlet/scripts/gauntlet.sh`) finds skillc's checkout by resolving its own path through the link. In a plain copy it can't, so it reports `cannot find a usable skillc` and exits 2. That's safe, but the skill is unusable until this lands.

## What

1. **`make install-skill` installs a COPY, never a link.**
   - Copy `<main checkout>/.claude/skills/skill-gauntlet/` into `~/.claude/skills/skill-gauntlet/` as regular files: no symlink anywhere in the result (Kyle's deploy refuses any).
   - Write a small locator file inside the copy (e.g. `.skillc-checkout`) holding the main checkout's absolute path. It's written at install time on the owner's host and NEVER committed; the repo's copy has none.
   - The launcher reads the locator first. With none, it falls back to its own real path (today's in-repo behaviour), and otherwise reports cannot-find and gives no verdict.
2. **Refresh, not live updates.** A skillc `git pull` no longer updates the installed copy. `make install-skill` re-run REPLACES a copy it owns (it recognises its own via a marker file) atomically (temp dir, then rename). It refuses a foreign entry, and it migrates an old skillc-owned symlink to a copy.
3. **`make uninstall-skill`** removes only a copy carrying skillc's marker.
4. **A drift note:** `/skill-gauntlet` or the launcher warns when the installed copy differs from the checkout's (a digest kept in the marker), and says "re-run make install-skill". It warns only and never blocks.
5. **Kyle compatibility check, committed:** a test asserts that the installed tree contains NO symlinks, mirroring Kyle's refusal rule. The issue body cites `deploy/operator_config.py:404` as the reader.

## Acceptance

- [ ] An install produces a tree with zero symlinks (`find -type l` is empty), and that is asserted.
- [ ] The launcher in the installed copy finds the checkout through the locator and reaches the same verdicts as #768's CPP session. A fresh session opened in claude-power-pack is quoted in the PR.
- [ ] Controls:
  - a foreign entry is refused;
  - an old skillc symlink is migrated to a copy;
  - re-install replaces the copy atomically;
  - uninstall removes only the marked copy;
  - a missing or wrong locator gives cannot-find (exit 2, no verdict);
  - drift is warned.
- [ ] No account path in any committed file; the locator is written only at install time.
- [ ] Before the real install on the owner's host, kyle-cli-helper confirms it via the wave mailbox, so Kyle's deploy is never surprised again.

Refs #763, #738. Found during wave skillc-work.


<!-- end of body -->
