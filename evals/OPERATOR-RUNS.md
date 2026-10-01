# Operator-run commands: the paste-able block and the hand-back

This file is the one place a live, operator-run command lives, for any issue
whose declaration says the run happens on the operator's own machine. Each
such declaration (for example
[`evals/selection-probe/retention-run-declaration.md`](selection-probe/retention-run-declaration.md))
states WHAT is approved - identities, arms, caps, under
[ADR 0005](../docs/decisions/0005-runtime-scope-and-cost-rulings.md) rule 5.
This file states HOW to run it: one paste-able block, and what comes back
afterward. A new declaration adds its own command line here rather than
inventing its own runbook.

## The paste-able block

Run from a terminal on the machine that will actually execute the attempt -
never from a shared or managed session. Fails closed: any preflight failure
stops the script before the first paid call, under `set -euo pipefail`.

```bash
set -euo pipefail
DECLARED_SHA="<the exact commit named in the ready message for this run>"
git clone https://github.com/cooneycw/skillc.git skillc-run && cd skillc-run
git checkout --quiet "$DECLARED_SHA"
[ "$(git rev-parse HEAD)" = "$DECLARED_SHA" ] || { echo "HEAD != declared commit, refusing"; exit 1; }
docker version >/dev/null                                     # preflight: daemon reachable
[ -f "${CODEX_HOME:-$HOME/.codex}/auth.json" ] \
  && echo "codex login: present" || { echo "codex login: ABSENT, refusing"; exit 1; }
[ "$(env | grep -c '^KYLE_' || true)" -eq 0 ] || { echo "KYLE_* present in this shell, refusing"; exit 1; }
uv sync --extra dev --quiet
docker build -q -t skillc-trial:latest docker/trial/ >/dev/null
echo "image_digest=$(docker image inspect --format '{{.Id}}' skillc-trial:latest)"
BASE="$(mktemp -d)"
# --- the one declared command for this run; a different declaration names its own here ---
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc selection-probe --detection-control --agent-timeout 900 --base "$BASE"
# --- end declared command ---
mapfile -t RUN_DIRS < <(find "$BASE" -mindepth 1 -maxdepth 1 -type d)
[ "${#RUN_DIRS[@]}" -eq 1 ] || { echo "expected exactly 1 run dir under $BASE, found ${#RUN_DIRS[@]}, refusing"; exit 1; }
STORE="${RUN_DIRS[0]}/selection-probe-detection-control-store"
TRANSCRIPTS="${RUN_DIRS[0]}/retained-transcripts"
mkdir -p "$TRANSCRIPTS"                # created only if any attempt retained one; make it exist for the scan below
uv run skillc leak-check "$STORE/selection-probe-report.json" "$TRANSCRIPTS"
echo "hand-back ready: $STORE/selection-probe-report.json  $TRANSCRIPTS"
```

- **The commit check is first and literal**, not "whatever `main` is today" -
  a declaration names an exact SHA, and this script refuses to proceed on
  any other one, including a later commit that looks like a harmless
  superset.
- **Neither preflight line prints a secret.** The codex check reports
  presence only (`-f`, a file existence test); the credential's own content
  never appears in this script's output.
- **The `KYLE_*` check is not specific to this operator's own setup.** Any
  prefix a caller's own environment uses for session-scoped state is the
  same hazard this line guards against: a subject or agent process must
  start from a clean environment, never inheriting state from whatever
  shell happened to launch it.
- **A different declaration (e.g. a #203 candidate's own calibration run)**
  swaps only the one marked command line, including its own caps and flags
  from its own declaration - everything above and below it is unchanged.
- **Every preflight (daemon, codex login, `KYLE_*`) runs before the slow
  steps** (`uv sync`, the image build), so a failing preflight stops the
  block before either one is paid for in wall time, not after.
- **The run-directory count is asserted, not assumed.** `find` finding zero
  or more than one directory under a freshly-created `$BASE` is refused by
  name rather than silently picking the wrong one or failing deep inside a
  path substitution.

## The hand-back: what returns, how, and who writes it up

Follows the precedent in
[`evals/selection-probe/evidence/README.md`](selection-probe/evidence/README.md):
a public, dated writeup with a results table, built FROM what the operator
returns - never the raw run store itself, and never written by the operator
directly.

**For `selection-probe`, retention needs no separate export step and no
flag.** `AgentTrialRunner.__call__` (`skillc/selection_probe.py:702`) passes
`retain_transcript=True` on every attempt, unconditionally - the parameter
it sets (`agent_trial.run_one_attempt`'s own `retain_transcript: bool =
False`, `skillc/agent_trial.py:1134`) defaults to off for OTHER callers, but
this command's one caller always turns it on. Each retained transcript is
already leak-checked at write time, by the retention code itself
(`_retain_transcript`, `skillc/selection_probe.py:631`) - a leak there
refuses that one file's retention, never the run. So by the time the
command above exits, the files below already exist in plain, unexported
form; nothing needs to be staged or published out of the store first.

**Stays on the operator's machine, always:** the full run store - the
ledger, journal and objects `trial.plan()`/`run_planned_selection_probe`
write as they go. Matches existing precedent: per-run observation records
and ledgers live in the operator's own run store, never in the repository.

**Returned by the operator, after the run** (both under the one run
directory the block above prints, as siblings - the transcripts are NOT
nested inside the store):

1. The report file the command writes directly into the store
   (`<run-dir>/selection-probe-detection-control-store/selection-probe-report.json`).
2. The retained-transcripts directory beside it
   (`<run-dir>/retained-transcripts/*.jsonl`) - these files only, never the
   store's own ledger/journal/objects.

**The block above already leak-checks both**, on the operator's own
machine, as its last step, before either file is held out as ready to hand
back - the same `skillc leak-check` this project's other operator-facing
commands (`skillc demo`'s own paste-back block) already run before printing
anything. A refusal there stops the block with nothing copied; it is itself
the finding to report, never something to redact and resend.

**Where the leak-checked files go, and who writes the results table:**

- A small report (this control: 2 attempts) goes as a comment on the issue
  the run answers - the report JSON pasted inline, the retained transcripts
  attached if the issue's host allows it, linked otherwise.
- A larger run (more attempts, or transcripts too large for a comment) goes
  as a PR adding the files under that probe's own `evidence/` directory,
  matching `evals/selection-probe/evidence/`'s existing shape.
- **Either way, the results table and narrative are written by whoever is
  driving the run (not the operator) from the returned files** - the same
  authorship `evals/selection-probe/evidence/README.md` already has. The
  operator's own part ends at running the block above and returning its
  leak-checked output; reading and reporting what it shows is a separate
  step, done afterward, from the files themselves.
