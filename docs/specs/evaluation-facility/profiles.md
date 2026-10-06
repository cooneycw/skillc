# Installation profiles

- Status: Implemented as `skillc profile validate` (`skillc/profile.py`), #265
- Builds on: [materialization.md](materialization.md) (the subject declaration)
- Vocabulary: [protocol.md section 10.4](protocol.md) (#264) - treatment
  question `product`/`prose`, helper parity, `common`/`treatment` scope
- #266: host-filesystem installation, digest receipts and installed drift checks
  delivered with synthetic consuming-path controls. Cold-container execution
  (acceptance item 2) remains owed to a Docker-capable run.

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
probe order. The synthetic #266 control observes its installed consuming path;
the real pinned helper proof remains owed.

It establishes that, at this revision, the declared closure is closed: every
reference the patterns can see resolves, every installed file has a digest and
exactly one destination, and declared mirrors are current.

It does not establish:

- **execution readiness**: installation is checked separately below; the real
  pinned helper, external package resolution and cold-container proof remain owed;
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


## Host installation (#266)

`skillc profile install PROFILE --repo CHECKOUT --home HOME --out RECEIPT`
revalidates the live pinned source, preflights all destinations, installs exact
bytes and modes, and re-reads every installed file before emitting a receipt.
`--snapshot` substitutes a labelled directory snapshot. The home must already
exist. Different pre-existing bytes are refused; identical bytes are recorded
in `preexisting` and their mode is normalized. `--overwrite` replaces only the
output receipt, never permits overwriting conflicting installed bytes.

The receipt binds the inventory's `installed_surface` digest to an exact file
list and carries its own canonical SHA-256 digest. Unsupported references and
client declarations remain explicit. Destinations are home-relative. A relative
caller-supplied home is recorded verbatim; an absolute home is omitted rather
than leaking host identity. `verify_installed(inventory, home)` re-reads the full
population: byte or mode drift is `violated`, missing/unreadable is `unknown`.

Tools are supplied, never installed. Their IDs are looked up literally on PATH.
Numeric operator-plus-dotted-version constraints (optionally followed by a
parenthesized explanation) are compared as padded numeric tuples. `any` or no
constraint accepts a found executable. Missing tools, unsupported constraints
and failed probes report `unknown` with a reason; mismatches report `violated`.
This uses the project's satisfied/violated/unknown vocabulary rather than
introducing a fourth `missing` state. Tool problems remain visible in receipts
and the CLI summary; file verification failure refuses receipt publication.

The historical real profile uses labels such as `tool-python`, grouped tool
entries, and external package declarations. These are not bare executable
names. No mappings or package installations are guessed: literal lookup reports
unknown/missing, and no real readiness claim follows. Historical pins and
profile declarations are unchanged. Baseline task readiness requires no profile;
installation readiness is a separate treatment-specific fact.

The committed `tests/fixtures/profile-install` snapshot and
`tests/test_profile_install.py` exercise executable preservation, installed
helper-to-library resolution, missing dependencies, version mismatch, a fake
operator-home decoy, conflicts, identical files and subsequent drift/deletion.
Host tests do not contain absolute reads, inherited secrets, PATH binaries or
external caches. They do not satisfy the cold-container acceptance item.

## Human-only real-pin proof owed (not wired into tests)

The following is documented intent, not an automated test or an isolation claim.
Use the already available checkout at the subject's historical pin, a disposable
home, a tiny project with declared gate inputs, and a separate fake operator
home. Never seed the operator's actual home. Place distinctive decoys at the
fake home's `.claude/scripts/flow-finish-gate.sh` and
`Projects/claude-power-pack` paths. Record observed consuming paths and limits.

```text
skillc profile install evals/subjects/cpp-codex-flow-check/profile.json \
    --repo <claude-power-pack checkout> --home <disposable dir> \
    --out evidence/install-receipt.json

env -i HOME=<disposable dir> PATH=<minimal tool PATH> \
    uv sync --locked --project <disposable dir>/Projects/claude-power-pack

env -i HOME=<disposable dir> PATH=<minimal tool PATH> \
    CPP_DIR=<disposable dir>/Projects/claude-power-pack \
    bash -c 'cd "<tiny fixture project>" && exec "$HOME/.claude/scripts/flow-finish-gate.sh"'
```

Exact gate arguments and project inputs must be confirmed against the pinned
helper by the human operator. This host procedure, even with `env -i`, cannot
prove that the helper avoids absolute operator-home reads. strace is unavailable
in the implementation environment. A separate cold-container run with no
operator skill, home, MCP, or secret mounts is still required for acceptance item 2.
Locked package resolution requires external access or a prefilled cache; neither
is supplied by this installer. No real pinned-revision proof has run here.
