"""Provider-only network egress for LIVE agent containers (#442).

A live agent container joins ONE per-attempt Docker `--internal` network and
nothing else. An internal network has no gateway and no NAT, so a direct TCP
connection to any outside address has no route: that, not a proxy setting, is
what stops a client that ignores `HTTPS_PROXY`. The only way out is a
per-attempt proxy container that sits on that network AND the default bridge,
accepts `CONNECT host:443` for the hosts in `ALLOWED_HOSTS` and nothing else,
and logs every request. The agent gets the proxy's address in its proxy
environment and no DNS server (`AGENT_DNS`): with a proxy the client needs no
name resolution of its own (measured, below), so DNS is closed rather than left
as a channel.

This reverses the owner's #11 ruling (open egress for agent containers) for the
#288 study: skillc's graders live in this PUBLIC repository, and an open
container could fetch the grader it is judged by.

WHAT THIS COVERS - CLIENT-SIDE FETCHES ONLY. A tool that runs at the model
provider (a server-side web search, a remote plugin or app) never touches the
container's network, so no egress rule can stop it. Those channels are closed
by the client's own declared configuration (`collection_conformance.
DEFAULT_CLIENT_ARGVS`, refused at preflight when missing) and checked after
every attempt by the transcript census (`agent_trial.SERVER_SIDE_LINE_TYPES`),
which blocks grading when one appears. See `docs/specs/evaluation-facility/
trial-bootstrap.md`, "Egress".

THE ALLOWLIST IS A MEASUREMENT, re-taken whenever the pinned client changes
(`MEASUREMENT` records the run it came from). It is never widened by guessing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

#: The only hosts a live agent's proxy forwards to, on port 443. Measured
#: 2026-10-17 (#442): pinned codex 0.157.1 with ChatGPT auth, through a
#: logging CONNECT proxy and `strace -f -e trace=connect` on the whole process
#: tree, with the server-side flags pinned. `auth.openai.com` is allowed by the
#: orchestrator's ruling for token refresh (OpenAI-controlled; not exercised in
#: the measurement).
ALLOWED_HOSTS: tuple[str, ...] = ("auth.openai.com", "chatgpt.com")
PROXY_PORT = 3128
#: The agent's DNS server: none that answers. The client resolves nothing
#: itself when a proxy is set (measured), so a lookup can only be a channel.
AGENT_DNS = "0.0.0.0"
#: Where the proxy writes its log inside its own container.
PROXY_LOG_PATH = "/tmp/skillc-egress-proxy.log"
#: The manifest observation stream the proxy log is captured as.
PROXY_LOG_STREAM = "egress-proxy-log"
#: The role label the proxy container carries beside the ownership labels, so a
#: reader of `docker ps` can tell it from the agent container.
ROLE_LABEL_KEY = "skillc.role"
PROXY_ROLE = "egress-proxy"

MEASUREMENT: Mapping[str, object] = {
    "date": "2026-10-17",
    "issue": 442,
    "client": "codex 0.157.1",
    "auth": "chatgpt",
    "method": "logging CONNECT proxy + strace -f -e trace=connect on the whole process tree",
    "observed_with_server_side_flags": ["chatgpt.com", "ab.chatgpt.com"],
    "denied_and_run_still_succeeded": ["ab.chatgpt.com"],
    "not_contacted_with_plugins_disabled": ["*.oaiusercontent.com"],
    "direct_connects_bypassing_proxy": 0,
    "dns_lookups_by_client": 0,
    "allowed_by_ruling_unexercised": ["auth.openai.com"],
}


def allowlist_document(hosts: Sequence[str] = ALLOWED_HOSTS) -> dict[str, object]:
    """The allowlist as the proxy logs it on its first line."""
    return {"policy": "provider-only", "issue": 442, "hosts": sorted(hosts), "port": 443,
            "measurement": dict(MEASUREMENT)}


def allowlist_digest(hosts: Sequence[str] = ALLOWED_HOSTS) -> str:
    raw = json.dumps(allowlist_document(hosts), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


#: The proxy itself: stdlib only, run by the trial image's own `python3`, so
#: there is no second image to pin. argv: port, log path, allowlist JSON.
#: `decide()` is the whole policy and is exercised in-process by the tests.
PROXY_SOURCE = r'''
import asyncio, json, sys, time

def decide(target, hosts):
    """CONNECT host:443 for an exactly-listed host; everything else refused."""
    host, sep, port = target.rpartition(":")
    if not sep or not host or port != "443":
        return False
    return host.lower().rstrip(".") in hosts

async def _pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass

def main():
    port, log_path, allow = int(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
    hosts = frozenset(h.lower() for h in allow["hosts"])
    log = open(log_path, "a", buffering=1)
    log.write(json.dumps({"event": "start", "allowlist": allow, "digest": sys.argv[4]}) + "\n")

    def record(method, target, decision):
        log.write(json.dumps({"t": round(time.time(), 3), "method": method, "target": target,
                              "decision": decision}) + "\n")

    async def handle(cr, cw):
        try:
            head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 30)
            method, target, _ = head.split(b"\r\n", 1)[0].decode("latin1").split(" ", 2)
        except Exception:
            cw.close()
            return
        if method != "CONNECT" or not decide(target, hosts):
            record(method, target, "denied")
            cw.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await cw.drain()
            cw.close()
            return
        host, _, port_text = target.rpartition(":")
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(host, int(port_text)), 30)
        except Exception as exc:
            record(method, target, "upstream-failed: " + type(exc).__name__)
            cw.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await cw.drain()
            cw.close()
            return
        record(method, target, "allowed")
        cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await cw.drain()
        await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))

    async def serve():
        server = await asyncio.start_server(handle, "0.0.0.0", port)
        async with server:
            await server.serve_forever()

    asyncio.run(serve())

if __name__ == "__main__":
    main()
'''


def network_name(container_name: str) -> str:
    return f"{container_name}-egress"


def proxy_name(container_name: str) -> str:
    return f"{container_name}-proxy"


def create_network_argv(docker_bin: Sequence[str], network: str, labels: Mapping[str, str]) -> list[str]:
    """`--internal`: no gateway, no NAT - a container on ONLY this network has
    no route out except through another container that bridges it."""
    argv = [*docker_bin, "network", "create", "--internal"]
    for key, value in labels.items():
        argv += ["--label", f"{key}={value}"]
    return [*argv, network]


def proxy_run_argv(
    docker_bin: Sequence[str], *, image: str, name: str, labels: Mapping[str, str], container_user: str,
    hosts: Sequence[str] = ALLOWED_HOSTS,
) -> list[str]:
    """The proxy container, started detached on the default bridge (it needs
    DNS and egress to reach the allowed hosts); `network connect` then joins it
    to the attempt's internal network."""
    argv = [*docker_bin, "run", "-d", "--name", name]
    for key, value in labels.items():
        argv += ["--label", f"{key}={value}"]
    allow = json.dumps(allowlist_document(hosts), sort_keys=True)
    return [
        *argv, "--label", f"{ROLE_LABEL_KEY}={PROXY_ROLE}",
        "--network", "bridge", "--user", container_user, "--init",
        "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64", "--cpus", "0.5",
        "--", image, "python3", "-c", PROXY_SOURCE, str(PROXY_PORT), PROXY_LOG_PATH, allow,
        allowlist_digest(hosts),
    ]


