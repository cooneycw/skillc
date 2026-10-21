<!-- flow-run n=1 id=40ab0e2ecdf5414d85869f62df948b8b -->
## Run 1 - issue #500 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #500
- Read at:      2026-10-21T01:32:13Z
- updatedAt:    2026-10-21T01:06:36Z   (context only - moves on comments and labels)
- Body digest:  001702ed780678fd72ec08d4ac790a86fabd843445927fa54e8387cc671e6093   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3378 of 3378 (cap 16384)

### Body as read
## Problem (containment and cost)

Calibration attempts (`skillc calibration-run`, the #287 path) do NOT carry #434's nested-codex guard. Under flow:auto's Step 6 (CPP 86641e8, PROFILE.md D3), the agent improvises a counter-model review by launching its OWN `codex` processes. In the #287 option-1 pilot (run 20261021T003158Z-600e90, owner-approved), at least one such nested session RAN and reached the model outside every control the declaration binds. Found by skillc-worker-A's read-only diagnosis of the retained store.

Facts:
- **a-4ef6692fdccb (degraded, graded PASS, read as model_eligible=True):** the agent ran `codex exec --skip-git-repo-check --ephemeral --sandbox read-only --model gpt-6-sol --output-last-message …`.
  - The session banner reads `model: gpt-6-sol`, which is **not the declared model** (gpt-6-astra).
  - It produced at least 3 model turns, and listed MCP resources.
  - It was launched **without** the declared server-side-off flags (`--strict-config`, web_search disabled, apps/plugins/remote_plugin disabled). Those apply only to the top-level client, so server-side tools (including web search) were not ruled out for it.
  - Proxy: an extra burst of 18 CONNECTs to chatgpt.com. The allowlist passes nested-client traffic.
  - `--ephemeral` wrote no session file, so the one-transcript check saw one file and **graded the attempt**. Its tokens are uncounted.
- **a-480a47e18ec8 and a-34463e3fc3f1:** the capture found 2 transcript files, and **discarded both** ("expected exactly one transcript file, found 2"). Their containers were torn down. The proxy logs show a second concurrent session burst at about 41–43 s. Nothing else survives.
- **Two others** ran `codex review --uncommitted`, which failed in about 0.1 s with no model contact.

## Defects

1. **No nested-codex guard on the calibration path:** an agent can launch codex with ANY model and ANY server-side configuration.
2. **`model_eligible` is blind to nested models:** a-4ef6692fdccb reads eligible while gpt-6-sol ran inside it.
3. **The "exactly one transcript" check is defeated by `--ephemeral`,** and when it does fire it **discards** the evidence instead of retaining both files.
4. **Token accounting covers only the top-level session:** the pilot's reported 5,165,245 tokens is an undercount of unknown size.

## Acceptance

- [ ] The #434 nested-codex guard (or an equivalent) is installed on calibration attempts. A refused nested launch is counted and reported. A nested launch that is NOT refused, and any suspected or ancestry-unknown launch, blocks credit and stops the schedule.
- [ ] With more than one transcript, all transcripts are RETAINED and the attempt is flagged, never silently discarded.
- [ ] Model eligibility and token accounting consider every codex session in the attempt (a nested session on another model makes the attempt ineligible).
- [ ] Reds: an unguarded nested `codex exec --ephemeral --model other` is detected; a two-transcript attempt keeps both files.
- [ ] No further live calibration runs until this merges.

## Impact on recorded results

The #287 pilot's honest-report result (9/9 per arm) stands as graded, but its token total is an undercount, and the declaration's containment premise (provider-only egress, server-side tools off, the declared model only) did **not** hold for at least one attempt. Record that on #287.

