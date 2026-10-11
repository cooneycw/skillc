# Approved change: retry the canary rollout step

- **Change:** add `"retries": 3` to the `rollout` block in
  `config/deploy.json`.
- **Approved diff:** [`approved.diff`](approved.diff).
- **Approved by:** release review, 2026-09-18.

The approval covers the key's name, value and placement inside the
`rollout` object - operators read this file to know how many times a
canary rollout retries before paging on-call, so a dropped `retries` key
is a silent behavior change, not a cosmetic one.

The config on `main` must carry this change exactly as approved.
