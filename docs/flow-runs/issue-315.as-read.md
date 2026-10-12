<!-- flow-run n=1 id=15df254ef4304a81b71efba70ac896f0 -->
## Run 1 - issue #315 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #315
- Read at:      2026-10-12T14:14:21Z
- updatedAt:    2026-10-06T21:19:07Z   (context only - moves on comments and labels)
- Body digest:  ecf046582de2b47eaef60675a6cf7be99ae1fa5b852e05d7df6edfbde72a509e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 10241 of 10241 (cap 16384)

### Body as read
Linked from #309. This is the operator-executable checklist for provisioning
the dedicated `docker-ci` Woodpecker agent #309's design calls for. No
hostname, IP, internal URL, user or path appears below - placeholders
(`<agent-host>`, `<server-grpc-endpoint>`) stand in wherever the operator
supplies a real value.

## Why dedicated, not the shared pool

A privileged container is root-equivalent on whatever host its daemon runs
on, regardless of which Linux user owns the agent process - Woodpecker's
docker backend needs a rootful daemon connection to function at all, and
privileged-mode escape techniques operate at the kernel/namespace level, not
through Unix file permissions. The only mitigation I'd rely on without
further verification is giving this agent its own virtualized boundary with
nothing else of value reachable from inside it. A shared host running other
sensitive workloads would need either a non-privileged sandboxed runtime
(unverified whether Woodpecker's docker backend supports selecting one) or
a guarantee that nothing else sensitive is reachable from it (not something
this issue can assert) - so dedicated is the option I'd act on, and reusing
a shared host is the one I'd only recommend after one of those two gaps is
independently closed, which this issue does not attempt.

## 1. Sizing

Based on what #183 (live conformance, 4 break modes), #266 (cold-container
smoke test) and #269 (exec/kill/export through the real backend) need, plus
dind's own overhead, at one workflow at a time (matches
`WOODPECKER_MAX_WORKFLOWS` default of 1 - no override needed):

- **vCPU: 2.** One for the outer agent/dind daemon overhead, one for the
  nested test containers (python:3.12-slim runner plus small subject
  containers) - these tests run one at a time, not under load.
- **RAM: 8 GiB.** dind itself, the nested daemon's own image store, the
  python:3.12-slim test runner, and the small containers #183/#266/#269
  start and kill - none of this is memory-heavy individually, but dind's
  own baseline plus headroom for an unexpected image pull argues for
  comfortable rather than minimal.
- **Disk: 60 GB, SSD if available.** The OS, Docker engine, and the AGENT's
  own (outer) image cache persist normally across runs. The NESTED daemon
  inside the dind service does not: this design deliberately avoids a
  host-mounted volume for the dind service (to avoid needing
  `trusted.volumes` on top of `trusted.security`), so every run's inner
  image cache starts empty and re-pulls whatever the tests need. That's a
  conscious trade-off (narrower privilege, slower runs) worth revisiting
  later if run time becomes a problem, not something to fix by adding the
  volume back now.
- **OS: whatever current Linux amd64 distribution matches the operator's
  standard provisioning** - the server already expects `platform=linux/amd64`
  from every agent; no other agent-side OS requirement is implied by
  anything in this design.

## 2. Software

- **Woodpecker agent version: must match the server's.** Checked directly:
  this server reports **version 3.13.0** via its own `/version` endpoint.
  Install the matching agent release, not merely "the latest."
- **Backend: `docker`** (every agent in this instance's pool already runs
  this backend; no reason to diverge).
- **Docker engine:** a current stable release the operator's standard image
  already provides; no version-specific requirement surfaced by this design
  beyond supporting `docker:dind` and `privileged: true`.
- **Nothing else** this design needs beyond the agent binary and a working
  Docker engine - the per-clone test toolchain (Python, `uv`) is installed
  inside the pipeline's own step containers, not on the agent host.

## 3. Agent configuration

