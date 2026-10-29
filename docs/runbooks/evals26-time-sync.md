# evals26 time sync

The real-Docker runner VM (proxVMevals26, Proxmox VM 126) posts GitHub statuses,
writes evidence timestamps and talks TLS to api.github.com, so its clock has to
stay synchronized. This records how it is synchronized and why
([#541](https://github.com/cooneycw/skillc/issues/541)).

## Why the default does not work

DHCP hands the VM 192.168.4.1 as its NTP server. VM 126's Proxmox firewall
(`/etc/pve/firewall/126.fw` on ThreadripperPro32) admits outbound traffic to
192.168.4.1 only on ports 53 and 67, then drops everything else to
192.168.0.0/16, so `systemd-timesyncd` never received a packet. By 2026-10-29
the clock was 9.24 s behind kyle19, up from under 1 s on 2026-10-23.

## What is configured

The fix stays inside the VM and leaves the firewall untouched, including the
kyle#1593 SSH-ingress rule. Public NTP is already admitted by the firewall.
`/etc/systemd/timesyncd.conf.d/skillc-ntp.conf` (root, 0644):

```ini
[Time]
NTP=ntp.ubuntu.com
```

A drop-in rather than an edit of `/etc/systemd/timesyncd.conf`, so a package
upgrade does not overwrite it. Applied 2026-10-29 between runner timer ticks:
the first sync steps the clock (it stepped +9.42 s), so check that no runner job
is active before restarting timesyncd (`pgrep -x run-real-docker`,
`pgrep -x pytest`, `systemctl is-active skillc-real-docker.service`).

## Verify

From kyle19 (`ssh evals26` hops through proxmox32):

```bash
ssh evals26 'timedatectl show -p NTPSynchronized; timedatectl timesync-status'
```

Healthy is `NTPSynchronized=yes`, server `ntp.ubuntu.com`, a non-zero
`Packet count` and an offset in milliseconds. The failing reading this check
gave before the fix was `NTPSynchronized=no`, server `192.168.4.1`,
`Packet count: 0`.

## Revert

```bash
ssh evals26 'sudo rm /etc/systemd/timesyncd.conf.d/skillc-ntp.conf && sudo systemctl restart systemd-timesyncd'
```

That returns the VM to the unreachable DHCP server. The other route is to admit
NTP to the gateway in 126.fw (`OUT ACCEPT -dest 192.168.4.1 -p udp -dport 123`,
above the 192.168.0.0/16 DROP), which widens the VM's LAN access.
