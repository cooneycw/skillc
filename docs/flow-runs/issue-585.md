# Flow run record - issue #585

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=d22dbdce1d9e466fa85f04a8d17ce9c7 -->
## Run 1

- Run-id:            d22dbdce1d9e466fa85f04a8d17ce9c7
- Run-start:         1d129f90d37c27c3122b0c3074833723e7b4ebdc

- Issue:             #585
- Base SHA:          1d129f90d37c27c3122b0c3074833723e7b4ebdc
- Necessity verdict: Still needed, required front-queue blocker
- Approval:          granted
- Approver:          orchestrator, ruling-585-actual-step3-implementation.md
- Recorded at:       2026-10-27T16:32:00.372791+00:00

### Section A - intent
The normal lint command writes scratch caches inside a frozen source copy.
Lint can pass but the next verification fails because the copy no longer has
its promised files. Keep the same Python coverage while placing generated
caches outside frozen copies; strict membership must keep rejecting extras.

### Section B - necessity evidence
Issue filed2026-10-27T16:21:48Z; actualread2810bytes digest8a23642c72bc415664b10fb56534e08a93410596ff61b654ca65840d22d92d5e.
Actualbase1d129f9/tree969657 includes584/583/582/579, allbeforefiling; no
global/scoped commits or mergedPRafterfiling. Relevant5d04193/582 introduces
87ecstrictfixture and1fcf690/567 leavesproducer. Issues553/20/364/513 checked;
553oldercache/pycache symptom doesnotfixactualRuffproducer.
Actualfirst547full3e61df3 failedchangelog after7893PASS6SKIP; second90d9951
failedtest with7887PASS6FAIL6SKIP/7899IDs. Sixoutermembershipfailures are
distinct fromnestedexpectedcontrols. Bothnativefailures/logs preserved by
worker01, untouchedhere.
CausalactualRuff0.16.7 ondisposablecopies: initial389files/strictcheckerPASS,
publishedMake -o sync lint AND CI-YAML-extracteduvcommand eachexit0 but29new
cachefilesunderfixture, strictcheckerFAIL; existingbytes/modes unchanged.
Explicit --cache-dir .ruff_cache onfreshcopy twiceexit0 leavesall389 unchanged;
rootF821control stillfails exit1. NoRUFFenvset; UVusesalreadyinstalleddevvenv,
no sync/install/sharedfixturewrite. Rawcausalresults/beforeafter/stdoutstderr
retained /tmp/skillc-585-causal-evidence. Hostpreflightready, genuinefresh
resolververified/stashcurrent/claimactual1102501; contextblockabsent.

### Section C - approved changes

1. `Makefile` - Explicitroot --cache-dir .ruff_cache in lint recipe, same coverage/config/exitstatus andsync prerequisite; concise immutablefixture reason.
2. `.woodpecker/ci.yml` - Same explicitroot cache directory in actual CI gate Ruffcommand, no other steps/population changes.
3. `tests/test_lint_fixture_cache.py` - ActualMake -o sync lint and CI-YAML-extractedcommand regressions on exactdisposablefixturecopies: healthyinitial389/files/bytes/modes, actualpublishedcommandtwice preservesfixture, seedcacheextra refused, rootANDcopiedvendorF821 stilldetectedforeachproducer. Readactualproducer/config, notmirroredfixedcommand. Firstred onunchangedMake/CI withstrictmembershipafterexit0, thenfixedgreen; no missingAPI failure.
4. `changelog.d/585.md` - One validbullet for repeatablelint cacheisolation.

Scope: exact4product+2canonicalworkflow;220TOTALnonworkflowADincllater
separatelygranted genuine receipt<=42. Returnexcessbeforeexpansion, no
compression. ~136-195AD expected includingreceipt. No vendor/pin/manifest/
source-reader/ignorefilter/exclusion/--fix change. Exact388manifestrows+
README389files andbytes/modes remain. Dependenciesalreadyprovided in
regression viaUV_PROJECT_ENVIRONMENT=sys.prefix andmake -o sync, bounded
subprocess60s; no packageinstall/model/client/Docker/hostprobe.
Risks: fixingonlyoneentrypoint, mirroredcommandtest, fixtureexclusionor
zero-lint falsepurity, env/cache/venv leakage, scratchignoresemantics and
hardlink/sharedwrites. Actualcommands, root+vendorF821 andstrictmembership
controls discriminate. Focusedchecks onlynow; review/receipt/full/PR later
gates. Current547cache/evidence untouched; ownerarchives thenonlyproven
generatedcachecleanup underlaterrootclearance.547/544standingHOLDbehind585;
544f845/source/review/receipt/worktree preserved. No approvalbypass used.
