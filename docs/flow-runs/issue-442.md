# Flow run record - issue #442

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=3cff4a54a8354d0f85b0084e89ca50bb -->
## Run 1

- Run-id:            3cff4a54a8354d0f85b0084e89ca50bb
- Run-start:         dae6785166a0378612a29e3b1a05bd42a16af76c
- Issue:             #442
- Base SHA:          dae6785
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T21:20:00Z

### Section B evidence
Since #442 was filed (2026-10-17): no commit on origin/main touches skillc/docker_backend.py network/argv, skillc/collection_conformance.py AGENT_NETWORK/DEFAULT_CLIENT_ARGVS, or skillc/agent_trial.py census/eligibility; no PR references #442; no duplicate or superseding issue. Design approved on #442 (comment 6240675972) with rulings; measurements on #442 (comment 6240788282): allowlist chatgpt.com + auth.openai.com (ab.chatgpt.com denied and exec still works; *.oaiusercontent.com not contacted with plugins disabled); B2 remote-plugin channel (16 curated remote plugins incl. GitHub in default prompt-input; any of apps/plugins/remote_plugin disabled removes all).

### Section C - the approved plan
1. `skillc/egress.py` - new: committed allowlist constant + measurement record + digest; stdlib allowlisting CONNECT proxy script run by the trial image's python3; docker argv builders for per-attempt internal network, proxy container (bridge then network connect), agent proxy env, teardown with log export and digest.
2. `skillc/docker_backend.py` - `egress` field; prepare() creates internal network + proxy and starts the agent only on the internal network with --dns 0.0.0.0 and proxy env; destroy() exports the proxy log and removes proxy and network; describe() states the policy; compose_run_argv optional dns.
3. `skillc/collection_conformance.py` - replace AGENT_NETWORK "bridge" and the #11 ruling with #442's policy; agent_backends builds the egress-managed agent backend; codex DEFAULT_CLIENT_ARGVS gains --strict-config -c web_search="disabled" --disable apps --disable plugins --disable remote_plugin.
4. `skillc/agent_trial.py` - preflight refuses a live codex argv missing any of the five server-side flags; the transcript census makes grading_eligible false on any server-side tool line type (web search, MCP, app, image generation), naming it; proxy-log and allowlist digests in the attempt's observation record.
5. `tests/fixtures/docker-backend/fake_docker.py` - network create/connect/rm; record container networks and dns.
6. `tests/test_egress.py` - new: proxy decision function; agent argv never bridge, carries internal net, dns, proxy env; lifecycle against fake docker incl. teardown on failure; preflight red per flag (5); census red (planted mcp/remote-plugin/web_search line) and green (clean transcript).
7. `tests/test_agent_egress_live.py` - new, real_docker: from inside a live-configured container, chatgpt.com via proxy ok; github.com and raw.githubusercontent.com 403; --noproxy and direct IP no route; getent fails.
8. `ci/real-docker/break-lib.sh` - egress break family (bridge-network, allow-all, dns-on), strict xfail per property.
9. `ci/check_real_docker_ran.py` - floor entry for the live egress test.
10. `ci/real-docker/README.md` - the egress family and floor entry.
11. `docs/specs/evaluation-facility/trial-bootstrap.md` - egress section: container egress covers client-side fetches only; server-side channels closed by declared flags + post-run census; names the B2 prompt-input measurement (16 plugins) and the re-measure-on-bump rule.
12. `CHANGELOG.md` - entry.
Existing tests asserting bridge or the old describe text are updated where they live.

Scope: large. Risks: Docker 29 embedded DNS on --internal networks (settled empirically by --dns 0.0.0.0 + the getent control); runner user needs network create/rm (docker group); a future codex bump can add server-side features (bounded by the pin, --strict-config and the census gate; re-measure on bump); one more small paid exec on evals26.
