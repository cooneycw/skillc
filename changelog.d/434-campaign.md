- **The #434 production-path campaign: flow:auto's clean-project case, scripted, on
  evals26** (#434, PR 3).
  - `skillc/fixture_campaign.py` runs PR 1's qualify candidates as real attempts
    through 2b's wiring, with a scripted actor in place of the model (network
    `none`, a dummy credential).
  - The actor's first act is a bare `codex --version`, so the nested-codex guard's
    top-level decision is a real one. The report says the top-level process is the
    actor, not the agent.
  - Its git operations are `qualify._apply_git`'s, proven equivalent by capture,
    with a dropped-op control.
  - Its per-attempt settings are held equal to `run_level1_agent_attempt`'s, with a
    perturbed-limit control.
  - `evals/level3/campaign-434/` freezes 46 rows:
    - 37 scored, CLEAN and TWIN reported side by side;
    - 3 guard rows (nested, suspected, none) expecting the credit gate's reasons;
    - 6 observed rows, whose expectation depends on a witness state a live attempt
      cannot reproduce. They record the real gate's runs and are never scored.
  - The report counts UNKNOWN-by-unreadable rows apart, and raises the pack trigger
    for any scored row there.
  - `skillc level3-campaign` routes a fixture-task manifest to this harness;
    `level3_campaign` and #375's harness digest are unchanged.
