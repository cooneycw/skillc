<!-- flow-run n=1 id=7b5f0d7dd246474983553442203138fc -->
## Run 1 - issue #654 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #654
- Read at:      2026-10-31T12:44:21Z
- updatedAt:    2026-10-31T11:25:02Z   (context only - moves on comments and labels)
- Body digest:  673bbc14d22ecac09ae348bfb736e2c9be1bfa2baa34c8241a5368b72545209f   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3100 of 3100 (cap 16384)

### Body as read
## The real-Docker runner certifies its OWN pinned product code, not the main head's

`ci/real-docker/run-real-docker` line 123 does `export ... PYTHONPATH="$INSTALLED_ROOT"` (the installed runner, `/opt/skillc-real-docker-runner`). The pytest subshell at lines 340-365 inherits it, so `import skillc` inside the certifying pytest resolves to the **runner's pinned copy**, ahead of the work checkout's editable install. The checkout contributes only the test files.

The script's own header (R1) says the opposite is intended: the installed copy is for "this script, and the ci/*.py modules it calls", and "the checkout supplies ONLY the test files pytest collects; it is never on PYTHONPATH for the verdict/summary/posting step". The export is process-wide, so it also reaches the step it should not reach.

### Evidence (evals26, 2026-10-31)

As `skillc-rd` in `/var/lib/skillc-real-docker/checkout` at `c177eb5`, a one-line probe test printing `skillc.inventory_oracle.__file__`:
- with `PYTHONPATH=/opt/skillc-real-docker-runner` (what the runner passes): `/opt/skillc-real-docker-runner/skillc/inventory_oracle.py`
- without it: `/var/lib/skillc-real-docker/checkout/skillc/inventory_oracle.py`

Consequence observed: #652's fix (PR #653, merged `c177eb5`) changes `skillc/inventory_oracle.py`. The timer run on `c177eb5` still posted `FAILURE: 32 executed (sha c177eb5b1d9a, runner 097c1ddae5ce)` with the identical `[executable]` assertion, because the oracle it exercised was the runner's `097c1dd` copy. The same fixed tree passes on evals26 against both `skillc-trial:latest` and a freshly built trial image when `skillc` is imported from the tree (JUnit kept at evals26 `/tmp/rd-c177eb5.xml`).

### Why it matters (gate letting work through)

Every `skillc/real-docker` status since the runner went live has certified **main's tests against the runner pin's `skillc/` code**:
- A product regression merged after the pin is invisible until the next re-pin, and a fix stays red until then.
- A green status on a main head is not evidence about that head's product code. That is the property the status description (`sha <head>`) implies.
- The existing RUNNER_BEHIND control (#456) catches floor-file drift only, not product-code drift.

### Suggested fix and negative control

- Do not export `PYTHONPATH` process-wide. Set it per invocation on the runner's own `ci/*.py` calls (lines 205/282/333/382 already do this inline), and run pytest with `env -u PYTHONPATH` (or an explicit checkout-first path).
- Commit a control that makes the instrument report the other verdict: a runner self-test asserting that, inside the certifying pytest, `skillc.__file__` is under `$WORK_CHECKOUT`, red on the current script. Add a test that the runner's pin and the checkout can differ in `skillc/` and the verdict follows the checkout.
- After the fix lands, re-pin the runner (operator step) so the corrected script is the one installed.

Found while working #652 via `/flow:auto` (PR #653). #652 stays open until a runner whose product import is correct (or a re-pin to >= `c177eb5`) posts SUCCESS.


<!-- end of body -->
