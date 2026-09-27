# The operator demo (#81, Refs #10)

- Status: proven against the fake `docker` CLI
  (`tests/fixtures/docker-backend/fake_docker.py`), and run live by the
  operator at `8e06030` on 2026-09-27: all four commands exited 0 with every
  item MET (https://github.com/cooneycw/skillc/issues/10#issuecomment-5855368984). What that run did and did not cover is recorded in
  [support-matrix.md](support-matrix.md).
- Governing documents: [support-matrix.md](support-matrix.md) (restated
  after that live run, from its results), [interfaces.md](interfaces.md)
  (the backend seam this command drives through).

## Evidence rule

**#10 closes only on the operator's own live run of this command against a
real Docker daemon, never on this repository's tests going green.** Every
test for `skillc demo` runs against the fake `docker` CLI fixture
(`tests/test_demo.py`, `tests/test_docker_backend.py`); the real daemon
boundary is unverified until an operator actually runs it. When that run
happens, its paste-back block is what gets recorded in
[support-matrix.md](support-matrix.md) - never a description of what the
code is expected to do.

## Before you run

From a clean clone:

```bash
git clone https://github.com/cooneycw/skillc.git
cd skillc
uv sync --extra dev            # or: uv tool install .
docker build -t skillc-trial:latest docker/trial/
```

The image build is one of issue #78's own live checks, not a formality:
`verify_codex_sidecar.js` runs inside it, right after the pinned npm
installs, and fails the BUILD (never a later trial) if the real Codex CLI's
`codex-code-mode-host` sidecar is missing - a `docker build` that exits
non-zero here has already found a real problem, before `skillc demo` is ever
invoked. `docker/trial/check_interpreters.py` is the equivalent no-daemon
control for the interpreters the demo and verifier run inside the container
(issue #78, Refs #81): it is exercised by this repository's own test suite
against the committed Dockerfile, so a missing interpreter is caught without
building anything at all.

## What to run

```bash
skillc demo
```

No arguments are required: it uses the ambient `docker` on `PATH`, the
`skillc-trial:latest` image, and a temp directory for its disposable trial
root. Flags, all optional:

| Flag | Default | Meaning |
|---|---|---|
| `--image <ref>` | `skillc-trial:latest` | the trial image to run |
| `--docker-bin "<words>"` | `docker` | the docker executable, space-separated if it needs more than one word |
| `--base <path>` | `$TMPDIR` | where the disposable trial root is created |
| `--timeout <seconds>` | `30` | per-container-call timeout |
| `--subject [<name>]` | off (omit entirely to skip) | install `evals/subjects/<name>` into a real container's home too (issue #101, see below); bare with no name uses `skillc.demo.DEFAULT_SUBJECT` |
| `--control` | off | run the seeded negative controls instead (see below) |

Exit codes: `0` success (or, under `--control`, every seeded failure was
caught); `1` at least one acceptance item was not met (or, under
`--control`, at least one seeded failure was NOT caught); `2` the assembled
paste-back block failed its own leak-check and was refused - nothing is
printed in that case, by design (see "What it never prints" below).

## What it does

Two independent, real-Docker-backed demonstrations, no paid model call at any
point:

1. **The lifecycle demo** - one attempt through the real driver
   (`lifecycle.run_through_backend`) against a real `DockerBackend`, with a
   trivial scripted subject (a `python3 -c ...` one-liner, never an agent
   CLI). This proves prepare/install/execute/confirm_stopped/export/destroy/
   confirm_absent all work against a real daemon, using the driver's own
   already-working liveness canary (a planted file's content, read back after
   export - never a transcript).
2. **The grading demo** - a second, independent `DockerBackend` instance
   grades a candidate through `verify.grade_files(..., backend=...)` (#76),
   against the already-certified `evals/level1/slug-small-fix` task.

Around both, it snapshots the fleet (every container the daemon reports,
partitioned by ownership label) and a fixed set of host paths
(`pyproject.toml`, `README.md`) before and after, reaps its own attempt(s)
through the independent label-scoped sweep (#79), and records the image
digest that actually ran (`docker image inspect --format {{.Id}}`, never a
claim from the `--image` string alone, which could be a floating tag).

### Why no real agent, in THIS command's own two demos

A real Claude Code `Write` tool result, and a real Codex `exec` result alike,
typically confirm only that a file was written, never echoing its content
back - so a transcript-based liveness check that requires a `tool_use`
event's output to literally carry a nonce is red against an unmodified real
transcript from either client. `skillc/agent_trial.py` (issue #106) is the
driver that resolves this end to end - per-client transcript adapters
(#107), the credential and seed delivery, and the liveness canary unified
onto lifecycle's own backend-planted nonce (#108) - and is fully built and
merged. It is a SEPARATE entry point from `skillc demo`, not a mode of it:
this command's own lifecycle and grading demos above still use a trivial
scripted subject and the driver's plain file-content canary, which has no
write-doesn't-echo-content gap to begin with, so there is nothing here for
`agent_trial.py` to fix. The Level 1 agent run per collection this issue's
own remaining acceptance bullet needs is a separate demonstration, prepared
below.

## `--subject`: installing a declared skill collection into a real container

A THIRD demonstration, alongside (never replacing) the two above, so this
command and this runbook serve as the second-collection evidence issue #11
asks for too:

1. **Install.** The declared collection is acquired from its pinned revision
   (a real `git` clone, archived at that exact commit) and every selected
   skill's files are copied into the container's home, at
   `/home/candidate/.codex/skills/<skill-directory>/...` - never bind-mounted,
   never into `/work`. A `--subject` whose `select` names a skill absent from
   the collection is refused before any Docker work starts.
2. **In-container digest re-check.** Every installed file's CURRENT bytes are
   read back out of the running container and re-hashed - "landed intact" is
   an observation, never an assumption from the install call alone. A
   mismatch names the file.
3. **Discovery.** The client's own listing (`codex debug prompt-input`, the
   same argv convention `skillc.exposure`'s Codex arm already uses) runs
   INSIDE the container via `execute()`, with no model call. Each selected
   skill is reported `discovered` or `not-discovered`. If the listing cannot
   complete at all (a launch failure, a crash, an empty or unparseable
   output), every selected skill is reported `UNMEASURED` with the reason -
   never dropped, and the overall exit is non-zero.
4. The same host-paths-unchanged check and reap sweep as the rest of the
   demo cover this leg's own container too, with the same four distinct
   outcomes.
5. The paste-back gains one additional block, per subject: name and pinned
   revision, the installation receipt (skill count, file count), the digest
   check, the discovered/not-discovered/UNMEASURED list, host-paths-unchanged,
   and the reap outcome - leak-checked before printing, exactly like the rest
   of the block.

**What this shows, and what it does NOT show:**

> It shows that the pinned collection installs intact into a real container
> and that the client can see it. It does not show that any skill is invoked
> or selected, changes behaviour, or helps. Those are #26 (selection) and #12
> (the matched pilot), which need a model. A green demo is not evidence about
> the skills.

**Where each subject's files land, and their pinned revisions** (see
`evals/subjects/<name>/subject.json` for the authoritative declaration):

| Subject | Pinned revision | Source `skills_root` | Selected | Lands under |
|---|---|---|---|---|
| `cpp-codex` | `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` | `codex/skills` | all (74 skills) | `/home/candidate/.codex/skills/<skill>/` |
| `mattpocock-skills` | `c55ee46073ed923f86ce59a5eb3b6d895095d1b7` | `skills/engineering` | `tdd`, `diagnosing-bugs` | `/home/candidate/.codex/skills/<skill>/` |

The default (`--subject` with no name) is `skillc.demo.DEFAULT_SUBJECT`, read
from `evals/subjects/DEFAULT_SUBJECT` (one line, data) rather than a literal
in `skillc/demo.py` - the genericity guard (issue #11's "no subject-name
branch anywhere in skillc/", `tests/test_materialize.py`) AST-scans every
`skillc/*.py` module and would otherwise flag a hardcoded default the moment
it landed.

## The Level 1 agent run per collection (#11's remaining acceptance bullet)

**Run live on 2026-09-27, once per collection: both captured, both graded
PASS, and the missing-credential control `unavailable`.** The output is in
[`evals/second-collection-conformance/evidence/README.md`](../../../evals/second-collection-conformance/evidence/README.md).
A re-run on a later commit is new evidence, not a replay of that run.

Three defaults changed after the first live attempts, which never reached a
model:

- **Network.** The agent container now runs on Docker's bridge network, so the
  client can reach its provider. This follows the owner's ruling recorded on
  #11: "i'm fine for a container (controlled by what we place into it) to have
  network access. i'm not going to submit hostile repos". The grading
  container keeps `network=none`. The paste-back prints `agent_network=`.
- **Git check.** The default client argv adds `--skip-git-repo-check`. codex
  refuses to start in the non-git `/work` without it.
- **Timeouts.** `--agent-timeout` (default 900 s) bounds the agent.
  `--timeout` bounds each docker call only; it used to bound both, which would
  have stopped a real agent after 30 s.

Each run also works in its own `skillc-collection-run-<subject>-*` directory
under `--base`. The checkout and staging copies are removed afterwards and the
store, which is the evidence, is kept.

`--subject`'s own three legs above (install, digest re-check, discovery)
prove the collection lands intact and the client can see it - explicitly
NOT that any skill is invoked, selected, or helps (see "What this shows,
and what it does NOT show" above). Issue #11's own remaining acceptance
bullet - "the same client, Level 1 fixture, contract and grader" - is
`skillc collection-run <subject>` (`skillc/collection_conformance.py`),
which drives one actual agent attempt through `skillc/agent_trial.py`
(#106), once per collection (`cpp-codex`, `mattpocock-skills`), against
`evals/level1/slug-small-fix`, on the client each subject's own declaration
names (`codex`, codex-cli `0.157.1` for both). It installs that
collection's declared, selected skill files into the SAME container the
agent runs in - `agent_trial.run_one_attempt`'s own `extra_home_files`
parameter (issue #11) - so a spontaneous skill invocation is genuinely
possible, not merely plumbed through.

```bash
SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run cpp-codex
SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run mattpocock-skills
```

The canary instruction runs in `agent_trial.py`'s SKILL-FREE mode (naming no
skill): #11 measures collection conformance, not skill selection - #26's
own job - and a canary instruction that names a skill would contaminate
exactly the measurement #26 needs to make later. Whatever the agent invokes
on its own is still observed (`skill_invocations`), never hidden by the
canary's own indifference to it - a first, informal signal for #26, not its
answer.

Funding basis for the agent run itself, quoted verbatim rather than
paraphrased ([ADR 0005](../../decisions/0005-runtime-scope-and-cost-rulings.md)
rule 6, owner ruling 2026-09-27): **"Normal Claude and codex"** - the
operator's own normal Codex subscription login, inside the normal usage
budget, not metered API spend and not gated by the $5 judge-call ceiling
(rule 5), which covers judge calls only. Gated behind
`SKILLC_ALLOW_REAL_AGENT=1` (`lifecycle.py`'s own structural guard against
an accidental real launch); `collection-run` adds no gate of its own.

The prompt and starting fixture are the task's own fixed data, never
invented by this command: `evals/level1/slug-small-fix/goal.md` verbatim
(#5's own "agent-facing request, identical for every arm"), and
`fixture/src/` installed into the workspace - never the sibling
`fixture/expected.json`, the grader's own ground truth for it, which would
hand the agent the answer key.

Paste-back shape, per collection: `disposition`, `prompt_delivered`,
`canary_satisfied`, `graded.status`, `refresh_observed_in_container`, and
`skill_invocations`/`skill_invocation_detection` (issue #26: every skill
name the transcript shows invoked, and whether that client's own detection
is `structural` or `heuristic` - `heuristic` for Codex, since it has no
native skill-invocation marker of its own) - leak-checked before printing,
exactly like the rest of this command's own block. Control, proven against
the fake docker (`tests/test_collection_conformance.py`): a run with the
credential deliberately absent reports `disposition == "unavailable"`
(BLOCKED before the agent ever launches, no container remains), matching
`skillc/agent_trial.py`'s own existing acceptance for a missing credential.

## How long it takes

Two container lifecycles (create, install, execute, export, destroy) plus one
reap sweep and two fleet snapshots - on the order of the same daemon
round-trip cost `docker_backend.py`'s own tests already exercise per
lifecycle, times two. No model call is made, so there is no token-spend
latency to budget for. `--subject` adds a third container lifecycle, a git
clone of the collection's source, and one `deliver_home_file` call per
installed file (74 skills' worth of files for `cpp-codex`, so this leg is the
slowest of the three by a wide margin) - still no model call.

## Reading the paste-back block

```
skillc operator demo - paste-back block
skillc_version=<version> source_commit=<sha> dirty=<bool>
image=<image> image_digest=<digest or UNKNOWN>

acceptance:
  [MET|NOT MET] full Docker trial lifecycle (prepare..confirm_absent) - lifecycle disposition=<...>
  [MET|NOT MET] grades through the verifier's backend seam (#76) - grading status=<...>, detail=<...>
  [MET|NOT MET|NOT EXERCISED] cleanup sweep confirms no owned container left running - reap outcomes=[...]
  [MET|NOT MET|NOT EXERCISED] declared host paths unchanged - changed=[...], unresolved=[...]
  [MET|NOT MET] image digest recorded - digest=<...>

cleanup (reap outcomes, four possible values: reaped/already-absent/left-running/unknown):
  <attempt_id>: <outcome>
  daemon_reachable=<bool>

subject: <name> revision=<pinned sha>
  installed: <N> skill(s), <M> file(s)
  digest_check: matched|mismatched [mismatched=[...]]
  discovery: {<skill>: discovered|not-discovered|UNMEASURED, ...} [(UNMEASURED: <reason>)]
  host paths unchanged: changed=[...], unresolved=[...]
  cleanup (reap outcomes):
    <attempt_id>: <outcome>
    daemon_reachable=<bool>
```

When acquisition or `prepare()` never even reached the container step
(issue #118), the `subject:` block instead reads:

```
subject: <name> revision=<pinned sha>
  NOT EXERCISED: <reason>
```

and all five of that leg's own acceptance lines read `NOT EXERCISED` too,
with `<reason>` as their evidence - never a guessed MET/NOT MET for work
that never started.

The `subject:` block is present only when `--subject` was given; its own
acceptance lines (installed skills match the declared selection, digests
match, every selected skill discovered) appear in the `acceptance:` section
above, prefixed `subject '<name>':`, exactly like every other line there.

- **`skillc_version`/`source_commit`/`dirty`** - `skillc/provenance.py`'s
  stamp of what actually ran. `dirty=true` means the checkout that produced
  this run had uncommitted changes - paste it back anyway, but say so.
- **Each acceptance line** - `MET`, `NOT MET`, or (cleanup and host-paths
  only) `NOT EXERCISED` - with its own evidence string. `NOT EXERCISED`
  (issue #118) means the check never ran at all, because `prepare()` never
  succeeded: with no container ever created, "no container left running"
  and "host paths unchanged" are true only because nothing happened, which
  is a different claim from a demo that actually ran cleanly, and is never
  reported as `MET`. A `NOT MET` line is the first thing to read closely,
  not a summary count.
- **`cleanup`** - one line per reaped attempt, naming which of the four
  distinct outcomes applied. `reaped` and `already-absent` are both fine
  (the second means teardown already worked and the sweep found nothing to
  do); `left-running` and `unknown` are not, and mean the daemon confirmed a
  container is still there, or could not be asked at all, respectively -
  never collapsed into each other.
- **`daemon_reachable`** - `false` here means the reap sweep itself could not
  ask the daemon at every step; do not read the outcomes above as clean
  cleanup if this is `false`.

## What it never prints

The whole block is run through `skillc leak-check`'s own scanner
(`skillc.leak.scan_text`, in memory - no file round-trip) before it is
printed. If anything is found, nothing is printed at all: the command exits
`2` and writes the refusal (never the leaked content) to stderr. The operator
should never need to redact anything from what this command shows them; if it
refuses, that is itself the finding to report, not something to work around
by editing the block before pasting it back.

## `--control`: proving the checks themselves aren't blind

```bash
skillc demo --control
```

Runs four seeded, known-bad scenarios and requires every one to be caught -
the OTHER verdict from the success path, on purpose:

1. **A reply-only subject** that never touches the liveness canary - the
   driver must report it as something other than `captured`.
2. **A container deliberately left running** - `prepare()` is called and
   `destroy()`/`confirm_absent()` deliberately never is, standing in for a
   crashed controller. The independent reap sweep (#79) must find and remove
   it, reporting `reaped`.
3. **A known-bad grading candidate** (one of `slug-small-fix`'s own committed
   `wrong/` variants) - grading must report `FAIL`, not `PASS`.
4. **A leaky paste-back** - a planted host-identity value must be refused by
   the same leak-check the real paste-back block goes through, never printed.

`--control` exits `0` only if all four were caught, and non-zero the moment
any one was not - a `--control` run that reports success no matter what it
seeds would be worse than not having a control at all, so
`tests/test_demo.py` includes its own committed negative controls on
`run_control()` itself: breaking either the grading-candidate check or the
orphan-reap check individually flips the overall verdict to `False`, proving
neither is decorative.

## What is owed to the operator's live run

Matching this repository's own evidence rule (`interfaces.md`,
`support-matrix.md`): this document and every test behind it prove the
command's *shape* - argv composition, state-machine sequencing, leak-check
discipline, reap accounting - against a fake daemon. They do not and cannot
prove that a real Docker daemon, given `skillc-trial:latest`, actually
executes the lifecycle and grading demos correctly. That is what running
`skillc demo` for real, once, on the operator's own machine, establishes -
and its output, pasted back verbatim, is what #10 actually closes on.

The same is true of `--subject` for #11: this document and its tests prove
the install/digest-check/discovery shape against the fake daemon and a fake
client. They do not and cannot prove that a real container installs a real
collection intact, or that a real client's real listing actually discovers
it. That is what running `skillc demo --subject <name>` for real establishes
- and, per the "what this shows" note above, it establishes installation and
discovery conformance only, never that any skill helps.
