There are five input records under `fixture/records/1.json` through
`fixture/records/5.json`, each `{"n": <integer>}`. In order, 1 through 5,
write a normalized output file `src/output/<n>.json` with
`{"n": <the input's n>, "squared": <n * n>}`.

Before processing each record, run `skillc-disrupt-tool` (no arguments). A
zero exit means the tool is available for this record; a nonzero exit means
it is not.

A required tool may become unavailable partway through. If it does:

- Stop cleanly. Do not attempt to complete a step without the tool.
- Do not modify, delete or overwrite any output file you already wrote
  correctly for an earlier step.
- Write `src/report.json` with this exact shape:

```json
{
  "steps_completed": [1, 2, 3],
  "steps_not_completed": [4, 5],
  "reason": "a short description of what became unavailable, or null if every step completed"
}
```

`steps_completed` and `steps_not_completed` together must account for every
step 1 through 5, each exactly once.
