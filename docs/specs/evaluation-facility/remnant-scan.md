# Bounded VM remnant detection (Refs #630, slice 4)

This is credential-DETECTION scope. It implements a detector over explicit
controller inputs, with synthetic memory-only tests. It does not resolve,
stage, inject, rotate or clean credentials, and does not contact a VM. Custody
(slice 3) and the stopped-run cleanup/release controller (slice 6) remain later
work.

`skillc.remnant_scan` takes supplied transient reference bytes, an approved
declaration, the complete private mapping of logical surface IDs to local roots,
an opaque controller observation-generation object, and a read-only reader.
References are never learned from the files being tested. The trusted adapter
must supply all delivered/authorized transient values, authenticate root mappings
and reader coverage, stop writers first and control the lifetime of the evidence.
This module neither discovers roots nor proves that a physical VM was observed.
Same-process Python is trusted; an authority string or public result cannot
authenticate that boundary.

## Declaration and required population

The optional `remnant_scan` field is supported only on a calibration declaration
with valid VM identity and operator-admission declarations. It has exactly these
fields (the values below are synthetic examples, not operating defaults):

```json
{
  "version": 1,
  "waves": [
    {"wave_id": "synthetic-wave-1", "roles": ["integrator", "worker"]},
    {"wave_id": "synthetic-wave-2", "roles": ["integrator", "worker"]}
  ],
  "limits": {
    "entries": 4096,
    "depth": 32,
    "file_bytes": 8388608,
    "total_bytes": 67108864
  }
}
```

The wave IDs and order must equal the admission planned population, and every
wave has a nonempty distinct role population. If `wave_export` is declared, its
wave/role population must agree exactly. The existing whole-declaration approval
digest binds the policy; a mutation after approval cannot earn CLEAN.

`surfaces(declaration.data)` derives the exact required root mapping:

- One VM `staging` root, including the staging area after teardown.
- For **every** planned wave/role: `home`, `vault`, `stdout`, `transcript` and
  `cache-log` roots, keyed as `wave_id/role/class`.
- One `export-payload` root if complete-wave export is declared.

Roots are directories: individual streams use a directory containing their
captured file(s). No exclude glob or caller-selected subset exists. Missing or
extra root keys, duplicate exact normalized root paths, inaccessible roots,
symlinks, FIFOs or other special entries make coverage UNKNOWN. The adapter owns
ancestor-path custody and the correspondence between a logical root and the
actual stopped VM surface; supplying the same content under different paths does
not prove distinct physical coverage. Overlapping surfaces may read the same
file twice and consume the common budget twice.

An empty plan is invalid. Empty references, an empty reference value, or **zero
readable regular files in any required surface** yield UNKNOWN. A readable empty
file counts as a file; an empty directory does not. Missing roots after deletion
do not establish absence. Confirmed-empty/removed surfaces require separate
trusted controller absence evidence, which is not implemented here.

## Fixed encoding coverage and resource bounds

Every reference is checked as raw bytes, including NUL/non-UTF-8 content; standard
and URL-safe base64, padded and unpadded; lowercase and uppercase hex; canonical
percent encoding and full percent encoding, with lowercase/uppercase escape
digits. Valid UTF-8 references additionally cover JSON string interiors with
`ensure_ascii` on and off, optional escaped solidus, a second JSON escaping layer,
and UTF-16 little/big endian. Matching interiors also catches quoted strings;
UTF-16 BOMs do not prevent a contained match. Filenames and file contents are
scanned as bytes. No file-type or binary/text classification skips a file.

This is a closed exact-byte detector. It does not decode arbitrary documents,
decompress archives, recover hashes, join split fragments, detect truncated or
rotated values, normalize Unicode, enumerate arbitrary mixed-case percent escapes,
or cover arbitrary repeated/nested combinations of encodings. CLEAN means no
match to the supplied values in the declared complete observed scope under this
encoding contract. It is not a universal secret-absence claim.

