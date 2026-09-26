# Flow run record - issue #5

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #5
- Base SHA:          c37c991fb152f8afb3e0b274c15cb4453e534df6
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive /flow:auto session
- Recorded at:       2026-09-26T12:32:31Z

## Section B evidence

Merged PRs since filing (2026-09-20): #17, #21, #24, #25, #29, #30, #31, #32 (#32
closed dependency #4). Commits since filing on evals/, tests/, PLAN.md, docs/specs:
2f74b83, 857781f, c352bbe, 36bc172, e02a217, b8809e0, 95fead8, c37c991 - none adds a
task, fixture or grader. Duplicate/superseding issues: none (search "slug" -> #5 only).

## Section C - the approved plan

1. `evals/level1/slug-small-fix/PROVENANCE.md` - CPP commit 5b6c4c64, tree/blob hashes, MIT notice, copied vs not copied, pin independent of #7 subject revision
2. `evals/level1/slug-small-fix/fixture/src/slugify.py` - byte-identical pinned copy of the broken start state
3. `evals/level1/slug-small-fix/goal.md` - single agent-facing request shared by both arms: reported example plus public rules R1-R4
4. `evals/level1/slug-small-fix/README.md` - scope, ceiling effects, old-arm audit, dev/held-out separation, deliberately unprobed edges
5. `evals/level1/slug-small-fix/grade_slug.py` - stdlib grader, candidate in subprocess with timeout, per-rule SATISFIED/VIOLATED/UNKNOWN
6. `evals/level1/slug-small-fix/reference/src/slugify.py` - correct reference fix
7. `evals/level1/slug-small-fix/alternatives/char-loop/src/slugify.py` - valid alternative implementation
8. `evals/level1/slug-small-fix/alternatives/findall-join/src/slugify.py` - valid alternative implementation
9. `evals/level1/slug-small-fix/wrong/example-only/src/slugify.py` - reported-example-only fix
10. `evals/level1/slug-small-fix/wrong/trailing-only/src/slugify.py` - rstrip-only fix
11. `evals/level1/slug-small-fix/wrong/no-collapse/src/slugify.py` - does not collapse runs
12. `evals/level1/slug-small-fix/wrong/no-lowercase/src/slugify.py` - drops lowercasing
13. `evals/level1/slug-small-fix/wrong/renamed/src/slugify.py` - breaks the interface
14. `evals/level1/slug-small-fix/grader-controls/always_pass.py` - broken grader control
15. `evals/level1/slug-small-fix/grader-controls/always_fail.py` - broken grader control
16. `evals/level1/slug-small-fix/grader-controls/crash.py` - broken grader control
17. `evals/level1/slug-small-fix/grader-controls/no_output.py` - broken grader control
18. `evals/level1/slug-small-fix/qualify.py` - certification gate using records.derive_status; refuses the four broken graders
19. `tests/test_level1_slug.py` - gate in pytest, pin hash, held-out separation, rule tagging, mutation red case
20. `evals/README.md` - point to the task
21. `AGENTS.md` - layout line for evals/level1/

Scope: ~22 new files, ~600-800 lines, no change to skillc/.
Risks: candidate runs in the reporting child so a hostile candidate can forge the
channel (hard isolation is #9, stated as a limit); evals/ outside mypy scope
(duplicate module names); task may be too easy (ceiling, accepted and recorded).
