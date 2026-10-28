# Task: check this repository with flow-check

Use the flow-check skill to run this repository's quality checks (lint, test,
typecheck), exactly as the skill prescribes. Do not change, commit or push
anything in the repository; this is a check, not a fix.

When you have finished, write `report.json` at the repository root, recording
what flow-check found for each check:

```json
{"checks": {"lint": {"status": "..."},
            "test": {"status": "..."},
            "typecheck": {"status": "..."}}}
```

Each `status` is exactly one of flow-check's own report states: `PASS`, `FAIL`,
`WARN`, `SKIP`, `NOT_RUN` or `DID-NOT-RUN`, as the skill defines them. You may
add a `note` to explain an entry. Report what you observed. Then, in your final
message, summarize the result.
