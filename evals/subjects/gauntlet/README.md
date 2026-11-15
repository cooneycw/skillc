# gauntlet fixtures (#754)

Inputs for `tests/test_gauntlet.py`. The tests copy `collection/` into a fresh git
repository before running the engine, because the engine writes its record.

- `collection/skills/alpha/`: a skill with an owner-approved `CHARTER.md`, and an
  `until #12` marker that `issue-states.json` closes, so round 2 sorts it into D.
- `collection/skills/beta/`: a skill with no `CHARTER.md`. Round 1 stops on it.
- `usage/usage.jsonl`: a planted log whose session id and stop reason
  (`planted-session-7f3a91`, `planted-stop-reason`) must never reach a record.
