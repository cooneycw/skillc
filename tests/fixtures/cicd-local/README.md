# Local CI/CD project fixture (skillc#280)

`project/` is the one Python project the `cpp-codex-cicd-86641e8` profile is
proven against. It is stdlib-only (no PyPI dependencies), so every target runs
offline through `uv run` against a zero-dependency `uv.lock`, and it satisfies
CPP's own `lib.cicd check` (8/8 recommended targets, every target through
`uv run`).

- `tests/check_calc.py`: the project's own unittest suite, named `check_*` (run
  with `-p "check_*.py"`) so it is never a `tests/**/test_*.py` of THIS
  repository: ci/typecheck-control.sh plants its probe in the first such file
  and pytest would collect it.
- `Makefile`: lint, test, typecheck, format, build, deploy, clean and verify,
  in `templates/makefiles/python-uv.mk`'s target shape. `deploy` is local only.
- `src/calc/service.py`: a loopback-only (`127.0.0.1:18080`) health service.
  The live test starts it inside the trial container; nothing leaves the
  container's own network namespace (`--network none`).
- `.claude/cicd.yml`: CPP's REAL schema at 86641e8 (`health.endpoints`,
  `health.smoke_tests`, `health.deploy_verification`).

`template-shape.cicd.yml` is the same probes in `templates/cicd.yml.example`'s
shape, which `lib.cicd` silently ignores (claude-power-pack#1476). The live
test uses it as the "no probes" case.
