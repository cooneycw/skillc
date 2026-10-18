# Trial image and agent bootstrap

- Status: Partially implemented - `skillc/trial_bootstrap.py` and
  `docker/trial/` (#78); consumed by `skillc/docker_backend.py` (#77's
  interface landed, its lifecycle implementation a follow-up PR)
- Date: 2026-09-26
- Governing documents: [interfaces](interfaces.md), issue #10's "Operating
  lessons from running Claude Code and Codex in Docker" comment (sections A
  and B are required reading before changing anything this document covers)

## What it does

Makes a live agent actually start and do work inside a Docker trial
container, rather than silently doing nothing while reporting exit 0. Every
failure mode this addresses was measured, at least once, on a sibling
platform, and every one of them looked healthy from outside the container:

| Failure | Looked like | Prevented by |
|---|---|---|
| Fresh `$HOME` wedges on an interactive first-run gate | A running, unresponsive container | `compose_claude_seed`, seeded per trial, never shared |
| Codex missing its `codex-code-mode-host` sidecar | Fluent prose, zero tool calls, exit 0, `codex doctor` all-ok | `docker/trial/verify_codex_sidecar.js`, run at build time |
| `codex exec --sandbox workspace-write` without bubblewrap | Every shell command declined, still exit 0 | Deliberate unsandboxed choice, `BWRAP_DECISION` |
| A prompt delivered by simulated keystrokes, retried or altered | A transcript that looks plausible | `verify_first_user_message` against the transcript's first user message |
| An agent that answers in prose without doing the work | A transcript that looks plausible | `check_canary`: requires a skill invocation AND a tool use, tagged with a per-attempt nonce |
| A shared or reused per-trial home | A credential or state leak across trials | `build_trial_home` refuses to reuse an existing tree |

## Boundary with #10's other pieces

