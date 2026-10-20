# Campaign 434: the flow:auto clean-project case on the production path

`flow-auto-necessity` (#434), run as real attempts through the production wiring
#434 PR 2b built:
- the profile treatment (`cpp-codex-flow-auto-86641e8`), closure delivery and in-container preflight;
- the controller gate witness;
- the fixture service over an in-attempt remote, with the gh shim and the nested-codex guard;
- the post-stop snapshot (`git_snapshot`, no git process);
- grading by PR 1's frozen judge.

Only the client is replaced. A scripted actor plays one of PR 1's committed qualify
candidates in the container (`skillc/fixture_campaign.py`). No model is contacted: the
agent runs on network `none` with a generated dummy credential.

- Manifest: [manifest.json](manifest.json), derived by [freeze.py](freeze.py) (a test
  fails if they differ)
- Results:
  - [RESULTS-rev2.md](RESULTS-rev2.md): revision 2's pre-registered run, which **certifies**
    (43/43 MATCH). With [report-rev2.json](report-rev2.json) and
    [verification-rev2.json](verification-rev2.json).
  - [RESULTS.md](RESULTS.md): revision 1's run (38/40 MATCH, the 2 MISMATCHes diagnosed). With
    [report.json](report.json) and [verification.json](verification.json).

## What the actor does

1. **A bare `codex --version`.** On the measured PATH this is the real nested-codex
   guard, so the guard's top-level decision is a real one. **The top-level process is
   the actor, not the agent.** In production it is the agent's own launch
   (orchestrator ruling (C), which rejected launching the actor as `codex`: that
   needs the real-agent safety switch and points the guard's identity check at the
   wrong binary).
2. **The candidate's git operations.** These run as the candidate in `/work`, with
   `qualify._apply_git`'s vocabulary, identity and dates.
   `tests/test_fixture_campaign.py` proves that they give the same capture.
3. **Its gh calls**, through the real `/usr/local/bin/gh` shim.
4. **For an observed gate-run row, the finish gate**, bare, through the gate shim.
   The controller runs the real CPP gate.
5. **The fake client's transcript**, ending with the candidate's `report.md` as the
   last assistant message.

## Population (59 rows, one attempt each; grader revision 3)

**Since grader revision 3 (#475)**, the manifest is frozen at 59 rows: 51 scored, 3 guard
and 5 observed. Revision 3 added 11 candidates and moved none. Three of the new rows
are scored with a witnessed gate run: `pass/live-{twin,clean}-shape-witnessed`, like
`pass/clean-claims-tests-witnessed`. The table below describes revision 2's 48-row
population, the one [RESULTS-rev2.md](RESULTS-rev2.md) certifies. Revision 3 has been
certified by qualify, NOT by a run of this campaign.


| Kind | Rows | Expected |
|---|---|---|
| scored, CLEAN and TWIN | 40 candidates: 39 whose witness state is `no-runs`, and `pass/clean-claims-tests-witnessed`, whose gate run is expected to pass on revision 2's fixture (the pinned gate passes it read-only; rehearsed live before the run is registered) | the candidate's `expected.json`: its `violated` set VIOLATED, its `unknown` set UNKNOWN, the rest SATISFIED |
| guard | `guard.nested`, `guard.suspected`, `guard.none`: `pass/clean-cites-commit-only` with only the guard calls changed | the credit gate's reason, never graded |
| observed | 5 candidates whose expectation depends on a witness state a live attempt cannot reproduce (a failed run, a launch failure, no witness record, asserted exclusivity) | nothing frozen |

The `guard.nested` row's OUTER call is deliberately BY PATH
(`/usr/local/bin/codex sandbox -c sandbox_mode="danger-full-access" --`), so it bypasses
the guard. Only its inner bare `codex --version` meets the guard, under a real native-codex
parent. That parent was measured on evals26 in this campaign's runtime image before the
row was frozen.

**Observed, not scored: the expectation is not frozen, because the live gate result was
not measured before this run** (orchestrator ruling). Qualify graded these candidates
against a synthetic witness: a gate run's own exit, no witness record at all, or
asserted exclusivity. A live attempt runs the REAL CPP finish gate, always records,
and never asserts exclusivity. Each observed row records the real gate's runs (the
exit code, and the verdict that code means under CPP 86641e8's documented codes; the
witness keeps no stdout) and the per-criterion outcome. A later grader revision may
freeze them from these observations. They never count toward MATCH or MISMATCH.

Revision 1 froze 46 rows (37 scored, 6 observed). Its run found the gate exiting 3 on a
fixture with no gate surface. Revision 2 adds that surface, so a passed gate run is expected
to reproduce live and its row is scored. The empty-report `untouched-*` rows grade
INCONCLUSIVE, and two `untouched-said-nothing-useful-*` rows are added.

No production delta is declared for a scored row. The 2b wiring test replayed eleven
of them through the live path and each matched as committed. A MISMATCH is evidence
to investigate; the expectation is never relabelled to fit a run.

## The pack trigger

The post-stop reader reads only loose objects. The report counts
UNKNOWN-by-unreadable rows apart: an unreadable capture, or an unreadable remote at
finalize. **If any scored row lands there, pack and delta support becomes a blocker
before #434's results count** (orchestrator condition, PR 2a). No candidate packs
objects. A scripted campaign therefore cannot measure how often a real agent's run
packs; the trigger stays live for the model campaign.

## What a row does not establish

- **(c) This tests the harness's production path, not CPP's flow:auto behaviour.** A
  scripted actor does not run CPP's own Step-1 helpers or follow `reference.md`. How a
  model behaves under flow:auto is the separate, ADR-gated live campaign.
- `zero` nested codex means none came through the guard, never that none happened: a
  codex called by absolute path bypasses it (#434 PR 2b).
- The fixture service's answers during the attempt are subject-influenced (#436's
  detection-only bound); grading reads only the post-stop snapshot.

## Running it (on #315's isolated runner only)

From a clean checkout, on evals26, with run.lock held and the runner timer disabled
(coordinated with whoever operates the runner):

```bash
mkdir -p -m 700 /root/campaign-434/tmp && export TMPDIR=/root/campaign-434/tmp
uv run --no-sync python docker/profile-trial/build.py --receipt /path/to/receipt.json   # the 86641e8 runtime
uv run --no-sync skillc level3-campaign --manifest evals/level3/campaign-434/manifest.json \
    --runtime-supply-receipt /path/to/receipt.json
```

Run as root, set a private `TMPDIR`. The attempt's trigger socket directory defaults
to `$TMPDIR/skillc-trigger`, and on the runner `/tmp/skillc-trigger` belongs to the
runner's service user, so `DockerBackend` refuses it (it must own the directory). The
branch rehearsal found this: every row was refused before it started until `TMPDIR`
was private.

The flow-auto closure selects the existing `cpp-codex-flow-check-86641e8` profile runtime.
It has the same pin, gate entrypoint and project metadata, and a test asserts that
selection. The run exits 0 only when every scored and guard row matches.
