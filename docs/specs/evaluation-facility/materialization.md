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
| `external_references` | patterns for references the bundle makes to things it does not carry |

Unknown keys are refused: an unread key is a convention its author believes is
honoured. `test_the_adapter_names_no_subject` fails if a subject's conventions
reach a string literal in the adapter, and is shown able to fail on a planted one.

## Refused by name

Nothing here is guessed. Each of these stops the run, removes what it created,
writes a report and **no receipt**:

- an unpinned or unresolvable revision; a skills root absent at it
- an empty surface ("empty discovery"), or a selected name not in it
- a symlink anywhere in the surface (copying would need an immutable target and
  a closure this adapter does not record)
- unsupported layouts: a `SKILL.md` at the skills root, or a skill nested below
  a directory that is not one
- a `SKILL.md` that does not parse, or declares no name the client could list
- two skills with one name; two directories that collide case-insensitively, or
  one named like the client's own `.system` directory
- a required reference that is missing: a relative Markdown link in the entry
  point, or a path captured by a declared `required_references` pattern
- a checksum-manifest mismatch, a listed file missing, or an empty manifest
- a client that alters an installed file

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
| `discovery_canary` | every selected skill is listed from the file this run installed | an installed skill is not listed | the client is absent, fails, times out, answers in an unparseable shape, or is not the pinned version |
| `baseline_absence` | the baseline lists no treatment skill and nothing outside the client's own `.system`, AND the control arm lists its planted skill | the baseline lists a treatment or foreign skill | the control's planted skill was NOT listed - absence then proves nothing - or a client answer is unusable |
| `ordinary_parity` | the arms' skill listings match outside the treatment, and the rest of the client input is identical after replacing each arm's own path | either differs | a client answer is unusable |
| `source_unchanged` | the source fingerprint (HEAD and `git status`, or the snapshot's digest) is identical before and after | it changed | - |
| `host_unchanged` | the host client's skills tree, `config.toml` and `AGENTS.md` are identical before and after | they changed | - |

`skillc materialize` exits 0 only when all five are SATISFIED. A receipt is still
written when one is not: a receipt whose canary failed is valid evidence
(records.md), but the exit code never lets it read as a ready install.

The canary is `codex debug prompt-input`, which renders what a session would be
given - including the skill list and the file behind each entry - without a
model call. It is a debug surface, so its shape is pinned with the client
version; a missing listing block is UNKNOWN, never "no skills", because the
client lists its own skills in every home.

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
- A root may not be created inside the host's `~/.codex`, `~/.agents`,
  `~/.claude`, `$CODEX_HOME` or the source.
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
