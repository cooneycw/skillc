<!-- flow-run n=1 id=26576e9483274db9b9731d0eaf55d8af -->
## Run 1 - issue #432 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #432
- Read at:      2026-10-17T18:11:07Z
- updatedAt:    2026-10-17T18:10:25Z   (context only - moves on comments and labels)
- Body digest:  dc76008a5c4c648088f40d0401bb857968b932df065cd0702d3b44664b09fd19   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2571 of 2571 (cap 16384)

### Body as read
## What is wrong

`skillc/calibration_run.py` `build_treatment` (added by #429 for #424, around lines 284-291) refuses unless

```python
closure.skill_pins == skill_digests
```

`closure.skill_pins` comes from the profile inventory and covers only the profile's **selected** workflow skill(s). `skill_digests` covers **every skill installed** into the treated home. For `evals/subjects/cpp-codex-flow-check-86641e8`, the inventory pins exactly one skill (`.codex/skills/flow-check/SKILL.md`), while the treatment installs the whole CPP collection: 77 `.codex/skills/*/SKILL.md` entries, from `browser-help` to `self-improvement-retro`. The two lists can never be equal, so every treatment built from this profile is refused.

Observed on #315's runner, 2026-10-17, `skillc level3-campaign --manifest evals/level3/campaign-271/manifest.json` at merged main `4bab8d3` (#403), before any row ran:

```
skillc: profile 'evals/subjects/cpp-codex-flow-check-86641e8''s inventory pins [{'path': '.codex/skills/flow-check/SKILL.md', ...}] disagree with the installed skills' own digests [{'path': '.codex/skills/browser-help/SKILL.md', ...}, ... 77 entries ...]
```

The flow-check entry is present on both sides with identical body and description digests. The refusal comes only from the extra installed skills.

## Why it matters (live)

- **Every Level-3 production campaign is blocked at main >= 0e09873**: #375/#376's 42 rows and #271's 28 rows (#271's last acceptance item). The last successful campaign ran at c1d6212, before #429.
- **Very likely the #287/#288 calibration study too.** It builds its treated arm through the same `build_treatment` with the same profile. Not run here; whoever owns #287 should confirm.
- #429's tests passed because their treatment fixtures pin exactly what they install (per its PR body, direct `Treatment(...)` fixtures carry "a fixed well-formed pin"). None exercises a real profile whose installed collection is larger than its selection.

## Fix shape (for the owner of #424)

Compare like with like. Either the pins must agree with the installed digests **for the pinned paths** (a subset check: every pinned path installed with identical digests), or the inventory must pin every installed skill. Which one is right depends on what #424's ledger lock is meant to bind: the selected workflow only, or the whole installed surface. A red case either way: a profile whose selected skill is substituted must still be refused, and the current full-collection profile must build.

Found while running #271's campaign after merging #403.

