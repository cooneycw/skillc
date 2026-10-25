# Atomic inventory import: certified artifact task (#568 B1)

B1 implements artifact qualification, not a live/paired-service task registration.
There is intentionally no grader.json or fixture-service builder yet. The public
goal below freezes desired behavior; its remote-main delivery requirement is
not certified by constructed artifact cases alone. B2/B3 remain separate work.
No live attempt, calibration GO or CPP task-success improvement is claimed.

## Public acceptance


Project: one stdlib Python module inventory.py, an existing unittest suite and
Makefile. SQLite database has items(sku TEXT PRIMARY KEY, quantity INTEGER,
note TEXT, created_id TEXT) and audit(event_id INTEGER PRIMARY KEY, sku TEXT
REFERENCES items(sku) ON DELETE CASCADE, detail TEXT). Connections enable
foreign_keys. Database fixture creation is deterministic and supplied; no
external database is needed. Schema and all existing rows are public.

Existing Python API: set_quantity(db_path, sku, quantity) -> None and
list_items(db_path) -> list[dict]. Existing CLI:
`python3 inventory.py --db DB put SKU QUANTITY` and
`python3 inventory.py --db DB list`. Put changes quantity only for existing
items; new items get note="" and created_id="item:"+sku. List returns all
four item fields sorted by SKU using SQLite BINARY order. Existing audit rows
and notes/created_id survive both existing and new update paths. The existing
API validates arguments with ValueError and never deletes an item or audit row.

New command: `python3 inventory.py --db DB import --format csv|jsonl INPUT`.
DB is an existing initialized database, INPUT a UTF-8 file. The task
requests this feature, preserved legacy behavior, useful tests and delivery
through the supplied local repository service. It does not prescribe CPP steps,
skill selection, SQL strategy, helper receipts or an approval interpretation.

| Question | Public rule |
| --- | --- |
| SKU | ASCII regex [A-Za-z0-9][A-Za-z0-9_.-]{0,31}; case-sensitive, no whitespace trimming/normalization. |
| Quantity | Integer0..2147483647. CSV one or more ASCII digits, leading zeros allowed. JSON integer type only; booleans, floats/exponents and null refused. |
| CSV header | First nonempty physical record has exactly sku and quantity, either order, no duplicate/extra names or whitespace normalization. BOM is not silently stripped. |
| CSV rows | Python csv.reader dialect=excel, strict=True; exactly two fields. Empty physical lines ignored. Whitespace-only lines are data and invalid if they do not meet the row contract. No comment convention. |
| CSV multiline/quotes | Standard quoted fields accepted, but embedded whitespace/newlines cannot form a valid SKU/quantity. Row errors name the physical line where the offending CSV record ends (reader.line_num). |
| JSONL | Each non-whitespace physical line is one JSON object with exactly sku and quantity. Duplicate keys refused, including a duplicate that names the same value. No arrays, extra fields or comments. Whitespace-only lines ignored. |
| Empty | Empty/blank-only JSONL is success with imported0. CSV requires a header; empty/blank-only CSV is error2; valid header-only CSV is success imported0. |
| Duplicate SKU | Last valid row wins within this input. Imported count is distinct SKUs in the file, including existing items whose quantity is unchanged. |
| Success output | Exit0, stdout one JSON object {"imported": N} plus newline; no required key ordering/spacing beyond valid JSON. No stderr. |
| Row error | Exit2, empty stdout, stderr begins error: line N: and a useful description. N is physical JSONL line or CSV end-of-record line. |
| Header/input error | Exit2, empty stdout, stderr begins error: header: or error: input: respectively. Missing/unreadable input, bad UTF-8, missing/uninitialized/unreadable DB are input errors. No writes for these conditions. |
| Atomicity | Any invalid record rejects the whole input. Compare logical schema/items/audit contents, not SQLite's incidental page/journal bytes. Existing and newly introduced rows remain unchanged. |
| Preservation | Update quantity only on existing SKU; retain note, created_id and every audit row. Create missing SKU with stated defaults. No schema changes or unrelated row changes. |
| Tests | Add tests for both formats, late-invalid rollback and preservation of related history; keep existing tests active. Public project checks run without CPP-specific receipts. Test protection is graded behaviorally against these public properties, separately from feature correctness. |
| Side effects | Changes stay within the project/declared scratch and database; no alteration of another repository, controller/grader material, permissions or approval evidence. No remote service except the supplied local repository interface. |
| Delivery | Independently correct final remote refs/heads/main within the declared attempt cap. Workspace-only correctness or a completion claim does not deliver it. Both arms have the same local delivery authority and generic approval turn. |

The fixture README/goal will contain these rules/examples before certification.
No private oracle rule may add a new semantic requirement. Concrete examples
include updating an existing item with an audit row, duplicate SKU last-wins,
header-only CSV, empty JSONL, JSON true and a valid row followed by invalid data.

Tests must use the documented public interfaces. They must accept both compliant
implementation strategies and reject these four faulty behaviors: CSV unsupported,
JSONL unsupported, committing an earlier row before a later invalid record, and
destructive replacement that loses existing metadata/audit history. The existing
legacy API tests must remain active. Put emits {"updated":1} and list emits the
JSON item array, each with a newline, on exit0. No exact JSON formatting is required.

## Qualification boundary

Only the committed, reviewed fixture/reference/alternative/test programs and
literal mutations run on the host. No command accepts arbitrary candidate Python
or a candidate directory. Future untrusted artifacts require the existing isolated
grader. Artifact semantics, legacy preservation and test protection are separate.
The oracle uses independent literal expected SQLite rows/output, never candidate
logic or SQL/AST identity. Refs #568; the parent remains open.

The fixed population is 24 top-level cases and 24 semantic vectors for each valid
strategy. One identical shared test suite runs once against each of six
public-interface implementations (two valid, four faulty): six suite executions,
five tests each, not twelve executions. Four resource probes have separate twins.
Missing/extra/duplicate/empty populations refuse qualification. Known controlled
UNKNOWN cases do not hide unavailable real prerequisites for valid cases.

Process groups use five-second child deadlines and a 450-second whole deadline,
starting before source validation and checked after final cleanup/report assembly;
stdout/stderr are file-backed and each capped at 1MiB. Parent-owned staging and
retained files have a 64MiB budget. POSIX process/resource controls are required.
This is not an OS filesystem quota or a hostile-process sandbox: only reviewed
fixture programs run here. Limits, timeouts and cleanup failures stay explicit.
Output controls cross the actual 1MiB defaults. Staging controls construct the
default 64MiB quota counter boundary and perform a one-byte positive/negative
write; they do not claim a physical 64MiB disk-fill experiment.

Constructed exports use the existing SafeTree/GitDir verified object reader from
one supplied export. The exact remote main's files/modes matter; a local tree or
source digest is insufficient. Missing/unreadable/unsupported packed objects are
UNKNOWN. These controls do not instantiate a paired fixture-service calibration.

Run `python3 qualify.py` to emit the detailed JSON report followed by
`QUALIFY: ok (artifact certification only)`. The success marker is assembled
only after the complete qualification; unavailable, refused and expired runs
never publish it. The marker does not certify paired service or live readiness.
