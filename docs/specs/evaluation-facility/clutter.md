# Controller-owned clutter inventory (#619)

The instrument measures surviving additions to the declared subject environment.
It records setup state, waits for controller-witnessed completion and the declared
settle point, then records state again **before stopping the roles**. Stopping a
container first would hide precisely the orphaned watch loops this endpoint must
find. No model call is part of collection or qualification.

## Outcome and preservation

Each added surviving logical item belongs to exactly one bin:

- `delivered`: an exact result selector in the common declaration;
- `declared-allowed`: an exact permitted-product selector, such as a friction log;
- `clutter`: every other addition.

Selectors are disjoint `(surface, key)` pairs. There are no implicit CPP exemptions
or unrestricted wildcard allowances. `CLEAN` means zero added clutter and complete
before/after coverage. Known clutter gives `NOT_CLEAN`; incomplete evidence without
a known violation gives `UNKNOWN`. The JSON `clean` value is respectively `true`,
`false`, or `null`. Counts describe the observed additions, including when another
surface is unknown; they never make unknown coverage clean.

Changes and removals of pre-existing items are **preservation observations**, in a
separate section. Neither increases nor reduces the clutter count. Legitimate task
edits and damage to sibling work both appear there; #278's independently declared
ownership rules decide which are permitted. A clutter-clean result is not a claim
that preservation passed. A live process in a removed cwd is separately reported
under `preservation.deleted-cwd`, including when its old pathname was recreated.

`clutter.no_forbidden_side_effect(report, preservation_outcome)` supplies #568's
composition: clutter or a deleted live cwd, or an independently violated #278
criterion, yields `VIOLATED`; missing clutter or preservation evidence yields
`UNKNOWN`; only clutter-clean plus independently satisfied preservation yields
`SATISFIED`. The function does not infer preservation from zero clutter, and does
not change any existing task's grading criteria automatically.

## Declared scope

`clutter_inventory` is an optional root field on calibration and discrimination
declarations. It is common to all arms. The whole-declaration approval digest
binds its schema version, scope, settle rule and complete allowed-product list.
Each planned trial's hashed configuration also binds that same policy and the
approved declaration digest. Report recovery uses those configuration objects,
not a replacement declaration or a mutable outcomes checkpoint. Declarations
without the field retain their previous configuration and report shapes.

Example policy shape (illustrative fixture paths, not a live approval):

```json
{
  "schema_version": 1,
  "daemon_scope": "controller-isolated",
  "settle_point": "after-completion-before-teardown",
  "settle_seconds": 0,
  "roles": {
    "agent": {
      "checkout": "/work/work",
      "gitdir": "/work/work/.git",
      "remotes": {"fixture": "/work/.remote/widget.git"},
      "cpp": {
        "registry": ["/state/registry.json"],
        "mailboxes": ["/state/mailboxes"],
        "cursors": ["/state/cursors"],
        "heartbeats": ["/state/heartbeats"],
        "locks": ["/state/locks"],
        "claims": ["/state/claims"]
      },
      "temp_roots": ["/tmp"]
    }
  },
  "shared_roots": [],
  "delivered": [{"surface": "agent/workspace", "key": "file:/work/work/result.txt"}],
  "declared_allowed": [{"surface": "agent/workspace", "key": "file:/work/work/friction.log"}],
  "allowed_subtrees": [
    {"surface": "agent/workspace", "path": "/work/work/.venv"},
    {"surface": "agent/workspace", "path": "/work/work/__pycache__"}
  ]
}
```

Use the actual paths of the pinned fixture and subject profile. Every CPP family
and a temporary-directory scope must be named, including for a no-CPP baseline.
An actually absent optional CPP path is an observed empty surface, not a missing
observation. An omitted family or role cannot establish clean coverage. The
single-attempt bridge has one role, `agent`; waves declare every role and at least
one shared-volume root. The shared-volume root must remain observable.

