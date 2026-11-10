# Three-role CPU/memory declaration inputs (Refs #624, PR-N2)

This slice validates an optional `wave_resources` declaration beside PR-N1's
`wave_accounting`. It adds a pure evaluator over supplied capacity facts. It
collects no host facts, configures no cgroups/quotas, reserves no resources and
issues no scheduling or credential authority. CPU/memory requirements are not
model-token caps. The existing storage helper continues to measure only available
bytes/inodes; a storage PASS cannot substitute for this input.

## Closed plan and joins

The version-1 resources object has exactly `version`, `sizing_report_digest`,
`concurrency`, `roles`, `auxiliaries`, `reservations`, `max_age_seconds` and
`max_collection_seconds`. Its digest must match the owner-declared planning source,
not a client-counter receipt or an accepted client usage basis. This join cannot
establish acceptable measurement provenance.
`concurrency` is `all-roles-simultaneous`; its three ordered role names must match
the declared planning population exactly. Each role supplies positive nonboolean integer
`cpu_millicores` and `memory_bytes` for one role container. This format covers one
simultaneous three-role wave, not an unaccounted overlap of multiple waves.

Auxiliaries are an explicit nonempty array; reservations are explicit and may
be empty. Every row has a unique logical `name`, nonnegative CPU/memory and a
positive integer `multiplicity`, with at least one positive resource demand.
Names are unique across roles/auxiliaries/reservations, avoiding an ambiguous
repeated demand label. The owner sizing lists all applicable controller, fixture,
proxy and other demands; parsing cannot prove that the actual topology was
completely described. Multiplicity counts distinct simultaneous instances, not
extra capacity. The provided fixtures include controller/fixture overhead and
three role proxies; their numbers are synthetic, not selected study settings.

All roles, auxiliaries and reservations contribute to CPU and memory totals.
A single VM's capacity is compared once against those sums; no alias population
is added as though each name were another machine. Values/products/totals fit
2^63-1. Auxiliary and reservation arrays are bounded to 256 rows each. Time
windows are explicit positive finite nonboolean numbers, not defaults.

Calibration parsing and approval revalidate this field. Discrimination refuses
it. Direct PR-N1 bound planning validates it too, so the two consumers share the
same role/source/shape rules. The existing whole-declaration approval digest
covers resource changes; supplying a digest is consistency, not issuance of an
approval. The rest of declaration validation remains its existing contract.
Legacy declarations without this opt-in retain their parsing, plan and report
behavior. No live caller is added.

## Pure supplied-fact evaluator

`wave_resources.Binding` binds logical collection/window/wave identifiers, VM
binding digest, whole declaration digest and sizing digest. The trusted caller
holds it independently. `evaluate(plan, receipt, binding, now)` requires a PR-N1
bound plan and exact bindings. The closed receipt has version 1, the binding,
started_at/finished_at, `complete: true`, `available_cpu_millicores` and
`available_memory_bytes`. Availability counters are bounded nonboolean integers;
zero is an observed shortage, not missing data. Missing, ambiguous, malformed,
future/stale or excessively slow facts are UNKNOWN. The supplied current epoch
is not a clock attestation; a fabricated receipt never gains authority.

CPU and memory must BOTH cover all declared simultaneous demands/reservations:
complete sufficient inputs yield PASS; measured-in-input shortage yields FAIL;
unavailable or misbound inputs yield UNKNOWN. Every result states
`admission_authority: false`. Sufficient output also says the source is
`owner-supplied-facts-no-host-observation-here`. No actual CPU or memory observation
was made to qualify this implementation. No private host names, filesystem paths,
raw process data or account identifiers belong in this format's public labels.

A later approved owner adapter would need to establish effective CPU/cgroup and
memory availability, relevant competing reservations, collection provenance and
freshness on the actual VM. Host-wide totals are not automatically available to
the run. Measurement alone would not reserve that capacity. Physical admission,
enforcement and the independently approved window remain separate work.

## Controls and scope

The committed pre-gate sweep exercises 44 parsed levels and 278 malformed or
incomplete variants across policy, role/auxiliary/reservation, binding and receipt
fields. Missing/extra members at each object, zero/overflow/nonfinite values,
consumer argument types and explicit empty-reservation controls supplement it.
PASS/FAIL/UNKNOWN twins distinguish sufficient capacity, CPU shortage, memory
shortage, reservation pressure and incomplete evidence. Actual compiled
always-PASS, ignore-reservations and ignore-owner-binding variants must lose
those committed witnesses. These qualify a NEW evaluator; old-main absent APIs
are not regression evidence. Private-output qualification includes a seeded leak.

Before this fix, 20 unchanged existing-consumer controls failed on
pinned main `3ef2546` because invalid resource inputs were ignored; one valid-input
identity control passed. All 20 were meaningful DID NOT RAISE DeclarationRefused
failures, with no API/setup errors. They cover the missing third role, CPU/memory
shape, source/concurrency, auxiliary/reservation and freshness inputs. The new
controls include 19 calibration cases and one discrimination opt-in refusal. The
resource evaluator is qualified separately with authored data only.

Capped dispatch remains refused under the existing NHL limits contract; uncapped
mode installs no model-token stopper. This PR changes no credential, steward or
agent-trial delivery code and invokes no host/model/Docker operation. The secret
adapter remains deferred to its separate SECRET-PATH review and #630 contracts;
actual subscription concurrency and final resource sizing remain #639 work.
