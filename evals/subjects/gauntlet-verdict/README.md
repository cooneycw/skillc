# round 5 (verdict) fixtures (#737)

Inputs for `tests/test_gauntlet_verdict.py`. The tests copy `collection/` into a
fresh git repository and run the real engine (`gauntlet run`) to write each
skill's GAUNTLET.json, then run `gauntlet verdict` on it.

- `collection/skills/{lean,trimmable,shadowed}/`: three skills with
  owner-approved charters. `trimmable` carries a passage a round-4 variant removes.
- `reports/`: planted round 3/4 reports in `dataclasses.asdict(RoundReport)`
  shape (#736), round 3/4 declarations, and round 1 overlap reports (#726 part
  B's kinds). Each names the case it drives.
- `usage/usage.jsonl`: one invocation per skill, so round 0 reads OBSERVED.
