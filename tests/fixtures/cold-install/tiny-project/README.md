Deliberately minimal fixture project for #266's cold-container-install
proof: it exists only so `flow-finish-gate.sh` has a real directory to
run against inside the container, not to exercise any particular gate
outcome. The real-pin hand-run against an equally trivial project
(`docs/specs/evaluation-facility/profiles.md`'s "Human-only real-pin
proof" section) reported the real `lib.cicd` runner reaching completion
with `FLOW_FINISH_GATE: warn`, exit 3 - an honest "nothing here for a
test/lint runner to recognize", not a failure of the installed path. This
test asserts THAT classification (the real runner was reached, not the
Makefile fallback), not any particular lint/test outcome.
