# Flow run record - issue #536

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=bfaff44c62344e6b94602cebda83b6f2 -->
## Run 1

- Run-id:            bfaff44c62344e6b94602cebda83b6f2
- Run-start:         c80455538d4412391a375b76202f8c4ec6338be7

- Issue: #536
- Base SHA: c80455538d4412391a375b76202f8c4ec6338be7
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-complete orchestrator, GO-WITH-CONDITIONS for PR A items 1/2 only; B held, item 3 conditional
- Recorded at: 2026-10-24T22:30:36.719155+00:00

### Section B evidence
Verdict: Still needed for items 1, 2 and 4. Item 3 retains its explicit conditional disposition.

Since filing 2026-10-24T10:42:32Z:
- Commits/merged PRs: only 237ab8f / #558 since filing on main; it fixes a separate make-test environment and does not address these items. No post-filing commits touch fixture_live.py, agent_trial.py or gate_witness.py. Earlier inspected changes 80eca1d/#523, bbfb55d/#524, 653353e/#527, d846a69/#531, f280331/#532 and 5ece908/#534 explain the current steward, witness and report behavior but leave these gaps.
- Related issues inspected: #279 (open Step-6 work), #530 (closed flow-check route guard), #547 / pending #559 (retention dependency), #556 / #557 (export and owner's repeat, distinct work), #434 (CLOSED 2026-10-21T13:00:04Z; no resume authorization), #334 (closed earlier preflight/runtime gap), #26 and #287 (other studies). No superseding fix found. #309 is unrelated Docker-CI design, not gate-state inheritance.
- Host sibling evidence: the earlier wave-wide worktree inspection found only old unpushed 9caf33c (#348) touching witness plumbing; it implements runtime transport/readiness, not these items. Own #547 work adds diagnostic retention, not opt-in preflight, scan report fields or state inheritance. AA's CLI/export lane is active and must be coordinated before a CLI edit.
- No-spend reproductions on main: the real lifecycle guard refuses ['codex','exec'] without SKILLC_ALLOW_REAL_AGENT, and accepts exact value '1', without launching anything. There is no tracked live-launch opt-in preflight entrypoint; actor rehearsal substitutes actor argv before reaching the guard.
- Pure real report reproduction: build_report receives a record with transcript_codex_invocations=[] and transcript_files_found=1, but neither key appears in its attempt row.
- Real GateWitness state reproduction with a scripted backend: first plan starts clean with a readable source digest, the backend leaves .git/cpp-runs/check-witnessed.json, and the immediately following summary records 'unreadable: resumable gate state present at .git/cpp-runs'. The current guard has no witnessed-end-state distinction.


### Section C - the approved PR A plan
1. `skillc/fixture_live.py` - share the exact model/effort-pinned real argv builder between run_live and a no-launch preflight helper; that helper invokes lifecycle._refuse_real_agent against the actual current launch environment. Add transcript_codex_invocations and transcript_files_found to every attempt report row next to nested_codex. Preserve [] versus null and 0 versus null; never rescan or synthesize historical observations while building a report.
2. `skillc/cli.py` - add a narrowly named level3-live --preflight-launch-env path, before private-directory/image/credential/backend/run allocation. It checks the actual default real-client argv through the shared helper and exits; its output claims only the opt-in guard condition, never 'all preflight passed'. Reject combination with actor/dry rehearsal flags rather than test actor argv and call that real-launch readiness. Default live/rehearsal behavior and the launch-time guard remain intact.
3. `tests/test_fixture_live.py` - report regressions for observed zero, positive/unreadable scans, multiple transcript files and absent observation; pure guard preflight tests for missing/wrong/exact opt-in and exact pinned argv. Demonstrate the report omission red before changing production.
4. `tests/test_fixture_live_cli.py` - CLI missing/wrong opt-in refusal and exact-'1' success; assert no client subprocess, backend, credential, image lookup or private run directory is touched. Prove the live guard still checks again if the environment changes after a successful preflight.
5. `tests/fixtures/fixture-preflight/cases.json` - committed absent/empty/'0'/'true'/'1' environment inputs, with positive and refusal verdicts exercised by the real CLI/helper. Do not store a real environment or credentials.
6. `docs/specs/evaluation-facility/fixture-service.md` - narrowly scoped preflight meaning, same-environment usage and report field/unknown semantics.
7. `README.md` - document the no-launch flag next to level3-live; no claim that it authorizes a paid trial.
8. `changelog.d/536.md` - one issue-fragment bullet for items 1/2.

Privacy condition for item 2: scan hits include argv_head from RAW transcript input. Do not blindly copy credential-bearing free text into a retained report. Apply the existing retention/leak checks before persistence; retain the exact ordinary scan when safe. If unsafe/unreadable, write null plus an explicit bounded retention/coverage reason, never [] or a partial list pretending to be complete. Keep the live in-memory credit calculation unchanged. Add an unsafe-argv regression and do not print the unsafe value in diagnostics. V2 record schemas remain unchanged; these are additive report fields.

Scope: 8 planned files plus automatic workflow artifacts, approximately 300-500 lines.
Risks: unsafe raw argv text must not be persisted; preflight must claim only current opt-in and perform no launch side effects; zero and unknown must remain distinct. AA released the CLI lane; #560 keeps merge priority. No material concern beyond those conditions.


### Execution evidence (approved PR A scope unchanged)

Observed red before production edits: 11 regression failures, covering all five
CLI opt-in cases (the new flag was unsupported) and six report cases (fields
absent). Committed environment inputs cover absent, empty, `0`, `true` and
exact `1`; the actual CLI refuses the first four and accepts only the last.
The real lifecycle driver refuses after a successful preflight if the opt-in
is then removed. No image, credential, backend, private store or client is
used. Scan controls cover observed zero, safe positive, missing, unreadable,
malformed, unsafe identity and synthetic credential input, plus a safety-check
read failure; unsafe or unreadable input never becomes an empty clean scan.

Focused suites: 274 passed. Final strengthened CLI side-effect controls: 9
passed. Selftest: 31/31 discriminating. Lint, types, negative controls, type
scope control, leak check and controls, README drift, and secret scan/control
passed. No paid evaluation was run. Full-suite validation follows the wave's
shared slot and exact-head CI policy.

Counter-model review: measured `codex/gpt-6-astra`, reviewer thread
`01a1700e-2656-7282-a18d-9103f6af89ad`; no defects found. Report digest:
`sha256:5565289115d59d88f9b0af2dcf009dd40ce5f7dbb7d980e6bef3d43d2bd0aeb6`.
Scope probe: unverified (reviewer did read surrounding repository files);
network probe: blocked; repository-local credentials: absent. Under the
orchestrator's existing truthful-attribution disposition for this mixed-model
worker thread, no single-implementer receipt is fabricated: registration
included `gpt-6-astra`, while implementation is `gpt-6.1-sol`. The helper's
whole-thread attribution limitation is recorded in CPP Nit Store #864,
comment 6389865902. The review was performed, not skipped. This appended
execution evidence leaves the approved Section C unchanged; the plan stability
checker will truthfully flag the appended note.

### Actual receipt completion after CPP1558

The merged helper generated schema3 ran receipt docs/measurements/counter-model/2026-10-25T005520Z-issue-536.json
from the original fresh-run and review traces. Implementer codex/gpt-6.1-sol;
reviewer codex/gpt-6-astra; scope unverified, network blocked, local credentials
absent. Initial cleanliness remains unmeasured and approval execution unverified;
no anchors were reconstructed. Six whole report entries are proposed, zero
credited as already covered under the verified pre-first-proposal/all-subcases
standard. Zero does not claim that no existing controls covered those cases.
The prior full make verify EXIT0 and original outer missing-receipt EXIT1 remain
separate historical outcomes. Current-base integration and final CI remain held
until the #563 prerequisite merges.
