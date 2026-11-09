# Declaration-bound NHL egress controls (Refs #638)

`policy.json` is synthetic-control input, never live authorization.
`legacy-policy.json` pins canonical provider-only policy/digest and denied-traffic
classification from pre-fix main e22a436. `mutants.json` selects committed blind
variants exercised by the tests: allow-all, ignore-denied and always-issue.

The unchanged behavior tests on that main produced 14 failures and 8 passes:
two allowed NHL hosts wrongly stopped native scheduling; denied and failed-upstream
undeclared requests wrongly allowed later slots; seven malformed policies were accepted;
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

`shapes.json` drives one complete 42-level wrong-type table, including every
new fixed declaration/network field, stored config/binding/declaration, summary
and counter field, and permit/session/backend boundary. The final table on
pre-sweep cd2cd0c gives 225 refusals-contract failures and 64 passing controls:
12 TypeError, 46 AttributeError, 74 delegated declaration refusals rather than
the policy API refusal, and 93 cases lacking the new explicit refusal. Many
summary cases already failed closed by returning unavailable evidence; these
are error-contract qualification, not claims of earlier unsafe authorization.
The three policy files have 360 passing controls. Runtime callers translate
PolicyRefused observations back into the same unavailable-evidence stop. Valid
extensible legacy config dictionaries remain accepted. Failed upstream CONNECT
attempts to an undeclared host also stop the strict opt-in, even without a
successful connection; they do not measure HTTP requests or response codes.

`wire.json` commits nine raw-log cases: non-object JSON roots, mixed lines,
an invalid object, and a healthy twin. The wire tests additionally cover six
transport shapes and a later healthy read that must not erase a latched stop.
On e7f3b4a6 these tests give 12 exception failures and 5 preservation passes;
with NHL-only wire validation all four test files give 377 passes. The strict
observer and capture boundary reject invalid wire evidence before the historical
object-only decoder; generic legacy decoding and valid log output are unchanged.
These are fake-only controller controls, not physical proxy qualification.
