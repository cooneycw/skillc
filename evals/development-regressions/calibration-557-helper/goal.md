# Replay goal and limits

Reproduce one observed historical grading distinction with the unchanged
revision-1 `helper-different-question` grader: the captured bad candidate must
FAIL with exactly `one-section-per-step` and `report-verdict` violated, and the
pre-existing qualified good candidate must PASS without violations. Refuse every
other pair, including always-pass and always-fail judge controls.

This is an ambiguity-bounded development regression for the evaluator. The
historical task wording did not unambiguously require renumbering the approved
text. A reproduced FAIL therefore establishes the grader's distinction, not a
causal CPP defect. No subject repair, new model success, held-out improvement,
readiness success, or aggregate effectiveness result is claimed.

Use the existing contained verifier, fixed source/candidate/grader identities,
two deterministic grades per pair, 30 seconds per stage, 120 seconds per pair
excluding cleanup. No agent/model trial, API judge, retry, private-store write,
or fallback execution is permitted.
