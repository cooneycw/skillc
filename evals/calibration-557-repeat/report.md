# #557 repeat: preparation evidence

Status: preparation only. No new subscription model attempt has run. The
declaration is unapproved. The post-#547 controller freeze was approved by
the wave orchestrator on 2026-10-24 at source
`5f302a0619dfc88a53025bd177489214353eed0f`, with reviewed retention merge
`c80455538d4412391a375b76202f8c4ec6338be7` in its ancestry.
This is a new requested experiment, not a reconstruction of historical
`calibration-09960aea`.

## Verified inputs

- The archived revision-1 task is 188 files from skillc `fc02838`, tree
  `2321b8cfd1dc45ce10449e87df2e373a02a2629c`. All source bytes and executable
  modes are compared against Git. Current revision 2 remains untouched.
- Goal: `sha256:dd288ba5f15f17cf824de881ba86220b4e4d848b69343072fd070a76f5c701c4`.
- Grader: `sha256:c35cc7f666ac84858640d114804ac3db546dd8a501213ba6dcc7470516050523`.
- Delivered fixture: `sha256:22ba733867862b536a7064596a4800e158494b03d3c2c613cb8518c4a2a62c4f`.
- Replacement image: `sha256:b9816879e22d1f62dc6b8614c787e7666c1d9f438437c3d03d3c622513d1a563`.
  Actual credential-free network-none version probe: `codex-cli 0.157.1`.
- The CPP commit `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` exists locally.
  Actual treatment acquisition/discovery is not established by commit existence.
- The local credential selector/lifetime check accepts the subscription login
  for a 1200-second attempt. It must be reread before each actual attempt.
  No secret bytes or machine-specific selector are part of this report.

## Red and green evidence

The original historical grader, using the current verifier, certifies its
committed good/bad candidates, refuses all five broken graders, and passes
13 validity controls. In particular the starting fixture fails, the reference
passes, and the helper prints `CHANGED` when an approved line is missing while
printing `INTACT` on the duplicated-step fixture. This establishes the narrower
helper contract and the grader's discrimination, not the validity of every
interpretation of revision 1's public wording.

The original declaration is accepted against archived revision 1 and refused
against current revision 2. Merely replacing the old image under the original
approval is refused by the production whole-declaration digest check.

`controls.json` commits ten refusal inputs exercised by preflight: current
task under the original declaration, changed image under stale approval,
changed historical content fingerprint, changed schedule, temporary evidence
store, stale controller source, actual controller bytes, actual archived fixture
bytes, loadable divergent bytecode and missing launch approval. A synthetic
in-memory control with the exact digest is accepted by the production approval
validator before each mutation. It authorizes no actual run.

Preparation succeeds only with an explicit `NOT AUTHORIZED TO LAUNCH` result.
Launch-ready without approval exits nonzero. Image, credential and historical
grader checks are individually labeled when not requested. Rehearsal or source
inspection does not establish actual attempt containment, uptake or outcome.

## Still owed

The reviewed controller/runtime dependency identities are frozen in the
declaration and the full verification gate passed. Review the final declaration
digest under delegated authority, verify
the actual launch boundaries, and execute precisely the 18 planned slots once.
Retain every attempt and object byte privately, including failures and unknowns.
No observed client/model/effort, trial outcome, uptake, actual egress/guard
eligibility, token usage or schedule/cleanup wall time is claimed here.

After that run publish a privacy-checked, source-linked summary and determine
whether any observed failure supplies #28 lineage. No failure is guaranteed.
Revision 1's wording ambiguity and replacement image/current controller/model
provider state limit historical comparability; a floor/ceiling outcome supplies
no generalized improvement claim. See [README.md](README.md) for the bounds.

## Independent review

Two review passes ran with measured `codex/gpt-6-astra`, against the measured
implementer `codex/gpt-6.1-sol`. Scope: full repository reads; the sandbox's
GitHub network probe was blocked with a successful outside positive control;
repository-local credential configuration was absent. The generated receipt is
`docs/measurements/counter-model/2026-10-24T215806Z-issue-557.json`.

All three medium findings were accepted and fixed: the controller-byte control
now starts from a complete passing scratch checkout and requires its changed
file's refusal; preflight uses a fresh bytecode cache before controller imports;
and the actual qualification subprocess also uses a fresh cache. The committed
unchecked-hash bytecode case proves the divergent cache loads normally, then
proves source executes through both production cache boundaries. The launch
runbook separately selects a fresh cache for its child process.

The actual first-review preflight was recovered from that review's recorded
diff and exercised on the targeted cases. Controller-byte discrimination and
preflight cached-code exclusion each failed before the fix (exit 1) and passed
after it (exit 0). The actual qualification subprocess boundary, supplied the
same source-versus-cache sentinel in place of its grader, likewise failed on
the before-fix code and passed on the fixed code. No third review pass ran;
these are model-free post-review checks, not a claim of a clean third review.
The receipt's red-case counts enumerate the 16 groups across both review
reports, with one complete historical-grader group already covered; they do
not assert every suggested extension was implemented.

## Frozen preparation verification

Canonical unapproved declaration:
`sha256:1b888ca6a77ada22768c9226a2ff3e8b8302ecaa80db013c600e5e02c3993797`.
Root independently recomputed and reviewed this digest; actual launch approval
remains absent until its separate ruling. Source freeze is true, and no later
wave merge may silently replace the reviewed runtime.

`make verify` exited 0 on this frozen source/preparation. Pytest: 6907 passed,
5 expected skips, 6912 independently collected identities matched the JUnit
report. Ruff and mypy passed (316 source files). Selftest and the general,
typecheck, leak, secret-scan, git-execution and pytest-population negative
controls passed: the planted type error and secret were detected, the short
population/missing or skip-corrupted execution reports were refused, and the
corresponding valid inputs passed. Changelog and README drift checks passed.
The privacy scan found no matching leaks in 5544 files under its configured
patterns/exclusions; no hostname deny-list was configured. Raw logs and JUnit
population evidence are retained privately, not published as trial evidence.

The five skips comprise two diagnosed frontmatter cases, the deliberately
opt-in timeout negative control, and two real-Docker cleanup tests reserved
for the separate locked real-Docker runner to avoid affecting neighbours.
The full model-free prepare after source freeze passed all ten committed
preflight controls, actual image/client and credential eligibility checks,
and grader certification (five broken graders refused, 13 validity controls).
Launch-ready still exited 1 when approval was absent. No model trial has run.
