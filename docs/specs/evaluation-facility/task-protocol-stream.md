# Controller-observed task-protocol stream (#620 PR-B design)

Status: proposed for owner review. This document approves no implementation,
credentials, image change, container launch, model call or live run. The owner
must accept the transport and authentication choices before PR-B code starts.
The [2026-11-10 ruling](https://github.com/cooneycw/skillc/issues/620#issuecomment-6773434609)
authorizes this minimal design. #639 owns the eventual declaration and execution
approval. #623's detailed timings, listener monitoring and per-poke snapshots
remain deferred.

The recommendation is a controller-owned local Unix-domain socket, one endpoint
per isolated session sandbox, with the same small command-line client in both
arms. Identity comes from the controller's endpoint-to-launch binding, never a
role, attempt or session field supplied by an agent. No bearer credential is
minted or passed in the recommended design. Its authentication unit is the
assigned sandbox principal; it does not prove authorship by a particular model
process. Accepting that distinction is an explicit owner decision below.

## Existing boundaries and the proposed additions

Source baseline: skillc main `12f12cf54f574e5b089e179ab55d89be1c17f50e`.

| Existing component | Reuse and limit |
| --- | --- |
| `live_wave_assembly.py`, PR #695 (`c3bca3f`) | Reuse original planned population, separate expected/export bindings, byte catalogue and independent artifact-grader join. Its current protocol input is authored ack/complete JSONL, not an authenticated live producer. It does not accept the proposed full journal unchanged. |
| `live_wave.py` | Reuse task/revision/nonce matching, ack/completion ordering, explicit common-deadline rules, all-planned-attempt denominator and independent delivery grading. Offers/refusals and authenticated ingress need an explicit versioned adapter; treating them as today's ack/complete rows would be incorrect. |
| `wave_wake_capture.py` (#622) | Reuse context-bound ordered records, previous-record hashes, fsync-before-action, closed seal and independently held reference. Wake attempts/pokes are not task acknowledgements or completions. |
| `codex_goal_capture.py`, PR #698 (`b5a75c3`) | Reuse private append/seal/reference custody and fail-closed storage behavior. Its current context/sequence does not establish the common clock or task semantics; a native goal saying complete is not a task completion receipt. |
| `controller_turns.py`, `codex_goal.py` | Reuse the independently drained initial exec header, or the pinned app-server's controlled thread/start response, to bind the actual client session. Never use an editable rollout, environment variable, mailbox entry or agent prose as the identity source. |
| #623 final capture and #634 attribution discipline | Keep final artifact/writer-stop capture separate. Attribute FAIL only to a positively established candidate/protocol violation. Transport, controller, uncertain stop or capture loss remains UNKNOWN. |

New work would be the local receiver/client, immutable endpoint lease and startup
binding records, the task-protocol journal/verifier, idempotent decision receipts,
and a qualified projection into the existing assembly/verdict boundary. No new
goal driver, wake driver, task scheduler or interpretation of CPP mail is proposed.
Shared custody patterns should be reused without silently broadening either
existing capture format or borrowing its reference as authority for new bytes.

## 1. Transport and task scope

The client has identical bytes, path, arguments, availability and responses in
both arms. The illustrative executable name is `skillc-task-protocol`; it is a
proposal, not an existing command. Its fixed endpoint inside each session sandbox
is `/run/skillc-task-protocol/channel.sock`.

| Arm | Role-facing operation | Controller side |
| --- | --- | --- |
| Single-session Codex /goal | Invoke the client for offer, ack, complete or refusal in its ordinary tool execution environment. | One endpoint lease bound to that attempt's one declared session. The goal connection remains separate. |
| Multi-session wave | Invoke the same client in each declared role's ordinary tool execution environment. | One exclusive endpoint lease per declared role/session; one ordered receiver/journal for the planned attempt. |

A controller-created Unix socket is mounted at the same path in each sandbox.
Each sandbox sees only its own socket, not a shared directory of all endpoints.
The parent directory is controller-owned and mounted read-only; participants
cannot replace the socket or reach the listener's private journal. There is no
HTTP service, external route, Docker socket, credential-bearing URL or new NHL
host allowance. This does not replace #638's egress or existing isolation policy.

The initial version offers only the declared task contribution/public goal for
that role. It does not invent subtasks, parse project issues, pass another role's
messages, reveal progress or dispatch dependencies. CPP may still use its own
workflow as part of the treatment. The protocol adds no privileged scheduling
assistance to that workflow. The single-session arm receives its declared global
contribution through the identical interface. Granularity must be accepted in
the declaration, not inferred later from CPP's mailbox or generated issue graph.

Requests contain a version, operation enum, positive integer request number,
controller-issued public offer ID where applicable, and an enumerated refusal
reason where applicable. Operations are offer, ack, complete and refuse. Agents
supply no role/attempt/session identity or clock value. Offer IDs and assignment
nonces are public correlation data, not authentication secrets. No arbitrary
message body, transcript, command, artifact path or free-form refusal text is
needed. Completion is a claim; independent captured-artifact grading establishes
whether anything was correctly delivered.

The controller validates a request, durably appends its attributed decision,
then returns a receipt. A returned offer means the controller issued an offer;
only an accepted ack observes acknowledgement. An ack does not establish work
completion. A complete claim does not establish correct integrated delivery.
A role's explicit refusal and the controller's rejection are distinct record
kinds, with closed reason codes. A well-formed role refusal is retained as a
refusal, not automatically promoted to task failure.

Retries of the same request number and identical normalized operation return the
same durable decision. Their retry observations remain in the journal, but they
do not become second semantic completions. Reusing a request number with different
content, or issuing a second distinct completion for the same offer, is recorded
as a protocol conflict. No retry renews the original task/deadline/generation.

## 2. Authentication and immutable binding

The trust root is the trusted controller/runtime, its private endpoint namespace,
and its predeclared launch inventory. It is not knowledge of an offer ID.

1. Before launch, retain the approved declaration digest and full planned
   attempt/role/task population, including generation, revision and task nonce.
   Nonstarts remain in that inventory. Establish the one common clock origin.
2. Create a fresh endpoint for each planned isolated sandbox, and hold its
   runtime instance identity privately. No endpoint is reused across attempts,
   new sessions or replacement containers. Resumes of the same observed session
   retain its original lease and clock.
3. Independently capture/validate the initial client session ID from the trusted
   startup channel. Bind it to the launch slot and endpoint. Missing, ambiguous
   or conflicting startup identity prevents task credit; it does not authorize
   accepting an agent's claimed replacement ID.
4. Before any task offer, freeze the concrete role/session plan and capture
   expectation. The recommended startup barrier finalizes every planned slot
   as bound or positively unstarted/unavailable. The prelaunch population is
   unchanged. `freeze_plan` remains immutable once called; startup resolution
   must not rewrite it after task-protocol observation begins. Clarify this
   startup phase in PR-A's producer contract rather than mutating its held bytes.
5. On ingress, look up role/attempt/session from the endpoint's active lease.
   Independently confirm that the endpoint still belongs to that runtime
   instance and allowed generation. Verify isolation/peer identity before
   accepting the event. Any uncertainty refuses attribution and gives UNKNOWN.
6. Persist the binding and its evidence reference before accepting offers/acks.
   Receiver-filled actor identity is distinct from any invalid identity field
   an agent tried to supply. Revocation is durable; old endpoints cannot be
   reassigned to a later session.

At lease time the controller independently inspects the actual runtime mount
and namespace configuration for every planned sandbox, rather than trusting the
requested launch options. Its held inventory must show that this socket is
mounted only into its own sandbox, without a shared ancestor/alias, inherited
cross-role descriptor, privileged namespace access or exposed runtime socket.
A sibling's identical in-sandbox pathname resolves to that sibling's distinct
listener. A missing, extra or ambiguous binding prevents the lease becoming
active. Retain the private inspection reference and a logical mapping digest.

Qualify the other-session case explicitly: a request from sandbox B cannot
reach A's listener through its declared filesystem. A deliberately mis-mounted
A endpoint in B must cause the exclusivity audit to refuse before any task
event is accepted; this is the known-bad control for that proof. Test endpoint
revocation/replacement too. The deployment must prove that only the assigned
sandbox can reach its endpoint.
Kernel Unix-socket peer credentials and runtime namespace/cgroup membership can
corroborate that lease; payload PIDs or role fields cannot. PID reuse, namespace
visibility, UID mapping, peer exit races and lease revocation require fail-closed
model-free qualification. Do not fall back to a shared UID, a caller-provided
PID, a path string or a bearer token when that check cannot be established.

**UNVERIFIED deployment facts:** this proposal has not qualified read-only socket
mount/connect behavior, peer-credential visibility or exclusive runtime mapping
on the eventual evaluation environment. The same isolated, model-free deployment
proof is required in both arms before declared use. If the controller cannot
prove exclusive access, this transport design is not ready; it yields UNKNOWN.

A confused agent cannot change its attributed role by editing JSON, changing its
working directory or writing another role's mailbox. A compromised role can lie
about its own acknowledgement/completion, replay its own public references or
have any process in its own sandbox call the client. Under this proposed default, child processes intentionally speak as the role:
what the sandbox emits is its claim, consistent with the attribution discipline.
Those claims remain subject to the state machine and artifact grading. It cannot authenticate as another
isolated sandbox without breaching the assumed containment/controller boundary.

This does not distinguish the model process from its tools, shell children or a
second process it starts inside that same sandbox. The recorded sender means
"the principal assigned to this controller-observed session", not proof that
particular model reasoning produced the bytes. A compromised controller, runtime
or kernel is outside this custody/authentication guarantee. Stronger model-process
mediation would require a different owner-approved design, not stronger wording
on the same socket. No secret-bearing fallback is implicit.

## 3. Clock, ordered journal and assembly

One controller monotonic origin covers setup, launches and task observations for
the planned attempt. All roles use it; no resume, receipt, refusal, reconnect or
replay restarts it. Agents' timestamps and filesystem times earn no credit. The
controller assigns a global sequence and integer elapsed nanoseconds under one
serialization point. Equal timestamps remain ordered by sequence. UTC is optional
private audit metadata, never the ordering or deadline clock.

A record has a closed versioned schema: global sequence, previous-record hash,
controller elapsed time, bound principal/offer references, operation/decision and
closed reason code. Context binds declaration, original planned population,
concrete startup bindings, original clock/deadline policy and producer version.
An offer, accepted ack, complete claim, role refusal, controller rejection,
idempotent retry and binding/closure event are all retained. Invalid requests
retain a bounded classification and content digest, not arbitrary participant
bytes that might contain private data. Accepted fields are enums, integers or
references to controller-known logical values. Sanitization may not erase an
accepted event or turn a refused request into success.

Use the existing append/seal discipline: fresh private directory, exclusive
writer, canonical newline records, contiguous sequence, hash chain, complete
fsynced record before any receipt or state advance. Directory entries are also
flushed. A failed/short write or fsync poisons the capture and stops acceptance.
No successful receipt can be returned for an uncommitted decision.

The event time is the trusted ingress/decision observation, not proof of network
send time or the instant fsync finished. The final controller capture/cleanup
completion must also satisfy the original common deadline where that deadline is
an approved task requirement. Slow journal I/O cannot turn a late complete capture
into PASS merely because an earlier observation timestamp was on time. Technical
I/O bounds are infrastructure policy, not undeclared participant time limits.

After ingress is fenced, in-flight work is drained and the relevant writers are
independently stopped, seal with record count, last hash, per-lease coverage and
controller closure outcome. Store the verified read-only content-addressed object
and retain its Reference/context separately, as in the existing capture modules.
Final seal/coverage failure is UNKNOWN. A valid hash is custody, not task truth.
No role-supplied final manifest or receipt becomes the expected reference.

The new verified adapter must account for every journal row. It exposes the full
offer/refusal/retry evidence as well as a deterministic ack/complete projection
for the existing verdict seam. Each projected row binds original
wave/role/attempt/session/task/generation/revision/nonce and controller elapsed
time. Integer ordering/deadline decisions remain authoritative; qualification
must cover float conversion near a cutoff in the existing `elapsed` interface.
A versioned extension must carry authenticated rejection evidence explicitly;
never discard it or fabricate an ack/complete row to make the old parser accept
it. PR-A's current `protocol` reference alone does not authenticate this journal.

The #622 poke capture and #637 goal capture remain separately verifiable inputs.
Their sequence numbers are not interchangeable clocks. Goal capture currently
has no common-clock binding; do not infer one from a file time or a goal status.
The new controller context and producer integration must explicitly establish
any clock join. This adds no detailed handoff-latency endpoint, listener-state
monitor or per-poke shared-state snapshot under the deferred #623 scope.

## 4. Failure semantics and attribution

The principles are the same as #634's attribution contract: task FAIL requires a
positive, independently retained, attributable violation; unknown runtime or
capture cause is not candidate failure. A signal-range exit alone, stopped
container or missing reply cannot prove the candidate caused it. OOM or a harness
I/O timeout remains UNKNOWN pending the applicable #639 policy. A protocol receipt
never substitutes for independent no-controller-stop/cancellation evidence.

| Observation | Protocol consequence |
| --- | --- |
| Complete, authenticated, on-time stream and independently correct artifacts/lifecycle | Eligible for existing PASS checks, not PASS solely from the stream. |
| Listener absent, socket error, request/reply lost, incomplete frame, missing binding, receiver outage, unknown peer, corrupted/unsealed capture, unconfirmed drain/cleanup | UNKNOWN for affected evidence. No completion is invented. |
| Same request number and identical operation retried | Same decision, retained retry; no duplicate semantic completion. A lost reply cannot manufacture FAIL. |
| Different second completion, ack after completion, complete before ack, or changed content under the same request number | FAIL only when the violating request is positively attributed and the frozen public protocol makes that rule applicable. Preserve its decision and binding witness. |
| Old/wrong offer on a proven current lease | Refuse; attributable protocol FAIL under the declared rule. Assign it to the actual sender, never the role named by the offer. |
| Unknown/unbound sender tries another role's reference | Refuse; UNKNOWN/unauthenticated-ingress diagnostic. It cannot make the target role FAIL. |
| Late event, including an event arriving after the original task deadline or closure fence | Retain as late, give it no completion credit, and report UNKNOWN for that protocol observation. Lateness alone is not candidate FAIL. Any separately proven task-deadline violation remains a distinct existing-kernel witness, never inferred from late telemetry. |
| Missing ack/complete | UNKNOWN while coverage or infrastructure cause is uncertain. An explicit unacknowledged completion is a positive violation; an otherwise fully observed natural abandonment may use the existing kernel rule only with independent healthy-coverage and no-controller-stop witnesses. |
| Role says it cannot complete | Retain refusal. Determine failure from the declared task/lifecycle evidence; refusal text alone cannot diagnose infrastructure or artifact correctness. |
| A later, unrelated stream loses custody | Do not erase an independently verified earlier positive artifact/protocol violation. Conversely, an unverified memory entry or broken journal prefix is not surviving evidence of a violation. |

All planned attempts remain in the denominator, including nonstarts, UNKNOWN and
protocol failures. A successful worker is not an integrated project. Protocol
violations and task grades remain separate fields; the owner must approve their
exact use in the comparison. No protocol success upgrades a delivered artifact
and no missing instrument is quietly treated as product failure.

## 5. Arm-neutrality

Both arms receive the same client, schema, public offer metadata, task-protocol
instructions, retry policy, per-session technical bounds and transport access.
The single-session arm has one declared principal; the wave has its declared
principals. Neither may impersonate extra sessions. This preserves the intended
product-level comparison, not an artificial equal-role-count third arm.

The receiver does not expose other roles' status, communicate work content,
recommend work order, generate CPP issues or wake a role. It changes neither
arm's ordinary tools, native goal behavior, model, token measurement nor egress.
Task offers carry only already-declared information. Any future dependency
routing, dynamic issue offers or extra observations would need a new symmetric
contract. Protocol status is never used to select only successful attempts for
analysis. The independent NHL delivered-result grade remains visible for every
planned attempt; CPP-specific procedure is not a hidden NHL grading criterion.

## 6. Secret handling and required qualification

The recommended design is **not secret-path**: it creates **no application
authentication token or password**, and mints or passes no bearer credential.
There is no credential file, environment variable, argv token, secret URL or
session signing key in a role sandbox. The protected resource is access to its
controller-mounted endpoint. Private runtime IDs/peer credentials and controller
storage paths remain controller-side, outside agent mounts and public exports.
Offer IDs/nonces are explicitly nonsecret and confer no identity authority.

If an alternate design mints or passes a credential, its implementation is a
**secret-path PR**: explicit owner approval, an independent second-model review
and committed no-leak controls are required. Before approval it must specify
where the credential is minted, held, transmitted, revoked and destroyed. No
bearer fallback is approved by this document. A credential visible to an agent
could be deliberately printed or shared by that agent; ordinary log redaction
cannot prove containment of such a secret. Do not promise otherwise.

Even the no-bearer implementation needs independent authentication review and
committed no-leak controls. Plant synthetic secret canaries and private-identity
sentinels in malformed fields, errors and peer metadata; ensure they cannot enter
client replies, controller summaries, public exports, exception text, argv or
environment diagnostics. Qualify the scanner with a deliberately leaking variant
and a clean opposite. Do not retain arbitrary refused bodies as a backdoor into
the journal. Existing private transcript capture remains governed by its own
retention/export boundary, not a new claim that hostile agent output is safe.

Before shipping an implementation, commit model-free controls for honest streams,
alternative allowed work order, wrong-offer attribution, unauthenticated ingress,
endpoint cross-access, stale/revoked leases, misleading payload identities,
startup/session conflicts, retries versus distinct duplicate completion, missing
coverage, deadline boundaries, controller cancellation, fsync failures, altered/
truncated/reordered/misbound seals and the no-leak cases. Make each changed gate
reject a deliberately blind variant. True regressions run on pre-fix public APIs;
new transport APIs are qualified as new instruments. Physical endpoint isolation
and mount/peer behavior need separate authorized qualification; a scripted peer
cannot establish those facts. No such execution is authorized here.

## 7. Owner decisions, with recommended defaults

1. **Authentication unit:** accept the controller-bound sandbox principal,
   including its tools/children. Recommended: yes, with exclusive-session runtime
   qualification and the stated limit on model-process authorship. If literal
   model-process mediation is required, stop and redesign; app-server tool
   mediation in both arms is an alternative, **UNVERIFIED** for the existing
   wave exec/resume path and outside this implementation proposal.
2. **Transport:** use the isolated local socket and no bearer credential.
   Recommended: yes, conditional on identical model-free physical qualification
   in both arms. Unsupported isolation yields UNKNOWN, not a weaker fallback.
3. **Task granularity:** one offer for each predeclared role contribution/public
   task, with no CPP issue or mailbox inference. Recommended: yes. Finer dynamic
   handoffs would change the task/protocol scope and need a separate decision.
4. **Startup binding:** freeze the full launch population before launch, and the
   concrete session-bound assembly plan before the first task offer. Recommended:
   one explicit startup barrier, preserving all nonstarts and the original clock;
   accept no mutable plan after protocol observation. Validate the added producer
   phase against PR-A rather than assuming it already exists.
5. **Effect on grading:** retain #620's attributable protocol verdict separately
   from the independent delivered-result grade, keep every planned attempt and
   never reward CPP-specific procedure. Recommended: use protocol evidence for
   the declared wave/instrument diagnostic; settle any primary endpoint effect
   explicitly in #639 before making participation a candidate requirement.
6. **Retry semantics:** identical request retry is idempotent; a distinct second
   completion is a positive violation under the frozen rule. Recommended: yes.
   Clock/lease/deadline never renew on retry.
7. **Technical limits:** freeze identical bounded requests, journal capacity and
   I/O policy for each session before launch. Recommended starting proposal:
   4 KiB requests, 256 decisions per session and an attempt journal bounded by
   64 MiB/32,768 records, with reserved closure capacity. Qualification must show
   normal operation fits. Overflow or I/O timeout makes coverage UNKNOWN; it is
   not a new task/time/token cap. #639 settles the task deadline independently.

Until these choices and the exact reviewed bytes are accepted, the deliverable
remains this design only. It grants no PR-B implementation or live-run authority.