All four positive integer caps are explicit in the declaration, at or below the
hard ceilings shown above. Entry count and byte budgets are shared across all
roots; roots themselves count as entries. Depth is relative to each root. The
default reader bounds directory enumeration as well as file reads. Injectable
readers must honor that same no-follow, complete-enumeration and bounded-read
contract; they are trusted adapters, not participant callbacks. A read exceeding
the per-file or shared cap makes coverage UNKNOWN, never a truncated clean scan.
The supplied reference population is limited to eight nonempty byte values and
64 KiB total, and the compiled fixed patterns to 1 MiB. Exceeding a bound yields
UNKNOWN; no reference or encoding is silently dropped to fit.

## Results, privacy and composition

`References(tuple_of_bytes)` is an opaque, redacted memory-only container. There
is no reference file, environment lookup, provider or command-line resolver. The
scanner never writes files and never returns a reference, its length, digest,
excerpt, offset, marker ID or a scanned path. Reader exceptions are suppressed
at the collection boundary without publishing their text or exception chains.
References, patterns and result private fields have redacted representations.
This reduces accidental output; arbitrary Python inspection/debugger locals and
process memory remain trusted. Python cannot promise cryptographic erasure.

`ScanResult.public()` is an exact allowlist: version, status, coverage, fixed
class counts (`required`, `complete`, `files`, `matches`) and fixed encoding
match counts. Counts report matched patterns per observed name/file, not unique
secrets or occurrence offsets. A raw value may also match an encoding category
whose representation is identical. Neither identities nor private bindings are
published. `repr(result)` contains only its status.

- `NOT_CLEAN`: at least one observed match, even if other coverage is UNKNOWN.
- `CLEAN`: every required surface has readable files, every encountered entry
  was read completely within bounds, and no declared encoding matched.
- `UNKNOWN`: no observed match establishes a leak, but reference/approval/input
  validity or complete coverage could not be established.

The in-memory result privately binds the approved declaration, exact supplied
root mapping and observation-generation object. `matches(...)` checks that
composition context, with generation identity, not just equality. It is neither
a transferable certificate nor current freshness or dispatch permission. The
public dictionary has no release authority and must not be accepted in place of
controller-owned evidence.

The future stopped-run controller must treat only a matching complete CLEAN as
one prerequisite for release of this declared scope. NOT_CLEAN blocks release
regardless of whether a matched file is delivered, allowed or clutter; UNKNOWN
also cannot satisfy the prerequisite. This never earns task credit. #619's
zero-clutter outcome cannot establish secret absence, and this scanner never
deletes unrelated benign files. Stop ordering, physical collection, custody,
cleanup, transfer and source retirement remain separate requirements. In this
slice **no hook is added to `wave_export.freeze`**, and `leak.scan_path` retains
its existing identity/text-screening behaviour. Existing declarations without
this optional field retain their behaviour.

## Committed controls

`controls/remnant-scan/cases.json` commits placement/action descriptors rather
than reference bytes. Tests generate conspicuously synthetic random references
in memory and plant them through an overlay reader over benign temporary trees;
even synthetic references are never written to the fixture files. Cases cover
post-teardown staging, every role surface, stdout, JSON-escaped transcript,
binary cache/log, export payload, filename bytes, all fixed encoding variants,
missing/partial/empty populations, unreadable inputs, special files and bounds.
Qualification must refuse both an always-CLEAN checker and a checker whose
expected census and input mapping omit staging. Good complete scans preserve
all benign bytes and modes. A deliberate assertion failure captures its traceback
with locals in memory and proves that its output contains no generated reference;
the failing frame uses opaque fixture/result representations. The private audit
covers raw bytes, Python bytes/string repr and escaped interiors (both quote
styles), JSON escaping and every fixed detector encoding, independently of the
production pattern compiler. Every test's captured stdout, stderr and logs are
audited against its generated references. Captured tracebacks use an opaque
container so even a rejected witness is never printed. Committed unsafe twins
put raw bytes or a decoded string in the failing frame: the audit must reject
both, while accepting the redacted twin. The two witnesses failed the literal-only
audit on `5e44f55` (no refusal); an explicit literal-only blind mutant reproduces
that acceptance and is rejected by the strengthened audit.

Eight declaration ignored-field cases were run unchanged on parent `e597de2d`:
all eight failed because no refusal occurred. Two additional unsupported-kind
checks refuse a field injected after parsing (record and dispatch gates).
These eight ignored-field failures are genuine prefix reds;
the new detector's planted byte cases qualify a new API and are not described
as regression tests based on that API being absent on the parent.
