---
name: mapping-compatibility
description: Use when compatibility holds a mapping instead of a string.
compatibility:
  min: "1.0"
---
`compatibility` exists but holds a mapping. `Skill.get` used to return None for
it, so this passed every rule unexamined.
