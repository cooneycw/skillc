# Operator receipts and admission lifecycle

This is the second bounded code slice of #630. It records and validates
controller/operator evidence; it does not observe hosts, execute system tools,
launch work, deliver credentials, operate Docker or change runner state.
CLOSED covers admission lifecycle only. Credential cleanup, host teardown and
runner restart belong to later slices.

The collector callback is the trust seam. Authenticating its authority is a
later trusted-adapter responsibility. Neither a self-written authority string
nor a matching digest proves physical provenance. In-process registration stops
participant dictionaries or another collector's receipts from being accepted;
it does not defend against malicious Python within the trusted controller.
No participant JSON route, automatic observer or receipt-loading endpoint exists.

## Declaration and existing approval gate

An ordinary `calibration-declaration` can add `operator_admission` only alongside
the slice 1 `execution_environment`. The closed version 1 object declares a
nonempty, distinct `planned_waves` list and a complete `policy`:

- `max_receipt_age_seconds`;
- `max_clock_sample_age_seconds`;
- `max_clock_offset_seconds`;
- `collection_timeout_seconds`;
- `firewall_policy_digest`;
- `allowed_workloads`, the exact allowed logical host-workload set.

All operational values are declaration inputs with no defaults. The owner must
supply the actual policy. Committed fixtures explicitly label their values as
synthetic; they are not deployment recommendations. Numeric values must be
finite nonboolean numbers, ages/offset nonnegative and collection timeout
positive. Firewall identity is a content digest. Logical identities are bounded
and distinct. There are at most 1,000 planned waves, 10,000 issued receipts per
collector and 64 KiB per receipt as implementation resource bounds.

These fields join calibration's existing whole-declaration digest. There is no
new approval-writing or alternative authorization path. Discrimination
parsing and both discrimination approval entry points refuse the field.

`calibration.require_approved` gains only a keyword-only `operator_admission`
input of type `ApprovalInput`. Opted-in declarations refuse missing, mismatched
or insufficient evidence there, after existing approval and installation checks.
Non-VM and slice 1 binding-only declarations keep their existing behavior.
A binding-only declaration cannot create a `WindowSession` for dispatch: the
admission API requires the explicit policy and planned-wave population.

## Collection and provenance

`OperatorCollector(authority, callback)` calls only the explicitly supplied
trusted callback. A request carries check name, controller collection identity,
window ID, wave ID, VM binding digest and whole-declaration digest. The callback
returns those binding fields, an `observed_at` epoch timestamp and check payload.
The collector stamps its authority, check, version and monotonically increasing
sequence into immutable canonical bytes, then registers the issued object.

A session accepts only registered objects from its configured collector, with
the exact binding and increasing sequence. Copies, unregistered objects, raw
participant dictionaries, duplicate checks and replay refuse. Retained facts
are copied before later source mutations can affect them. A successful send or
operator-provided authority string alone is never sufficient.

Required observations are:

| Check | Required facts |
|---|---|
| verified-key | Out-of-band verification succeeded and observed fingerprint equals approved VM fingerprint. |
| time-sync | Synchronized, positive packet count, fresh exchange, explicit restart fact, offset within declared bound and fresh nonfuture clock sample. A retained synchronized flag with zero packets cannot qualify after restart. |
| firewall-isolation | Matching policy digest; complete firewall and isolation observations; approved management/provider connectivity and blocked forbidden egress; complete workload population within the declared allowed set. Container state does not imply host isolation. |
| runner-drain | Complete observation; timer and service inactive, service substate dead, no runner job or process. Inactive timer with activating oneshot service refuses. |

Observation completeness is an assertion from the trusted callback, not derived
physical evidence in this pure slice. Its actual collection/authentication and
independent positive/negative host probes must be supplied by a later adapter.
Private evidence may contain operator identity; public reports must remove real
machine, account, topology and local-path information.

## Clocks, transitions and nonstarts

A `WindowSession` snapshots the declaration and records its slice 1 VM/install
binding. Both wall and monotonic clocks are explicit injected inputs. Wall epoch
seconds evaluate the approved window, receipt age and clock-sample age. Future,
stale or outside-window receipts refuse. A separate per-wave monotonic deadline
starts with collection; it cannot be reset by adding another receipt, and late,
backward or unavailable readings refuse. The synchronous API rejects results
returned after its deadline; the trusted adapter must independently bound any
blocking IO because this API cannot preempt a hung callback.

State operations are serialized within a session. Every planned wave starts
PLANNED and moves through COLLECTING and ADMITTED to DISPATCHED, then CLOSED.
`admit` and `request_dispatch` call the existing calibration approval gate.
Dispatch rechecks approval, VM/install binding, receipt completeness/freshness,
wall window and monotonic deadline. It records a transition only; it executes
nothing. A second or concurrent duplicate dispatch refuses.

An unverified admission records terminal NONSTART with task status UNKNOWN and
sanitized reasons. Later good receipts cannot rewrite it. CLOSED can follow
NONSTART or DISPATCHED but never asserts host cleanup. The report contains every
planned wave, including untouched waves with no observations and no dispatch.
All task statuses remain UNKNOWN: admission does not grade a task or certify
that execution actually began. Receipt digests and source authority retain the
provenance join; report copies cannot mutate the session.

## Controls

`controls/vm-admission/` contains synthetic policy, receipt payloads and planted
inputs. Healthy full same-window evidence and a valid alternative check order
admit. The inactive-timer/activating-service case, stale/future/wrong-window or
wrong-approval/VM receipts, zero packets, unexpected workload, incomplete
firewall and absent host observation require nonstart UNKNOWN. The same
committed activating-service input defeats a deliberately always-admit
implementation. Wrong collector, arbitrary participant dictionaries, source
mutation, replay, duplicate dispatch and clock failure are separately tested.
The calibration regressions that previously ignored `operator_admission` are
pre-fix reds; new state-machine controls are planted cases, not claims that a
missing new API was an old defect.
