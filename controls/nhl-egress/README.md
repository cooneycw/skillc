# Declaration-bound NHL egress controls (Refs #638)

`policy.json` is synthetic-control input, never live authorization.
`legacy-policy.json` pins canonical provider-only policy/digest and denied-traffic
classification from pre-fix main e22a436. `mutants.json` selects committed blind
variants exercised by the tests: allow-all, ignore-denied and always-issue.

The unchanged behavior tests on that main produced 13 failures and 8 passes:
two allowed NHL hosts wrongly stopped native scheduling; a denied undeclared
request wrongly allowed later slots; seven malformed policies were accepted;
and all three purposes could pass existing approval without a frozen NHL digest.
No missing new API/import error is counted. Schedule controls replace only the
approval and expensive attempt/backend boundaries with synthetic in-process
inputs. Unpatched approval is independently required to refuse every NHL plan.

Permit API, alias, copy, issuer, backend/attempt, mutation/revocation and Docker
no-I/O cases qualify the new seam; they are not claimed as old-API regressions.
Existing off-list-success stopping and default denied-traffic continuation are
preservation controls. The frozen Docker backend binds a permit once through
its issuing session; a permit-shaped object or copied permit is not sufficient.

Real Docker preparation and execution refuse synthetic permits. The live digest
registry is empty, and the live permit/dispatch adapter is deliberately held for
a reviewed owner-approved #639 freeze. Even changing that registry alone cannot
enable execution: the missing live issuer/window join is an explicit refusal.
This change does not relax #630 or handle any credential. No live run, sizing,
host action, physical proxy/cancellation qualification, byte measurement or
HTTP request/response measurement is claimed. Bytes are a later #638 slice.
