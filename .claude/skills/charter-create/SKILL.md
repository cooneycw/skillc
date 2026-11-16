---
name: charter-create
description: Compose a skill's charter with the owner, from every existing piece of evidence, one decision at a time, with a trap-task stub for every rule. Use when the owner wants to write or rewrite what a skill promises, or when /skill-gauntlet stops at round 1 for lack of a charter.
---
# /charter-create <collection> <skill>

Composes a skill's CHARTER.md WITH the owner. The engine gathers the evidence
and writes the files. You hold the conversation. **You never answer for the
owner**: every accept, edit, drop, rule, shortcut and approval is theirs, in
their words.

Run the launcher in this skill's own directory:

```bash
<this skill's directory>/scripts/charter.sh evidence <collection> <skill> --ref <discussion|issue|PR> ... --out <evidence.json>
<this skill's directory>/scripts/charter.sh create <collection> <skill> --evidence <evidence.json> --answers <answers.json>
```

If it prints `CHARTER_CREATE: cannot find a usable skillc (...)`, report that
line and stop.

## 1. Gather the evidence first

Ask the owner where the skill's intent is written: discussions, issues, PRs.
Pass each as `--ref`. Add `--doc` for its spec, `--usage` for its usage logs.
Run `evidence`, then show every `SOURCE` line. A `not examined` source was not
read: say so, never treat it as empty.

## 2. Walk the owner through it, one decision at a time

For every suggestion in the evidence file, in order, show its text and its
citation, and ask: **accept, edit, or drop?** One suggestion per question.
Observational items show what someone wrote, never what the skill does: say so.
Record the answer exactly; an edit is in the owner's words.

## 3. Compose, one section at a time

- **Intent:** the job in one sentence. Ask whether the owner approves it.
- **Must always:** each outcome, one at a time.
- **Must never:** for each rule, ask: *"What is the tempting shortcut a
  capable model would take here?"* That answer is the rule's bad case. No
  shortcut, no rule: ask again, or leave it out.
- **Authority:** who approves, and what the skill may never do alone, with
  its shortcut too.
- Offer an existing test (from the evidence) as a clause's test; the owner
  decides.

Ask open questions only where there is no evidence.

## 4. Write the answers file, then run create

Write the owner's answers as JSON, in the shape `docs/specs/charter-create.md`
fixes: `schema`, `answers`, `intent`, `purpose`, `clauses`, and `approved_on`
only if the owner approved something. Every accepted or edited suggestion goes
in some clause's `from`. Read it back to the owner before you run `create`.

`create` refuses, and writes nothing, on any gap. Relay the refusal word for
word and ask the owner about that one gap. On success it prints the charter,
each trap-task stub, and "nothing was committed".

## Never

- Never answer, approve or pick for the owner, and never fill a gap yourself.
- Never set `approve` or `approved_on` without the owner's explicit yes.
- Never edit the skill. Never commit, stage or push the charter or the stubs:
  committing them is the owner's act.
- Never call a stub a test that passes: it has no grader until #736 fills it.
