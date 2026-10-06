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

## Human-only real-pin proof (run, not merely documented)

This has been RUN once, by hand, against a real `git clone` of
`github.com/cooneycw/claude-power-pack` from GitHub at the subject's pin
(never a host checkout - #266's orchestrator review required that
distinction). Evidence: `evidence/install-receipt.json` (63 files, scrubbed
of any absolute host path by `install()`'s own design - `"home": null`).
Running the sequence is the evidence; this is not a claim about code that
was only written and never executed.

```text
skillc profile install evals/subjects/cpp-codex-flow-check/profile.json \
    --repo <real claude-power-pack checkout, cloned from GitHub> \
    --home <disposable dir> --out evidence/install-receipt.json
# -> 63 files installed, 4 tools checked (all `unknown`: the real profile's
#    tool ids are labels - tool-python, tool-uv, tool-pypi-runtime,
#    tool-make-git-bash - not bare executable names; literal PATH lookup
#    correctly finds none of them, see PROFILE.md's Known limits)

env -i HOME=<disposable dir> PATH=/usr/bin:/bin:/usr/local/bin \
    uv sync --locked --project <disposable dir>/Projects/claude-power-pack
# -> resolved and installed pydantic/pyyaml; needed network for the first
#    resolve (no cache was pre-supplied) - a genuinely network-less trial
#    would need one or must report this step unavailable

env -i HOME=<disposable dir> PATH=/usr/bin:/bin:/usr/local/bin \
    uv run --locked python -c "import lib.cicd; import lib.security"
# -> IMPORT OK: the library imports cleanly in the disposable home

env -i HOME=<disposable dir> PATH=/usr/bin:/bin:/usr/local/bin \
    FLOW_GATE_CPP_DIR=<disposable dir>/Projects/claude-power-pack \
    bash -c 'cd "<tiny fixture project>" && exec <disposable dir>/.claude/scripts/flow-finish-gate.sh'
# -> the REAL lib.cicd runner ran (not the Makefile fallback), produced a
#    structured plan report, reached FLOW_FINISH_GATE: warn, exit 3 (a
#    fixture this trivial has nothing a test/lint runner recognizes - an
#    honest qualified result, not a failure of the installed path).
# NOTE: CPP_DIR (as written in an earlier draft of this section) is not the
# variable the helper reads - FLOW_GATE_CPP_DIR is, and without it the
# helper's own default search needs a CLAUDE.md marker this profile does
# not install, so it silently degrades to the Makefile fallback instead of
# exercising lib.cicd at all. See PROFILE.md's Known limits.
```

Fake-operator-home ambient control, both directions: a THROWAWAY directory
(never the real operator $HOME) was seeded with decoys at the profile's
relative paths (`.claude/scripts/flow-finish-gate.sh` printing a distinctive
sentinel and exiting 99, and `Projects/claude-power-pack/CLAUDE.md`).
Negative control: the real sequence above, run with `HOME` at the legitimate
disposable dir, produced zero occurrences of the sentinel anywhere in its
output. Positive control: the identical helper invocation, run with `HOME`
pointed AT the fake operator home instead, produced exactly one occurrence -
proving the sentinel check itself is not blind.

Missing-helper red case: `GitTree` reads a pinned revision's git-committed
blobs via `git cat-file`, never a working tree, so deleting a file from a
checked-out working tree changes nothing it returns for that commit. The red
case instead used a plain-directory snapshot of the real pinned tree
(`git archive <pin> | tar -x` into a directory, confirmed to install
identically to `--repo` first), then deleted `scripts/flow-finish-gate.sh`
from that snapshot and re-ran `skillc profile install --snapshot`:
`REFUSED - missing helper helper-flow-finish-gate: scripts/flow-finish-gate.sh
is absent from the source`, exit 2, nothing written to the home directory.

What this does NOT prove: absolute operator-home reads by the helper's own
code are unobserved (strace is unavailable in the implementation
environment, stated as a boundary, never assumed covered), and no container
isolation was attempted or claimed. A separate cold-container run with no
operator skill, home, MCP, or secret mounts is still required for acceptance
item 2.
