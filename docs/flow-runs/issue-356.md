# Flow run record - issue #356

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8ed3689975004c7895260eec660adeb2 -->
## Run 1

- Run-id:            8ed3689975004c7895260eec660adeb2
- Run-start:         450445da5eb83719aa68f0f448f29bda56358ec9
- Issue:             #356
- Base SHA:          450445da5eb83719aa68f0f448f29bda56358ec9
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the session user (owner), replying "approved" to the Step-3 ELI5 report
- Recorded at:       2026-10-12T15:30:00Z

### Section B evidence
commits: none on origin/main since 2026-10-12T14:33:54Z. PRs merged: none. Open PR #358 (#355) touches only gate-overlay/gate-witness/decide-reply live tests + docs - no overlap. Dup/superseding issues: none (search returned #356 itself, nit store #20). Host siblings: no unpushed commits touching docker/trial, .gitignore or the fixture.

### Section C - the approved plan
1. `docker/trial/Dockerfile` - global-scope `ARG UV_VERSION=0.9.7`, named `uv-bin` stage, `COPY --from=uv-bin`; drop the per-stage re-declaration.
2. `.gitignore` - keep `secrets.*`; add the scoped negation `!tests/fixtures/**/secrets.py`.
3. `tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/lib/security/modules/secrets.py` - add, byte-identical to CPP ea6dbfa.
4. `tests/test_profile_fixture_completeness.py` - no-git inventory-vs-fixture completeness test (regression) + needs_git check-ignore negative control for the narrowed rule.
5. `CHANGELOG.md` - Fixed entry.

Scope: 5 files, ~80 lines plus the vendored module. Risk: cold-install image cache digest keyed on uv.lock should be unaffected (confirm live); full suite will reveal anything relying on secrets.py's absence.
