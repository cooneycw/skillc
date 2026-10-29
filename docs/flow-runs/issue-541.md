# Flow run record - issue #541

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ce76892b274b40dcb573098ca50be0e5 -->
## Run 1

- Run-id:            ce76892b274b40dcb573098ca50be0e5
- Run-start:         75636b9762b8512e5742cce439ea18be529198de
- Issue:             #541
- Base SHA:          75636b9762b8512e5742cce439ea18be529198de
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), in-session reply "approved" to the Step-3 report recommending option (b) + runbook PR
- Recorded at:       2026-10-29T11:58:30Z

### Section B evidence
Live probe 2026-10-29 11:55Z: evals26 NTPSynchronized=no, server 192.168.4.1, packet count 0;
126.fw unchanged from the issue text; VM clock -9.24s vs kyle19 (both kyle19 and proxmox32 NTP-synced),
up from <1s on 2026-10-23. Commits since 2026-10-24: 30 on main (75636b9 .. 1d129f9), none touch
host time/firewall config. Merged PRs since filing matching evals26/ntp/firewall: none.
Duplicate/superseding issues (skillc + kyle): none.

### Section C - the approved plan
Host change (outside the repo): option (b) - drop-in /etc/systemd/timesyncd.conf.d/skillc-ntp.conf
with NTP=ntp.ubuntu.com on evals26, restart systemd-timesyncd between runner timer runs; 126.fw untouched.
Verify NTPSynchronized=yes, packet count > 0, offset vs kyle19 < 0.5s, 126.fw byte-identical.

1. `docs/runbooks/evals26-time-sync.md` - new runbook: what changed on the host, why, verify and revert commands

Scope: 1 host config change, 1 repo doc (~40 lines). Risks: ~9s forward clock step on first sync
(apply when no runner job is active); option (b) depends on internet egress the runner already needs.
