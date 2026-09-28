# Level 3 task: slugkit installed (#13)

A fix that passes a visible unit test must ALSO work when the package is
actually installed and invoked through its real consumer - packaging,
import paths, entry-point wiring or data files can break it even when the
unit test passes. This is #13's own reframing of "a real installed
consuming path": a property of the CANDIDATE's code, not of whether an
agent consulted an installed skill (that is skill consumption, already
measured by #26/#150's own controls - a code-execution canary here would
also put candidate code in the grader's path, which this task's whole design
avoids).

| File | Role |
|---|---|
| `goal.md` | The agent-facing request. States the bug, the replacements-table requirement and the two-graded-ways rule - every requirement is PUBLIC |
| `fixture/` | Pinned starting state: a tiny installable-in-name package (`pyproject.toml`, `slugkit/`, `tests/`) carrying the same trailing-hyphen bug |
| `grader.json` | Grader definition: `functional-trailing-hyphen`, `integration-installed-path` |
| `probe.py` | Runs the visible unit test AND the installed-path check (via the emulation or real-pip modes below). The only grading code that runs candidate code |
| `inputs.json` | goal.md's own worked example plus one held-out input, for the installed-path check |
| `grade_slugkit.py` | The judge: holds every expected value, including the held-out one. Never shown to the agent |
| `reference/`, `alternatives/apply-first` | Correct outcomes, differently shaped |
| `wrong/scratch-copy`, `wrong/stale-data`, `wrong/renamed-entry-point` | Each passes the visible unit test and fails `integration-installed-path`, for a different reason |
| `*/expected.json` | Each candidate's required status and the exact criteria it must violate |
| `grader-controls/` | Broken graders: always-pass, always-fail, crash, no-output, omits-criterion (the last drops `integration-installed-path` specifically - #13's own acceptance line, "a passing unit test must not imply installed-path success", is exactly what a grader missing that criterion would violate) |
| `qualify.py` | Certification gate, copied from Level 1's generic harness (`REQUIRED_CRITERIA` and the candidate-validity check - `pyproject.toml` instead of `src/slugify.py` - differ) |
| `check_real_pip_mode.py`, `fixtures/fake-pip/` | A separate, standalone proof that the OPTIONAL real-pip upgrade path and its mode-selection branch work - not part of `qualify.py`'s own gate. See "The two grading modes" below |

```bash
uv run python evals/level3/slugkit-installed/qualify.py       # QUALIFY: ok, exit 0
python3 evals/level3/slugkit-installed/check_real_pip_mode.py  # separate proof, see below
```

## The two grading modes for `integration-installed-path`

**`stdlib-emulation` - the PRIMARY mode, and the only one that runs in this
repository's real environment today.** Checked directly, 2026-09-28: neither
pip nor any build backend is importable in this dev venv (`import pip`,
`setuptools`, `hatchling`, `wheel`, `build` all fail), and
`docker/trial/Dockerfile` (the #78 trial/grading container) installs only
`ca-certificates git python3` via apt - no `python3-pip`, no `python3-venv`.
So a mandatory criterion whose only grading path needed pip would be
UNKNOWN on every attempt everywhere, and `qualify.py` could never certify
this task at all (rejected during review - see the PR body). Instead,
`probe.py` reads the candidate's `pyproject.toml` with `tomllib` (stdlib)
for its declared package directories and `[project.scripts]` target, copies
ONLY those declared directories into a fresh temp "site dir" - nothing
else, no undeclared file, even if one exists in the candidate tree - and
invokes the console-script target in a fresh interpreter with only that
site dir on `sys.path`. This is honestly named in the evidence
(`mode=stdlib-emulation: ...`), never worded as if a real pip/wheel build
happened.

**What the emulation does NOT cover, versus a real pip install / wheel
build:** real build-backend configuration correctness (MANIFEST/
include-exclude rules beyond the one declared-packages/package-data
convention this emulation reads), dependency resolution, and any compiled
extension handling. This is a deliberate, named trade-off, not a silent
gap.

**`real-pip` - the OPTIONAL, secondary mode.** When `python -m pip
--version` succeeds AND the declared backend module is importable,
`probe.py` instead runs a real, offline `pip install --no-index
--no-build-isolation --target SITE_DIR CANDIDATE_DIR` and invokes the entry
point the same way - the evidence names `mode=real-pip` explicitly, so a
report never conflates the two modes. Since pip is absent everywhere this
repository runs today, this mode never actually fires in a real
`qualify.py` run here; what can and must be proven instead is that the
MODE-SELECTION branch itself is correct. `check_real_pip_mode.py` does
this: it runs `probe.py` twice against `reference/`, once with nothing
special on `PYTHONPATH` (confirms `stdlib-emulation` fires, the honest
default) and once with `fixtures/fake-pip/` prepended to `PYTHONPATH` (a
committed, controllable fake `pip`/`hatchling` - the same fault-injection
convention `tests/fixtures/docker-backend/fake_docker.py` already
establishes, adapted for a MODULE rather than a PATH-resolved CLI, since
that is what `probe.py` actually invokes) - confirms `real-pip` fires
instead, still produces the correct output, AND still correctly excludes
`wrong/scratch-copy`'s undeclared fix. This is a real proof of the branch
and of the real-pip install logic's own selective-copy behaviour, not a
completed real install (the fake pip's own `install` implementation copies
declared packages the same way the emulation does - it is a test double for
the CLI surface, not a claim that a real pip run was performed).

## Which environments this grade is valid in

**Today: this dev venv, via the `stdlib-emulation` mode.** Nothing the
emulation does depends on anything beyond `python3` itself, so there is no
reason to expect it to behave differently in the #78 trial/grading
container - but that container's own `qualify.py` run has not been
performed as part of this PR (no image changes, no CLI wiring - out of
scope; see below). A real pip-based grade (stronger coverage - see "does
NOT cover" above) is possible only once a platform's environment gains pip
and a build backend, which is explicitly out of scope here.

## Held-out variation

`inputs.json`'s second entry, `"user@host"`, exercises a replacements-table
entry (`"@"` -> `"at"`) goal.md's own worked example (`"Rock & Roll!"`,
which uses `"&"`) never shows - chosen so it only comes out right if the
REAL shipped `slugkit/data/replacements.json` is read, which is exactly
what `wrong/stale-data` gets wrong: its unit test genuinely passes (the
visible example needs no replacements table at all), while its installed
path is wrong on this one held-out input.

## What qualify.py proves, and its red cases

| Gate input | Required verdict | Observed |
|---|---|---|
| `fixture/` (unfixed start) | FAIL | FAIL (`functional-trailing-hyphen`, `integration-installed-path` - goal.md's own worked example now carries a trailing `!`, so it exercises the base bug through BOTH grading paths, not only the unit test) |
| `reference/`, `alternatives/apply-first` | PASS | PASS |
| `wrong/scratch-copy` (fix applied to an undeclared `scratch/` copy; the visible test was rewritten to test IT instead) | FAIL | FAIL (`integration-installed-path` only - `functional-trailing-hyphen` SATISFIED, since the rewritten unit test genuinely passes) |
| `wrong/stale-data` (`core.py` fixed correctly; shipped `replacements.json` left stale) | FAIL | FAIL (`integration-installed-path` only, on the held-out `"@"` case specifically) |
| `wrong/renamed-entry-point` (entry function renamed; `pyproject.toml`'s target never updated) | FAIL | FAIL (`integration-installed-path` only - a clean `install_error`, never a probe crash) |
| `always_pass` grader | refused, PASS throughout | refused: fixture and every wrong/* PASS |
| `always_fail` grader | refused, FAIL throughout | refused: reference and alternatives FAIL |
| `crash` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `no_output` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `omits_criterion` grader (drops `integration-installed-path`) | refused, INCONCLUSIVE throughout | refused: the report lacks a required criterion |

No live model call was made to build or certify this task.

## Scope

`#13` stays open after this PR for its "compare matched configurations" and
"report separately" acceptance items, which are owed to an actual run
through `collection-run`/`agent_trial` - explicitly out of scope here (no
CLI wiring, no live runs, no trial-image or `pyproject.toml` dependency
changes to this repository itself).
