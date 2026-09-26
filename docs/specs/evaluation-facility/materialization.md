# Native materialization and the clean baseline

- Status: Implemented as `skillc materialize` (`skillc/materialize.py`), #7
- Date: 2026-09-26
- Governing documents: [interfaces](interfaces.md), [records](records.md), [specification](spec.md)
- First subject: [CPP native Codex skills](../../../evals/subjects/cpp-codex/SUBJECT.md)

## What it does

interfaces.md lifecycle steps 2-4 for one surface and one client: resolve
immutable inputs, prepare only in allocated home and workspace directories, and
verify the native installation, its dependency closure and a clean baseline. It
produces an `installation-receipt` (records.md, version 2) and a report.

```
subject.json --> acquire (pinned commit, read-only) --> inventory + closure
                                                          |
             +---------------------+----------------------+
             v                     v                      v
        treatment arm         baseline arm           control arm
        (every selected       (nothing)              (one selected skill)
         skill)
             |                     |                      |
             +------ the client lists what it can see ----+
                                   |
            readiness, derived ONLY from those three listings
```

## Generic by declaration

The adapter names no subject. A subject is a `subject.json`:

| Key | Meaning |
|---|---|
| `locator`, `revision` | source identity; `revision` must be a full commit SHA |
| `surface`, `client` | only `codex-skills` and `codex` are supported; anything else is refused by name |
| `skills_root` | the directory whose children are skill directories |
| `select` | `"all"`, or the skill names that make up this treatment |
| `checksum_manifest` | optional per-skill manifest (`<sha256>  <file>` lines) to verify |
| `required_references` | patterns, one capture group, for the entry point's "read this file" phrasing |
| `external_references` | patterns for references the bundle makes to things it does not carry, read from every text file in each selected skill, scripts included |

Unknown keys are refused: an unread key is a convention its author believes is
honoured. `test_the_adapter_names_no_subject` fails if a subject's conventions
reach a string literal in the adapter, and is shown able to fail on a planted one.

## Refused by name

Nothing here is guessed. Each of these stops the run, removes what it created,
writes a report and **no receipt**. Names are read for every skill in the
surface, because selection is by name; everything else is checked for the
SELECTED skills only, so a broken neighbour that is not installed does not block
a treatment that does not include it.

- an unpinned or unresolvable revision; a skills root absent at it
- an empty surface ("empty discovery"), or a selected name not in it
- a symlink anywhere in the surface, or in the path from a snapshot down to its
  skills root (copying would follow it to wherever it points)
- unsupported layouts: a `SKILL.md` at the skills root, or a skill nested below
  a directory that is not one
- a `SKILL.md` that does not parse, or declares no name the client could list
- two skills with one name; two directories that collide case-insensitively, or
  one named like the client's own `.system` directory
- a required reference that is missing, or that points outside the skill: a
  relative Markdown link in the entry point, or a path captured by a declared
  `required_references` pattern. Equivalent spellings (`./scripts/x`) are
  normalized first
- a checksum-manifest mismatch, a listed file missing or outside the skill, or an
  empty manifest
- a client that alters an installed file
- an operational failure - an unreadable file, a missing workspace fixture - which
  is recorded as a refusal with its cleanup, never raised past the report

A **mention** of a path is not a requirement. Text that merely looks like a file
reference is a static finding in the report, and static findings never establish
or refute readiness: review.md rejects a general Markdown-link heuristic as
readiness proof, and the CPP run confirmed why - it refused sound skills for
naming files of the repository they document.

## Readiness, and what each fact can say

Every fact below is tested from both sides in `tests/test_materialize.py`, and
each guard was removed in turn to confirm its test goes red.

