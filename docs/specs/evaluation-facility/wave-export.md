# Complete wave export integrity

This is the fifth bounded code slice of #630. The APIs seal a local manifest
and check local arriving bytes. They perform no transport, VM access, container
operation, credential handling, source deletion or dispatch. The operator
selects and executes actual transfer and retains the source. VERIFIED means
export integrity only; it never changes task PASS, FAIL or UNKNOWN.

The controller catalogue and separately retained expectation are trust inputs.
A later trusted adapter owns their authentication and custody. Neither a
self-authored manifest nor a matching digest proves physical provenance.
There is no participant catalogue endpoint or automatic observer. Public
summaries must omit private identities and paths from protected run evidence.

## Approved population and provenance

An ordinary calibration declaration may add `wave_export` version 1, with
`waves` entries containing `wave_id`, a nonempty distinct `roles` list and an
explicit `empty_capture_roles` subset. Wave IDs/order must exactly match
`operator_admission.planned_waves`; VM environment and operator admission
policy are required. These values join the existing whole-declaration digest.
Discrimination parsing and approval entry points refuse the field. Existing
declarations without it keep their behavior. No existing declaration is edited.

`calibration.approval_record_binding` shares the existing schedule/approval
record and whole-declaration digest checks. Its frozen `ApprovalProvenance`
contains the declaration digest only; the entire original approval snapshot is
retained in the sealed manifest. Unchecked approval annotations gain no new
serialization constraint in existing approval calls. It is not dispatch
admission, current VM eligibility, an approval-writing API or a capability.
`require_approved` shares the helper at its existing digest backstop; all other
approval and host-admission requirements remain in place. The helper's result
cannot replace a controller admission input or dispatch argument.

Export intentionally uses this stored provenance join, not `require_approved`:
a failed host admission still needs its NONSTART evidence exported. Sealing
UNKNOWN evidence cannot authorize a run or convert it into success.

## Trusted final catalogue

`ControllerCatalogue.from_controller` snapshots canonical immutable bytes from
an explicitly supplied controller catalogue. This constructor authenticates
nothing. The trusted capture producer must enumerate every expected record,
turn/stream, transcript and capture before sealing; deriving expectations from
the arriving tree would hide omissions.

The closed catalogue has version, declaration/window/VM-binding digests,
identity/admission record paths, the complete original slice 2 admission report,
per-wave role/record metadata and an independent exact payload census.

Each wave preserves its original task status and every declared role. Required
slots are a captured wave report and, for each role, a captured role report,
transcript slot and capture slot. A slot is CAPTURED with a safe path, or UNKNOWN
with no path and an explicit reason. Unknown transcript/capture slots preserve
unavailable evidence without inventing empty transcript files. NONSTART waves
remain task UNKNOWN with unknown transcript/capture slots. Raw operator receipts
referenced by the admission report must all be included and joined by digest,
sequence, check, authority, wave, window and declaration identity.

Additional turn, stdout, stderr, protocol and artifact records are allowed only
as explicit unique catalogue entries tied to declared roles. Every payload item
must belong to a record scope or its ancestor directories. Explicit capture
subtrees may contain their enumerated opaque entries; uncatalogued extras
refuse. Empty capture files/directories need the approved role allowance.

The original slice 1 MATCH identity record is checked against the stored VM
contract, not against a current host. A closed UNKNOWN identity diagnostic with
reason and declaration/window binding can also be preserved. Its canonical
identity digest joins the admission report; this cannot confer VM eligibility.
Wave report bytes retain their wave/status identity, role reports retain
wave/role identity, and admission bytes must equal the complete retained report.
Untouched UNKNOWN rows and CLOSED NONSTART rows are never filtered out.

## Local sealing and arrival verification

`freeze(source, declaration, catalogue, fresh_manifest_out)` reads source
through SafeTree, compares actual population/content to the independent
catalogue, checks record joins, then repeats the census to reject ordinary
drift. It writes **manifest only** in a fresh disjoint output directory. No
payload is copied, no destination is replaced and no source is modified or
removed. Existing or overlapping output refuses. Sealing failure returns no
verified receipt; callers must retain source and report unavailable export.
The two reads are not an atomic filesystem freeze: custody after sealing
remains a controller/operator obligation.

The returned frozen expectation contains manifest SHA256, declaration digest,
canonical plan and original wave outcomes. Retain it independently from the
transfer. The operator builds an arrival containing exactly `manifest.json`
and `payload/`, using its own transport. Manifest mode is 0600. Payload census
records regular files and directories, full permission bits, sizes and content
digests, including explicitly empty directories. Links and special files refuse.

`verify_arrival(arrival, expected)` requires that separate expectation. It reads
the manifest against the independently retained digest, rechecks declaration
provenance, approved population and record joins, and recenses actual payload
bytes/modes twice. A transfer receipt is not an input and earns no credit.
Replacing both manifest and payload still fails against the original expected
digest. The arrival API is read-only; it never retires the source, even after
success.

Any missing, extra, altered, truncated, wrong-wave, absent-role, unreadable,
unreachable or changed arrival gives export UNKNOWN for the full planned
denominator. It never invents task FAIL or silently drops a nonstart. An exact
arrival gives export VERIFIED while retaining task outcomes unchanged. A later
`live_wave` adapter may consume verified Blob bytes or mark capture unavailable;
this slice adds no grading algorithm and erases no independently known violation.

SafeTree and `wave_capture`'s shared 4,096-entry, 64 MiB and depth-32 bounds are
reused, with 8 MiB per file and 4 MiB metadata. No profile export schema,
exclusion glob, host Git execution or widening of existing final-two-root
capture contracts is introduced. The reader injection seam is for trusted
adapters/tests; unreadability controls use injected errors so root cannot
bypass a permission-only test.

## Evidence and controls

`controls/wave-export/` declares only synthetic expected populations and planted
bad arrival actions. Healthy exact export includes empty allowed captures,
UNKNOWN outcomes and NONSTART records. Controls cover role/nonstart/transcript/
record/turn/stream omissions, byte/file/directory/manifest-mode corruption,
truncation, wrong wave, extra envelope/payload entries, links, missing empty
surface, replaced manifest plus bytes and unreachable arrival. A committed
missing-transcript case defeats an always-verified checker. Independent tests
inject unreadability and source drift, enforce bounds, reject invalid source
catalogues and preserve original PASS/FAIL/UNKNOWN without dispatch eligibility.
Fixtures explicitly materialize file and directory modes before introducing
corruption, so permissive checkout umasks do not change the control artifact.

The ignored `wave_export` calibration-field tests are genuine pre-fix refusal
regressions. New freeze/arrival controls are planted inputs, not a claim that an
absent new API was an old defect. Production record wiring, authenticated
transport, source retirement and physical execution remain later work.
