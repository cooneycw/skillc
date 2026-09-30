# Flow run record - issue #198

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=f529dc35b6a94a15badd194863fefe91 -->
## Run 1

- Run-id:            f529dc35b6a94a15badd194863fefe91
- Run-start:         6a278ceb8dc3ecf5c54aade7a87664bcf3c9a324
- Issue:             #198
- Base SHA:          6a278ceb8dc3ecf5c54aade7a87664bcf3c9a324
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (session user, "approved")
- Recorded at:       2026-09-30T00:00:00Z

### Section B evidence
Commits on origin/main since 2026-09-29T11:19Z: none (base is 6a278ce, the filing revision).
Merged PRs since 2026-09-29: #197 #196 #195 #194 #193 #192 #191 #190 #187 #185 #184 #182 - none touch skillc/degrade.py or materialize._verify_checksums.
Duplicate/superseding issues: none (search "SHA256SUMS degrade" returns only #198). Option (a) chosen.

### Section C - the approved plan
1. `skillc/degrade.py` - rewrite manifest lines for overridden manifest-listed files; `manifest_rewrites` on DegradedSource and receipt; locations unchanged; skip when the manifest itself is edited
2. `tests/test_degrade.py` - regression (fails on old code), post-degrade negative control, receipt field test
3. `docs/specs/evaluation-facility/degraded-subjects.md` - document manifest rewrites as bookkeeping
4. `docs/runbooks/150-discriminating-run.md` - SKILLC_ALLOW_REAL_AGENT=1 on collection-run commands; manifest_rewrites in the receipt check
5. `CHANGELOG.md` - Unreleased entry

Scope: small (~60 lines code, ~80 lines tests). Risk: manifest path spelling variants - match on resolved paths.