| Fact | SATISFIED when | VIOLATED when | UNKNOWN when |
|---|---|---|---|
| `discovery_canary` | every selected skill is listed from the file this run installed | an installed skill is not listed | the client is absent or cannot start, fails, times out, answers in an unparseable shape (including any listing row it does not recognize), or is not the pinned version |
| `baseline_absence` | the baseline lists nothing from outside the client's own `.system` directory, AND the control arm lists its planted skill | the baseline lists any skill from elsewhere - a treatment skill, or a differently named one leaking from another root | the control's planted skill was NOT listed - absence then proves nothing - or a client answer is unusable |
| `ordinary_parity` | outside the treatment, the arms list the same skills with the same descriptions, and all other client input - including text around and inside the listing block - is identical after replacing each arm's own path | any of it differs | a client answer is unusable |
| `source_unchanged` | the source fingerprint (HEAD, `git status`, and the CONTENTS of every dirty or untracked path; or the snapshot's digest) is identical before and after | it changed | git could not report the source state |
| `host_unchanged` | in every host client home in effect (`~/.codex` and any `$CODEX_HOME`), the skills tree, `config.toml` and `AGENTS.md` are identical before and after | they changed | a home could not be read |

`skillc materialize` exits 0 only when all five are SATISFIED. A receipt is still
written when one is not: a receipt whose canary failed is valid evidence
(records.md), but the exit code never lets it read as a ready install.

The canary is `codex debug prompt-input`, which renders what a session would be
given - including the skill list and the file behind each entry - without a
model call. It is a debug surface, so its shape is pinned with the client
version. A missing listing block is UNKNOWN, never "no skills", because the
client lists its own skills in every home. So is a second listing block, and any
line inside a listing section that is not a row the adapter recognizes: a skill
written in a shape the parser skipped would otherwise never reach the absence
check.

## Four facts, kept apart

The report's `observations`: `installed` (files and digests), `available` (the
canary), `invoked` (`NOT_OBSERVED` - no model runs) and `task_outcome`
(`NOT_APPLICABLE`). Evidence of one never fills in another. There is no
prompt-substitution path: if native installation fails, the run stops before the
client is ever asked, and nothing pastes instructions into a prompt instead.

## Isolation and cleanup

- The source is read with `git archive` at the pinned commit (or copied from a
  labelled snapshot) into controller-owned staging. `git status` runs with
  `--no-optional-locks`, so even the index is left alone. Dirty working-tree
  bytes are never installed as the commit.
- Each run creates one root with a random marker. `cleanup` removes only a root
  whose marker matches; it is safe to repeat and refuses anything else.
- Neither the disposable root nor the CLI's `--out` evidence directory may be
  inside the host's `~/.codex`, `~/.agents`, `~/.claude`, `$CODEX_HOME` or the
  source, resolved through symlinks. Evidence written into the source would
  change it after `source_unchanged` was taken.
- The client runs with an empty environment apart from `HOME`, `CODEX_HOME`,
  `PATH` and `LANG`, in its own process group, and the group is killed on
  timeout.

## Limits

- **One client, one layout.** Other clients (Claude Code, others) and layouts
  need their own tested adapter; they are refused, not approximated.
- **CI cannot run the real acquisition or canary.** The CI image has neither git
  nor Codex. CI exercises every rule through a fake client that answers in the
  observed shape; the git and real-client tests skip there and run on a host.
  The committed CPP evidence is the real client's answer.
- **The host binary.** The canary runs the host's `codex` against disposable
  homes. No agent and no model run, so ADR 0003's rule that launched agents run
  in the Docker lane does not apply; #10 moves the client into that lane.
- **The baseline has no receipt of its own.** The receipt contract requires a
  non-empty `installed`, and a baseline installs nothing. It is described in the
  report and summarized in `baseline_absence`; #12 decides how an experiment's
  baseline arm is recorded.
- **Readiness still does not gate a PASS.** Refusing a PASS built on an unready
  receipt is the assembler's rule (#9).
- **Fingerprints are narrow on purpose.** Host sessions and caches are excluded
  because other sessions write them continuously; a fingerprint that moves for
  unrelated reasons detects nothing.
