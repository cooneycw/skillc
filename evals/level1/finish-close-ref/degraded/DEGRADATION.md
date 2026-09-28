# The degraded arm's source (issue #150-B3b)

`finish-close-ref`'s baseline arm installs `cpp-codex` (`evals/subjects/cpp-codex/`)
unmodified: its `flow-finish` skill teaches the negated/incidental
closing-keyword rule this eval grades, so an agent that has read it should
avoid the mistake for reasons unrelated to any skill it might additionally be
given. The degraded arm needs the SAME subject with that specific teaching
removed - not a different, weaker subject - so the comparison isolates the
skill collection under test rather than a difference in the underlying agent.

**No CPP text is vendored here.** `degrade.toml` commits only facts about
five files at `cooneycw/claude-power-pack@85e9b03ad2af1c41020ff6d92d36fa257bdacd2b`
(sha256 hashes, line ranges, and exact substring replacements) - never their
content. CPP's own `LICENSE` is MIT, but its `## Scope` section lists
`scripts/`, `.claude/commands/`, `mcp-second-opinion/` and configuration or
templates; `codex/skills/` is not among them, so committing this text is a
licensing question for the repository owner, not something a session decides
for itself. `degraded/prepare.py` turns the facts below into the five actual
files, given a real checkout - a runbook step, not a build step this repo's
own tests or CI perform.

## What each location said, and what was removed

The removed content, everywhere, is the same fact stated five ways: that
GitHub's issue-closing keyword still closes the issue even when the keyword
is negated ("does not close #N") or merely incidental (adjacent to `#N`
without being a directive) - the exact class of mistake `finish-close-ref`
grades against (`no-closing-match`).

- **`flow-finish/reference.md`** (one range deleted): a paragraph, in the
  merge step's guidance, telling the reader to select a non-closing reference
  when the acceptance accounting is incomplete, and explaining that the merge
  helper itself refuses a negated or incidental closing keyword rather than
  trusting prose review alone.

- **`flow-merge/reference.md`** (two range groups deleted, one preserved
  between them): the same explanatory paragraph as flow-finish's, plus -
  further down, in the merge helper's exit-code documentation - the two
  bullets describing the helper's refusal for a negated closing keyword and
  for an incidental one (and its own self-check). The bullet in between,
  documenting an unrelated exit code (the base branch moving during the
  required-check wait), is untouched.

- **`flow-auto/reference.md`**: structurally identical to flow-merge's - the
  same explanatory paragraph, and the same three exit-code bullets with the
  same unrelated one preserved between them, at flow-auto's own (later) line
  numbers.

- **`flow-merge/scripts/gh-pr-merge.sh`** and **`flow-auto/scripts/gh-pr-merge.sh`**
  (byte-identical originals, byte-identical results): every PROSE statement
  of the rule is removed, and every CODE line is kept. Removed: the
  negated-close guard function itself (with its header comment and its one
  call site), the corresponding CLI flag's variable and case-parsing, the
  flag's own usage-string token (via an exact, hash-checked substring
  replacement on three shared usage lines, so the two RETAINED flags stay
  documented on the same lines), two top-of-file header paragraphs
  explaining the negated and incidental rules to a reader, the exit-code
  documentation for both, and - in the RETAINED
  `_is_incidental_close_match`/`guard_incidental_close_keywords` region -
  every comment paragraph that states the rule (see below). Kept, CODE-INTACT:
  `guard_incidental_close_keywords` itself and its self-check, still called -
  a live merge-time control, not documentation, and disabling it would change
  the script's behaviour rather than only what an agent reads.
  `expected_removed_code_lines` in `degrade.toml` names every non-comment
  line each range actually removes, so a range that swallowed anything past
  what is described here would be refused, not merely undocumented.

## Residual lines (scripts only), and the honesty check on them

The first pass at this section (found by explicitly checking, not assumed
clean) classified the retained region's matched lines as mostly harmless
identifier citations, with a few real but "kept because deleting them would
gut the retained guard's documentation" statements of the rule. On review,
that was the wrong trade: those lines are `#`-prefixed COMMENTS, not the
retained guard's CODE. A comment can be deleted with no behaviour change at
all - `guard_incidental_close_keywords` and every line of its own control
flow are exactly as live with or without the prose explaining them to a
human reader. So the degradation now removes ALL of it: the classifier's own
header comment, its "ownership" paragraph, and the retained guard's own
header paragraph are deleted alongside everything else that states the rule,
and only two lines remain that `rule_patterns` still matches -
`degrade.toml`'s `residual_lines` names them by content hash. Both are (a),
harmless: one cites `--allow-negated-close` inside a reorder-rationale
comment about TEST ORDERING (which internal check runs first), the other
cites `#726` inside an ownership comment in the self-check helper (which
guard owns a negated-and-possessive construction) - neither states what
either guard actually does to a keyword next to `#N`.

`rule_patterns` also gained two entries for the general fact itself
(broader than "negated"): GitHub closes on a close/fix/resolve keyword next
to `#N` regardless of grammatical context. Both are drawn from the exact
wording the two deleted header comments used, verified to match the
ORIGINAL text (the positive control) and to match NOTHING in the prepared
text - the mechanical check now sees this broader class too, not only the
identifier-scoped one.

**The degraded scripts retain the incidental guard's code, which handles
negation internally, but no prose stating the rule. An agent could still
infer the rule by reading the guard's control flow.** That residual is true
and much narrower than the first pass's finding - reading raw control flow
(a classifier function and its self-check, with no explanatory comment left)
to reconstruct "a keyword adjacent to `#N` still closes, even as an
adjective or governing a different noun" is a materially harder inference
than reading a paragraph that states it, and the task's own principle is
that the agent under test is unlikely to do the former at all. The runbook's
non-discriminating-result branch should still consider this before assuming
the skill collection under test failed to teach anything.

## Procedure

1. Clone `cooneycw/claude-power-pack` and check out `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b`.
2. `python3 degraded/prepare.py --checkout <that checkout> --out <dir>`.
3. `prepare.py` verifies every fact in `degrade.toml` against the real files
   (original hash, positive control, the code-vs-comment check, result hash,
   `bash -n`, the residual allowlist, `must_still_contain`, and that the five
   declared files are the only place the rule is still stated anywhere under
   `codex/skills/`) before writing anything, and refuses naming the first
   fact that does not hold.
4. It prints the exact `skillc degrade-subject cpp-codex --checkout <that
   same checkout> --override-file <skill>:<path>=<prepared file> ... --out
   <DEGRADE_OUT_DIR>` command to build the degraded subject from the five
   prepared files - `--checkout`, reusing the real checkout this script
   already read from, never `--revision`, which would waste a second clone;
   `<DEGRADE_OUT_DIR>` is a placeholder for wherever the operator wants
   `receipt.json` and the persisted degraded tree, a different directory
   from `prepare.py`'s own `--out`. The exact argv is built once
   (`prepare.py`'s `degrade_subject_command`) and fed straight to
   `skillc.cli.build_parser()` in `tests/test_degraded_prepare.py`, so a
   renamed or removed `degrade-subject` flag fails that test, not only a
   human copy-pasting the printed line.

This script and its own tests (`tests/test_degraded_prepare.py`) run against
a synthetic mini-checkout, never the real CPP text - running it against the
real revision, and the `degrade-subject` invocation it prints, are runbook
steps.
