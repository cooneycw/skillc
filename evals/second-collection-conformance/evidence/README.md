# Second-collection conformance: live evidence (#11)

Everything here was produced by a real Docker daemon, the pinned trial image and
the real codex-cli. It is recorded verbatim, not re-derived. The paste-back
blocks are the ones skillc printed after its own leak check.

- Host: the operator's machine, native Docker Engine 29.8.1, Linux x86_64.
- Image: `skillc-trial:latest`, digest
  `sha256:d1b2ced9dc6d25e9e1bc673c1973f032ced50a11da234fcd617ee376ff36eefc`
  (the image #10's operator run built; nothing under `docker/` changed since).
- Client: codex-cli 0.157.1, the operator's normal Codex subscription login
  (`auth_mode` chatgpt, no API key), per ADR 0005 rule 6, "Normal Claude and
  codex". No judge call and no metered spend.

## 1. Installation and discovery, no model call (`skillc demo --subject`)

Run by the operator at main 8e06030 for #10, posted in full at
<https://github.com/cooneycw/skillc/issues/10#issuecomment-5855368984>. The per-subject lines, verbatim:

```
subject: cpp-codex revision=85e9b03ad2af1c41020ff6d92d36fa257bdacd2b
  installed: 74 skill(s), 273 file(s)
  digest_check: matched
  discovery: (74 of 74 discovered; same map as the acceptance line above)
EXIT=0

subject: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7
  installed: 2 skill(s), 7 file(s)
  digest_check: matched
  discovery: {'diagnosing-bugs': 'discovered', 'tdd': 'discovered'}
EXIT=0
```

The cpp-codex `discovery:` line was condensed to a count by the operator
before posting; the full 74-entry map is in the linked comment.

## 2. The Level 1 agent run, once per collection (`skillc collection-run`)

The same client, the same fixture (`evals/level1/slug-small-fix`, its
`goal.md` verbatim, `fixture/src/` only), the same contract
(`agent_trial.run_one_attempt`, skill-free canary mode) and the same grader
(the fixture's `grader.json`, in a separate `network=none` container). Only
the installed collection differs. Run 2026-09-27 from the #11 branch
(`skillc collection-run` from #121 plus this PR's three default fixes),
with the plain runbook commands and no override flags:

```bash
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run mattpocock-skills;  # EXIT=0
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run cpp-codex;          # EXIT=0
```

```
collection agent run: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=codex
  agent_network=bridge
  disposition=captured
  prompt_delivered=True
  canary_satisfied=True
  skill_invocations=['diagnosing-bugs'] (detection=heuristic)
  refresh_observed_in_container=None
  graded.status=PASS
  grading_blocked_reason=None
EXIT=0

collection agent run: cpp-codex revision=85e9b03ad2af1c41020ff6d92d36fa257bdacd2b client=codex
  agent_network=bridge
  disposition=captured
  prompt_delivered=True
  canary_satisfied=True
  skill_invocations=[] (detection=heuristic)
  refresh_observed_in_container=None
  graded.status=PASS
  grading_blocked_reason=None
EXIT=0
```

| collection | attempt | agent wall-clock | disposition | graded | skills the agent invoked (heuristic) |
|---|---|---|---|---|---|
| mattpocock-skills (2 skills) | a-b2f835ebf45c | 40 s (11:41:48Z-11:42:28Z) | captured | PASS | `diagnosing-bugs` |
| cpp-codex (74 skills) | a-a70dbbc1097f | 35 s (11:42:46Z-11:43:22Z) | captured | PASS | none |

The instruction named no skill. `diagnosing-bugs` was the agent's own choice,
detected by codex's heuristic (it has no native invocation marker). It is one
observation, not a selection measurement; that is #26's job.

### The control: a missing credential blocks before launch

```bash
SKILLC_ALLOW_REAL_AGENT=1 uv run skillc collection-run mattpocock-skills --credential <absent file>  # EXIT=1
```

```
collection agent run: mattpocock-skills revision=c55ee46073ed923f86ce59a5eb3b6d895095d1b7 client=codex
  agent_network=bridge
  disposition=unavailable
  prompt_delivered=None
  canary_satisfied=None
  skill_invocations=None (detection=None)
  refresh_observed_in_container=None
  graded.status=None
  grading_blocked_reason=attempt disposition is 'unavailable', not captured
EXIT=1
```

### What the first live attempts found, and what changed

The runs above are the fourth attempt. The first three, on #121's defaults,
never reached a model:

1. codex refused the non-git `/work` ("Not inside a trusted directory and
   --skip-git-repo-check was not specified"), exit 1 in 0.4 s: `inconclusive`.
2. With that flag, the prompt was delivered but every provider request failed
   (`request timed out`, `error sending request for url (https://chatgpt.com/...)`,
   `Reconnecting... 5/5`), exit 1 after ~3 minutes: `inconclusive`. Every
   `DockerBackend` container ran `--network none`. The owner ruled the agent
   container may have egress (recorded on #11); the grading container stays
   `none`.
3. A same-subject re-run failed at `git clone`: fixed `/tmp/<subject>-checkout`
   paths were never removed.

A fourth default would have failed next: one `--timeout` (30 s) bounded both
each docker call and the agent. Each fix has a test that fails without it
(`tests/test_collection_conformance.py`, "the live run's three defaults").
In every one of those failures the trial machinery reported the truth
(`inconclusive`, never graded), which is the behaviour it exists for.

## Annotation (#124): `refresh_observed_in_container=None` above is a key bug, not "not observable"

The three `refresh_observed_in_container=None` lines above are recorded
verbatim and left unedited, but they do not mean what they appear to. The
paste-back (`collection_conformance.build_collection_paste_back`) read the key
`refresh_observed_in_container`; the record stores the value as
`credential_refresh_observed_in_container`
(`credential.CredentialUsage.to_record_fields`). So these lines printed `None`
whatever the record held, and the record held a real `True`/`False` for every
captured run. The observation is not persisted to the run store, so those
values cannot be recovered. What this evidence shows about an in-container
refresh during #11's runs is therefore **nothing**, and the reason is the
misread key, not the credential being unobservable. #124 fixed the key, with a
regression test red on the old one; its Claude Code runs read `False`
([evals/claude-code-agent-arm](../../claude-code-agent-arm/evidence/README.md)).
#98's closing accounting cited this `None` as "not observable"; the correction
is posted on #98.

## What this does NOT show

- Which collection helps an agent more. Both passed a ceiling-prone canary
  task once each; that is #12's matched pilot, not a comparison.
- Anything about Claude Code: both subjects declare codex (#124 tracks the
  Claude Code arm).
- mattpocock-skills' 23 unselected skills, including the 14 policy-hidden ones
  (`evals/subjects/mattpocock-skills/SUBJECT.md`).
- Egress restricted to the provider: the agent container's network was open
  (`agent_network=bridge`), by ruling.
- Repeatability: one attempt per collection.
