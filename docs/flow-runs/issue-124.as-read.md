# Issue #124 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #124
- Read at:      2026-09-27T12:23:11Z
- updatedAt:    2026-09-27T12:21:32Z   (context only - moves on comments and labels)
- Body digest:  48eabf405cf9a8c0cf69a30c5d8c5fc228a8a4d77f97361d3a5bbaf054422183   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2337 of 2337 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P1
Depends on: #11 (the per-collection `--agent` leg this reuses).

## Problem and outcome

Every real-agent path skillc can drive in a container today is Codex-only above the driver. `skillc/agent_trial.py` already knows both clients (`CLIENT_SPECS["claude"]`: credential/onboarding delivery, `.claude/projects` transcript, structural skill-invocation detection), and the trial image pins Claude Code 2.1.283 (`docker/trial/pinned-versions.json`). But:

- `skillc/materialize.py` has only the `codex-skills` surface; nothing installs a collection into the container's `~/.claude/skills/`.
- Both subjects (`evals/subjects/cpp-codex`, `evals/subjects/mattpocock-skills`) declare `"client": {"name": "codex"}`.
- `skillc demo --subject` discovery uses `codex debug prompt-input`. Claude Code has no no-model listing command (`skillc/exposure.py` states the same limit), so discovery cannot be observed the same way.

Outcome: one Claude Code agent run per collection on `evals/level1/slug-small-fix`, through the same contract and grader as #11's Codex runs, with the evidence and its limits published.

## Acceptance

- [ ] A `claude-code-skills` surface in `materialize.py` (install into `~/.claude/skills/<name>/`), generic - no subject-name branch (the #94 guard stays green).
- [ ] Claude Code subject declarations for both collections, or a documented reason one is not compatible (e.g. mattpocock/skills' `disable-model-invocation` skills), reported before selection.
- [ ] Discovery for Claude Code stated honestly: without a no-model listing, either observe it from the real transcript (skill listing / invocation) and label it as such, or report it UNMEASURED - never a borrowed Codex result.
- [ ] `skillc demo --subject <name> --agent --client claude` (reusing #11's leg) run live once per collection on the operator's normal Claude subscription login (ADR 0005 rule 6), plus the missing-credential control reporting `unavailable`.
- [ ] Discriminating controls under ADR 0001 for every new check (a skill not installed must turn the install/discovery check red).

## Scope

Not a second benchmark and not a Codex-vs-Claude comparison; that is #12's territory. Filed from the #11 flow run when the owner asked whether both clients are tested in containers (answer: only Codex, above the driver).

