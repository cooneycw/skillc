<!-- flow-run n=1 id=69ab673a99494644939cdc4a03988a58 -->
## Run 1 - issue #360 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #360
- Read at:      2026-10-12T17:11:57Z
- updatedAt:    2026-10-12T17:01:14Z   (context only - moves on comments and labels)
- Body digest:  85d7041601ca5a06738d767c9ee412b3c2b594d1d88bd25e19630daf260b258b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2100 of 2100 (cap 16384)

### Body as read
## Problem

`tests/test_profile_closure_preflight_live.py::test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner` (`none` mode) fails against a real daemon (Docker 29.8.2) because the preflight refuses the attempt:

```
the attempt was refused: tool dependency 'tool-pypi-runtime' is not satisfied in the container: violated - could not import ['pydantic', 'yaml']: import failed
```

The refusal is correct. `evals/subjects/cpp-codex-flow-check-ea6dbfa/profile.json` declares `tool-pypi-runtime` with `supply: "EXTERNAL: uv resolves these from a package index on first run. Trials have no network (spec.md section 4), so #266 must pre-supply a filled cache or report the gate step unavailable"`. `docker/trial/Dockerfile` pins `uv` (#343) but carries no pre-warmed uv cache for CPP's `uv.lock`, so the probe cannot import pydantic/pyyaml offline. `docker/profile-cold-install/Dockerfile` does pre-warm such a cache. That is why the cold-container test passes while this one does not.

This was hidden until now. Before #356, the trial image did not build on Docker 29, so this test errored at setup. PR #349's own notes say its `none` mode "has never actually run against a daemon". This is the first live run, and it is a production gap (the trial image every treated live attempt runs in), not a test defect.

## Why it matters

Every treated, profile-opted live attempt for the `cpp-codex-flow-check-ea6dbfa` profile is refused at preflight. That blocks the real-daemon campaign (#315) and the #287 study's treated arm.

## Decision needed

Either (a) pre-warm a uv cache in the trial image from the pinned CPP `uv.lock`, as `docker/profile-cold-install/` already does. That couples the trial image to a profile pin, and the coupling needs a decision about how several pins are supported. Or (b) report the gate step unavailable for this profile, per the `supply` text.

Repro (daemon host): `uv run pytest -q tests/test_profile_closure_preflight_live.py`

Found while running #356's live verification (PR to follow). #356 fixed the build error that was masking this.


<!-- flow-run n=2 id=3bc0ddeb6b1f4450a3be58d4a89d6a0b -->
## Run 2 - issue #360 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #360
- Read at:      2026-10-13T20:15:13Z
- updatedAt:    2026-10-13T20:03:04Z   (context only - moves on comments and labels)
- Body digest:  85d7041601ca5a06738d767c9ee412b3c2b594d1d88bd25e19630daf260b258b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2100 of 2100 (cap 16384)

### Body as read
## Problem

`tests/test_profile_closure_preflight_live.py::test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner` (`none` mode) fails against a real daemon (Docker 29.8.2) because the preflight refuses the attempt:

```
the attempt was refused: tool dependency 'tool-pypi-runtime' is not satisfied in the container: violated - could not import ['pydantic', 'yaml']: import failed
```

The refusal is correct. `evals/subjects/cpp-codex-flow-check-ea6dbfa/profile.json` declares `tool-pypi-runtime` with `supply: "EXTERNAL: uv resolves these from a package index on first run. Trials have no network (spec.md section 4), so #266 must pre-supply a filled cache or report the gate step unavailable"`. `docker/trial/Dockerfile` pins `uv` (#343) but carries no pre-warmed uv cache for CPP's `uv.lock`, so the probe cannot import pydantic/pyyaml offline. `docker/profile-cold-install/Dockerfile` does pre-warm such a cache. That is why the cold-container test passes while this one does not.

This was hidden until now. Before #356, the trial image did not build on Docker 29, so this test errored at setup. PR #349's own notes say its `none` mode "has never actually run against a daemon". This is the first live run, and it is a production gap (the trial image every treated live attempt runs in), not a test defect.

## Why it matters

Every treated, profile-opted live attempt for the `cpp-codex-flow-check-ea6dbfa` profile is refused at preflight. That blocks the real-daemon campaign (#315) and the #287 study's treated arm.

## Decision needed

Either (a) pre-warm a uv cache in the trial image from the pinned CPP `uv.lock`, as `docker/profile-cold-install/` already does. That couples the trial image to a profile pin, and the coupling needs a decision about how several pins are supported. Or (b) report the gate step unavailable for this profile, per the `supply` text.

Repro (daemon host): `uv run pytest -q tests/test_profile_closure_preflight_live.py`

Found while running #356's live verification (PR to follow). #356 fixed the build error that was masking this.

