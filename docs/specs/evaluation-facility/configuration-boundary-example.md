# Configuration boundary: a worked comparison against one retained bundle

Issue #28's second half, delivered without a source failure (#28's Step 1
found none eligible - see the issue comment). This is the "readable
comparison between [retained] evidence's tested identities and a
deliberately changed configuration" the issue asks for: for each dimension a
new run could change, does the OLD claim still cover it, using only the
identity fields `skillc` already records - no new schema, no watcher, no
second registry.

## The evidence and its claim

Bundle: [`evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/`](../../../evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/README.md)
(experiment `matched-pilot-64396611`), chosen because it is the one retained
bundle with both a `trial-ledger` and stored `verified-result` records (the
first, superseded bundle predates #139 and has neither a real receipt nor a
stored result - see below).

**Claim:** installing the whole `cpp-codex` skill pack made no measurable
difference to `slug-small-fix` outcome or completion time, across three
matched treatment/baseline pairs. **No qualification claim and no
broad-benefit claim** - the bundle's own README says so explicitly, and nothing
below changes that.

Two different verdicts live in this one bundle, from two different fields -
worth separating precisely, because #28's review of this document's first
draft caught exactly this conflation:

| Field | Source | Value (all 6 attempts) | What it means |
|---|---|---|---|
| `graded_status` | `records/report.json`, per attempt | `PASS` | The fixture's 5 task criteria, all `SATISFIED` - the grader's verdict on the candidate code alone. |
| stored `verified-result.status` | `records/result-r-*.json` | `INCONCLUSIVE` | The task criteria are still `SATISFIED`, but `installation-ready` is `UNKNOWN` (agent path, no installation receipt - #139's B1 ruling; #150-D narrows this). One mandatory `UNKNOWN` criterion makes the derived status `INCONCLUSIVE`, never `PASS`, whatever the task grade says. |

The first (superseded) bundle,
[`evals/matched-pilot/evidence/`](../../../evals/matched-pilot/evidence/README.md),
predates PR that introduced `verified-result` storage (#139) entirely - it has
`report.json`'s `graded_status: PASS` on all 6 attempts and **no stored
`verified-result` records at all**. Its PASS is the report's task grade,
exactly like the second bundle's - the difference is that the second bundle
*also* has a stored, independently-derived status to compare it against, and
the first does not.

## The evidence's tested identities

One representative trial, `t1-matched_pilot_treatment_1`
(`records/ledger.json`), plus the report-level fields the ledger's own
`config` does not carry (see below):

| Identity | Value | Recorded in |
|---|---|---|
| `case.id` / `case.revision` | `slug-small-fix` / `2` | ledger, per trial |
| `grader.id` / `.revision` / `.digest` | `slug-small-fix` / `2` / `sha256:3bb202eb…` | ledger, per trial |
| `subject.digest` | `sha256:ceba20f1…` (treatment) | ledger, per trial - `materialize.acquire_snapshot`'s `tree_digest` over the WHOLE acquired `cpp-codex` tree at revision `85e9b03a`, not a per-file list |
| `subject.digest` (baseline) | `sha256:e3b0c442…` | the empty string's own SHA-256 - literally nothing installed, not "unmeasured" |
| `client.name` / `.version` | `codex` / `0.157.1` | ledger, per trial |
| `image.digest` | `sha256:d1b2ced9…` | ledger, per trial - the trial container image actually used |
| `config.digest` | (opaque, per trial) | ledger, per trial - **only `{"arm": ..., "repeat": ...}`** for this producer (`matched_pilot.py`); it is bookkeeping, not launch configuration |
| `model_observed` / `_declared`, `reasoning_effort_observed` / `_declared` | `gpt-6-astra` / `gpt-6-astra`, `high` / `high` | `report.json`, per attempt - read back from the real transcript, not the ledger |
| `cli_version_observed` | `0.157.1` | `report.json`, per attempt |

**A precision worth stating plainly:** the model/effort identity that most
readers would expect the ledger's `config` field to carry is NOT there for
this producer - `matched_pilot.py` plans `config` as `{arm, repeat}` only.
The actual launch parameters live in the CLI's own `-m`/`-c` argv (declared in
`run-manifest-2026-09-27-gpt-6-astra.json`, outside any record) and are
independently checked back from the transcript into `report.json`'s
`model_observed`/`_declared` fields. A reader comparing two runs' `config.digest`
values for this producer learns nothing about the model or effort used;
they must compare `report.json`'s fields instead.

## Six dimensions, changed one at a time

For each: what changes, which recorded field would show it, and whether the
old claim ("no measurable difference, n=3, no broad claim") still covers a
run made under the changed configuration.

| # | Dimension | A deliberately changed configuration | Recorded identity that moves | Still covered by the old claim? |
|---|---|---|---|---|
| 1 | **Skills** | `cpp-codex` updated to a newer revision (a skill added, removed or edited) | `subject.digest` (ledger) - `tree_digest` is a whole-tree content hash, so ANY change inside the acquired collection changes it, whether or not the changed file is the one a task would touch | **No.** A different `subject.digest` is definitionally a different subject; nothing here says the two are comparable, and #28's spec explicitly treats digest equality as the boundary, not a judgment call. |
| 2 | **Transitive helpers, INSIDE the collection's own tree** | A skill's `SKILL.md` references a shared script that ships inside `cpp-codex`'s own repo, and that script changes | `subject.digest` (same mechanism as #1 - `tree_digest` covers the whole acquired tree, not just `SKILL.md` files) | **No**, and visibly so - same reasoning as #1. |
| 3 | **Client version/config** | `codex-cli` upgraded from `0.157.1` to a later release, or a different model/effort declared | `client.version` (ledger) for a CLI bump; `model_declared`/`model_observed`/`reasoning_effort_*` (report.json) for a model/effort change | **No.** Either field moving is a different tested configuration; `model_matches_declaration`/`reasoning_effort_matches_declaration` (report.json) exist specifically to make a mismatch loud rather than silent (#141). |
| 4 | **Task** | A different Level 1 task, or the same task at a new revision | `case.id` / `case.revision` (ledger) | **No.** Different task ID or revision is a different claim's scope entirely - this bundle says nothing about any other task. |
| 5 | **Grader** | `slug-small-fix`'s grader criteria edited (even without touching the task fixture) | `grader.digest` (ledger) - pinned independently of `grader.revision` string, so an edit that forgets to bump the revision still changes the digest (#139) | **No.** A different grader digest means a different acceptance bar; a PASS under the old grader says nothing about the new one. |
| 6 | **Image / environment** | The trial image rebuilt (base image patched, a tool version bumped, `docker/` changed) | `image.digest` (ledger) - the actual running container's own digest, read from the container itself, never a floating tag (kyle issue #836's same "commit tag is identity, `:latest` is a convenience alias" reasoning, independently arrived at here) | **No**, PROVIDED the rebuild actually changes the digest. `FROM ubuntu:24.04`-style moving base tags mean two builds of the identical Dockerfile can legitimately differ too - `image.digest` is a real, checked fact about what ran, not a promise that "same Dockerfile" implies "same image." |

## The one change these identities cannot see

**A skill's own instructions telling the agent to fetch or execute something
from OUTSIDE the acquired collection's pinned tree at run time** - a `curl`
to a URL, a clone of a second repository, an invocation of a host tool whose
version is not pinned in the trial image. None of the six identities above
would move:

- `subject.digest` covers only what `materialize.acquire_snapshot` acquired
  into the collection's own tree - a network fetch initiated by the running
  agent, from inside its own tool calls, happens entirely outside that
  acquisition step and leaves no digest anywhere.
- `image.digest` covers what is baked into the image at build time - a tool
  invoked at build time is covered; the SAME tool's output when the agent
  calls it live, against whatever the network serves at attempt time, is not
  - the image identity says "this binary was present," never "and it did
    the same thing this time."
- Nothing in `report.json` or the transcript census records "the agent
  fetched external content mid-attempt" as its own fact; `skill_invocations`
  is heuristic and only sees a `SKILL.md` read via `exec`, not what that
  skill's instructions caused the agent to reach for afterward.

This is the useful finding #28 asked for: **it is possible for two attempts
to carry byte-identical `subject.digest`, `image.digest`, `client.version`
and `case`/`grader` identities and still not have run the same thing**, if
either attempt's skill instructions reached outside the pinned collection
tree. Nothing here proposes a fix (#28 does not edit subjects or add a
watcher); this is the boundary the six checked identities draw, stated so a
reader does not assume they draw a wider one.

## What this delivers, and what it does not

This is a worked example against one bundle, per #28's stopping condition -
not a general policy and not a second identity registry. It reuses exactly
the fields `trial-ledger` and `verified-result` already carry
([records.md](records.md)); nothing here is a new schema, and nothing here
runs anything. The product decision #28 also asks this bullet to state:
**unresolved** - whether a skill reaching outside its pinned tree at run time
should be detected, and how, is a decision for the subject/backend design
(#64's managed-container plug-in, #133's docker backend hardening, or a
network-egress policy), not something this comparison settles.
