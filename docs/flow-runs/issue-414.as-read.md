<!-- flow-run n=1 id=cced860eb9fd431684169a26315465ec -->
## Run 1 - issue #414 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #414
- Read at:      2026-10-17T18:00:53Z
- updatedAt:    2026-10-17T18:00:15Z   (context only - moves on comments and labels)
- Body digest:  b9bcf313395ecf74bfd970c67e3c2399dc6f9b84c394254ee1c87077741a4948   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2378 of 2378 (cap 16384)

### Body as read
## What is wrong

The real-Docker runner ends every run with `docker image prune -f` (`ci/real-docker/run-real-docker:360`). That removes every **dangling** image on the runner. `docker/profile-trial/build.py` builds the campaign runtime image **untagged** on purpose (`docker build --iidfile`, no `-t`; `build.py:457-459`), and campaigns reference it only by the receipt's `image_id`. So the first `run-real-docker` invocation after a build deletes the image every receipt-driven campaign depends on.

## Evidence (2026-10-17, evals26)

- 10:56Z: the full #375 campaign at `7c9be48` ran 42/42 attempts against `sha256:843fd83e…` (`receipt-a100da5.json`).
- 11:22-12:57Z: campaign 4 for #334/#332 made 24 `run-real-docker` invocations. The #392 timer was then re-enabled and now runs on every main merge.
- 13:35Z: the #375 campaign at `c1d6212` refused all 42 rows in 0.1s: `image 'sha256:843fd83e…' is not present locally; refusing rather than letting 'docker run -d' pull it mid-trial`. `docker images` held only `python:3.12-slim` and `alpine`. The `receipt-br271.json` image (`a7b4843a…`, used for #403/#271's rows) is gone too.
- skillc's refusal is correct: it doesn't pull mid-trial. The damage is that a certifying campaign can't run after any timer tick.

## Workaround in use

Rebuild with `build.py --receipt`, then tag the image (`docker tag <image_id> skillc-profile-runtime:<runtime_id>-<sha>`). Tagging doesn't change the image ID, so the receipt stays valid, and a tagged image isn't dangling. Applied to `sha256:a89ab24e…` (`receipt-c1d6212.json`; every input hash is identical to the `a100da5` receipt's).

## Design choices

1. **`build.py` tags its output** with a deterministic name derived from the receipt (runtime id plus source commit), so a built image is never dangling. Smallest change, and it covers every caller.
2. **`run-real-docker` stops pruning images** (or prunes only images it built itself, by label). The runner's own images are its business, but a host-wide prune reaches other workloads' images.
3. Both: keep the runner's cleanup scoped to what it created, and make `build.py`'s output survive any prune.

Whatever the fix, add a red case: build an image via `build.py`, run `docker image prune -f`, and the receipt's `image_id` must still resolve.

Found by session `skillc-400` while rerunning the #375 campaign after #408.

