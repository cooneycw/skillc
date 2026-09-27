# Agent trial driver: live evidence (#106)

This is #106's remaining acceptance item, "owed to the operator's live run". It
covers a real client, a real login, the host login still working afterwards,
and the real transcript format. Level 1 was run once per collection, through
the same client and grader as #11
([`evals/second-collection-conformance/evidence/`](../second-collection-conformance/evidence/README.md)).
This time the run kept evidence on prompt delivery, the canary, the credential,
the outcome and the cleanup.

All output here came from a real Docker daemon, the pinned trial image and the
real codex-cli. It is recorded verbatim. Each paste-back block is the one
skillc printed after its own leak check.

- **Date:** 2026-09-27, 13:02–13:05Z, from the #106 branch based on main
  ab04c6c, plus this PR's evidence fields.
- **Host:** the operator's machine, native Docker Engine, Linux x86_64.
- **Image:** `skillc-trial:latest`, id `d1b2ced9dc6d`. It is the same image #10
  and #11 ran; nothing under `docker/` has changed since.
- **Client:** codex-cli 0.157.1, on the operator's normal Codex subscription
  login (`Logged in using ChatGPT`, no API key), per ADR 0005 rule 6. There
  was no judge call and no metered spend.
- **Commands:** the plain runbook commands. The only flags used were the ones
  that make the two controls fail.

```bash
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run mattpocock-skills   # EXIT=0
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run cpp-codex           # EXIT=0
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run mattpocock-skills --credential <absent file>          # EXIT=1
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run mattpocock-skills --minimum-credential-seconds 1000000000  # EXIT=1
```

## 1. The Level 1 attempt, once per collection

### mattpocock-skills

```
collection agent run: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=codex
  agent_network=bridge
  attempt_id=a-2782040b6a11
  [prompt delivery]
    prompt_delivered=True
    prompt_delivery_reason=None
    transcript_files_found=1
  [canary]
    canary_satisfied=True
    canary_reason=None
    liveness_method=canary
  [credential]
    credential_delivered=True source=subscription
    remaining_at_launch=9949m
    refresh_observed_in_container=False
    host_credential_unchanged=True
    host_remaining_after=9948m
  [outcome]
    disposition=captured
    stop.reason=exited stop.exit_code=0 stop.confirmed=True
    skill_invocations=['diagnosing-bugs'] (detection=heuristic)
    graded.status=PASS
    graded.criteria=R4-interface=SATISFIED, reported-example=SATISFIED, R1=SATISFIED, R2=SATISFIED, R3=SATISFIED
    grading_blocked_reason=None
  [cleanup]
    workspace_cleanup=partial failures=['the workspace was never cleaned up']
    backend_teardown=confirmed
    backend_teardown_error=None
    daemon_comparable=True leaked_owned_containers=0 foreign_vanished=0
    store_kept=<tmp>/skillc-collection-run-mattpocock-skills-3gwth9gw/mattpocock-skills-store record_written=True
  [transcript format]
    client_version=0.157.1 model=gpt-6-astra
    unrecognized_types=[]
    line_types={'event_msg/item_completed': 13, 'event_msg/task_complete': 1, 'event_msg/task_started': 1, 'event_msg/token_count': 6, 'response_item/custom_tool_call': 5, 'response_item/custom_tool_call_output': 5, 'response_item/message': 8, 'response_item/reasoning': 1, 'session_meta': 1, 'token_usage_record': 6, 'turn_context': 1, 'world_state': 1}
EXIT=0
```

The `workspace_cleanup=partial` line in this first run turned out to be
**wrong about what happened**, and this run is how that was found.
`lifecycle.run_through_backend` finalizes the attempt record before it cleans
the workspace. So the record's `cleanup` field reads "partial" on every
lifecycle-driven attempt, even when the workspace was removed. The attempt's
own journal, written after the removal, records the actual outcome
(`journal/a-2782040b6a11.jsonl` in the kept store, verbatim):

```
{"at": "2026-09-27T13:03:26.982263Z", "event": "cleaned", "failures": [], "status": "removed"}
```