- **Logical label:** `docker-ci: "yes"` (placeholder name - substitute the
  operator's preferred convention).
- **`WOODPECKER_MAX_WORKFLOWS=1`** (the default; stated explicitly here so
  it's a deliberate choice, not an accident of not having configured it).
- **Privileged allowance scoped to this agent only** via this repository's
  `trusted.security=true` - verified live against this server: currently
  `{"network": false, "volumes": false, "security": false}`. Enabling it is
  repo-wide, not agent-wide (Woodpecker has no per-agent privileged-allow
  setting - see §4), which is exactly why this agent must be the only one
  that could ever be scheduled for this repo's privileged workflow.
- **A dedicated, non-login OS user** for the agent process on `<agent-host>`
  - ordinary host-level hygiene; it does not substitute for VM-level
  isolation (§ "Why dedicated" above) because `privileged: true` operates
  below the Unix-user layer.
- **Network:** outbound only, to `<server-grpc-endpoint>` (this Woodpecker
  instance's agent gRPC port) and to whatever image registries the pipeline
  pulls from; no inbound access beyond whatever the operator's own
  management/SSH access requires.
- **Agent token:** issued via this server's normal agent-registration flow
  (Settings -> Agents -> Add agent, or the equivalent CLI/API call), stored
  wherever the operator keeps other agent secrets for this instance - no
  new storage mechanism implied by this design.

## 4. The prod-host / shared-pool exclusion - verified facts and an open item

**What's verified:**
- Woodpecker's label match is "every label the *agent* requires must be
  satisfied by the *workflow*." Several agents in this instance's existing
  pool declare no distinguishing labels at all, so they are default
  candidates for nearly any workflow regardless of what extra label a
  workflow also carries - extra labels on the workflow side never
  disqualify an undemanding agent.
- Woodpecker 3.11+ supports a mandatory `!key=value` agent label (the
  workflow must carry a matching label or that agent refuses it). This is
  configured per-agent, by that agent's own operator.
- Every workflow automatically carries a `repo=<org>/<name>` label, with no
  change to its own pipeline file required.
- Searched specifically for an OR or negation operator in Woodpecker's
  label-filter syntax (e.g. "accept any repo except X") and found none
  documented. Filters appear to be single `key=value` (or `key=*`) pairs,
  matched by exact value or wildcard only.
- There is **no native Woodpecker setting that lets an agent refuse a
  privileged step independent of the repository's own `trusted.security`
  flag.** One unofficial third-party reverse-proxy pattern exists in the
  community (filtering requests to the container socket independently of
  what the orchestrating server permits) - unverified by this issue beyond
  one search result, not recommended without separate vetting.

**What follows, stated plainly because the review asked for plainness
here:** the auto-attached `repo=` label *could* be used as an allowlist on
an existing agent (e.g. requiring `repo=<some-other-repo>`), but this pool
currently serves three repositories' CI interchangeably across its agents,
and an allowlist on any one agent would need to name every repo that agent
must keep serving - not a single clean "exclude skillc" rule, and not
something expressible without knowing the pool's current capacity
distribution across those three repositories. **I don't have that
visibility from here, and getting it wrong risks exactly the CI-outage-on-
another-repo's-main the review warned about.** This is an infrastructure
decision for whoever has that visibility (the operator), not something this
issue can safely resolve on its own authority.

**Open item for the operator:** decide whether to (a) treat agent-pool
exclusivity as its own follow-up infrastructure task - reviewing the
existing pool's labels/capacity across all three repositories and applying
allowlists where capacity allows, tracked separately from this agent's
provisioning; or (b) accept, for now, the weaker guarantee available
without touching any other repository or agent: the dedicated agent is
*requested* by label and *verified empirically* (next section) to be where
the workflow actually lands in practice, while knowing this is not a proof
against some future, equally undemanding agent joining the same pool.
Either way, **nothing here is a substitute for making `trusted.security`
only as true as this repo needs it to be** - no finer-grained setting
exists to fall back on if neither (a) nor (b) is satisfactory.

**Negative control for whichever mechanism is chosen:** before relying on
it, push a harmless, non-privileged smoke workflow that requests the
`docker-ci` label, run it repeatedly (enough runs that landing on the wrong
agent by chance would show up), and confirm it always lands on the
dedicated agent. If (a) is chosen, also confirm normal kyle/claude-power-pack
pipelines still schedule exactly as before the pool changed - a passing
smoke test on the new agent proves nothing about whether an unrelated
pipeline just broke.

## 5. Ordered enablement

1. Provision `<agent-host>` (§1-§2).
2. Register it against this Woodpecker instance; set its label to
   `docker-ci: "yes"` and nothing else that would make it a candidate for
   unrelated workflows (§3).
3. Resolve §4's open item (exclusivity mechanism) and apply whatever it
   decides - or explicitly accept the weaker guarantee and record that
   choice here.
4. Run the negative control in §4 (repeated smoke workflow) and confirm the
   result before proceeding.
5. Enable `trusted.security=true` on `cooneycw/skillc` only.
6. Land the `.woodpecker.yml` change proposed in #309 (not before now).
7. First real run: confirm the real-Docker tests go **red** against the
   pre-change commit and **green** on the head that adds the step - the
   same standard already applied to #307's own checker.

## 6. Rollback

Unset `trusted.security` on `cooneycw/skillc`; deregister the agent from
this Woodpecker instance; revert the `.woodpecker.yml` step if it was ever
merged. No other repository's configuration needs touching to roll this
back, regardless of which §4 option was chosen for enablement.

---

No `.woodpecker/` change for #309 merges until the operator confirms steps
1-2 above are actually done, per the standing instruction on #309 itself.

