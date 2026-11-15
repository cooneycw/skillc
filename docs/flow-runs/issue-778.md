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
