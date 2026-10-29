<!-- flow-run n=1 id=ce76892b274b40dcb573098ca50be0e5 -->
## Run 1 - issue #541 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #541
- Read at:      2026-10-29T11:55:03Z
- updatedAt:    2026-10-24T10:42:38Z   (context only - moves on comments and labels)
- Body digest:  af1162d275f5ec5b27fd26f8ee6ec7a8502b1c51cd51767da000c05937adc9cf   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2516 of 2516 (cap 16384)

### Body as read
**Severity: LOW.** The clock is correct today; the risk is drift. **Waiting on the owner's choice of fix.**

## Problem
`systemd-timesyncd` on proxVMevals26 uses the DHCP-supplied server, 192.168.4.1. VM 126's Proxmox firewall (`/etc/pve/firewall/126.fw` on ThreadripperPro32) admits outbound traffic to 192.168.4.1 only on ports 53 and 67, then drops everything else to 192.168.0.0/16. Result: `Packet count: 0`, `NTPSynchronized=no`. The runner's GitHub statuses, its evidence timestamps and TLS to api.github.com all depend on the VM clock.

## Options
- (a) Add `OUT ACCEPT -dest 192.168.4.1 -p udp -dport 123` to 126.fw.
- (b) Set `NTP=ntp.ubuntu.com` in timesyncd.conf. Public NTP is already allowed by the firewall.

## Acceptance
- [ ] `timedatectl show -p NTPSynchronized` reads `yes`, and `timesync-status` shows a non-zero packet count.
- [ ] The kyle#1593 SSH-ingress restriction stays unchanged.

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6376754939 (2026-10-23)</summary>

**Severity: low. evals26 (the real-Docker runner VM) has no working time sync.**

Where: the Proxmox firewall for VM 126 (`/etc/pve/firewall/126.fw` on ThreadripperPro32) and `systemd-timesyncd` on proxVMevals26.

What is wrong: timesyncd uses the NTP server DHCP hands out, 192.168.4.1. The VM's firewall allows outbound traffic to 192.168.4.1 only for DNS (port 53) and DHCP (port 67), then drops all other traffic to 192.168.0.0/16. NTP (UDP 123) is therefore dropped: `timedatectl timesync-status` shows `Packet count: 0` and `NTPSynchronized=no`. The clock was correct to within 1 second of kyle19 and Proxmox on 2026-10-23 23:25Z, so this is drift risk, not drift yet.

Why it matters: the runner's GitHub statuses, the evidence timestamps, and TLS to api.github.com all depend on the VM clock. A long uptime with no sync can drift until those break or mislead.

Fix options: (a) add `OUT ACCEPT -dest 192.168.4.1 -p udp -dport 123` to 126.fw, or (b) set `NTP=ntp.ubuntu.com` in timesyncd.conf. Public NTP is already allowed, and a probe on UDP 123 to 185.125.190.56 went out.

Found during: an owner-requested health check of evals26 after the Proxmox host changes (2026-10-23). No issue or PR was in progress.


</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- end of body -->
