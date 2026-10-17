<!-- flow-run n=1 id=0b16ae68339a4a78b7be5b85c3b55738 -->
## Run 1 - issue #365 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #365
- Read at:      2026-10-17T14:55:40Z
- updatedAt:    2026-10-12T18:05:17Z   (context only - moves on comments and labels)
- Body digest:  47fdbacede1db99ad959d0063b8d2b64ef60210670ae023b995fb324e74ba805   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1831 of 1831 (cap 16384)

### Body as read
Found while running the full suite for #364 in a disposable CI-shaped container.

`skillc/profile.py:1651-1652` forwards the entire ambient environment to `uv run --project <installed-project>`. With `UV_PROJECT_ENVIRONMENT` pointing at the test runner's dev environment, the import probe uses that environment instead of the fresh dependency-less project's environment. The existing committed negative control `tests/test_profile_probes.py::test_red_case_a_module_present_in_this_interpreter_but_absent_from_the_uv_env_is_refused` then reports `satisfied` instead of `violated` for importing pytest.

Observed twice: the full parallel suite had this failure, then the exact test passed after removing the environment override and using a fresh default `.venv`. This is independent of scheduling. No tests were weakened in #364; its validation setup was corrected.

Reproduce in a disposable checkout (the nested `uv run` may reconcile the environment it is pointed at): create a dev venv containing pytest, set `UV_PROJECT_ENVIRONMENT` to that venv's absolute path, and run the test above.

Resolve the runtime contract explicitly: if `uv_project` means the declared installed project's isolated environment, remove or constrain inherited uv environment-selection overrides and commit the ambient-override red case. If the real runner intentionally honors that override, document and account for that external environment as a runtime dependency rather than claiming the installed checkout alone proves the requirement. Do not merely relax the negative control's expected result.

Acceptance: the declared project's dependency evidence cannot silently come from an undeclared external dev environment; the ambient-override control distinguishes the chosen contract; ordinary isolated-project pass/fail controls remain effective.

