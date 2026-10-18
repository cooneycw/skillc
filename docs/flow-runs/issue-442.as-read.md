<!-- flow-run n=1 id=3cff4a54a8354d0f85b0084e89ca50bb -->
## Run 1 - issue #442 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #442
- Read at:      2026-10-17T20:41:38Z
- updatedAt:    2026-10-17T20:40:53Z   (context only - moves on comments and labels)
- Body digest:  ae76f6d0704d1ca4ab7b7b76758e8c5f1e43ec91a8289841ef5743c717f93c69   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1962 of 1962 (cap 16384)

### Body as read
## Why

Live agent containers run on Docker's default `bridge` network (`skillc/collection_conformance.py:118`, `AGENT_NETWORK = "bridge"`), with egress OPEN by the owner's ruling on #11 (`skillc/docker_backend.py:915`). skillc's graders, task fixtures and expected outcomes live in this PUBLIC repository. A live candidate can therefore fetch the very grader it is being judged by. The #288 audit (https://github.com/cooneycw/skillc/issues/288#issuecomment-6240591620) found no such fetch in the 10 live attempts whose transcripts survive, but the #203-era runs, the bulk of live spend, are unreachable. So the #288 study cannot assume the graders were unreachable.

Owner ruling (via the orchestrator, recorded on #288): **reverse #11 for live agent containers. Before #288 runs, a live container may reach only its model provider.**

## Outcome

From inside a live agent container:
- the model provider endpoints the pinned client actually uses are reachable (**measured**, not guessed);
- everything else is unreachable, including `github.com` and `raw.githubusercontent.com`;
- even a client that ignores proxy settings has no bypass route;
- DNS-based exfiltration is addressed, or its residual is stated.

## Required controls (red and green, from inside a live container on the real runner)
- A request to `github.com` (and `raw.githubusercontent.com`) **fails**; a request to the provider endpoint **succeeds**.
- A client that **ignores `HTTPS_PROXY`** (direct TCP/443 to github.com by IP and by name) still **fails**: there is no bypass route.
- DNS: arbitrary-name resolution, or a DNS-tunnel style lookup, is either blocked or its residual stated and bounded.
- Each control can be shown to fail when the restriction is removed (otherwise it is blind).

## Not in scope
Grading containers (already `network none`); the Level-3 scripted campaigns (already `network none`).

Design first: the ELI5 goes to the orchestrator before any implementation.

