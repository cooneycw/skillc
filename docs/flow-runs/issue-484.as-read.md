<!-- flow-run n=1 id=b6dc259e2fd243c0841ee0b4104f0578 -->
## Run 1 - issue #484 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #484
- Read at:      2026-10-28T11:58:44Z
- updatedAt:    2026-10-22T10:43:27Z   (context only - moves on comments and labels)
- Body digest:  9055f2389d95f962c3e2cd5c93d21f93b8e585c30731fa31dda9697f893f5718   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2310 of 2310 (cap 16384)

### Body as read
## Problem

The CI host kyleci (proxVMkyleci22, 8 CPUs; it runs both skillc and kyle Woodpecker pipelines) suffers disk I/O stalls severe enough to time out unrelated tests. Each red below was explained by #479's failure-time capture (`FAILURE_CONTEXT`):

| pipeline | failing test (untouched by the PR) | load1 | psi_cpu10 | psi_io10 | kyle CI running? |
|---|---|---|---|---|---|
| 963 (push, 043279f) | test_uptake_study::test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested (pytest-timeout 120 s) | 18.4 | ≤48 | **61, peaks ~90** | yes |
| 964 (restart) | test_load_harness::test_busy_workers_are_attributed_their_cpu_time | 14.98 | **68.87** | 1.95 | yes (kyle push 3486) |
| 968 (push, 16ccfdf) | test_skillc_disrupt_tool::test_exit_1_when_the_channel_refuses_the_tool_call (subprocess 10 s timeout) | 8.52 | 0.45 | **83.13** | **no** (skillc held lock 2) |

964 was CPU contention from a concurrent kyle pipeline, and serialising the two repos' CI on lock 2 (2026-10-20) addresses that. **963 and 968 are I/O stalls, and 968 happened with no other pipeline on the box.** So kyleci's disk stalls independently of concurrent CI.

## Why it matters

kyleci's PR CI is now skillc's only full-suite gate (owner ruling 2026-10-18). Every stall turns a correct PR or main push red, costs a serial hold, and hides real regressions among noise.

## Likely causes to check (unverified, nothing measured yet on the host itself)

- Proxmox storage shared with other VMs (a backup job, kyle19's or evals26's heavy I/O, snapshot or replication schedules).
- The Docker layer and pull activity, or Woodpecker workspace clones on the same disk.
- The disk's own health (SMART) or the thin-pool state.

## Acceptance

- [ ] Measure kyleci's I/O over a window covering CI runs (iostat/PSI on the host, plus the Proxmox host's storage stats) and name the source of the stalls.
- [ ] Fix it, or isolate CI from it (separate storage, schedule backups off CI hours, or a per-pipeline I/O budget).
- [ ] Afterwards, N consecutive skillc full-suite runs complete with psi_io10 below 20 throughout (N stated in the fix).

Interim skillc policy while this is open: a CI red may be retried once inside its hold when its FAILURE_CONTEXT shows psi_io10 ≥ 50 and the failing test is untouched by the PR.


<!-- end of body -->
