---
name: metadata-non-string-value
description: Use when a metadata value is an unquoted number, not a string.
metadata:
  version: 1.0
---
`metadata.version` is unquoted YAML, so it parses as a float, not a string.
