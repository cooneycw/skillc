# Installation profiles

- Status: Implemented as `skillc profile validate` (`skillc/profile.py`), #265
- Builds on: [materialization.md](materialization.md) (the subject declaration)
- Vocabulary: [protocol.md section 10.4](protocol.md) (#264) - treatment
  question `product`/`prose`, helper parity, `common`/`treatment` scope
- Next: #266 installs a validated profile into a disposable home and proves it runs

## Why a profile exists

A subject declaration pins WHICH skills are the treatment. When a skill's text
points at something the bundle does not carry - a host helper, a library in the
source checkout, a tool - the subject records it as `external-not-materialized`
and stops. That is an honest scope boundary, and it means the subject cannot
say what a working installation of a given workflow needs. A trial built on it
either fails for reasons that are not the skill's, or quietly borrows the
operator's own helpers.

A profile names those dependencies. It layers on one subject and declares, for
a selection of its skills, every helper, library, tool and startup context the
workflow reaches, the source each comes from at the pinned revision, and the
one place under the client's home it may be installed. `skillc profile
validate` walks that closure from the source and either returns a
content-addressed inventory or refuses with a named reason.

## What validation does

1. Reads the subject's pinned revision from a git checkout (`--repo`), or a
   directory standing in for it (`--snapshot`, labelled a snapshot, never a
   commit).
2. Runs the selected skills through materialize's own inventory: name parsing,
   selection, collisions, declared required references and checksums.
3. Walks the closure. Every text file reached - each selected skill's files,
   then each dependency's files - is scanned for the profile's declared
   `reference_patterns`. Each hit must resolve to a dependency that
   `satisfies` it, or to an `unsupported` entry with a reason. A satisfied
   dependency's own files join the walk, so a helper that sources a library
   pulls the library in: that is the transitive part.
4. Places every file at `destination/<path under source_root>` and refuses any
   destination outside `allowed_destinations` or claimed twice.
5. Checks declared byte mirrors (`mirrors`) and records declared transforms
   (`generated_from`).
6. Emits the inventory.

## The declaration

| Key | Meaning |
|---|---|
| `subject` | path to a `subject.json`, relative to the profile |
| `select` | a list of skill names (a **targeted** treatment) or `"all"` (the **full-pack** treatment); a different selection is a different treatment |
| `treatment_question` | `product` (the skill as installed, prose plus helpers) or `prose` (identical helpers in every arm) |
| `allowed_destinations` | relative roots under the client's home that may receive files |
| `reference_patterns` | regexes whose whole match is a reference, each with a `class`: `home-relative`, `variable-rooted` or `absolute` |
| `dependencies` | `helper`, `library`, `startup-context` or `tool` entries (below) |
| `unsupported` | references deliberately not supplied, each with a reason |
| `mirrors` | generated files that must be byte- and mode-identical to an upstream file |
| `generated_from` | generated files produced by a transform; both digests are recorded, freshness is not claimed |
| `declared_empty_kinds` | kinds with no dependency, named so "none" is a declaration |
| `client_profiles` | per client: `declared` (the subject's own client only) or `unsupported`, each with a reason |

A dependency has an `id`, `kind`, `scope` (`common` or `treatment`), and:

- for files: `source_root`, `paths` (files or directories under it),
  `destination`, `satisfies` (`{"reference", "path"}`; `path` is under
  `source_root`, or `null` for the destination root itself), and `traverse`
  (default true; false needs a `no_traverse_reason`);
- for a tool: `version` and `supply`, and no files - a tool is supplied by the
  environment, never installed from the source.

A dependency no reference reaches needs an `unreferenced_reason` (a tool run as
a command word, a startup file the client loads by itself).

## Refused by name

Each has a committed known-bad case in `tests/test_profile.py`, and each check
was disabled in turn to confirm its case goes red.

| Refusal | Why |
|---|---|
| empty selection | a profile of nothing would validate vacuously |
| missing reference | a skill's entry point links a file the bundle lacks (materialize's own rule) |
| missing helper / library | a dependency's source path is absent at the pin |
| missing library file | a reference resolves inside a dependency that does not carry that file |
| stale mirror | a generated copy's bytes or mode differ from its declared upstream |
| conflicting destination | two owners for one installed path, even with identical bytes, or a file overlapping a directory |
| unresolved reference | a pattern hit nothing satisfies and nothing declares unsupported - including one inside an unreferenced dependency (a startup file), which is walked after the referenced closure |
| home reference installed elsewhere | `~/x/y` satisfied by a dependency that installs at a different path under the home; an installer could not honour it |
| satisfied absolute path | an absolute path cannot be installed into a disposable home; it must be declared unsupported |
| destination outside allowed roots | an install target the profile did not permit |
| prose without helper parity | a `prose` question with a `treatment`-scoped dependency, or a non-Markdown file bundled in a selected skill with no common-scoped dependency carrying identical bytes (the expanded-instruction arm has no skill directory) |
| unreferenced dependency without a reason | padding, or a dependency the patterns cannot see, has to say which |
| untraversed tree without a reason | a hole in the closure may be deliberate, never silent |
| kind neither declared nor declared empty | "no startup context" is a statement, not an omission |
| no reference patterns | a walk with nothing to look for finds nothing, and that reads like a closed closure |
| a non-native client `declared`, or any `ready` status | a manifest cannot establish readiness or parity |
| a symlink the closure reaches | links are neither installed nor followed; one elsewhere in the source, including inside an unselected neighbour skill, is ignored |
| a linked skill directory or `SKILL.md` | it hides a skill's name, so discovery fails for every selection |

## What the inventory establishes, and what it does not

A home-relative reference is checked against where its dependency installs. A
`variable-rooted` one (`$SOME_DIR/...`) is checked only for the file existing in
the dependency: which directory the variable names at run time is the procedure's
probe order, and #266 observes it.

It establishes that, at this revision, the declared closure is closed: every
reference the patterns can see resolves, every installed file has a digest and
exactly one destination, and declared mirrors are current.

It does not establish:

- **installation**, or that any helper, library or tool runs - #266;
- **availability, invocation or outcome** for any client;
- **parity** for any client profile other than the declared one;
- **completeness beyond the patterns.** A reference no declared pattern
  matches - a computed path, an import, a command word - is invisible to the
  walk. That is why untraversed trees and unreferenced dependencies must say
  so, and why the `absolute` class has its own committed case.

## Generic by declaration

Nothing in `skillc/profile.py` names a subject. `tests/test_materialize.py`'s
genericity guard scans every `skillc/*.py` module, this one included, and
`test_an_unrelated_collection_validates_without_a_code_branch` declares a
different layout, helper home and dependency mix with no code change.

## Declared profiles

- [cpp-codex-flow-check](../../../evals/subjects/cpp-codex-flow-check/PROFILE.md) -
  CPP's generated Codex `flow-check` skill, targeted, product question.