The paste-back now prints both: the journal's event as
`workspace_cleaned(journal)`, and the record's field, labelled
`(record, at finalize)`. The runs below show both lines. The ordering defect
in `lifecycle.py` is recorded in the Nit Store (#20) rather than changed here.

### cpp-codex

```
collection agent run: cpp-codex revision=85e9b03ad2af1c41020ff6d92d36fa257bdacd2b client=codex
  agent_network=bridge
  attempt_id=a-b59737cad3bc
  [prompt delivery]
    prompt_delivered=True
    prompt_delivery_reason=None
    transcript_files_found=1
  [canary]
    canary_satisfied=True
    canary_reason=None
    liveness_method=canary
  [credential]
    credential_delivered=True source=subscription
    remaining_at_launch=9947m
    refresh_observed_in_container=False
    host_credential_unchanged=True
    host_remaining_after=9947m
  [outcome]
    disposition=captured
    stop.reason=exited stop.exit_code=0 stop.confirmed=True
    skill_invocations=[] (detection=heuristic)
    graded.status=PASS
    graded.criteria=R4-interface=SATISFIED, reported-example=SATISFIED, R1=SATISFIED, R2=SATISFIED, R3=SATISFIED
    grading_blocked_reason=None
  [cleanup]
    workspace_cleaned(journal)=removed
    workspace_cleanup(record, at finalize)=partial
    backend_teardown=confirmed
    backend_teardown_error=None
    daemon_comparable=True leaked_owned_containers=0 foreign_vanished=0
    store_kept=<tmp>/skillc-collection-run-cpp-codex-bii_bnws/cpp-codex-store record_written=True
  [transcript format]
    client_version=0.157.1 model=gpt-6-astra
    unrecognized_types=[]
    line_types={'event_msg/item_completed': 9, 'event_msg/task_complete': 1, 'event_msg/task_started': 1, 'event_msg/token_count': 6, 'response_item/custom_tool_call': 5, 'response_item/custom_tool_call_output': 5, 'response_item/message': 7, 'session_meta': 1, 'token_usage_record': 6, 'turn_context': 1, 'world_state': 1}
EXIT=0
```

## 2. The controls: each blocks before launch and leaves nothing behind

Both controls printed their paste-back before the `reason=` line was added to
it. The reasons below are quoted from each run's kept
`collection-run-record.json`.

### Missing credential

```
collection agent run: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=codex
  agent_network=bridge
  attempt_id=a-af1111d13fa9
  [prompt delivery]
    prompt_delivered=None
    prompt_delivery_reason=None
    transcript_files_found=None
  [canary]
    canary_satisfied=None
    canary_reason=None
    liveness_method=None
  [credential]
    credential_delivered=None source=None
    remaining_at_launch=None
    refresh_observed_in_container=None
    host_credential_unchanged=None
    host_remaining_after=None
  [outcome]
    disposition=unavailable
    stop.reason=never-started stop.exit_code=None stop.confirmed=True
    skill_invocations=None (detection=None)
    graded.status=None
    graded.criteria=None
    grading_blocked_reason=attempt disposition is 'unavailable', not captured
  [cleanup]
    workspace_cleaned(journal)=removed
    workspace_cleanup(record, at finalize)=partial
    backend_teardown=confirmed
    backend_teardown_error=None
    daemon_comparable=True leaked_owned_containers=0 foreign_vanished=0
    store_kept=<tmp>/skillc-collection-run-mattpocock-skills-4t3f3pf9/mattpocock-skills-store record_written=True
  [transcript format]
    client_version=None model=None
    unrecognized_types=None
    line_types=None
EXIT=1
```

Record `reason`: `no codex credential at <tmp>/claude-1000/absent-credential.json (the explicitly given path) - a trial refuses rather than guess at another location or proceed without one`.
`host_credential_unchanged=None` is correct here. The "host" credential for
this run was the absent file, so no comparison could be made, and the line
does not claim one.

### Credential below the threshold

```
collection agent run: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=codex
  agent_network=bridge
  attempt_id=a-ae2a6a93b98d
  [prompt delivery]
    prompt_delivered=None
    prompt_delivery_reason=None
    transcript_files_found=None
  [canary]
    canary_satisfied=None
    canary_reason=None
    liveness_method=None
  [credential]
    credential_delivered=None source=None
    remaining_at_launch=None
    refresh_observed_in_container=None
    host_credential_unchanged=True
    host_remaining_after=9947m
  [outcome]
    disposition=unavailable
    stop.reason=never-started stop.exit_code=None stop.confirmed=True
    skill_invocations=None (detection=None)
    graded.status=None
    graded.criteria=None
    grading_blocked_reason=attempt disposition is 'unavailable', not captured
  [cleanup]
    workspace_cleaned(journal)=removed
    workspace_cleanup(record, at finalize)=partial
    backend_teardown=confirmed
    backend_teardown_error=None
    daemon_comparable=True leaked_owned_containers=0 foreign_vanished=0
    store_kept=<tmp>/skillc-collection-run-mattpocock-skills-uyrm5b70/mattpocock-skills-store record_written=True
  [transcript format]
    client_version=None model=None
    unrecognized_types=None
    line_types=None
EXIT=1
```

Record `reason`: `codex credential has 596822s remaining, below the required 1000000000s - refusing rather than risk needing to refresh mid-trial`.

## After the runs: two paste-back lines added by the cross-model review

The blocks above are the paste-back exactly as it printed during these runs.
The counter-model review of this PR then changed two things. Neither changes
what these runs showed:

- **Cleanup is now judged per run.** The exit code is decided by
  `attributable_leftover_containers`: containers still labelled with this
  run's own attempt ids, meaning the agent's and each grading probe's. The
  daemon-wide `leaked_owned_containers` line is printed as `context:` only,
  because a concurrent run's container would otherwise fail a clean run.
  These runs came before that line, but their evidence is stronger than it.
  The daemon-wide diff was 0 on every run, and afterwards **no** skillc-owned
  container of any attempt remained (section 3). No attempt, this run's
  included, could have left one.
- **An empty transcript is no longer read as "no drift".** The census now
  reports `response_items_inspected` and prints `unrecognized_types=None`
  (not assessed) when that count is zero. Both captured runs inspected 11
  response items: 5 tool calls, 5 outputs, and 8 or 7 messages plus
  reasoning, per their `line_types`. So their `[]` is a real result.

The kept `collection-run-record.json` files from these runs hold the driver
record only. The saved file is now an envelope that also carries the host
comparison, the attributable leftovers and the journal's cleanup event.

## 3. The host login afterwards

| | before (13:02:39Z) | after (13:05:10Z) |
|---|---|---|
| `codex login status` | `Logged in using ChatGPT`, exit 0 | `Logged in using ChatGPT`, exit 0 |
| `sha256 ~/.codex/auth.json` (first 12 hex digits) | `f577abde4073` | `f577abde4073` |
| skillc-owned containers (`docker ps -a --filter label=skillc.managed=true`) | - | 0 |

Each run's own `host_credential_unchanged=True` agrees. Neither container
changed its copy of the credential (`refresh_observed_in_container=False`), so
there was no refresh that could have rotated the host's token.

## What this does NOT show

- **A host-side model call after the trials.** "Still working" rests on three
  things: `codex login status`, a byte-identical credential file, and about
  9,947 minutes of remaining life. The host was not asked to make a model
  request.
- **What happens when the token does refresh inside a container.** With about
  a week of remaining life, no refresh occurred. That path is still covered
  only by the hermetic tests.
- **Transcript drift over time.** The census shows no drift for codex-cli
  0.157.1 today (`unrecognized_types=[]`): every `response_item` type is one
  the adapter handles or deliberately ignores. It is a snapshot, not a
  guarantee for a later CLI version. Claude Code is not assessed (#124).
- **Anything for #26 or #12.** One skill-free attempt per collection is not
  #26's three predeclared selection cases, and it is not #12's matched pilot.
  `diagnosing-bugs` appeared again under the skill-free instruction, detected
  by codex's heuristic. That is a second single observation, not a measurement.
- **Egress restricted to the provider.** The agent container's network was
  open (`agent_network=bridge`), per #11's ruling.
- **Repeatability.** There was one attempt per collection.
