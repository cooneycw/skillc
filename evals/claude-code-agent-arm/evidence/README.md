# Claude Code agent arm: live evidence (#124)

Everything here was produced by a real Docker daemon, the pinned trial image and
the real Claude Code CLI. It is recorded verbatim, not re-derived. The
paste-back blocks are the ones skillc printed after its own leak check.

- Host: the operator's machine, native Docker Engine 29.8.1, Linux x86_64.
- Image: `skillc-trial:latest`, digest
  `sha256:d1b2ced9dc6d25e9e1bc673c1973f032ced50a11da234fcd617ee376ff36eefc`
  (the image #10's and #11's runs used; `claude --version` inside it:
  `2.1.283 (Claude Code)`).
- skillc: this branch at `ed66b40` (issue #124).
- Client: Claude Code 2.1.283, argv `claude -p --dangerously-skip-permissions`
  (`collection_conformance.DEFAULT_CLIENT_ARGVS["claude"]`) plus the `--name`
  flag `agent_trial` appends. It used the operator's normal Claude subscription
  login (`~/.claude/.credentials.json`, OAuth), per ADR 0005 rule 6, "Normal
  Claude and codex". No judge call and no metered spend.
- Run by the flow session driving #124, on the operator's host, with
  `SKILLC_ALLOW_REAL_AGENT=1`.

## 1. The Level 1 agent run, once per collection (`skillc collection-run`)

The fixture (`evals/level1/slug-small-fix`, its `goal.md` verbatim,
`fixture/src/` only), the contract (`agent_trial.run_one_attempt`, skill-free
canary mode) and the grader (the fixture's `grader.json`, in a separate
`network=none` container) are the same ones #11's Codex runs used. What
differs is the client, and that the collection is installed in the agent's
`~/.claude/skills/`.

mattpocock-skills-claude-code, 2026-09-27T13:07:58Z to 2026-09-27T13:08:22Z:

```
collection agent run: mattpocock-skills-claude-code revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=claude
  agent_network=bridge
  disposition=captured
  prompt_delivered=True
  canary_satisfied=True
  skill_invocations=[] (detection=structural)
  refresh_observed_in_container=False
  discovery={'diagnosing-bugs': 'listed', 'tdd': 'listed'} (source=transcript skill_listing)
  graded.status=PASS
  grading_blocked_reason=None
EXIT=0
```

cpp-claude-code, 2026-09-27T13:08:22Z to 2026-09-27T13:08:46Z:

```
collection agent run: cpp-claude-code revision=85e9b03ad2af1c41020ff6d92d36fa257bdacd2b client=claude
  agent_network=bridge
  disposition=captured
  prompt_delivered=True
  canary_satisfied=True
  skill_invocations=[] (detection=structural)
  refresh_observed_in_container=False
  discovery={'best-practices': 'listed', 'boot': 'listed', 'browser-tiered': 'listed', 'cicd-verification': 'listed', 'claude-md-config': 'listed', 'code-quality': 'listed', 'context-efficiency': 'listed', 'documentation': 'listed', 'evaluate': 'listed', 'hooks-automation': 'listed', 'idd-workflow': 'listed', 'infrastructure-hardening': 'listed', 'mcp-optimization': 'listed', 'project-deploy': 'listed', 'python-packaging': 'listed', 'secrets': 'listed', 'session-management': 'listed', 'spec-driven-dev': 'listed'} (source=transcript skill_listing)
  graded.status=PASS
  grading_blocked_reason=None
EXIT=0
```

## 2. The missing-credential control

`--credential` pointed at a path that does not exist. The attempt must
report `unavailable`, never launch the agent, and exit non-zero:

```
collection agent run: mattpocock-skills-claude-code revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=claude
  agent_network=bridge
  disposition=unavailable
  prompt_delivered=None
  canary_satisfied=None
  skill_invocations=None (detection=None)
  refresh_observed_in_container=None
  discovery=UNMEASURED (no transcript observation)
  graded.status=None
  grading_blocked_reason=attempt disposition is 'unavailable', not captured
EXIT=1
```

## 3. The host login after the trials (the check #98 transferred here)

After the last trial ended (2026-09-27T13:08:46Z), one host
Claude Code turn, `claude -p "Reply with exactly the single word OK and
nothing else."` (host CLI 2.1.281), ran from 2026-09-27T13:08:54Z to
2026-09-27T13:09:00Z:

```
OK
EXIT=0
```

The host login still works after both trials. `refresh_observed_in_container`
read `False` in both captured records: the credential file in the container
had the same bytes at teardown as at delivery, so neither trial rewrote the
refresh token. In the control it reads `None`, meaning nothing was delivered
and nothing could be compared. That is not a "no refresh" reading.
`credential.refresh_observed` compares bytes only; it says whether the file
changed, not whether a rotation happened.

## 4. Earlier runs, superseded and why

The first pair of live runs (13:05:43Z and 13:06:21Z, same branch before
`ed66b40`) also finished captured, PASS and EXIT=0, with the same discovery
maps. Both printed `refresh_observed_in_container=None`. The paste-back read
the key `refresh_observed_in_container`, but the record stores the value
under `credential_refresh_observed_in_container`
(`credential.CredentialUsage.to_record_fields`), so the line printed `None`
whatever happened. #11's Codex paste-backs carry the same blind `None`. The
record is not persisted to the store, so those runs' real values could not
be recovered. The key was fixed (with a regression test, red on the old key)
and both runs were repeated. The blocks above are the repeats.
