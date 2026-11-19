# Lanes demonstrated - issue #783 (PR 1 of 2)

<!-- lanes-demonstrated run=f1c739b197084826a7585861f65ba39b plan=bb09e4905fd86684a923fe054203a0413747c06b4f7320a32035d40bf703df88 -->

The coverage OUTCOME against the plan's lanes table, reconciled after the counter-model review (pass 1 to 3 LOW findings: the plan promised client lanes the diff does not exercise).

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed - main checkout | every gauntlet test runs the engine on a fresh git collection; a linked worktree: not tested |
| Run placement | passed - host targeted set; Woodpecker CI on the PR is the gate | tests/test_gauntlet_report.py, test_gauntlet.py, test_gauntlet_verdict.py, test_charter_create*.py, leak, changelog, readme-drift |
| Agent client | **not tested** - Claude Code | no test drives a client reading the changed SKILL.md; the engine's report was run directly (the owner's own `/skill-gauntlet` target, quoted in the PR) |
| Client invocation | **not tested** - single attempt | as above; declared resume turns and codex app-server goals: not applicable |
| Static-check target | passed - claude-code | existing `test_the_skill_passes_skillc_check_for_the_claude_code_target` and `test_the_skill_stays_inside_its_word_budget` (531 of 600 words) pass on this branch; portable: not tested |
| Subject collection | passed - synthetic (evals/subjects/gauntlet); CPP at d5ef0a66: the existing pinned test passes unchanged; mattpocock-skills: not applicable (no gauntlet run on it in this change) | |
| skillc distribution | passed - source checkout (`uv sync --extra dev`); built wheel: not tested | |
| Python version | passed - 3.12; 3.11 not tested | |
| Reader: the owner reading the plain report | passed | one golden per fixture stop (8, including a real copied-passage finding), no rule id (scan with a negative control), the stopping Do next names a command or file (check with a prose negative control) |
| Reader: tests and gauntlet verdict reading the machine lines | passed | 8 machine goldens captured on f29e3a3's engine before #783 (commit de2614d; findings-copied's on f29e3a3's engine too), byte-identical on this branch and after the re-sync onto main |
| Reader: the engine's resume reading reason/facts from the display cache | passed | a cached rerun reports the same; a cached round with no display data shows its recorded detail and never invented counts |
| Reader: /skill-gauntlet relaying the output | **not tested** | the skill's SKILL.md tells it to show the plain report first; no client run exercises that here |