`allowed_subtrees` is optional (default: none), with at most 64 exact, distinct,
non-overlapping paths strictly beneath a declared workspace checkout. Directory
contents at those roots are not walked. Every report names them under
`not_inspected` and states that their contents were not inspected. `CLEAN` means
zero observed clutter outside these explicit blind spots, not inspection of
their contents. A file or symlink at an allowed directory path is still recorded
as an item; targets are never followed. There are no default cache exclusions.
The example list above is illustrative only; the actual study list requires
owner approval in the frozen declaration (#639), equally for both arms.

Allowances cannot name the whole checkout, another surface, a declared product,
or overlap declared Git metadata, fixture remotes, CPP roots, shared wave state or
temporary scope. They affect only workspace enumeration. Independent worktree,
ref, CPP and shared-state collectors still run: a registered worktree beneath
an allowed environment directory remains visible and an extra branch remains
clutter. Putting a shared wave-state root beneath an allowance is refused.

The controller must designate an isolated daemon namespace before using
`daemon_scope: controller-isolated`. The declaration alone does not establish
physical isolation. All containers and networks in that namespace are inventoried
without an untrusted-label ownership filter. A shared or unobservable daemon must
use `daemon_scope: unobservable`, which yields UNKNOWN rather than an invented
empty census. Different role-daemon bindings also remain UNKNOWN in this profile.

## Observations

For each role the required surfaces are worktrees, local Git refs, fixture-remote
refs, stashes, workspace files, all six CPP families, processes and temp roots.
There are also required shared-state, container and network surfaces.

- Git comes from `git_snapshot.SafeTree`/`GitDir`, never a Git subprocess over
  subject-controlled configuration or hooks. Linked-worktree registration is
  checked both ways. Stash identities come from the ref and reflog, not a count
  that could match after replacing another task's stash. Ref inventories include
  tracking, tag and other ref namespaces as well as branches.
- Workspace enumeration includes files even when Git ignores them. It does not
  emulate ignore-pattern semantics or discard a file because it is ignored.
  Only explicit `allowed_subtrees` stop enumeration. Symlinks are items containing
  a target and mode fingerprint, read under a pinned no-follow parent; neither a
  dangling target nor a target outside the checkout is followed. Unreadable or
  changing links remain unknown. Git metadata must still support raw Git reads.
- Files, directories and structured state entries are distinct logical items.
  JSON object/array nodes and revision-framed CPP mailbox messages are observed
  separately from their storage file: appending a registry entry or message to a
  pre-existing file cannot disappear into that file's preservation change.
- Process identity is `(PID, kernel start time)`, with a second start-time check
  to detect PID reuse during collection. The collector reads the kernel cwd inode
  and link count, not a recorded pathname. It does not read process environments
  or retain argv. The observer process excludes itself. The Linux reader checks
  filesystem credential transitions when observing a different process identity;
  its real/effective identity stays privileged and no container capability is
  added. Unsupported or refused transitions make coverage unknown. A cross-user
  kernel control runs only as root; its explicit skip is not a positive result.
- The daemon census is bounded and read-only. Every enumerated immutable ID must
  be inspected exactly once. Missing, duplicate, foreign or unreadable inspection
  rows do not count as complete coverage. Genuine complete empty censuses do.

The collector uses shared byte/item/depth bounds and bounded CLI output/deadlines.
Unsupported Git metadata, special files, malformed structured state, unreadable
paths, missing namespaces or exceeded budgets remain UNKNOWN. It never launches
subject code on the controller host. The Docker path sends only trusted collector
source through the backend's root observation primitive; unavailable Docker roles
have no host-execution fallback.

## Controller lifecycle and evidence

`clutter_controller.docker_inventory(policy, sources, shared_role=...)` requires
all role handles and captures the selected role's shared mount. `Session.setup()`
records the before view. The controller records each role's completion, then
`Session.finish()` observes the declared settle delay and captures the after view.
A missing completion or an early settle point cannot certify clean.

Calibration passes the same policy through its existing dispatch path in both
arms. Its successful final turn witnesses completion; timeouts and non-starts do
not. `before_stop` captures while the role is still running. Existing attempt
accounting and task grades remain separate from this additional endpoint.

The before view and final report are write-once content-addressed controller
objects, bound by `clutter-before` and `clutter-after` journal events. Report
recovery verifies those objects and re-runs classification; it does not trust a
cached clean flag. Fixture graders receive the opt-in inventory evidence through
the controller-held trusted envelope. The multi-role API is available to wave
controllers; it does not create a new wave launcher or bypass #621's lifecycle.

## Controls and limits

`controls/clutter-inventory/cases.json` commits planted worktree, local/remote
branch, stash, watch/supervise process, lock, registry, mailbox, cursor, heartbeat,
claim, ignored-file, shared-state, temp, container and network cases. Every planted
case must read NOT_CLEAN. The tests also plant actual trusted Git/files/process
state, and prove both worktree-first and stash-first cleanup orders clean. Other
controls cover unknown/partial/malformed observations, missing roles, daemon
binding drift, mutable baseline aliasing, PID reuse, deleted/recreated cwd,
controller-object corruption, duplicate journal entries and checkpoint tampering.
`realistic.json` supplies environment/cache roots and independent worktree,
branch and wave-state controls. The realistic positive twin delivers its product
with a venv symlink and cache; outside residue fails while inside contents are
explicitly not inspected. A symlink outside allowances stays observable as an
item without discarding the delivered-product rows.

Local qualification is model-free: trusted fixture repositories, fixed sleeping
processes, fake Docker transport and a trusted read-only collector packet. It is
not a physical multi-container or native-client qualification. No Docker image is
built and no live model is called by these controls.

A final snapshot cannot see something created and deleted between observations.
Captures across surfaces are not an atomic transaction. Processes are visible
only within the controller's declared namespaces. Daemon attribution requires the
controller's isolated namespace. The in-container process census has only fake
Docker qualification here. It excludes the observer itself, but has no separate
controller-ownership attribution: a controller-owned process started mid-attempt
and still present at the final snapshot is an added clutter candidate unless
explicitly declared allowed. Skillc's own harness cleanup is #549; sibling
preservation is #278. Declare the actual subject/project roots rather than
silently treating either workstream as permission to leave subject residue.

The coverage and identity-floor patterns adapt `core/container_inventory.py:328`
and `:629`, and kernel cwd liveness adapts `core/cwd_liveness.py:137` and `:258`,
from `cooneycw/kyle` at `4021172f70d9cfab533f82987159d82447fc644c`. The owner
allowed copying at that pin; this implementation has no import, call or runtime
dependency on that repository (#64).
