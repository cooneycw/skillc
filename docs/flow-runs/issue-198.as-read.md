<!-- flow-run n=1 id=f529dc35b6a94a15badd194863fefe91 -->
## Run 1 - issue #198 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #198
- Read at:      2026-09-30T12:37:14Z
- updatedAt:    2026-09-29T11:19:38Z   (context only - moves on comments and labels)
- Body digest:  5097d0461d688618f06fee940be9fd88df184ff50f12d64ca83d1fb67bb1539c   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3096 of 3096 (cap 16384)

### Body as read
Blocks: #150 acceptance item 3 (the live discriminating run). Found during the `/flow:auto #150` live run on 2026-09-29 at skillc `6a278ce`.

## What is wrong

`skillc degrade-subject` replaces files with `--override-file` but never updates the skill's declared checksum manifest (`subject.json` `checksum_manifest`, `scripts/SHA256SUMS` for `cpp-codex`). `collection-run --degraded` then prepares the subject through `materialize._verify_checksums` (`skillc/materialize.py:436-454`, called at `:567`), which refuses the tree:

```
skillc: subject 'cpp-codex' could not be prepared from degraded tree <runs>/degraded: flow-auto: checksum mismatch for gh-pr-merge.sh
EXIT=2
```

The five-location degradation for `evals/level1/finish-close-ref` (#162, `degraded/degrade.toml`) overrides `scripts/gh-pr-merge.sh` in both `flow-auto` and `flow-merge`. Both skills' manifests still pin the original hash (`flow-auto/scripts/SHA256SUMS:27` and `flow-merge/scripts/SHA256SUMS:15`, `c3d82706...`). So the runbook path `docs/runbooks/150-discriminating-run.md` steps 3-4 cannot complete as written. `reference.md` overrides are unaffected because the manifests do not list them.

## Why it matters

The degraded arm is the only way #150 can show discrimination. Every run of it fails before launch. The failure is correct integrity behaviour applied to a deliberate, recorded mutation. No test covers an override of a manifest-listed file: `tests/test_degrade.py`, `tests/test_degrade_collection_run.py` and `tests/test_degraded_prepare.py` never combine the two.

## Reproduce

1. `python3 evals/level1/finish-close-ref/degraded/prepare.py --checkout <cpp@85e9b03> --out <runs>/prepared`, which passes.
2. Run the printed `skillc degrade-subject cpp-codex ... --out <runs>/degraded`, which passes. The receipt lists 5 locations.
3. `SKILLC_ALLOW_REAL_AGENT=1 skillc collection-run cpp-codex --task evals/level1/finish-close-ref --degraded <runs>/degraded --evidence <dir> --evidence-role control` fails with exit 2 as shown above, before any agent launch.

## Proposed fix (pending owner choice on #150's run)

- (a) When an override replaces a file listed in that skill's declared checksum manifest, `degrade-subject` rewrites that manifest line to the new hash. It records the rewrite in the receipt as a separate `manifest_rewrites` field, so `mutation.locations` stays exactly the declared five. Preparation keeps verifying against the rewritten manifest, so a file changed after `degrade-subject` still fails. The regression test must fail on the current code, and a committed negative control (a post-degrade edit) must still be refused.
- (b) Alternative with no code change: the operator also overrides both `SHA256SUMS` files. That produces 7 receipt locations against `DEGRADATION.md`'s declared 5, and it records manifest bookkeeping as rule removal.

## Related runbook gap

`docs/runbooks/150-discriminating-run.md` never names `SKILLC_ALLOW_REAL_AGENT=1`, the opt-in that `lifecycle._refuse_real_agent` requires. Its `collection-run` commands are refused as written (`RealAgentBlocked`).

