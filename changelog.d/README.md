# Changelog fragments

A PR that changes `skillc/` adds its release note here as **its own file**:
`changelog.d/<issue>.md`, or `changelog.d/<issue>-<slug>.md` for a second PR on
the same issue. The file holds one Markdown bullet, the same shape as an entry
in `CHANGELOG.md` (`- **Title** (#N). ...`, with continuation lines indented by
two spaces). `ci/changelog_check.py` requires one, or a
`Changelog-exempt: <reason>` trailer on the last commit.

Do not edit `CHANGELOG.md`'s `[Unreleased]` section. Every PR used to, so every
merge conflicted with every queued branch there, and "keep both sides" can
silently splice two bullets that share a first or last line (#439). A fragment
is written only by its own PR, so it cannot conflict.

At release, `python3 ci/changelog_assemble.py` folds every fragment into the top
of `[Unreleased]` (by issue number, then file name) and deletes them; then the
#72 checklist moves `[Unreleased]` under the new version heading. Until then,
`CHANGELOG.md`'s `[Unreleased]` does not list what is pending here.