- **Not this document's job:** the `ExecutionBackend` implementation itself
  (`skillc/docker_backend.py`, #77) - argv composition for `docker run`,
  resource limits, network isolation, `confirm_stopped`/`confirm_absent`.
  This document's functions are called BY that backend's `install()` and
  `execute()`, never the reverse; nothing here imports `docker_backend`.
- **Not this document's job:** the generic, backend-planted, content-diff
  liveness check `skillc/lifecycle.py` already performs (`CANARY_NONCE_KEY`,
  distinct from this document's `AGENT_CANARY_NONCE_KEY`). That check proves
  *something* changed between two `export()` snapshots; this document's
  canary proves the *agent itself* invoked a real skill and a real tool,
  which a content diff cannot distinguish from the agent's own unrelated
  file writes.
- **Not this document's job:** translating a specific client's real on-disk
  transcript format into the normalized event shape
  `verify_first_user_message` and `check_canary` read (`{"role": ...}`,
  `{"type": "skill_invocation", ...}`, `{"type": "tool_use", ...}`). That
  per-client adapter is owed to the live run, the same kind of gap
  `skillc/backend.py`'s own docstring states for `docker_backend.py` itself.

## Onboarding seed: closed schema

`compose_claude_seed` sets exactly four things - `hasCompletedOnboarding`,
`bypassPermissionsModeAccepted`, and per-`workdir`
`hasTrustDialogAccepted`/`enabledMcpjsonServers` - and
`validate_seed_before_launch` refuses a seed carrying any key outside that
set. This is deliberately closed rather than an allowlist grown over time: an
undeclared key is something ELSE deciding a prompt on the agent's behalf,
which is exactly the class of silent failure this module exists to prevent.
A seed is pinned to the exact CLI version it was measured against, because
Claude Code rewrites this file on first start and has been observed to drop
acceptance keys across versions (issue #10 lesson A1).

## Liveness canary: two independent checks, not one event, and output-only

`check_canary` requires BOTH a `skill_invocation` event naming the installed
skill and a `tool_use` event whose CONFIRMED, error-free `output` carries the
per-attempt nonce - checked independently rather than requiring one event to
satisfy both, because a client may model "invoke a skill" and "use a tool" as
separate transcript events, and collapsing them would make the check brittle
to a client whose skill invocation is not itself a tool call. Matching only
`output`, never `input`, matters: a Codex code-review finding on issue #78
caught an earlier version matching the whole serialized event, which a
REQUESTED-but-denied-or-failed tool call satisfies just as well as a
completed one - the nonce a caller asks a tool to write is present in the
request whether or not the tool ever ran. The nonce is generated fresh per
attempt (`new_canary_nonce`) and is meaningless outside that one transcript,
so satisfying one attempt's canary proves nothing about another's.

## Client-specific invocation flags are not generic

`build_invocation`'s `supports_name` parameter is required, not defaulted,
because `--name` is real for exactly one pinned client. Claude Code's own
binary documents `--name <name>` ("Name for the session (shown in
claude.ai/code)"), confirmed by extracting the pinned 2.1.283 tarball; the
pinned Codex release's `exec` subcommand parser accepts no such flag,
confirmed against its source at `rust-v0.157.1`. A Codex code-review finding
on issue #78 caught an earlier version of this function appending `--name`
to any client's argv unconditionally, which would have failed Codex's own
argument parsing before a trial even started - a generic-looking helper is
not automatically client-agnostic, and this module states explicitly, per
function, which claims are pinned-CLI-specific.

## Egress: provider-only, and what it does not cover (#442)

A live agent container reaches its model provider and nothing else. This
reverses the owner's #11 ruling (open egress for agent containers) for the
#288 study: skillc's graders, fixtures and expected outcomes live in a public
repository, so an open container could fetch the grader it is judged by.

`DockerBackend(egress=True)` (`skillc/egress.py`) gives each attempt:

- its own Docker `--internal` network and nothing else. An internal network has
  no gateway and no NAT, so a client that ignores proxy settings has no route
  out at all (measured on the runner: "Network is unreachable");
- no external name resolution. An internal network resolves no external name
  even with `--dns` set (measured on the runner, Docker 29.8.2); `--dns 0.0.0.0`
  is defence in depth;
- a per-attempt proxy container, on that network and the default bridge, that
  forwards `CONNECT host:443` only for `egress.ALLOWED_HOSTS` (`chatgpt.com`,
  `auth.openai.com`) and logs every request. The agent gets the proxy's address
  in its proxy environment. The log is captured into the attempt's artifact
  manifest as the `egress-proxy-log` stream; its first line records the
  allowlist and its digest.

The allowlist is a measurement, re-taken whenever the pinned client changes:
pinned codex 0.157.1 with ChatGPT auth, through a logging CONNECT proxy, with
`strace -f -e trace=connect` on the whole process tree. Every connection went
through the proxy and the client resolved no names itself. `ab.chatgpt.com` was
denied and the run still succeeded; `*.oaiusercontent.com` was not contacted
once plugins were disabled. `auth.openai.com` is allowed for token refresh by
ruling (not exercised in the measurement).

**Container egress covers CLIENT-SIDE fetches only.** A tool that runs at the
model provider never touches the container's network, so no egress rule can
stop it. Measured with the pinned client: by default `codex debug prompt-input`
lists **16 OpenAI-curated remote plugins** to the model, among them `GitHub
(github@openai-curated-remote)`; disabling any one of `apps`, `plugins` or
`remote_plugin` removes all 16. Server-side web search is a separate channel.
Both are closed in the client's own argv (`egress.CODEX_SERVER_SIDE_OFF`):
`--strict-config -c web_search="disabled" --disable apps --disable plugins
--disable remote_plugin`. `--strict-config` makes an unknown or renamed key an
error rather than a silently ignored one.

Two checks enforce it:

- **Preflight, before any container exists**: `agent_trial.run_one_attempt`
  refuses (`ServerSideChannelRefused`) a live codex attempt whose argv lacks any
  of those flags or re-enables one later in the argv, and a live codex attempt
  on an open network with no egress policy.
- **After every attempt**: `agent_trial.server_side_tool_uses` reads the stored
  transcript, both item types and call names (a remote plugin can surface as a
  `function_call` with a namespaced name), plus the census line types. Any
  server-side tool use blocks grading with `not credited: server-side tool
  observed (<type>)`. The attempt stays in every account with that reason; it is
  never dropped from a population or denominator.

**Re-measure on every client bump.** A later client can add a server-side
feature these flags do not name. Bumping the pinned codex means re-running both
measurements (the egress hosts and `codex debug prompt-input`) before a live run.

Not covered: Claude Code live attempts. Its server-side web search is not pinned
off here, and #288 runs codex only.

The real-Docker controls (`tests/test_agent_egress_live.py`, in the runner's
floor) check from inside a live-configured container that the provider is
reachable through the proxy, GitHub is refused by it, and a proxy-ignoring
client has no route and resolves no name. The `egress:allow-all`,
`egress:bridge-network` and `egress:dns-hosts` break modes each make exactly one
of those fail. The proxy serves only clients from the attempt network's own
subnet, so a neighbouring container on the shared bridge cannot add to an
attempt's log.

**Readiness (#460).** `prepare()` returns only once the proxy accepts TCP
connections. The backend probes it from inside the proxy's own container
(`egress.READY_SOURCE` via `docker exec`), polling until
`DockerBackend.egress_ready_seconds` runs out (30 s by default). On expiry it
refuses the attempt with `BackendUnavailable` and removes the proxy and the
network. Before #460, a proxy slower to start than the agent container
refused the agent's first CONNECTs (`Errno 111`). The proxy's `start` log line
is written only after the port is bound, so it means "listening". The probe
is a loopback peer, and **only a process inside the proxy container can be a
loopback peer**. So a loopback client outside the attempt subnet is closed
without a log record. The exemption is exactly `127.0.0.0/8`: every other
client outside the subnet is still logged `peer-rejected`. The allowlist, its
digest, the server-side codex flags and the network label are unchanged.

## A per-trial seed is bound to exactly one project and one CLI version

`validate_seed_before_launch` requires `projects` to contain EXACTLY one
entry - the `workdir` being launched into - and requires the seed's recorded
`_skillc_seed_cli_version` to exactly match the version about to launch, both
supplied as required (not optional) parameters. Two Codex code-review
findings on issue #78 caught the earlier, weaker versions of these checks: a
seed carrying an undeclared SECOND project could pass with that project's own
acceptance settings unexamined, and a seed merely marked with SOME version
(any non-empty string) would validate for launching a completely different,
pinned CLI - neither failure would have surfaced as anything other than a
correctly-formed JSON file passing a schema check that proved less than it
claimed to.

## Controls (committed)

All in `tests/test_trial_bootstrap.py`:

- An empty transcript (a fake client that exits 0 having done nothing) is
  refused by `check_canary` as not-live.
- A transcript with plausible assistant prose but no `skill_invocation`/
  `tool_use` events is refused the same way.
- A tool call whose nonce appears only in its request (`input`), because it
  was denied or failed, is refused - only a confirmed, error-free `output`
  satisfies the canary.
- A transcript whose first user message differs from the prompt sent is
  refused by `verify_first_user_message`.
- A seed carrying an undeclared key, an unaccepted trust dialog, a stale CLI
  version, a second undeclared project, or a missing file is refused by
  `validate_seed_before_launch` - never a hang.
- An invocation for a client that does not support `--name` gets no such
  flag; one for `--remote-control`, or one whose `extra_env` tries to
  override `GIT_TERMINAL_PROMPT` away from `"0"`, is refused by
  `build_invocation`.
- A stale `ARG` default in `docker/trial/Dockerfile` against
  `pinned-versions.json` is reported by `docker/trial/check_pins.py`; an
  unrelated ARG is not; a new manifest pin with no matching ARG is caught
  without a second, hand-maintained mapping to keep in sync.
- `docker/trial/verify_codex_sidecar.js` (run under Node against a fake
  platform-package layout - no Docker needed) refuses a missing sidecar, a
  directory posing as one, a non-executable file, and an absent platform
  package.

## Evidence rule

The seed, home, MCP config, invocation and canary-checking logic are proven
here, in this repository, without Docker. Whether the pinned image actually
builds, whether `codex-code-mode-host` lands beside `codex` at build time,
and whether a real CLI started this way starts un-wedged, are all owed to a
live run with a Docker daemon - see `docker/trial/README.md` for exactly
which of those this PR could and could not exercise from this session.
