# Flow run record - issue #778

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8935e2bef25540c7b4cb5982f8fee831 -->
## Run 1

- Run-id:            8935e2bef25540c7b4cb5982f8fee831
- Run-start:         295e743be21b4a94b06c55eb174ac682dd8b3363
- Issue:             #778 (PR A of 2: `charter evidence` only; PR B, stacked, is `charter create`)
- Base SHA:          295e743
- Necessity verdict: Still needed (no merged work since filing; no GitHub reader exists, #718 build step 4 is unbuilt)
- Approval:          granted (GO-WITH-CONDITIONS, PR A scope)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 72
- Recorded at:       2026-11-15T18:30:00Z

### Section B evidence
- since 2026-11-15T18:18:16Z: none touching skillc/charter*.py, skillc/contracts.py or .claude/skills; 295e743 (#762) merged before filing and is the base
- merged PRs after filing: none. Open in the area: #771, #770, #773
- dup/super: none (search "charter create": only #778)

### Section C - the approved plan
1. `skillc/charter_evidence.py` - `skillc charter evidence`: gathers repository evidence (explicit --ref first, name search only with --search), an existing CHARTER.md and its git history, SKILL.md MUST/NEVER lines and --doc spec docs, usage records, and existing tests naming the skill; each suggestion has an id, section, a quote under 40 words, a citation and a kind (stated, observational, test); each source has a status examined / none found / not examined: <reason>
2. `skillc/repo_reader.py` - the RepoReader seam: GhReader (read-only gh calls only, asserted: issue view, pr view, a GraphQL discussion query, search only on opt-in) and FakeReader; the heading-based extractor (Job/Intent, Must always, Must never, Authority, as headings or bold labels) honouring the CommonMark fence rule
3. `skillc/cli.py` - `charter evidence <collection> <skill> [--usage P]... [--repo O/N] [--ref REF]... [--search] [--doc P]... --out FILE`
4. `tests/test_charter_evidence.py` - the controls: a planted discussion with a Must never list is offered with its URL; a comment without charter-shaped headings yields no suggestions; a Must never heading inside a fenced code block is ignored; no gh reads "not examined" and the run continues, never empty; only read-only gh argv is ever run; quotes stay under 40 words and the real copied-passage detector is clean on evidence.json; the frozen #718 Charter v1 comment yields its Job, 4 must-always and 5 must-never with the comment URL
5. `tests/fixtures/charter-evidence` - the frozen #718 comment and the planted discussions
6. `docs/specs/charter-create.md` - the evidence step's rules, the evidence.json shape, and what is not examined (PR B extends it with create and the stubs)
7. `README.md` - the command line
8. `AGENTS.md` - the layout line
9. `changelog.d/778-evidence.md` - the fragment

Conditions (rev 72): two PRs, both Refs #778; the extractor's no-headings control and fenced decoy; gh read-only, asserted; name search off by default; quotes under 40 words, with the copied-passage detector run on evidence.json; targeted set only; up to 3 counter-model passes per PR, with pass-3 findings deferred; mailbox-gated pushes. PR B (later): stubs at `evals/trap-tasks/<contract>/<clause-slug>/{bad,good}/`; in another repo's collection, create writes and never commits.
Scope: ~9 paths plus fixtures, ~700-900 lines. Risks: a heading-based extractor misses intent written as prose (the source is reported as examined with 0 suggestions, and the skill asks open questions); gh rate limits or auth read "not examined", never empty.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test - Woodpecker CI (full-suite gate); host targeted set only |
| Execution backend | not applicable |
| Agent client | not applicable - no client and no model call |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test - synthetic fixtures and the frozen #718 comment; live GitHub not covered in CI (GhReader is exercised by argv tests and a fake gh) |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout; built wheel not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: PR B's `charter create` and the `/charter-create` dialogue skill read evidence.json. Compatibility: the shape is versioned (`schema: 1`) and fixed in the spec.
- Reader: the owner reads the suggestions. Compatibility: every suggestion carries its citation and kind; observational items are labelled so.

### Plan deviations
- 2026-11-15, Checkout lane corrected (owner question "did you examine the lanes?"): the plan answered Checkout "not applicable". The counter-model pass-1 fix (`6a9b50b`) made `charter evidence` read the gauntlet's own draft from the MAIN checkout's `.skillc/gauntlet/<slug>/` through `gauntlet.main_checkout`, which resolves a linked worktree to its main checkout. So the lane applies: **will test - main checkout and linked worktree**. `test_the_gauntlets_own_draft_under_skillc_gauntlet_is_found` covers the main checkout, and `test_from_a_linked_worktree_the_draft_in_the_main_checkout_is_found` covers a collection opened from `git worktree add`. The latter passed on `6a9b50b` too: coverage the code already earned, not a regression test.
- 2026-11-15, counter-model passes 1 and 2 added paths to the plan's list: `skillc/repo_reader.py` (named in Section C item 2), `--draft` on the CLI, and `tests/fixtures/charter-evidence/` (item 5).

<!-- flow-run n=2 id=10ee830790e24aa8a62fd66c401c0365 -->
## Run 2

- Run-id:            10ee830790e24aa8a62fd66c401c0365
- Run-start:         7c630d2632b799493c20c73891d1ed8460c3ad41
- Issue:             #778 (PR B of 2: `charter create`, the trap-task stubs and the `/charter-create` dialogue skill; stacked on PR A, #780)
- Base SHA:          7c630d2 (PR A's head; main 295e743 beneath it)
- Necessity verdict: Still needed (PR A delivered the evidence step only)
- Approval:          granted (GO for PR B under the #778 gate, mailbox rev 73)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 73
- Recorded at:       2026-11-15T19:00:00Z

### Section B evidence
- since 2026-11-15T18:18:16Z: PR A (#780: 1077bb0, 593e10f, 6a9b50b, 4bab5a9, 7c630d2) is this branch's base; nothing on main touches skillc/charter*.py or .claude/skills since 295e743
- merged PRs after filing: none. Open in the area: #780 (PR A), #771, #770, #773
- dup/super: none

### Section C - the approved plan
1. `skillc/charter_create.py` - `charter create`: reads the evidence file (PR A's schema 1) and the owner's answers file (JSON, schema 1), and refuses with nothing written when: an offered suggestion has no answer (accept, edit or drop); an accepted or edited suggestion is used by no clause, or a dropped one is used; a clause has no text or an unknown section; a must-never or authority clause has no `shortcut`; an approval is asked for outside intent and authority, or without `approved_on`, or with an impossible date; a clause id repeats. It stamps `approved` only on intent and authority clauses the answers mark `approve: true`. It writes CHARTER.md where `gauntlet.resolve_skill` places it (refusing to overwrite unless every existing clause is a draft and `--replace-draft` is given), plus a trap-task stub per clause at `evals/trap-tasks/<contract>/<clause-slug>/{bad,good}/` holding STUB.md, goal.md and fixture/README.md but no grader, so `verify.GraderDef.load` refuses it. It then runs the contracts rules over the collection: any error finding, or an approval-present warning on a clause the owner approved, rolls back everything it created. It never runs git and never commits; it never changes the skill (tree digest, CHARTER.md and GAUNTLET.json excluded).
2. `skillc/cli.py` - `charter create <collection> <skill> --evidence FILE --answers FILE [--replace-draft]`
3. `.claude/skills/charter-create/SKILL.md` - the dialogue: run evidence, walk the owner through every suggestion one at a time (accept, edit, drop), then intent, each always/never (asking for the tempting shortcut), and authority; write answers.json in the owner's words only; run create. Never answers, approves or picks for the owner. Pinned word budget 600. Not installed under ~/.claude (rev 68).
4. `.claude/skills/charter-create/scripts/charter.sh` - the launcher: finds the skillc checkout as gauntlet.sh does, and runs `skillc charter evidence|create`
5. `tests/test_charter_create.py` - the controls: planted answers give a CHARTER that passes contract-shape, clause-backed and negative-backed (the real rules); an unanswered suggestion is refused; no approval without approve plus a date; a never without a shortcut is refused; the skill tree digest is unchanged; a stub is refused by GraderDef; a failing final check rolls back; nothing is overwritten
6. `tests/test_charter_create_skill.py` - the word budget (and one word over fails), the never-answers text pins, the launcher refusing without a checkout
7. `evals/subjects/charter-create/` - the planted skill, evidence and answers the controls use
8. `docs/specs/charter-create.md` - create, the answers file, the stub shape and how #736 PR 2 fills a stub
9. `README.md` - the command line
10. `AGENTS.md` - the layout line
11. `changelog.d/778-create.md` - the fragment

Conditions (rev 72, 73): stubs at `evals/trap-tasks/<contract>/<clause-slug>/{bad,good}/` at the collection root; in another repo's collection, create writes and never commits; approval-present may warn only where the owner withheld approval; the dialogue skill is not installed under ~/.claude; targeted set only; up to 3 counter-model passes; mailbox-gated pushes. The live /skill-gauntlet composition is the owner follow-up after this merges.
Scope: ~11 paths plus fixtures, ~900-1,200 lines. Risks: a stub backs a clause by existence only (STUB.md marks it and GraderDef refuses it, so round 3 cannot grade it); the answers file is a contract with the dialogue skill, so its shape is fixed in the spec; the skill's launcher duplicates gauntlet.sh's lookup.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | will test - main checkout (the planted collections are plain directories and `git init` repos); linked worktree not covered here: create reads no main-checkout state (placement is `gauntlet.resolve_skill`), and PR A's evidence test covers a linked worktree |
| Run placement | will test - Woodpecker CI (full-suite gate); host targeted set only |
| Execution backend | not applicable |
| Agent client | not applicable - no client and no model call; the dialogue skill is text, pinned by tests |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test - synthetic planted collection; the live /skill-gauntlet composition is the owner follow-up |
| Subject installation | not applicable - the skill is not installed (rev 68) |
| skillc distribution | will test - source checkout; built wheel not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: `skillc contracts` and gauntlet round 1 read the CHARTER. Compatibility: #720's format, checked by the real rules before create reports success.
- Reader: #736 PR 2 and round 3 read the stubs. Compatibility: the shape is fixed in the spec; a stub has no grader, so `read_task` refuses it until it is filled.
- Reader: the dialogue skill writes the answers file and create reads it. Compatibility: `schema: 1`, fixed in the spec.

### Plan deviations (run 2)
- 2026-11-15, counter-model pass 1 (LOW), Checkout lane: the row promised a `git init` main checkout, but no test ran create in one. `test_create_in_a_git_main_checkout_writes_and_commits_nothing` now does, and asserts HEAD is unchanged, nothing is staged, and the charter and stubs are untracked. It passed when added: coverage, not a regression test.
- 2026-11-15, counter-model pass 1 (LOW), a missing Reader:
  - Reader: the `/charter-create` dialogue reads create's and the launcher's output: stdout `skillc: charter written to`, `skillc: trap-task stub ...`, `skillc: warn: ...`, `nothing was committed`; stderr `skillc: charter create refused: <reason>`, `CHARTER_CREATE: cannot find a usable skillc (...)`, `CHARTER_CREATE: usage`; exit 0 written, 1 refused, 2 usage. Compatibility: `test_the_cli_reports_the_charter_the_stubs_and_that_nothing_was_committed`, `test_the_cli_refusal_exits_1_and_writes_nothing`, and the launcher tests pin those lines and codes; the spec states them.
- 2026-11-15, counter-model pass 2 (LOW), a missing Reader:
  - Reader: `charter evidence` (`charter_evidence._charter_file`) reads the CHARTER.md that create wrote on a later run, including list-valued `test` fields. Compatibility: `test_charter_evidence_reads_back_the_charter_create_wrote` runs create, then evidence, on real output. It passed when added: coverage, not a regression test.
