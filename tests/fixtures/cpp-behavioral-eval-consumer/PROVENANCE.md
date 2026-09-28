# Vendored: CPP's `scripts/check-behavioral-eval.py`

- Source repository: `cooneycw/claude-power-pack` (same owner as this repository)
- Source path: `scripts/check-behavioral-eval.py`
- Source commit: `aa2653ebf79b3ccbed37d54d15eb13b257b161e2` (last commit to touch this file)
- Vendored: 2026-09-28
- `sha256sum check-behavioral-eval.py`: `a631a59b7e88f72e22fd20bdb72d48e811d6907a4d5e62b5e42652c448fe90bc`
- License: MIT (`claude-power-pack`'s `LICENSE`, whose "Scope" section names
  "All scripts in the `scripts/` directory" explicitly) - permits copying
  with the copyright notice retained. That notice: `Copyright (c) 2025
  cooneycw`.

## Why vendored, not re-implemented

This is CPP's consumer for the verified-result bundle skillc's `collection-run
--evidence` exports (issue #150 acceptance item 4). The export layout's whole
justification is what this reader actually does with it - a description of
its behaviour is not evidence that skillc's output satisfies it; running the
real reader against real skillc output is. `tests/test_behavioral_eval_consumer_contract.py`
imports this file directly (`importlib`, by path - it is not itself a package
skillc's own `skillc/` ships) and drives its `evaluate()`/`main()` against a
normal-arm export, a degraded-arm export, and an export carrying a non-result
file at the top level.

## Keeping it current

This is a SNAPSHOT, not a live dependency - skillc's CI has no network path to
CPP's repository (mirroring this project's own stated no-external-runtime
boundary, ADR 0003). If CPP's consumer changes its record contract
(`SUPPORTED_VERSIONS`, the vocabularies, `_contract_problem`'s rules), this
copy goes stale silently: nothing here re-fetches it. Re-vendor by hand
(update the commit SHA and digest above) when skillc's own `records.py`
contract changes in a way that could affect what this consumer accepts, or
when CPP's own PR history shows this file changed.
