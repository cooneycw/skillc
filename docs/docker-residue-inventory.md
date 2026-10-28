# Docker residue inventory and ownership boundary

Refs #549. This command inspects Docker and writes an **unapproved selection for
operator review**. It never builds, tags, starts, stops, removes or prunes a
resource. It has no apply mode. No image producer, live-test release helper or
container/network reaper is changed by this delivery.

```bash
python3 ci/docker_residue_inventory.py --out inventory.json
```

The output path must be new. Exit 0 means a complete, nonempty matching inventory,
not clean completion or removal permission. Exit 2 and `inventory_status: unknown`
mean an empty matching population, unavailable/invalid inspection, mismatched
IDs, or a population change. Positive observations remain in the artifact, but
all proposed removals are cleared when observation is incomplete. The default
overall observation budget is 120 seconds; `--timeout` accepts at most 600.

## What is observed

All image, container and network IDs are listed without label filters, inspected
in batches of at most 64, and listed again to detect arrivals/disappearances.
IDs must be full immutable IDs, not short display prefixes. `listed_counts` and
`inspected_counts` distinguish enumeration from successful inspection.

Images match a `skillc-` repository component, `skillc.managed=true`, or the
existing `org.skillc.image=trial-image` marker. Containers match the managed label
or a `skillc-` name. Networks match the label, a `skillc-` name, or an `-egress`
suffix. A name is candidate provenance, never ownership or proof of abandonment.
Image tag counts are separate from ID counts; digest aliases are not tags.

An unrelated container, including a stopped one, still protects the image it
references. A running matching container or an attached network is excluded from
proposals. Resources found only by a name or label retain `ownership: unknown`.
Even an idle matching resource proposed for review has `approved: false`.
Neither process death nor absence of active leases is inferred.

## Pins

These repository names are always protected:

- `skillc-375-final`
- `skillc-279-ca3030d`
- `skillc-434-rev2`
- `skillc-529-*`

**Any** pinned tag or digest alias protects the entire image ID, even when that
same ID also has an apparent clutter tag. Registry/namespace aliases are checked
by their final repository component. Pins appear separately in
`protected_image_ids`, and cannot appear in proposed removals. `skillc-trial` is
not a pin; it can be proposed for review if it has no observed container reference.
Unnamed or label-only images are retained as unknown provenance.

## Ownership contract and proposed follow-up

`cleanup_status` is always `unassessed`. This is an observation artifact, not an
ownership lease or an acceptance result. A stable ID set does not make aliases,
labels, references or external users atomic. Before any actual removal, the
operator must approve exact resource IDs and freshly inspect aliases, pins,
references and retention requirements. A new arrival is never chased.

The existing unlocked live-test release no-op is intentional shared-build
protection. Removing it while relying on a before/after image snapshot would
allow a concurrent cached build to be mistaken for the current run's property.

Proposed follow-up, **not implemented or approved here**:

1. An opt-in producer run UUID, ownership labels at build/run time and an atomic
   local allocation journal could distinguish created disposable resources from
   borrowed shared bases. Private tags must not move shared deterministic tags.
   New ephemeral identities/receipts must not rewrite historical evidence.
2. Only a matching positive ownership record could enable unlocked release;
   incomplete allocation/build/receipt paths would need reconciliation and
   independent absence confirmation. Shared, pinned, foreign and unknown inputs
   stay retained. No forced image removal or global prune is proposed.
3. A separately reviewed interrupted-owner recovery contract could bind owner
   PID, process-start generation and boot/daemon identity in local records, then
   reuse explicit selected-attempt recovery. Age or PID alone cannot authorize
   stopping an owner. Legacy unlabelled residue needs explicit operator selection;
   a name prefix must never be retroactively promoted into a lease.

## Read-only host handoff

The maintainer routes this inspection to the operator before merge. No resource
creation or removal is required for the first inventory. From a checkout holding
the proposed commit, use a fresh output filename:

```bash
inventory_source_commit=$(git rev-parse HEAD)
python3 ci/docker_residue_inventory.py --out docker-residue-inventory.json
inventory_status=$?
python3 - docker-residue-inventory.json "$inventory_status" "$inventory_source_commit" <<'PY'
import json
import sys
report = json.load(open(sys.argv[1]))
print(json.dumps({"source_commit": sys.argv[3], "exit_code": int(sys.argv[2]),
                  "inventory": report}, indent=2))
PY
```

Send back the JSON and the exact source commit. Expected observations on a host
with named unlabelled images: those images are included despite missing managed
labels, pins are separated, container references block image proposals, and all
proposals remain unapproved. Historical counts are not expected constants.
Zero matching containers/networks is only the observed result; it is not a seeded
hit test. An empty matching population or any inspection uncertainty must return
exit 2, `unknown`, and empty proposal lists. Do not publish the raw host artifact
without checking resource names for local/private identities.

The committed controls use named-but-unlabelled and pinned-alias fixtures, an
empty fixture, a foreign sentinel, and malformed/unavailable/changed inventories.
The actual CLI control permits only list/inspect argv shapes and rejects existing
output files. Container tests do not claim compatibility with a real daemon;
the operator's read-only handoff supplies that separate evidence. No removal
handoff is part of this PR.
