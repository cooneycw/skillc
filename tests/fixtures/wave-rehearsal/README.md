# Model-free wave actor preparation (#626)

This is a closed trusted-script fixture, prepared separately from the runtime
and final-capture delivery. It starts no model and makes no claim of full-path
protocol coverage, hostile participant isolation, native wake or physical Docker
qualification. No new runner/profile pin is selected here.

`role_actor.py ROLE MODE INITIAL_JSON` starts a session; subsequent turns use
`role_actor.py ROLE MODE resume SESSION LITERAL`. The initial JSON declares the
wave and all three role bindings (attempt, task, generation, revision and nonce).
The actor emits the parser's measured session header and scripted session metadata,
keeps its session across resumes, and refuses a stale session before touching
shared state. Its metadata identifies a scripted stand-in, not a real Codex run.

Stage `task.json` and the approved CPP pin's actual `flow-wave-registry.sh`,
`flow-wave-mailbox.sh` and transitive helpers beside the actor. The focused tests
use the existing `87ecb097` source fixture without changing its bytes. Both shared
root environment variables must be explicit and equal. Registry PID/session
facts come from the actual actor process; no helper liveness override is set.
Mailbox send, peek and explicit revision acknowledgement all execute the real
helper. Completion and acknowledgement bodies remain participant claims.

Each worker changes its own arithmetic source and pushes its own remote branch.
The orchestrator fetches both actual commits and integrates them into
`refs/heads/delivered`. The frozen quote domain is the existing rehearsal contract:
100 combinations of quantity, integer unit cents and basis-point tax, with
round-half-up tax. It does not resume the parked task-relay implementation.

`grade_delivery.py` reads only a stopped, retained remote with `git_snapshot`,
then stages delivered source through the existing supervised verifier. It checks
seed ancestry, both worker source identities, regular-file modes and unchanged
seed files. The independent Decimal judge checks all 100 public vectors. Correct
local files and participant success prose cannot rescue wrong/undelivered remote
output. Missing/unreadable snapshot evidence is UNKNOWN. These checks grade the
delivered quote only, not the entire wave protocol or its retirement.

`cases.json` freezes the intended full-path case population. The focused tests
exercise both work orders, actual helper receipts and committed stale/wrong-role
acknowledgement and duplicate-completion bodies, disappearance, wrong arithmetic,
missing integration, missing snapshot and stale resumes. Expected full-wave
verdicts are declarations for the later collector, not prerecorded evidence.
Lost-poke suppression, deadline enforcement, launch/capture loss and retirement
faults still need their controller-side injections through the real driver.

The approved trusted collector is now composed by `docker_rehearsal.py` using
`skillc.wave_tap`, its Docker executor and the existing driver. See the
[collection contract](../../../docs/specs/evaluation-facility/wave-rehearsal.md).
This source composition still needs full-path physical qualification. Do not
normalize actor-written logs or mailbox assertions into controller-owned
ack/complete coverage. Registry release leaves historical rows and mailbox state;
it is not proof of zero clutter or whole-wave retirement. A completed actor's
local state file is preparation data, not a declared allowed live-task artifact.
The physical three-container run, complete accounting and independent clutter
instrument still belong to the separately coordinated rehearsal.
