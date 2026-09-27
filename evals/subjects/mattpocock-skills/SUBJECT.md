# Subject: mattpocock/skills (select: tdd, diagnosing-bugs)

- Declaration: [subject.json](subject.json) - the machine form; this page explains it
- Adapter: `skillc materialize` ([materialization spec](../../../docs/specs/evaluation-facility/materialization.md)) - unchanged from [cpp-codex](../cpp-codex/SUBJECT.md), no new client or layout support
- Evidence: [records/receipt.json](evidence/records/receipt.json) and [report.json](evidence/report.json), produced 2026-09-26 (#11)
- Provenance: [mattpocock/skills lessons and concept map](../../../docs/research/mattpocock-skills-lessons.md) (#49)

This is the second declared subject (#11): a small, independently authored
collection with a different supported layout, proving `skillc materialize`
against a subject it was not written for. Refs #11, not Closes - the
conformance run of both subjects through one runner and grader, and the
bounded compatibility statement built on it, need #10's runner and are not
part of this PR.

## Selection, against the acceptance's four bullets

- **Independently authored, with a different supported layout.** [mattpocock/
  skills](https://github.com/mattpocock/skills), by
  [Matt Pocock](https://github.com/mattpocock), has no shared authorship or
  tooling with CPP. Three layout differences this adapter had never been
  exercised against:
  - **Bucketed skills**: `skills/<bucket>/<name>/SKILL.md`, not CPP's flat
    `codex/skills/<name>/`. `subject.json`'s `skills_root` selects one bucket
    (`skills/engineering`) as data; the adapter reads no bucket name.
  - **A manifest-declared shipped surface**: `.claude-plugin/plugin.json`
    lists 25 of the repository's 38 skill directories. The other 13
    (`skills/in-progress/*`, `skills/misc/*`) are drafts the manifest does not
    ship. This subject selects by name from within the declared surface
    (`select`, spec.md section 3), the same mechanism cpp-codex's whole-pack
    treatment does not exercise.
  - **Codex-native metadata**: every skill carries `agents/openai.yaml`,
    including an invocation policy. The collection targets Codex as well as
    Claude Code, so the `codex-skills`/`codex` surface and client #7 already
    qualified apply unchanged - no new client.
- **Compatible capability scope.** Not the whole pack. Of the 25 manifest
  entries, 14 declare `disable-model-invocation: true` in `SKILL.md` **and**
  the matching `policy.allow_implicit_invocation: false` in
  `agents/openai.yaml` (measured directly, both fields checked, all 14 pairs
  agree); the other 11 are model-invoked. **Selected: `engineering/tdd` and
  `engineering/diagnosing-bugs`**, the two of those 11 closest to the Level 1
  slug-fix goal (a small, self-contained bug in `slugify`): `diagnosing-bugs`
  is a diagnosis loop for exactly that shape of problem, `tdd` a test-first
  fix loop. Both read `CONTEXT.md` "if it exists" - a soft, optional
  environmental read the disposable home's absence of one does not break.
  Their own referenced files (`tests.md`, `mocking.md` for `tdd`;
  `scripts/hitl-loop.template.sh` for `diagnosing-bugs`) are plain relative
  Markdown links or in-directory paths, not host or other-client references -
  confirmed by grep, and by the `external_references` count of zero below.
- **"Tiny."** Two skills, seven files, no `checksum_manifest` (the collection
  ships none) and no `required_references`/`external_references` declared:
  every reference `tdd`'s and `diagnosing-bugs'` entry points make is a plain
  relative Markdown link, which the adapter already treats as required
  generically (`materialize.py`'s `_links`), so this subject needed no new
  declaration to prove that path.
- **Report unsupported formats or incompatible tasks before selection:**
  - The 13 `in-progress/`/`misc/` directories are draft, unshipped formats -
    excluded because the manifest does not ship them, not evaluated further.
  - The 14 user-invoked skills are format-incompatible with today's
    `discovery_canary` fact as written: it requires every SELECTED skill to
    be listed by the client's no-model canary, and Codex does not list a
    skill whose `agents/openai.yaml` sets `allow_implicit_invocation: false`
    (confirmed below). Materializing any of them as a treatment would report
    `discovery_canary: VIOLATED` for a correctly-installed skill - a false
    incompatibility signal, not a broken subject. This is a `skillc`
    defect, not a subject property, filed as an issue rather than patched
    here (out of this PR's scope; see "Left for later" below) - it does not
    block selecting `tdd`/`diagnosing-bugs`, which are both model-invoked.
  - `engineering/code-review`, though model-invoked, is excluded on the
    merits: it instructs the agent to redirect the user to
    `/setup-matt-pocock-skills` when `docs/agents/issue-tracker.md` is
    absent (`skills/engineering/code-review/SKILL.md:13`), an external
    dependency the slug-fix fixture does not provide and this subject does
    not select for.

## Pin

| Identity | Value |
|---|---|
| Locator | `github.com/mattpocock/skills` |
| Revision | `c55ee46073ed923f86ce59a5eb3b6d895095d1b7` (plugin v1.2.3, committed 2026-09-18) |
| Re-pin check (#11) | `git fetch origin main` on 2026-09-26 found 0 commits ahead of this pin - upstream has not moved since #49/#50/#51 cited it, so it is reused, not blindly carried forward |
| Surface | `codex-skills`: `skills/engineering` at that revision, `select: [tdd, diagnosing-bugs]` |
| Surface digest | recorded in the receipt's `subject.digest` |
| Client | `codex`, codex-cli `0.157.1` |
| Licence | [MIT](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/LICENSE) |

The Level 1 fixture is pinned separately
([PROVENANCE.md](../../level1/slug-small-fix/PROVENANCE.md)); this pin says
nothing about it. Terms of use: [ADR 0003](../../../docs/decisions/0003-no-external-evaluation-runtime.md)
and the provenance note above - ideas and, here, unmodified installed files;
nothing copied into skillc's own source.

## Treatment inventory

2 skill directories, 7 files, no symlinks, no checksum manifest. `README.md`
and every other manifest entry outside `skills/engineering` are not under
`skills_root` and are not installed - a property of the declared surface, not
a finding. The installed files and their digests are the receipt's
`installed`; `inventory.skills` in the report carries each skill's file count
and required-reference resolution.

## Conventions declared for this subject

| Declaration | Value | Why |
|---|---|---|
| `checksum_manifest` | not declared | the collection ships no per-skill manifest |
| `required_references` | not declared | both entry points use plain relative Markdown links (`[tests.md](tests.md)`, `[mocking.md](mocking.md)`) or an in-directory backtick path (`scripts/hitl-loop.template.sh`); the adapter's generic Markdown-link handling already requires the first two, and the third resolves because the file is present, declared or not |
| `external_references` | not declared | neither skill's files reference a host helper, another client's plugin root, or any other external location (checked by grep over both directories before selection) |

## Capabilities

**Supported (observed in the evidence, `skillc materialize` run 2026-09-26,
no model call):**

- Codex lists both selected skills, from the files this run installed:
  `discovery_canary` SATISFIED, "all 2 installed skill(s) listed".
- A baseline home prepared identically, minus the treatment, lists neither; a
  single planted control skill IS listed: `baseline_absence` SATISFIED,
  "no treatment skill listed in the baseline; the planted control was
  listed" - so absence is not blindness, the same discipline cpp-codex's
  evidence uses.
- Apart from the treatment, the client's input is identical between arms:
  `ordinary_parity` SATISFIED.
- The pinned source and the host's `codex` state were unchanged before and
  after: `source_unchanged` and `host_unchanged` SATISFIED.
- All five readiness facts SATISFIED; `skillc materialize` exits 0 (READY).

**Confirmed independently, informing the exclusion above (not part of this
subject's own evidence - a throwaway `skillc materialize` run selecting one
user-invoked skill, `engineering/ask-matt`, not committed as a receipt):**

```
installed     3 file(s) in 1 skill(s)
available     VIOLATED
VIOLATED  discovery_canary  installed but not listed: ['ask-matt']
UNKNOWN   baseline_absence  negative control failed: a treatment skill
                            planted in a baseline home was not listed, so
                            absence from the baseline proves nothing
```

Both the primary defect and the related trap #11's second tracker comment
(2026-09-26) named reproduce directly: Codex's no-model listing omits a skill
whose `agents/openai.yaml` sets `allow_implicit_invocation: false`, and the
planted-control baseline check has nothing to plant that this canary would
list either, so it reports UNKNOWN rather than a false SATISFIED.

**Excluded, and why:**

- **The 14 user-invoked skills of the 25 shipped.** See "report unsupported
  formats" above - a `skillc materialize` defect (`discovery_canary` is not
  policy-aware), not a property of those skills. Left for later, see below.
- **`engineering/code-review`.** External dependency this fixture does not
  provide (`docs/agents/issue-tracker.md`, via `/setup-matt-pocock-skills`).
- **The 13 `in-progress/`/`misc/` drafts.** Not in the manifest; not this
  collection's declared shipped surface.
- **External services and authority**, and **other CPP/mattpocock surfaces**
  (the Claude Code plugin form of this same collection) - same exclusions as
  cpp-codex's SUBJECT.md, for the same reasons (spec.md section 4).
- **Invocation and task outcome.** No model runs here (`invoked:
  NOT_OBSERVED`, `task_outcome: NOT_APPLICABLE`) - #10, #12, #26's to measure.

## What the evidence does not show

- One run, one host, one moment, exactly as cpp-codex's evidence states.
- `codex debug prompt-input` renders what a session WOULD be given; that a
  model then reads a listed skill, or invokes a user-invoked one explicitly
  (`$skill` syntax), is not shown - the second tracker comment on #11 found
  its own render surface cannot answer the explicit-invocation question
  either, for either arm.
- Static findings in the report (Markdown-link-shaped text not present in
  the installed skill) neither establish nor refute readiness, by design.
- The host's `~/.codex` skills tree and config files were fingerprinted
  before and after and did not change; sessions and caches were not,
  because other sessions write them.

## Left for later

- **A policy-aware `discovery_canary`, or a documented restriction of
  `select` to model-invoked skills.** The second tracker comment on #11
  found this gap and flagged it in the Nit Store (#20); it is a `skillc`
  defect this PR does not fix, because fixing it changes the adapter's core
  readiness contract, which is out of #11's scope (no runtime change beyond
  the declaration + evidence this issue asks for). Whoever picks it up should
  decide between the two options that comment names.
- **The conformance run of both subjects through one runner and one grader**,
  and the bounded compatibility statement built on it - prepared, not run,
  in [`evals/second-collection-conformance/`](../../second-collection-conformance/README.md):
  the exact command per subject, the expected paste-back shape, and the
  statement itself. Execution needs #81's operator demo command (a
  `--subject` flag, in progress) and #10's own live Docker run, neither of
  which exists yet; this subject's own evidence stays Refs #11, not the
  full close.
