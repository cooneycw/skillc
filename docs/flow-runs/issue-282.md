# Flow run record - issue #282

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ed24dd72b70c4c6d9192642d6bcc59bc -->
## Run 1

- Run-id:            ed24dd72b70c4c6d9192642d6bcc59bc
- Run-start:         5d0f5722217f7345bebf0f423741a7b4fb1e5fa2
- Issue:             #282
- Base SHA:          5d0f5722217f7345bebf0f423741a7b4fb1e5fa2
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T01:24:54Z

### Section B evidence
#280 (merged 5d0f572) proves healthy PROCEED, stopped-service ROLLBACK and template-shape REVIEW only; no merged PR covers regression, pre-existing failure, recovery, absent baseline, mismatched release identity, recommendation-is-not-execution or no-observation-is-unknown. CPP verify at 86641e8 has no release identity (filed claude-power-pack#1479).

### Section C - the approved plan
1. `tests/fixtures/cicd-local/` - releases with fixed faults (calc-wrong, metrics-500), a /version and /calc on the loopback service, a deploy.sh (stop pid with bounded wait, switch current, start, bounded health poll), cicd.yml variants (release-probe certified path, health-only, regression-unprobed, require_baseline).
2. `skillc/` judge module - parses `verify --json`; timeout, non-JSON or no verdict reads UNKNOWN; reports release identity (served vs intended) and baseline order independently of CPP.
3. `tests/` judge unit tests - including CPP#1476 (`health` exit 0 + "no checks configured" reads no_probes, never healthy).
4. `tests/test_cicd_deploy_verify_live.py` - runner-only live test reusing #280's image/closure: healthy PROCEED; regression ROLLBACK with /health still passing; pre-existing REVIEW; recovery PROCEED; absent baseline (regressed ROLLBACK, healthy PROCEED, require_baseline REVIEW); empty probes REVIEW; mismatched release under the release probe not PROCEED; after ROLLBACK the regressed release is still served; project:init template bytes from the installed closure, verbatim and uncommented, both zero probes.
5. Break family `cicdverify:` in `ci/real-docker/break-lib.sh` - regression-unprobed, baseline-after-deploy, restart-skipped, each strict-xfail on its own property.
6. Strict-xfail known gap linked to claude-power-pack#1479 - under the health-only config a mismatched release reads PROCEED.
7. `ci/check_real_docker_ran.py` floor 10 -> 11 files (+ its test), README, changelog fragment or entry.

Scope: large (~250 test/fixture, ~80 src lines). Risks: live-only paths certified only on the #315 runner; latency ignored (stated in PR); /project:init itself not run (ADR 0005).
Approver conditions: (1) mismatched release under health-only = strict xfail linked to the CPP issue, not only a documented limitation; (2) release-probe config is the certified path with its own passing case; (3) PR body states latency-ignore and ADR 0005.
