# Evals

Static analysis answers whether a skill is well-formed. It cannot answer the
question that actually matters: **does this skill change what the agent does?**

That needs a behavioural eval - define an environment, run an agent through a
task in it, and judge the result. The decisive form is the ablation: run the same
task with the skill loaded and without it. If the two runs score the same, the
skill is doing nothing, however well-formed it is.

Claude Code ships the runner (`claude plugin eval --ablation with-without`), and
the case format is a directory per case:

```yaml
# evals/<case>/case.yaml
name: rotate-credential-no-trigger
mustfail: true          # this prompt must NOT fire the skill
runs: 3
max_turns: 4
prompt: |
  Summarise what we changed in this file today.
graders:
  - tool_used:
      tool: Skill
      input_match: rotate-credential
      negate: true
    with_only: true
```

`mustfail` is the redcase idea at the eval layer: a case whose whole job is to go
red if the skill over-fires. Every skill wants both arms - a prompt that must
trigger it, and a prompt that must not. A trigger eval with only the positive arm
cannot tell a well-aimed description from one that fires on everything.

Not yet populated. The static rules had to prove themselves first.
