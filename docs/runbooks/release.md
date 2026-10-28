# Cutting a minor release

This is the procedure for the evergreen
[#72](https://github.com/cooneycw/skillc/issues/72) upkeep checklist. A release
records delivered capability and evidence limits; it does not approve a live
study, imply a general effectiveness claim, or authorize package publication.

1. Start an isolated release branch from current GitHub main. Read repository
   directives and `changelog.d/README.md`. Query GitHub main directly and fetch;
   do not assume a local remote-tracking ref is current.
2. Inventory the release since the previous tag. Read the actual implementations,
   reports and outstanding work. For every open/closed claim in the new notes,
   run `gh issue view NUMBER --repo cooneycw/skillc --json title,state,body`.
   Preserve historical reports and annotate known constraints where readers need
   them. Do not infer issue closure from a changelog bullet.
3. Run `python3 ci/changelog_assemble.py --check`, then
   `python3 ci/changelog_assemble.py`. Review the ordered entries and deleted
   fragments. Move the full Unreleased body beneath `## [X.Y.Z] - YYYY-MM-DD`,
   leaving a fresh empty `## [Unreleased]` above it. Add release-preparation
   details to that version's section. Reassemble if rebasing introduces fragments.
4. Bump `[project].version` in `pyproject.toml`, run `uv lock`, and
   `uv sync --locked --extra dev`. `skillc --version` must agree. Refresh README
   status and version, `docs/milestones.json`, and the README milestone table.
   Use the version milestone to describe delivered scope, not to close broader
   studies. Keep PLAN's historical baseline clearly labeled.
5. Write `docs/release-notes/X.Y.Z.md`: delivered behavior, real versus simulated
   evidence, open obligations, known unknowns and publication boundaries. Use
   absolute tag-pinned GitHub links, since repository-relative links break when
   the same file becomes GitHub release notes. Check the evergreen #72 checklist;
   do not close #72.
6. Checkpoint the final proposed change. If it changes `skillc/` without leaving a
   fragment (release assembly consumes them), put a justified
   `Changelog-exempt: release preparation assembles the version changelog`
   trailer on the HEAD commit. Run `make verify` on that exact head; a focused
   subset is development evidence only. The gate includes `make clean-install`:
   built wheel, fresh venv, source/package verdict comparison and three committed
   sabotage controls. `neuter-installed-rule` must detect the bad fixture's
   changed verdict; `delete-scratch-controls` must get the absent-controls
   refusal. `ci/clean-install-comparison-control.sh` changes packaged findings while
   preserving exit codes, and must observe script exit 1. A control's wrapper
   exits zero only after observing its red verdict.
   Preserve skip limitations, including missing gitleaks and real Docker.
7. Review the full diff and release text for secret or machine-identity leaks.
   Run the gate's leak scan and its seeded control. Any additional text scanner
   needs a known positive case before its empty output can be trusted. Request
   review with the exact SHA, diffstat, gate result, controls and draft PR text.
   Obtain required PR authorization, then require green PR CI on the same SHA.
   A changed or overlapping main requires rebasing and fresh exact-head CI.
8. Obtain explicit merge authorization. Before a squash merge, inspect GitHub's
   `closingIssuesReferences`; keep evergreen #72 open and close only work whose
   acceptance is satisfied. Pin the merge to the reviewed head with
   `gh pr merge --squash --match-head-commit SHA`. Confirm the merge commit from
   GitHub and that main CI is green.
9. Only after separate tag/release authorization, fetch the confirmed merge
   commit, create an annotated `vX.Y.Z` tag on that commit and push that tag.
   Verify the remote tag resolves to the intended commit. Publish the GitHub
   release using `--notes-file docs/release-notes/X.Y.Z.md`, after checking all
   tag-pinned links. Record tag, merge SHA, release URL and evidence limits in
   #72. Never tag the unmerged preparation branch.

For 0.5.0, **no PyPI publishing is authorized** (owner ruling, 2026-10-28).
Do not upload distributions as part of these steps. Local wheel construction
for clean-install verification is required and is not a publish action.