def network_connect_argv(docker_bin: Sequence[str], network: str, container: str) -> list[str]:
    return [*docker_bin, "network", "connect", network, container]


def proxy_address_argv(docker_bin: Sequence[str], network: str, container: str) -> list[str]:
    """The proxy's IPv4 address ON the internal network. The agent is given
    this address, not a name, so its proxy setting needs no DNS."""
    template = "{{(index .NetworkSettings.Networks " + json.dumps(network) + ").IPAddress}}"
    return [*docker_bin, "inspect", "-f", template, container]


def agent_proxy_env(proxy_ip: str) -> dict[str, str]:
    """Both spellings: clients disagree on which they read. `NO_PROXY` is set
    empty so nothing inherited can exempt a host."""
    url = f"http://{proxy_ip}:{PROXY_PORT}"
    env: dict[str, str] = {}
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        env[key] = url
        env[key.lower()] = url
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""
    return env


def proxy_log_argv(docker_bin: Sequence[str], container: str) -> list[str]:
    return [*docker_bin, "exec", container, "cat", PROXY_LOG_PATH]


def remove_network_argv(docker_bin: Sequence[str], network: str) -> list[str]:
    return [*docker_bin, "network", "rm", network]


def summarize_log(raw: bytes) -> dict[str, object]:
    """Allowed and denied targets with counts, and the allowlist digest the
    proxy itself recorded. A log that cannot be read says so; it is never an
    empty clean one."""
    allowed: dict[str, int] = {}
    denied: dict[str, int] = {}
    upstream_failed: dict[str, int] = {}
    digest: str | None = None
    unparsed = 0
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            unparsed += 1
            continue
        if entry.get("event") == "start":
            digest = entry.get("digest")
            continue
        decision = str(entry.get("decision"))
        bucket = (allowed if decision == "allowed" else denied if decision == "denied"
                  else upstream_failed if decision.startswith("upstream-failed") else None)
        if bucket is None:
            unparsed += 1
            continue
        target = str(entry.get("target"))
        bucket[target] = bucket.get(target, 0) + 1
    return {"allowlist_digest": digest, "allowed": allowed, "denied": denied, "upstream_failed": upstream_failed,
            "unparsed_lines": unparsed}


