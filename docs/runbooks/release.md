# Cutting a minor release

This is the procedure for evergreen
[#72](https://github.com/cooneycw/skillc/issues/72). A release records delivered
capability and evidence limits. New live studies, tags, GitHub publication and
package uploads retain their own authorization requirements.

1. Start an isolated release branch from current GitHub main. Read repository
   directives and `changelog.d/README.md`. Query main through
   `gh api repos/cooneycw/skillc/branches/main --jq .commit.sha`, then fetch it;
   do not assume a local remote-tracking ref is current.
2. Inventory the change since the previous tag. Read shipped implementations,
   retained reports and each PR's final description. For every open/closed claim,
   run `gh issue view NUMBER --repo cooneycw/skillc --json title,state,body,comments`.
   Check external-repository claims against that repository too. Distinguish a
   bounded completion from coordination closure, scope reduction and transfer
   to an open successor. A changelog bullet cannot establish issue closure.
3. Bump `[project].version` in `pyproject.toml`, run `uv lock` and
   `uv sync --locked --extra dev`. Check `skillc --version`. Refresh README
   status/version, `docs/milestones.json` and the README milestone table; label
   PLAN's planning baseline historical. Preserve older declarations and reports.
4. Write `docs/release-notes/X.Y.Z.md`: delivered behavior, real versus simulated
   evidence, partial deliveries, open obligations and publication boundaries.
   Use absolute tag-pinned GitHub links, since repository-relative links break
   when the file becomes GitHub release notes. Leave #72 open.
5. Wait for every required prerequisite PR to merge, refresh main and recheck
   the claim ledger. Keep all fragments unassembled during that work. After a
   prerequisite squash merge, apply only the release's own change onto the new
   main; do not replay a temporary dependency stack blindly. Resolve conflicts
   and review the resulting diff. A maintainer-authorized reuse of verification
   must name both heads, unchanged file bytes and non-overlap; it never covers
   new edits. The final assembled release head gets its full gate.
6. **Assemble last**, after the notes, metadata and prerequisite set are final.
   The repository's deterministic assembly command is:

   ```bash
   python3 ci/changelog_assemble.py --check
   python3 ci/changelog_assemble.py
   ```

   The first command previews only; the second folds validated fragments in
   issue-number/file-name order and deletes them. Preserve a pre-assembly
   checkpoint. Review every folded entry and deletion, then move the entire
   Unreleased body beneath `## [X.Y.Z] - YYYY-MM-DD`, leaving a fresh empty
   `## [Unreleased]` above it. Add missing notable deliveries as fragments before
   this step. If new prerequisite fragments arrive, update the pre-assembly
   checkpoint and regenerate rather than splicing competing assembled copies.
7. Commit the final assembled change. When `skillc/` changed and assembly consumed
   its fragment, justify the exemption with a HEAD trailer such as
   `Changelog-exempt: release preparation assembles the version changelog`.
   Run `make verify` on that exact head; a focused selection is development
   evidence only. In a two-CPU-quota container use `PYTEST_WORKERS=2`, with
   SIGINT/SIGQUIT reset to SIG_DFL in Python before executing make. Follow the
   active suite-scheduling ruling and check process usage after teardown.
   Preserve explicit real-Docker/client skips and any unavailable local scanner;
   no missing scan or skipped daemon test counts as positive evidence.
8. Confirm the negative controls still discriminate. The clean-install target
   builds a wheel in a fresh venv and runs three sabotages: the installed-rule
   verdict changes, missing supplied controls refuse, and same-exit mismatched
   findings fail the script. A control wrapper exits zero only after seeing its
   required red. Population and execution checks must retain every selected test
   identity exactly once, including any separately executed serial population.
   Run the leak/secret scanners and their committed seeded controls. Any extra
   text scan needs a known positive before its empty output is trusted.
9. Request PR review with exact SHA, diffstat, gate result, controls, limitations,
   claim evidence and draft body. Obtain required PR authorization, then require
   green PR CI on the same head. Branch-protection updates need fresh exact-head
   CI. If newer work overlaps or the implementation changes, reverify according
   to the active ruling; do not silently relabel old evidence as a new-head run.
10. Obtain explicit merge authorization. Inspect `closingIssuesReferences` before
    a squash merge; keep #72 open and close only work with satisfied acceptance.
    Use `gh pr merge --squash --match-head-commit SHA`, confirm the merge commit
    from GitHub, and check main CI.
11. Only after separate tag/release authorization, fetch the confirmed merge
    commit and create an annotated `vX.Y.Z` tag on it. Push only that tag and
    verify the remote tag resolves to the intended commit. Publish the GitHub
    release with `--notes-file docs/release-notes/X.Y.Z.md` after checking all
    tag-pinned links. Record merge SHA, tag, release URL and evidence limits in
    #72. Never tag the unmerged preparation branch.

For 0.5.0, the test-lane change (#608), calibration-report recovery (#610),
qualifier follow-up (#611) and containment stop (#612) are merged. The owner
excluded the residue inventory (#609), whose host check is pending, to 0.5.1.
Preserve the release notes' real-daemon limitations; check the live trackers
again before the separately authorized tag.

For 0.5.0, **no PyPI publishing is authorized** (owner ruling, 2026-10-28).
Local wheel construction for clean-install verification is required and does
not authorize an upload.
