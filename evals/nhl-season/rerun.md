# Delivered-code NHL replay grading (#634)

The participant interface remains [goal.md](goal.md). This controller adapter
adds no participant file layout, implementation language or database requirement.
The controller reads the delivered README and maps its documented commands and
exports into a private adapter. Missing or failing documented entry points are
FAIL, with the reason retained. Never guess a command or repair the delivery to
make grading pass. A controller must review the adapter against the README;
a substring check prevents accidentally inventing a command but does not prove
that it performs the intended operation.

## Preparation and custody

This is model-free infrastructure. It authorizes no acquisition, live model
calls, paid spend, use of a particular host, or scored season run. Actual private
source adapter validation and acquisition under #633 still precede a declared
NHL trial. Never commit fetched NHL data, the private sample or plant recipes.

Select at least two distinct games from the checksum-pinned private reference.
Select complete games whose baseline F1-F8 reports all PASS: these games expose
false positives without suppressing natural discrepancies in the full-season
oracle. If no such population or no valid plant for a family exists, preparation
returns UNKNOWN with the reason; do not fabricate data or count the family as
graded. The sample selection and recipes are frozen controller declaration
inputs, not chosen in response to a candidate's output. This preparation does
not claim that every actual NHL source supplies all eight families.

Each recipe has `family_id`, `game_id`, `source_id`, `path` (existing JSON object
keys/list indices), `before` and `after`. Declare exactly one recipe per F1-F8.
The precondition must match the retained source and the mutation must change it.
The independent oracle must report DISCREPANCY in that family/game afterward;
other families may also change as a legitimate consequence, and every resulting
check is compared. The other game(s) must remain unchanged. Examples of valid
mutation targets are team score, team SOG, skater PIM/hits/TOI, a real shift-chart
goal timestamp, event situation code and roster membership. Only existing,
measured source structures may be targeted. Goalie rows do not acquire skater
fields or shift counts. F4 excludes `details.reason == teammate-blocked` while
raw retention and F7 keep those plays, following #632/#633.

Ten fresh replays run: baseline, added fields, then one per F1-F8. Added fields
appear in every existing object including nested arrays; original fields,
records and array multiplicities stay unchanged. The oracle checks that the
added fields change no expected facts. Each replay starts with a fresh project
copy and database; results cannot carry over from another scenario.

## Adapter and explicit command

A private adapter JSON selects:

- `readme`: project-relative README filename.
- `commands`: exact documented install/retrieve/reconcile/export shell commands,
  in order. One command may perform all operations if documented that way.
- `base_env`: documented API-base environment variable. Alternatively,
  `api_base_placeholder` names the literal placeholder in a documented command
  that is replaced with the replay base (for example a `--base <API_BASE>`
  argument). No source code is rewritten. The replay supplies
  `http://nhl-source:8080` for both NHL hosts, preserving paths and query strings.
  A project using another documented mapping needs an explicitly reviewed
  controller adapter extension; the grader must not silently call live URLs.
- `export_dir`: absolute output directory under `/project/` in the container.
- `reconciliation`: path relative to that directory for the public
  `reconciliation.json` export (including its `games` array).
- `payloads`: endpoint path plus query to relative retained-JSON export filename.
  The controller obtains these filenames from the delivered project's documented
  retained-source export. They need not use any particular participant naming.
  It must map every successfully requested schedule and detailed source; identical
  payloads may share a retained file. Unrequested schedule aliases need no export. A project
  retaining sources only in a database needs its documented export command to
  expose the source payloads; don't substitute controller-fabricated payloads.

Preload digest-pinned images containing Python 3 and the delivered project's
dependencies. The install command must work offline from those dependencies;
image preparation is controller setup, not an opportunity to change delivered
code. Both images must already exist: replay uses `--pull=never`. Run only after
checking the repository's real-Docker status on main and acquiring the shared
execution slot required by the current coordination policy.

```sh
uv run python -m skillc.nhl_rerun selftest
uv run python -m skillc.nhl_rerun run \
  --reference "$REFERENCE" --manifest-sha256 "$MANIFEST_SHA256" \
  --sample "$GAME_A" "$GAME_B" --plants "$PRIVATE_PLANTS" \
  --project "$DELIVERED_PROJECT" --adapter "$PRIVATE_ADAPTER" \
  --candidate-image "$PINNED_CANDIDATE_IMAGE" \
  --server-image "$PINNED_SERVER_IMAGE" --timeout 120 \
  --evidence "$NEW_PRIVATE_EVIDENCE"
```

The private evidence directory must be new and outside the delivered project.
The snapshot, expected reports, recipes, adapter and evidence stay under
controller custody. Do not place them inside the project copy or candidate
image. The server receives only the served payloads and a standalone stdlib
HTTP server; the candidate receives only its project. There are no host bind
mounts, Docker socket mounts, published ports or live NHL fallback. Two
containers share a new internal Docker network, removed after each case.
The server uses the live API path/query shapes and returns 404 for undeclared
requests. Every date covered by a retained schedule page can return that same
page, allowing different daily/weekly traversal choices without prescribing
fetch order. A controller-only server access log records successful requests;
readiness uses TCP rather than fetching a payload. Grading requires at least
one schedule request and all detailed endpoints for every selected game, then
compares retained payloads for the observed requests. Candidate processes never
receive the access log or private grader mapping. Containers drop capabilities, disallow privilege escalation, and have
PID/memory/CPU limits. Commands share a whole-case wall deadline and a four MiB per-command output
capture cap; exported JSON files must be regular, nonsymlink files no larger
than 64 MiB each. Freeze these bounds in the declaration after sizing. Delivered code
is stopped before collecting exports. Cleanup uses an independent deadline;
unconfirmed cleanup makes the result UNKNOWN, never a clean completion.

## Evidence and controls

Retention compares the entire parsed JSON payload, preserving object fields,
array order and multiplicity, and JSON types, while permitting whitespace/key
serialization differences. A marker alone, missing records, field-dropping or
unchanged cached payload fails. Reconciliation uses the independent #633
comparator for exact game/family/check populations, scoped values, units and
statuses. A planted discrepancy in the wrong game/family, a false positive on
an unchanged game, missing checks, and always-PASS reporting fail.

Private per-case `execution.json` records argv, exit status and captured output;
`output/` retains candidate exports and `verdict.json` names the reason. A final
`report.json` accounts for all ten cases. Exit codes are 0 PASS, 1 FAIL and
2 UNKNOWN. Preparation and Docker transport failures are UNKNOWN. A failed documented
command is FAIL only when an independent inspect still confirms the candidate
container running; failed/uncertain inspection does not blame the candidate. PASS here covers only these replay
checks; it is not a whole-project, full-season, viewer or on-ice verdict.

The committed [controls](../../controls/nhl-rerun/README.md) use two authored
synthetic games, actual local HTTP retrieval, SQLite persistence and documented
export entry points. Reference passes all ten cases; strict and field-dropping
retrievers fail drift; always-PASS reconciler fails each of eight plants. The
selftest verifies the exact committed case matrix. Tests also blind the export
comparator and require qualification to reject it. Docker CLI stand-ins exercise
network/custody arguments, failed entry points, failed collection and cleanup.
`tests/test_nhl_rerun_live.py` is selected by the existing real-Docker CI lane.
It runs the same twenty-one reference/bad project replays, including a different schedule date, proves a disconnected
witness is unreachable with a connected witness as the negative control, tests
host-file custody with an explicitly copied file as the bad access case, and
checks actual container/network absence after cleanup. A skipped local test is
not that evidence: retain the exact node's executed CI result before declared
use. No protected real-Docker runner files are changed here.