#: The codex client's server-side channels, pinned OFF for every live attempt
#: (#442, B2). Measured 2026-10-17 with pinned codex 0.157.1: by default
#: `codex debug prompt-input` lists 16 OpenAI-curated REMOTE PLUGINS to the
#: model, among them `GitHub (github@openai-curated-remote)`; disabling any one
#: of `apps`, `plugins` or `remote_plugin` removes all 16, and all three are
#: pinned so the result does not rest on which flag gates which. `web_search`
#: is a validated enum (`disabled`/`cached`/`indexed`/`live`); `--strict-config`
#: makes an unknown or renamed key an error rather than a silently ignored one.
#: RE-MEASURE ON EVERY CLIENT BUMP: a later client can add a server-side feature
#: these flags do not name.
CODEX_SERVER_SIDE_DISABLED_FEATURES: tuple[str, ...] = ("apps", "plugins", "remote_plugin")
CODEX_WEB_SEARCH_OFF = 'web_search="disabled"'
CODEX_SERVER_SIDE_OFF: tuple[str, ...] = (
    "--strict-config", "-c", CODEX_WEB_SEARCH_OFF,
    *(flag for feature in CODEX_SERVER_SIDE_DISABLED_FEATURES for flag in ("--disable", feature)),
)


def _config_settings(argv: Sequence[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Every config-affecting setting in argv ORDER, as `(kind, value)`:
    `("config", "<key>=<value>")` for `-c X`/`--config X`/`--config=X`/`-cX`,
    and `("enable"|"disable", feature)` for `--enable X`/`--disable X` and
    their `=` forms. Also the spellings it could not read with certainty
    (an option with no value), which the caller refuses rather than guesses."""
    settings: list[tuple[str, str]] = []
    unreadable: list[str] = []
    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        for flag, kind in (("-c", "config"), ("--config", "config"), ("--enable", "enable"), ("--disable", "disable")):
            if arg == flag:
                if i + 1 >= len(args):
                    unreadable.append(arg)
                else:
                    settings.append((kind, args[i + 1]))
                    i += 1
                break
            if flag.startswith("--") and arg.startswith(flag + "="):
                settings.append((kind, arg.split("=", 1)[1]))
                break
            if flag == "-c" and arg.startswith("-c") and not arg.startswith("--") and len(arg) > 2:
                settings.append((kind, arg[2:]))
                break
        i += 1
    return settings, unreadable


def missing_server_side_flags(argv: Sequence[str]) -> list[str]:
    """What a live codex argv lacks of `CODEX_SERVER_SIDE_OFF`, or does to
    undo it, as one sentence each; empty only when every channel is pinned off
    and nothing later in the argv turns one back on. Settings are read in argv
    ORDER, every spelling the client accepts (`-c X`, `-cX`, `--config X`,
    `--config=X`, `--enable/--disable X` and their `=` forms), and the LAST
    setting of each key wins, as in the client."""
    problems: list[str] = []
    if "--strict-config" not in argv:
        problems.append("--strict-config is missing (an unknown or renamed key would be silently ignored)")
    settings, unreadable = _config_settings(argv)
    for flag in unreadable:
        problems.append(f"{flag} has no value; the argv cannot be read with certainty")
    web: str | None = None
    features: dict[str, bool] = {}
    for kind, value in settings:
        if kind == "config":
            key, _, raw = value.replace(" ", "").partition("=")
            if key == "web_search":
                web = f"{key}={raw}"
            elif key.startswith("features."):
                features[key.removeprefix("features.")] = raw.lower() == "true"
        else:
            features[value] = kind == "enable"
    if web is None:
        problems.append('-c web_search="disabled" is missing (server-side web search stays at the client default)')
    elif web != CODEX_WEB_SEARCH_OFF:
        problems.append(f"web_search is set to {web!r}, not {CODEX_WEB_SEARCH_OFF!r} (the last setting wins)")
    for feature in CODEX_SERVER_SIDE_DISABLED_FEATURES:
        if feature not in features:
            problems.append(f"--disable {feature} is missing (a server-side remote plugin channel stays open)")
        elif features[feature]:
            problems.append(f"{feature} is re-enabled later in the argv (the last setting wins)")
    return problems
