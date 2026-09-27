# The Claude Code agent arm (#124)

Until #124, every real-agent path skillc could drive in a container was Codex
above the driver. `agent_trial` already knew Claude Code's credential, its
onboarding seed and its transcript, and the trial image already pins Claude
Code 2.1.283. What was missing: nothing could install a collection where
Claude Code reads skills (`~/.claude/skills/`), both subjects declared codex,
and Claude Code has no model-free listing to observe discovery with.

**Executed.** [`evidence/README.md`](evidence/README.md) holds the live
output. [`run-manifest.json`](run-manifest.json) cites it line by line, and
`tests/test_claude_code_agent_arm.py` fails if a cited line is missing from
the evidence or is attributed to the wrong collection.

## What ran, per collection

**`skillc collection-run <subject>`**, with one real Claude Code agent
attempt per collection:

- [cpp-claude-code](../subjects/cpp-claude-code/SUBJECT.md): CPP's native
  `.claude/skills`, 18 skills.
- [mattpocock-skills-claude-code](../subjects/mattpocock-skills-claude-code/SUBJECT.md):
  `tdd` and `diagnosing-bugs`.

The Level 1 task (`evals/level1/slug-small-fix`), the contract
(`agent_trial.run_one_attempt`, skill-free canary mode) and the grader are
the ones [#11's Codex runs](../second-collection-conformance/README.md)
used. Both collections: captured, prompt delivered, canary satisfied, every
selected skill `listed` in the transcript, graded **PASS**, EXIT=0.

The control, with the credential deliberately absent, reported `unavailable`
and blocked before the agent launched, with exit 1.

## Acceptance, against #124's bullets

| Bullet | Status | Backed by |
|---|---|---|
| A generic `claude-code-skills` surface (install into `~/.claude/skills/<name>/`), no subject-name branch | MET | `materialize.SURFACES`. The #94 guard (`tests/test_materialize.py::test_the_core_names_no_subject`) stays green over every `skillc/*.py` |
| Claude Code subjects for both collections, or a reported incompatibility | MET | both declared. The 14 `disable-model-invocation` mattpocock skills are reported incompatible with transcript-observed discovery before selection ([SUBJECT.md](../subjects/mattpocock-skills-claude-code/SUBJECT.md)) |
| Discovery stated honestly: observed from the transcript and labelled so, or UNMEASURED | MET | `discovery=... (source=transcript skill_listing)` in the evidence. With no listing it is `UNMEASURED` with a reason (`test_no_listing_in_the_transcript_is_unmeasured_never_a_pass_or_a_fail`). `skillc demo --subject` reports it NOT EXERCISED for Claude, and the host `skillc materialize` refuses a Claude subject |
| A live run per collection on the operator's Claude subscription, plus the missing-credential control reporting `unavailable` | MET | evidence sections 1 and 2 |
| Discriminating controls under ADR 0001 for every new check | MET | a skill whose files were withheld from the container turns discovery red and fails the exit (`test_a_skill_that_was_not_installed_turns_discovery_red`, `test_cmd_collection_run_exit_follows_measured_discovery`). So does an installed skill the listing omits. A surface/client mismatch is refused. A claude subject lands under `.claude/skills/` |
| (#98 transfer) The host login works after the trial; `refresh_observed_in_container` recorded | MET | evidence section 3: a host turn at 13:08:54Z returned `OK`, EXIT=0; `False` in both captured records |

## The bounded compatibility statement

**Shown by execution, for both collections, on one host:** a declared
collection installs into Claude Code's own skills directory in a real trial
container. Claude Code lists every selected skill to the model; this is read
from the real transcript's `skill_listing` attachment, not from a canary. A
real Claude Code agent then works the Level 1 canary through launch,
transcript, prompt-delivery check, liveness canary, capture and independent
grading to a PASS, on the same code path as the Codex runs.

**Not shown, and not claimed:**

- **Codex versus Claude Code, or which collection helps.** One ceiling-prone
  canary attempt each is not a comparison; that is #12's matched pilot.
- **Skill selection.** Neither agent invoked a skill in the skill-free run
  (`skill_invocations=[]`, structural detection). That is one observation
  per collection, not a measurement; that is #26.
- **An in-container, model-free discovery check for Claude Code.** None
  exists. The transcript listing is what the client told the model, observed
  after the run, and it is labelled as such.
- **The 14 `disable-model-invocation` mattpocock skills, and CPP's slash
  commands.** They are not installed; see the SUBJECT.md pages.
- **Contained egress.** As on #11, by owner ruling, the agent container ran
  on `bridge`; the grading container stayed `network=none`.
- **Repeatability.** One attempt per collection.
