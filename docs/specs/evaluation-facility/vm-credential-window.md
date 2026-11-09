# Operator login and held credential windows (Refs #630, slice 3)

This slice implements the owner-approved design's metadata and steward seams.
It does not implement a credential source, login command, token transfer,
reference-retention bridge, removed-root absence evidence or real-window executor.
All qualification uses synthetic callbacks and memory-only markers.

**Real credential-window dispatch, export and runner release remain blocked.**
The two later contracts are not approved: lawful memory-only reference retention
and trusted absence evidence for deleted roots. A missing/empty root remains
UNKNOWN under slice 4. Login/logout receipts, admission CLOSED, a public CLEAN
dictionary, or zero #619 clutter cannot fill those gaps. No flag, environment
variable or callback enables production dispatch/release in this implementation.
Only the owner controls eventual runner restoration under a separate window.

## Declaration and login

A calibration declaration may add the closed object:

```json
{
  "credential_window": {
    "version": 1,
    "client": "codex",
    "account_class": "owner-subscription",
    "source": "owner-interactive-login",
    "storage": {
      "kind": "tmpfs", "directory_mode": 448, "file_mode": 384,
      "persistence": "prevented"
    },
    "stop_on_refresh": true
  }
}
```

This is a required operating plan, not evidence that a host has that storage.
It requires the existing VM identity, operator admission and complete remnant
scan declarations. The scan plan supplies the exact wave/role population. All
fields join the existing whole-declaration approval digest; this is not an
approval writer or a new authorization path. Discrimination parsing and approval
refuse the field, including an opt-in injected after parsing.

The owner, through the authorized host helper, verifies endpoint identity,
reserves/drains the window, checks time/isolation and the reviewed install, then
logs in interactively over SSH into the declared transient session. No token
travels through GitHub, a mailbox, argv or an environment value. Do not copy a
persistent home or silently use an API key instead of the native subscription
login. Prevent swap/hibernation/core-dump persistence or keep the window blocked.
Physical observations and actual operator actions are separate approvals.

An opted-in admission requires all four existing host checks plus
`credential-login`. The existing collector issues immutable registered receipts;
raw dictionaries, copies and another collector's receipts are not provenance.
Login payloads contain exactly `account_class: owner-subscription` and a finite
`login_at` epoch timestamp. Only that minimal payload is serialized; unknown
fields/account identifiers/token hashes/paths are refused before issuing a
receipt. The binding envelope retains the existing collection/window/wave,
VM/install and approved-declaration identities, observation time and sequence.
Login must occur within the window, not in the future. Existing receipt/window
freshness and collection deadlines still apply. Policy values have no new
operational defaults.

`WindowSession.credential_input(wave, root)` first admits that metadata, then
returns a registered `WindowCredentialInput` containing no credential bytes.
The issuer rechecks object identity, receipt identity, approval/binding and
freshness before steward operations. Copies, stale input and held windows refuse.
Logout, failed active-input revalidation and stewardship failures latch a hold.
`request_dispatch` on an opted-in window explicitly records nonstart/UNKNOWN and
refuses because the two contracts are unavailable, even with complete login
receipts. Existing declarations without the opt-in preserve their admission
report bytes and never resolve/read a credential.

## Per-role steward and close rehearsal

`StewardBridge` accepts the registered input, every declared role's distinct
session UUID and explicit `RoleBinding` callbacks. The #624 adapter owns actual
role provisioning through the existing owner-only home delivery/steward APIs;
there is no automatic backend, source search or executor here. An adapter must
register cleanup for partial preparation before attempting it. Its source must
be fresh at each preparation and have sufficient known remaining lifetime for
the planned window; this bridge does not implement or attest that source reader.

Preparation requires each actual steward's armed acknowledgment. `before_turn`
requires the bound role/session and, for each resume, calls the existing driver's
restore-and-rearm path. A trusted controller separately records each actual
launch. Missing, duplicate, wrong-session or extra arms refuse; final steward
arms reconcile to those launch records. No record or arm launches a model.
Refresh/reappearance, missing coverage or an invalid turn holds the entire
window. Stewardship remains hygiene against accidental/instructed nested clients,
not hostile same-user containment. It does not prevent provider-side rotation.

Close holds the window first, freezes the pre-stop census, reads/stops each
started steward while accessible, confirms writer stops, obtains the operator
logout receipt, removes copies, attempts every role cleanup, then checks the
supplied read-only scan observation. Callbacks report confirmations; neither
calling them nor a Docker exit code is physical proof. Callback errors are fixed
unavailability facts, not raw diagnostics. Interrupts during preparation/close
attempt cleanup and propagate afterwards. Close is idempotent.

A `credential-logout` receipt has the same binding and exactly account class plus
`logout_at`; it must follow the held login, be fresh and come from the registered
collector. Logout collection itself latches a hold. A cleanup observation accepts
only the actual `ScanResult` matching the declaration, exact private roots and
same generation object; a copied public result does not qualify. Known matches
remain NOT_CLEAN and incomplete/missing observations remain UNKNOWN.

The report exposes only fixed statuses, booleans, counts and unavailable-contract
classes. Even a complete synthetic CLEAN scan remains diagnostic: the result is
UNKNOWN/held with `exported: false`, and the supplied export callback is never
called. No removed-root exception or reference extraction/retention is smuggled
into this rehearsal. Existing home delivery writes container files and existing
vaults are not automatically tmpfs; a later reviewed adapter must establish the
actual storage guarantees before any real window. This slice performs no
teardown, logout, VM observation or runner restart by itself.

## Qualification, privacy and operator boundary

The committed controls cover required login, closed payloads, binding/freshness,
copy/replay, model-free defaults, role/session/arm population, refresh, partial
preparation, interrupted cleanup, logout and scan-context errors. A legacy report
fixture captured on the parent pins byte-identical non-opted-in behavior.
Dispatch-allowing, always-release and leaking-repr variants are refused.

The five named no-leak tests audit only synthetic material: minimal receipt
fields; source-free default; public reports/reprs, adapter exceptions, argv,
files and captured stdout/stderr/logs; planted exported role material; and the
cleanup/release hold. The independent #678 no_marker oracle includes fixed
encodings and diagnostic renderings. A deliberately leaking variant must fail
that oracle. Steward repr now excludes its cached vault bytes. Raw references
are never test IDs or parameter values; opaque fixture objects prevent a forced
traceback with locals from serializing them. Arbitrary Python inspection of
private fields/process memory remains trusted; Python promises no secure erasure.

CI establishes these pure contracts and fake orchestration only. Real endpoint
identity, tmpfs/persistence behavior, native login, provider concurrency, physical
steward timings, complete scan custody/absence and final restoration need their
separately approved operator window. This SECRET-PATH PR additionally requires
owner `approve <PR>`, a different-model-family review and committed no-leak tests.
The design approval grants no declaration/window/spend/credential/operator action.
