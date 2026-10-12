# Pinned CPP offline runtime supply (Refs #360)

This optional image supplies the PyPI dependencies of the one declared
`cpp-codex-flow-check-ea6dbfa` profile. Its package cache is built using the
trial stage's own Python and pinned uv 0.9.7. It leaves the generic trial image
and historical subject, profile, fixture and evidence bytes unchanged.

Phase one supplies the builder and offline contract controls. It has NOT yet
established consuming-path Docker acceptance. Build execution requires the
#356 trial-image fix or an explicit source-head handoff; shared live-test and
runner integration follows the wave's separate handoff. No paid study is
implied by a successful build.

## Build and identity

From a reviewed checkout containing the required trial-image fix:

```bash
python3 docker/profile-trial/build.py --receipt /tmp/profile-runtime-receipt.json
```

The output path must not exist. Each build gets a private temporary context.
The builder reads the tracked `docker/trial/` inputs and the subject inventory
and metadata from one resolved repository HEAD. Dirty trial or fixture files
are not inputs. It appends `Dockerfile.fragment` to the unchanged trial
Dockerfile bytes. The fragment, policy and builder itself come from this
checkout; all prepared bytes are bound by `build_context_sha256`.

Only `pyproject.toml` and `uv.lock` from the pinned CPP fixture enter the build
context. Their exact SHA-256 values and revision must match both this bounded
policy and the existing inventory. Unknown input families, extra policy fields,
missing inputs and mismatches refuse before any Docker call. Preparation never
copies a host venv, source checkout, skill directory or host package cache.

The builder always selects an explicit target:

- `profile-runtime`: normal candidate-owned populated dependency cache.
- `profile-runtime-empty-cache`: identical runtime policy and descriptor, with
  no populated cache copied into the final image. The descriptor builder still
  runs; it does not warm the consuming attempt.
- `profile-runtime-cache-permissions`: same complete cache with candidate writes
  removed. This is a permissions control, not a usable runtime.

Both cache preparation and the common final runtime derive from `trial` in
one Docker build graph. The warm stage temporarily uses root and a scratch
project, with interpreter downloads disabled. It executes
`uv sync --locked --no-install-project --python /usr/bin/python3`, then checks
that metadata bytes still match the pins. Final stages restore `USER candidate`
and `/work`; only the dependency cache and descriptor cross from the warm
stage. No project source, skills, helpers or project `.venv` cross that boundary.
The existing generic trial helpers are unchanged.

Docker's `--iidfile` identity must match image inspection. The builder creates,
but never starts, a temporary container to extract the descriptor, then removes
it even if descriptor validation fails. It checks final candidate USER and
image environment against the descriptor before writing the external receipt.
The observed image configuration must not set `UV_PROJECT_ENVIRONMENT`, even
with an empty value: the supported runtime uses each project's own `.venv`.
This absence is checked against image inspection, independently of descriptor
claims. Candidate-writable project delivery and matching effective-environment
refusal belong to the supporting runtime integration, not this build receipt.
The output image is selected by immutable ID from that receipt. No default
image or evaluation declaration changes automatically.

## Closed schema 1 contract with #348

The root-owned descriptor lives at
`/usr/local/share/skillc/runtime-supply.json`. Its exact fields are:

- `schema_version`: integer 1, never a Boolean.
- `runtime_id`: `cpp-codex-flow-check-ea6dbfa`.
- `subject_revision`: full pinned 40-character lowercase Git revision.
- `pyproject_sha256`, `lock_sha256`: raw lowercase 64-character SHA-256 values.
- `uv_version`: measured `0.9.7`.
- `python`: exact keys `executable`, `version`, `cache_tag`, `platform`, `machine`.
  The executable is `/usr/bin/python3`; version/cache tag are measured and
  consistent with CPython >=3.11, platform is Linux, machine x86_64 or aarch64.
- `required_env`: exact keys from `runtime-policy.json` plus measured inherited
  `PATH`. HOME and cache are the candidate paths, uv is offline and locked,
  interpreter downloads are disabled, and link mode is copy. PATH is never
  read from the build operator's environment.

