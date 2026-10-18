# Flow run record - issue #280

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=27570ba3452143d0bf8e675af044365b -->
## Run 1

- Run-id:            27570ba3452143d0bf8e675af044365b
- Run-start:         1fc1e6ecf0c7e7c6b7fad6be99a7953b8a6bbe23
- Issue:             #280
- Base SHA:          1fc1e6ecf0c7e7c6b7fad6be99a7953b8a6bbe23
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T18:45:42Z

### Section B evidence
- commits since filing (2026-10-04): 841689b, 5cf1586, 0518cc0, 5e80d3e, f22d6c8, 02f1565, 558fe76, 1b62faa, 0e09873, c35034e - flow-check profile/runtime work, none adds a cicd profile, task or spec
- dup/super: none; #281 and #282 build on this issue
- CPP template drift found while grounding: filed as cooneycw/claude-power-pack#1476 (approver ruling: issue, not nit store)

### Section C - the approved plan
1. `scripts/freeze_cpp_fixture.py` - reproducible pin snapshot via git show from a CPP checkout at the pin; refuses a dirty or wrong pin
2. `tests/fixtures/profile-cpp-codex-cicd-86641e8/` - frozen lib/cicd, pyproject.toml, uv.lock, codex/skills/cicd-{init,check,health,smoke,verify,pipeline}, templates/makefiles/python-uv.mk
3. `evals/subjects/cpp-codex-cicd-86641e8/profile.json` - cicd profile: six cicd skills, tools python/uv/make-git-bash/curl/pypi-runtime, no gate_entrypoint, loopback-only services
4. `evals/subjects/cpp-codex-cicd-86641e8/subject.json` - subject at the 86641e8 pin
5. `evals/subjects/cpp-codex-cicd-86641e8/PROFILE.md` - exact local semantics: loopback HTTP, provider = generated YAML text, CPP_OFFLINE=1, no hosted CI or cloud
6. `evals/subjects/cpp-codex-cicd-86641e8/evidence/inventory.json` - validated inventory from a real checkout at the pin
7. `docker/cicd-trial/Dockerfile` - one curl layer FROM the validated flow-check profile-runtime image
8. `docker/cicd-trial/build.py` - layered build: validates the base receipt, binds layers+1, identical Env/User/WorkingDir, byte-identical descriptor, measured curl version; closed cicd-runtime receipt
9. `docker/cicd-trial/README.md` - recipe, receipt schema, controls
10. `skillc/runtime_supply.py` - selected_runtime() wrapping requires_supply() unchanged; cicd-runtime receipt kind with embedded base receipt; kind cross-checks
11. `skillc/cli.py` - the two call sites select by runtime kind; level3 campaign refuses cicd-runtime
12. `skillc/docker_backend.py` - only if the runtime-environment validation must accept the cicd receipt kind
13. `tests/test_runtime_supply.py` - flow-check selection identical before/after, every refusal still fires, cicd selection and cross-receipt refusals; mutations M-a..M-c
14. `tests/test_cicd_trial_image.py` - offline build controls with fake Docker (M-d layer count), golden flow-check build-input hashes from 1fc1e6e with a one-byte negative control
15. `tests/fixtures/cicd-local/` - stdlib-only Python project, Makefile lint/test/typecheck, loopback http.server health service, .claude/cicd.yml in CPP's real schema
16. `tests/test_cpp_codex_cicd_86641e8.py` - offline: inventory equals fresh validate; missing helper/reference, wrong version, ambient host dependency, no-probe tool refused
17. `tests/test_cicd_profile_live.py` - real_docker: check, run --plan check, health, smoke, verify --baseline, verify proceed; unreachable service -> rollback; no probes -> review; missing curl -> refused; wrong uv constraint -> violated; cleanup evidence
18. `ci/real-docker/break-lib.sh` - cicdprofile: break family
19. `ci/real-docker/README.md` - campaign step for the cicd floor entry
20. `ci/check_real_docker_ran.py` - floor entry for the cicd live test
21. `tests/test_run_real_docker_break.py` - break family tests
22. `docs/specs/evaluation-facility/profiles.md` - cicd profile section; missing declared tool is "violated" (align spec to code)
23. `CHANGELOG.md` - entry

Conditions from the approver: docker/trial/*, docker/profile-trial/* (incl. build.py), skillc/runtime-policy.json and all flow-check subjects/fixtures stay byte-identical; required golden-hash test with negative control; flow-check selected supply identical before/after with mutation-checked refusals; link claude-power-pack#1476 from the PR.
Scope: ~23 entries, large (fixture snapshot dominates). Risks: floor/campaign grows ~4 runs; apt curl unpinned by version (measured + probe constraint instead); provider YAML is text only here (#281 executes it).
