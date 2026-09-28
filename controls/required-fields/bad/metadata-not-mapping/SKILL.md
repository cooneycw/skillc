---
name: metadata-not-mapping
description: Use when metadata holds a bare string instead of a mapping.
metadata: some-string
---
`metadata` exists but holds a bare string. Claude Code drops a value here that
is not a map, so this is silently discarded, not merely malformed.