The receipt's exact fields are `schema_version`, `runtime_id`,
`subject_revision`, `pyproject_sha256`, `lock_sha256`, `image_id`,
`descriptor_sha256`, `recipe_sha256`, `base_recipe_sha256`,
`build_context_sha256`, `source_commit`, `target`.
All `*_sha256` fields are raw lowercase 64-character hex. Only `image_id` has
the `sha256:` prefix. `source_commit` is the full 40-character repository HEAD
from which the tracked trial and pinned metadata inputs were read. Descriptor
hashing covers exact file bytes, including the trailing newline. Recipe hashing
covers the exact generated Dockerfile bytes; base recipe hashing covers the
unchanged source Dockerfile. Context hashing covers canonical JSON of a sorted
mapping from every relative context file path to its raw SHA-256 digest. The
canonical encoding is `json.dumps(value, sort_keys=True, indent=2) + "\n"`, UTF-8.

The descriptor cannot identify its own containing image. The controller must
select a trusted external receipt, match its image ID to the actual runtime
image, compare exact descriptor bytes, and require `target=profile-runtime`.
Break-target receipts are for acceptance controls only. Neither a subject claim
nor a self-consistent descriptor/receipt pair found inside an image establishes
trust. These receipts are build provenance, not cryptographic signatures.

DD confirmed this schema boundary for #348. Its consumer integration remains
separate: bounded effective-environment capture before subject dispatch,
validation of descriptor AND enclosing-directory candidate non-writability,
comparison to verified installed closure metadata, then identical policy for
inherited preflight and frozen `env -i` witness execution. Full raw environment
stays private, in memory; do not publish it in observations or logs.

## Scope and controls

Every attempt has a private writable cache layer, without an operator cache
mount. Runtime package networking and interpreter downloads are disabled even
when model-provider access uses the existing bridge network. Uncached Python
packages are unavailable under this selected capability. Baseline and treated
arms must use the same final image ID and policy; the baseline receives no CPP
source or skill installation.

Run the offline controls without Docker:

```bash
uv run --extra dev pytest -q tests/test_profile_trial_image.py
```

Committed good descriptor/receipt examples and bad contract/input cases live
in `tests/fixtures/profile-trial-runtime/`. The tests exercise real validators,
preparation and build orchestration through an explicit fake Docker boundary.
They prove malformed/duplicate/empty JSON refusal, pin/metadata/environment
and receipt identity discrimination, zero Docker calls on invalid preparation,
and a closed warm/final recipe contract rejecting source/venv additions,
disguised cache sources, changed warm-stage ancestry and unlocked cache sync.
They do not prove cache usability or baseline absence in a running image.

Required live acceptance remains:

1. Record original generic image offline refusal with the candidate user and
   exact installed closure before the new image's positive run. This establishes
   the offline capability regression; historical bridge-network import failure
   remains separately undiagnosed because its original stderr was suppressed.
2. In a fresh candidate attempt with no project `.venv` and network none, run
   the actual closure preflight and pinned helper through the overlay/witness.
   Repeat with the frozen `env -i` policy, without prior attempt warming. Require
   unchanged project/lock hashes and the receipt's actual image ID.
3. Empty-cache target must yield a specific offline cache-miss diagnostic and
   refuse `tool-pypi-runtime`. Permissions target must fail the same consuming
   command on cache writes, while the complete candidate-owned cache passes.
   Unrelated setup failures are hard errors, never credited expected failures.
4. Validate actual descriptor file and parent ownership/modes, measured Python
   identity, and missing/changed required environment keys. A system-python
   package decoy cannot satisfy the uv project contract.
5. Compare observed baseline and treated image IDs. Scan the baseline for CPP
   source/helpers/discoverable skills, and prove that absence scan fails on a
   planted recognized-directory `SKILL.md`. No source/venv baked into the image
   may be credited as treatment installation.

Independent review, coordinated full verification and current-base CI remain
required before merge. Use Refs #360 until real consuming acceptance is recorded.
