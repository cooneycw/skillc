# Multi-container wave runtime (#621, first slice)

`skillc.docker_wave.DockerWave` owns multiple role containers under one wave
attempt. This first slice supplies the runtime and model-free lifecycle tests.
It makes **no real-daemon containment or delivery claim** and does not close
#621. It adds no CLI, paid invocation, study declaration or wake scheduler.

## Frozen topology

Every role owns one `DockerBackend` container, private project clone, home and
PID namespace. The controller creates one internal wave bridge with
`com.docker.network.bridge.enable_icc=false`. Each role joins it as well as its
own existing internal provider-egress network, with its existing allowlisting
proxy. Roles never join another role's provider-egress network.

There are exactly two application surfaces shared between roles:

- One controller-owned named wave-state volume, mounted read/write at
  `/run/skillc-wave`. Both `FLOW_WAVE_MAILBOX_DIR` and `FLOW_WAVE_REGISTRY_DIR`
  resolve there. The mount accepts a controller volume name, never a host path
  or arbitrary target. Workspace and home still move by `docker cp`.
- One controller-owned fixture git daemon, connected to each role's private
  egress network. Every role clones its remote into its own `/work`. The daemon
  starts from a copied controller fixture; it does not share a project clone
  with a role. No host port is published.

The bridge's ICC setting is a composed policy until qualified on a real daemon.
The fixture service and provider proxies are declared infrastructure. Roles
receive neither the Docker socket nor shared PID namespaces. Existing individual
backend callers retain their original argument composition and behavior.

## Turn and deadline ownership

`Role` declares a name, base argv, first literal prompt, role timeout and optional
literal resumed prompts. `run_scripted()` starts one thread per role. A failed,
cancelled or timed-out role stops independently; its siblings continue within
the common deadline. A turn cannot overlap another turn for that role.

`turn()` reads the session ID only from its first exec's controller-captured
stderr header using `controller_turns.session_id_from_header`. It never reads an
agent-editable session file. A missing or partial header prevents resumption.
Resume uses that role's own base argv and ID; disagreement in a resumed header
is retained as unknown evidence. Dynamic wake scheduling belongs to #622; a
caller delivering dynamic turns must bind its literal texts in its declaration.

A single `CompletionDeadline` starts before resource setup and is passed to all
role executions. Setup and execution refuse dispatch when it is exhausted.
Capture, provisional evidence publication and the leak scan are measured against
that same endpoint. Cleanup continues after exhaustion so resources can still be
retired, but completion then reports `on_time: false`. Final report emission is
explicitly outside the measured completion endpoint.

## Capture and retirement

The controller retains each turn's original stdout/stderr, execution metadata,
project artifacts and `.codex/sessions` transcript files, including resumed
turns. Transcript payloads receive content-addressed filenames; untrusted client
filenames are retained only as index keys. The credential directory is never
exported. Each role's guard is installed through the existing root-owned guard
installer. This model-free slice copies in no credentials and grants no live
client authority. Future live callers must use the existing credential freshness,
copy-in and guard accounting contracts per role.

Retirement proceeds in this order:

1. End every role and independently confirm its stop.
2. Export confirmed-stopped roles, shared wave state and the fixture remote.
3. Stop and remove the fixture service. Its endpoints must disappear before role
   backends can remove their private egress networks.
4. Destroy each role, including its proxy/network, and independently confirm
   absence. Finalize its guard channel and retain its record.
5. Remove the wave volume and network and independently list resources to
   confirm absence. A failed removal alone proves neither presence nor absence.

An unreachable daemon returns unknown observations. Missing planned roles,
unconfirmed stops/removals and capture failures remain explicit. The report's
status is deliberately `UNKNOWN` and its scope is `runtime-lifecycle-only`:
this seam does not grade a task, certify transcript coverage or infer CPP peer
liveness. The raw shared-state snapshot preserves CPP's own readings. No harness
process observation substitutes for those readings.

## Controls and remaining qualification

`tests/test_docker_wave.py` covers distinct header-derived sessions/resumes,
sibling independence, unavailable-daemon cleanup, partial preparation failure,
idempotence and closed mount arguments. Its real `DockerBackend` integration
runs trusted deterministic Python actors through the existing fake Docker CLI.
The private egress networks and fixture endpoints are represented in that fake;
the common wave network, shared volume, clone and guard installation are modeled.
The test explicitly makes no kernel isolation or shared-volume delivery claim.

The committed `remote-refuses-removal` case leaves the fixture service attached;
it must prevent confirmed role-network removal and completion. Reordering role
network removal before fixture retirement makes the intact test fail. Committed
`controls/docker-wave/cases.json` inputs also distinguish an open peer channel
from isolation and an unavailable/dead listener from either verdict.

The next slice must exercise both directions of volume delivery, each role's own
shell-origin forbidden egress and nested-client actions, separate PID namespaces,
and every ordered peer TCP leg with a live listener before and after it. Its
negative control must enable ICC and make the same isolation assertion fail.
Actual protections and cleanup need real-daemon evidence through the existing
qualification lane. This slice does not change that lane or its runner.

This implementation adopts the three-valued observation and ordered retirement
principles referenced by #621, but copies no source text from another repository.
