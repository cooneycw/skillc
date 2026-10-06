# Disposable git fixtures

- Status: Implemented in `skillc/git_fixture.py`, #275; synthetic local controls
- Builds on: #267 (declared surface versus whole fixture), #248 (workflow fidelity),
  [capture.md](capture.md) (controller-issued attempts)

## What it does

`build(declaration, root)` creates fresh git metadata in an existing empty
caller-allocated disposable directory. It never copies operator git state.
It returns a `BuildResult` with commit identities and caller-owned expectations.
`capture(experiment, attempt_id, repo, expected=result, worktree=result.worktree)`
checks the planned attempt and repository role, re-reads git state and records
facts through `Experiment.record` under its own `git-fixture-captured` event
(`trial.py`'s `_DETAIL_EVENTS`) - never the existing `workspace` event, whose
readers (`cleanup_workspace` and others) take the LAST such entry and index
straight into `entry["path"]`/`entry["nonce"]` with no guard; a capture
recorded under that name on an attempt that also allocated a real workspace
would be picked up as the workspace record and crash cleanup (confirmed
during review, fixed before merge). No CLI, Docker integration, remote access
or live trial is included.

## The declaration

The declaration is JSON serializable. File maps use relative paths mapped to
`{"hex": "<hex-encoded bytes>", "executable": false}`. Hex supports arbitrary
bytes without pretending JSON can directly encode Python bytes.

| Key | Meaning |
|---|---|
| `fixture_schema` | Version 1 |
| `commits` | Nonempty ordered commits: `message`, fixed `date` in `YYYY-MM-DDTHH:MM:SS+0000` format, `files`; writes overlay previous trees |
| `refs` | Full ref names mapped to zero-based commit indexes |
| `staged` | File map written and added after the stash |
| `unstaged` | File map written after staging, normally tracked modifications |
| `untracked` | File map written without adding |
| `ignored` | File map with root-relative entries in a generated `.gitignore` |
| `stash` | `staged` and `unstaged` file maps, applied before the final dirty state |
| `worktree` | Single sibling `name` and zero-based `commit` index; detached checkout |

Author and committer identities are fixed neutral literals. Commit and stash
creation dates come from the declaration. Identical declarations produce
identical commit SHAs across different disposable roots. No remotes are created.
A root is accepted only when empty, a stricter subset of empty-or-owned reuse;
rebuilding never overwrites a previous fixture.

## Refused by name

- `root-not-empty`, `linked-root`: root is not an existing empty directory or is a link
- `declaration-schema`, `empty-commits`, `fixed-date-required`, `file-mode`: unsupported declaration
- `unsafe-path`, `worktree-name`, `ref-name`: unsafe role or file names
- `wrong-repository-or-worktree`, `repository-shape`: wrong caller-owned role or git directory shape
- `absolute-path-leak`: an owned absolute path occurs anywhere in the facts,
  including nested values and keys

Git command errors during build stop construction. Capture reports each
observation separately: `satisfied` means read and consistent with expectations;
`violated` means read but inconsistent; `unknown` means that observation failed.
A declared file that disappeared is retained as `unknown`, because its bytes
and mode are unavailable. An omitted staged entry is `violated`, because a
successful index observation proves its absence.

## What it establishes and does not

HEAD, full ref mappings, index blob identities, working bytes and modes,
untracked and ignored inventories, stash working and index trees, and sibling
HEAD and pointer shape are observed separately from source bytes. File identities
use SHA-256 and git modes `100644`/`100755`. Stash reflog messages are never
captured; only object identities and trees are read. Pointer content is read
only to establish that it resolves inside the main repository's
`.git/worktrees/` directory. Its literal absolute path is never recorded.
The fact digest covers the complete canonical JSON payload before the digest
field is added, including the attempt ID. The journal is the existing attempt
binding mechanism, not a second log. Expectations must remain controller-owned.

This establishes declared git facts at capture time. It establishes nothing
about real operator repositories, GitHub state or agent behavior. It does not
prove temporal preservation without events; #276 and later work own those claims.

## Known limits

Every git call uses one helper with an allowlisted environment, disposable HOME
and XDG config home, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`,
`GIT_TERMINAL_PROMPT=0` and file-only protocol permission. Fixed identity and
`commit.gpgsign=false` are command overrides; init uses `--template=`.
Inherited git-directory, config-injection and credential variables are excluded.
The config-isolation boundary covers git's own config resolution. It cannot
sandbox an arbitrary pre-commit hook doing unrelated work. The hooksPath
control proves that operator hooks are not loaded, by temporarily removing
isolation and observing the planted hook execute. Disposable metadata must
remain trusted; this is not containment of adversarial local git configuration.

Capture is not an atomic snapshot under concurrent writes. Rename, merge-conflict,
submodule, symlink and multi-stash workflows are outside this bounded declaration.
The tests exercise a regular-file, single-stash fixture and one detached sibling.
No service effects or network operations are supported.
