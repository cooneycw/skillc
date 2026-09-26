# Flow run record - issue #7

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #7
- Base SHA:          3c243a1e26fa20bead62961946c6ceafb26e9bdf
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive /flow:auto session
- Recorded at:       2026-09-26T13:51:56Z

## Section B evidence

Commits since filing (2026-09-20T16:27:40Z): 2f74b83, 04de452, 857781f, c352bbe,
1c8a762, 36bc172, e02a217, b8809e0, 95fead8, c37c991, b1a1fdf, f2d1a5c, 3c243a1 -
none materializes a subject or runs a discovery canary. Merged PRs: #16, #17, #21,
#24, #25, #29, #30, #31, #32, #33, #34, #35. Duplicate/superseding issues: none
(#26, #27, #10, #11 depend on or neighbour #7). Dependencies #3, #4, #6 closed.

Probe: `codex debug prompt-input` (codex-cli 0.157.1) lists a skill copied into a
disposable CODEX_HOME and stops listing it when removed, with no model call.
Codex seeds `.system` skills into every home.

Owner revision before approval: the adapter must be generic to any skill repo.
CPP conventions (checksum manifest name, external helper patterns, skills root)
are declared data in a subject file, not code; other layouts and clients are
refused by name; genericity is proven by #11.

## Section C - the approved plan

1. `skillc/materialize.py` - stdlib generic Codex-skills adapter: git-archive acquisition at a pinned SHA (or labelled snapshot), inventory and named refusals, dependency closure, owned disposable root, baseline arm, client canary via `codex debug prompt-input` under env -i, parity, host/source fingerprints, owned idempotent cleanup, receipt and report
2. `skillc/cli.py` - `skillc materialize` subcommand
3. `tests/test_materialize.py` - red/green cases for every refusal, fake client, real-codex test where installed, no-subject-literal guard with a planted red run
4. `tests/fixtures/codex-subject/` - tiny synthetic two-skill collection and `fake_codex.py`
5. `evals/subjects/cpp-codex/subject.json` - declared subject: locator, revision, skills root, checksum manifest, external patterns, client pin
6. `evals/subjects/cpp-codex/SUBJECT.md` - pin, client version, treatment inventory, supported/excluded capabilities, observation limits
7. `evals/subjects/cpp-codex/evidence/receipt.json` - real host run receipt, passes check-records
8. `evals/subjects/cpp-codex/evidence/report.json` - full run evidence including a planted-contamination control
9. `docs/specs/evaluation-facility/materialization.md` - adapter contract as built and its limits
10. `docs/specs/evaluation-facility/records.md` - boundary note: readiness produced by #7, gating stays #9
11. `docs/specs/evaluation-facility/review.md` - Q2 installed surface defined
12. `PLAN.md` - #7 status line
13. `AGENTS.md` - layout entries
14. `evals/README.md` - pointer to the subject
15. `docs/flow-runs/issue-7.md` - this record
16. `docs/flow-runs/issue-7.as-read.md` - issue body as read

Scope: ~16 files, ~1,900-2,500 lines. No change to existing check rules.
Risks: `codex debug prompt-input` is a debug surface that may change (pinned,
unparseable -> UNKNOWN); CI has no git or codex, so git acquisition and the real
canary are local-only and CI exercises the fake client; the adapter reproduces
the install layout rather than executing subject code; the host codex binary runs
against disposable homes (no agent, no model); the receipt contract has no
baseline form, so the baseline lives in the report and in `baseline_absence`.
