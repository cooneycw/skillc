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
uv sync --extra dev --quiet
docker build -q -t skillc-trial:latest docker/trial/ >/dev/null
echo "image_digest=$(docker image inspect --format '{{.Id}}' skillc-trial:latest)"
docker version >/dev/null              # preflight: daemon reachable, or this aborts here
[ -f "${CODEX_HOME:-$HOME/.codex}/auth.json" ] \
  && echo "codex login: present" || { echo "codex login: ABSENT, refusing"; exit 1; }
[ "$(env | grep -c '^KYLE_' || true)" -eq 0 ] || { echo "KYLE_* present in this shell, refusing"; exit 1; }
BASE="$(mktemp -d)"
# --- the one declared command for this run; a different declaration names its own here ---
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc selection-probe --detection-control --agent-timeout 900 --base "$BASE"
# --- end declared command ---
STORE="$(find "$BASE" -mindepth 1 -maxdepth 1 -type d)/selection-probe-detection-control-store"
echo "run store: $STORE"
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

## The hand-back: what returns, how, and who writes it up

Follows the precedent in
[`evals/selection-probe/evidence/README.md`](selection-probe/evidence/README.md):
a public, dated writeup with a results table, built FROM what the operator
returns - never the raw run store itself, and never written by the operator
directly.

**Stays on the operator's machine, always:** the full run store - ledger,
journal, objects, every retained transcript. Matches existing precedent:
per-run observation records and ledgers live in the operator's own run
store, never in the repository.

**Returned by the operator, after the run:**

1. The one report file the command itself writes into the run store (for
   `selection-probe`, `*-report.json`).
2. The retained transcripts directory the run store holds
   (`retained-transcripts/*.jsonl`) - these files only, never the rest of the
   store (ledger internals, journal, objects).

**The one command that leak-checks both, on the operator's own machine,
before anything leaves it:**

```bash
skillc leak-check "$STORE/selection-probe-report.json" "$STORE/retained-transcripts"
```

This refuses the whole hand-back - prints nothing, copies nothing - the
moment it finds anything, exactly as `skillc demo`'s own paste-back block
already does before it prints. A refusal here is itself the finding to
report; nothing is redacted and resent.

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
