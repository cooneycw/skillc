# VM declaration binding and installed content

`calibration-declaration` may opt into a version 1 `execution_environment`
with `kind: dedicated-vm`. This is the first bounded code slice of #630.
It checks binding and content match only. It does not establish physical VM
provenance, deploy software, observe a host, handle credentials or launch work.

The closed object contains:

- `vm`: nonempty `id`, SSH public `host_key_fingerprint` (`SHA256:` form),
  `base_image_digest` (`sha256:` form), `kernel` and `docker_version`.
  The VM base image is distinct from the existing trial container image.
- `skillc`: reviewed 40-hex `revision` and nonempty `install_manifest`, mapping
  canonical relative paths to `mode` (0644 or 0755), `bytes` and `sha256`.
- `window`: nonempty `id` and timezone-aware `starts_at` / `ends_at`, ordered
  strictly. Current-time admission is a later run-window slice.
- `version: 1` and `kind: dedicated-vm`.

These values participate in the existing whole-declaration digest and approval
rule. There is no additional approval path or approval-writing API. Changing
VM identity, reviewed source or window after approval invalidates that approval.
Removing the VM subobject refuses shape validation; deleting the entire
optional environment from an approved declaration changes its digest.
Discrimination declarations explicitly refuse this field. Existing declarations
without it keep their two-positional-argument approval behavior and content.

`calibration.require_approved(..., vm_observation=...)` requires explicit
`vm_identity.Observation` evidence for this environment. Existing production
callers supply no such observation, so these declarations refuse until a later
reviewed adapter supplies it. Observations are trusted controller/operator
inputs, never an agent-provided identity document. The adapter must authenticate
physical identity and collect the reported import origins; this pure API cannot
authenticate a fabricated observation. No observer is selected automatically.

The verifier checks the complete bounded installation against the approved
manifest, including extra files, modes and runtime data. An unchanged revision
string alone is insufficient. Required observed import origins for `skillc`,
its calibration, VM identity and fixture service modules, and the fixture shim
must resolve to their reviewed source paths within that installation. A second
read refuses an observed content change during verification; this is not an
atomic freeze or a guarantee about later execution. A launch adapter must retain
custody and recheck before use.

Exclusions are closed: root `.git`, `.venv`, `.pytest_cache`, `.mypy_cache` and
`.ruff_cache` directories, and directories named `__pycache__`. Root `.git` may
also be a worktree metadata file. No caller glob or gitignore rule changes the
population. Other links and special files refuse; excluded entries masquerading
as ordinary files refuse. Import origins still must name the declared source,
not a cache or a virtual environment. Empty, unreadable or over-budget installs
cannot match. The limits are 20,000 files, depth 32, 8 MiB per file and 64 MiB
read bytes, in addition to the shared safe-reader enumeration bound.

A successful verifier returns an identity/window/content-digest record with
scope `binding-and-install-match-only`. It is protected controller evidence:
public summaries omit real machine identity and paths. Calibration still returns
`None` after all its existing approval requirements succeed. Joining identity
records into a production VM-run ledger is later integration work.

`controls/vm-identity/` contains only synthetic identities and installation
bytes. Its cases require both matching and refused verdicts, including missing
identity, wrong import origins, changed content with the same revision, extra
source and altered VM key/image. Its committed blind-verifier control runs the
same cases through an always-match verifier; qualification must reject it on
the changed-module input. The tests also retain calibration's exact approval
backstop, omitted-observation refusal and legacy non-VM behavior.

The synthetic test artifact is materialized with each manifest entry's explicit
mode before drift is introduced. Git checkouts preserve the executable class,
but other permission bits vary with checkout umask; those source checkout bits
are not the synthetic artifact's declared modes. This is test materialization,
not verifier normalization: the production verifier continues comparing full
permission bits. Both an executable-bit flip and an added write bit in the
installed artifact remain refused, as do changed data and extra modules.
