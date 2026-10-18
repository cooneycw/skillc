<!-- flow-run n=1 id=25b9452d3de6476da400a287e6513473 -->
## Run 1 - issue #456 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #456
- Read at:      2026-10-18T03:42:26Z
- updatedAt:    2026-10-18T03:41:56Z   (context only - moves on comments and labels)
- Body digest:  fef2dcfa2d824acfbb8c41b56dc6d259d2d979b36fe7150ad87959ccd0c0eef7   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1589 of 1589 (cap 16384)

### Body as read
## Problem

The evals26 certifying runner reads the real-Docker floor (the declared live-test files in `ci/check_real_docker_ran.py`) from the **installed runner's pin** (`/opt/skillc-real-docker-runner`), while the tests run from the checkout of **main head**. A live test merged after the runner's last re-pin runs but is never counted, and the status reads green exactly as if it were protected.

Observed 2026-10-17: #280's `tests/test_cicd_profile_live.py` merged at 5d0f572 and was uncounted until #282's re-pin at 746dd72. Main head b2fa7f8 reported `SUCCESS: 20 executed` = 16 + 4 egress, with #280 absent. The re-pin brought it in: `SUCCESS: 23 executed`.

Origin: the nit store, https://github.com/cooneycw/skillc/issues/20#issuecomment-6244541213. Found by skillc-worker-C while preparing #282's EXPECT_TOTAL.

## Why an issue, not just a nit

The floor exists so that a live test which silently stops running turns certification red. Every PR that adds a floor file reopens this gap until someone remembers the manual re-pin. Today that is a procedure step, not a check.

## Acceptance

- [ ] A certifying run refuses SUCCESS, or reports a distinct runner-behind verdict, when the tested commit's declared floor contains a file the runner's own floor lacks.
- [ ] Committed red: a commit declaring a file absent from the runner's floor does not report SUCCESS.
- [ ] Committed green: identical floors report as today.
- [ ] The runner docs (`ci/real-docker/README.md`) describe the re-pin trigger.

Design first: post a design comment for orchestrator review before any code.

