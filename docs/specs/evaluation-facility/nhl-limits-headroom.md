# NHL declared limits and owner storage evidence (Refs #638)

PR-C supplies explicit limit metadata and a standalone owner-run sizing helper.
It chooses no final study values and enables no live run. The owner still must
choose a limit mode, approve #639 sizing and freeze the declaration. PR-A's live
registry and permit/window join remain unavailable; #630's credential dispatch
hold remains separate. A JSON PASS below cannot remove any of those holds.

## Explicit limit mode

An NHL calibration declaration needs `nhl_limits` before new planning or approval.
Neither mode is a default. The object is version 1 and has closed fields:

| Mode | Required fields besides `version` and `mode` | Execution |
|---|---|---|
| `uncapped` | None; wall/token/sizing fields are forbidden | Still subject to ordinary approval, live authority and finite operational deadlines |
| `capped` | `sizing_report_digest`, `wall_seconds`, `tokens` | Refused until approved sizing and actual aggregate token enforcement are joined |

The sizing digest is lowercase `sha256:` plus 64 hex digits. Tokens must be a
positive nonboolean integer at most 2^63-1. Wall seconds must be a positive finite
nonboolean number. Parsing capped metadata is planning only: the number is not
enforcement. Unknown fields, partial caps, zero, nonfinite and wrong-type values
refuse. An orphan limits object without NHL policy also refuses. The existing
whole-declaration approval binds mode, both values and sizing identity; editing
any after approval invalidates provenance. Discrimination does not accept this
opt-in.

`uncapped` describes model-usage policy. Existing `shared.per_attempt_seconds`
and `shared.total_seconds` remain finite controller completion allowances for
execution, storage and cleanup. They are not disabled or silently enlarged.
The real scheduler can already carry multi-hour allowances. A synthetic injected
clock test preserves that behavior, including clipping to the original total
endpoint and accounting for unstarted attempts. Its numeric fixtures are not
study settings, elapsed host measurements or credential-coverage evidence.

Historical policy-only declarations remain parseable for read-only use and do
not acquire a mode. New scheduling refuses their missing mode. Reports derive
`nhl_limits.declared` only from the uniform verified launch-bound declaration
and recorded approval, never mutable outcomes. They explicitly state that
capped dispatch is unavailable and operational deadlines remain finite. Legacy
reports without a mode omit this field.

## Owner-run headroom helper

`python -m skillc.nhl_headroom` is a separate stdlib helper. It is not called by
planning, approval or participant execution. No evals26 measurement was made to
qualify this implementation. Tests inject directory facts, statvfs and clocks.

The owner supplies three private JSON inputs. Policy has exactly `version: 1`,
`sizing_report_digest`, positive finite `max_age_seconds` and
`max_collection_seconds`, nonempty `demands`, and explicit `reservations` (which
may be empty). Each resource row has exactly `root`, `copy_id`, `bytes`, `inodes`
and `multiplicity`. Byte/inode demands are bounded nonnegative integers with
at least one positive value; multiplicity is a positive integer. Every product
and aggregate must fit 2^63-1. Populations are bounded to 256 rows per kind.
These are technical representation limits, not chosen storage budgets.

Binding has exactly `collection_id`, `window_id`, `wave_id`,
`vm_binding_digest` and `declaration_digest`. The first three and resource names
are logical ASCII identifiers, not paths or host names; digests use the SHA256
form above. The private roots file maps every policy root to an absolute
directory path. No default path, demand, reservation, concurrency or freshness
window is inferred. The fixtures under `controls/nhl-headroom/` illustrate the
schema with synthetic values only.

An owner can explicitly collect evidence with:

```bash
python -m skillc.nhl_headroom collect --policy policy.json --binding binding.json \
  --roots private-roots.json --out private-receipt.json
```

Collection opens each directory once and uses `fstat` and `fstatvfs` on that
same descriptor. It records the run user's available blocks (`f_bavail` times
`f_frsize`) and inodes (`f_favail`), not privileged free totals. The raw receipt
is private, includes actual device/inode/filesystem identities, contains no
paths, and is created exclusively with mode 0600. Existing output is refused.
Stdout contains the public verdict only. Keep raw policy/binding/receipt files
private; logical identifiers in a public verdict are owner-chosen public data.

Evidence-only evaluation does not probe the host:

```bash
python -m skillc.nhl_headroom evaluate --policy policy.json --binding binding.json \
  --receipt private-receipt.json --now "$OWNER_OBSERVED_EPOCH_SECONDS"
```

The owner must supply the current epoch time; passing an old time does not
authenticate freshness. Exact policy/run binding, complete roots, bounded
timestamps and complete counters are mandatory. Duplicate JSON members refuse.
Unreadable roots, stale/future or slow collection, conflicting identities,
missing counters and malformed inputs yield UNKNOWN. Available capacity is not
reserved by measurement and can change immediately afterwards.

Roots sharing a device or statvfs filesystem ID share one capacity pool. Use the
minimum observed free capacity for that pool, never the sum of aliases. Distinct
copies and multiplicities add their demands, including retained-evidence
reservations. An alias is deduplicated only for the same explicit copy identity
and actual directory device/inode with identical sizing facts. Conflicting
sizing facts yield UNKNOWN. Available bytes and inodes must both cover each
pool: adequate evidence yields PASS, a measured shortage yields FAIL. Exit
codes are respectively 0, 1 and 2 for PASS, FAIL and UNKNOWN.

Public output includes logical roots, totals and bindings, excludes private
paths and raw filesystem identities, and always says `admission_authority:
false`. A digest establishes consistency, not who measured the VM. A trusted
owner adapter, actual evals26 measurement, reservation mechanism and pre-run
admission join remain future work. A fabricated receipt cannot authorize a run.

## Qualification and remaining issue scope

Committed PASS/FAIL/UNKNOWN fixtures include byte shortage, inode shortage,
reservation pressure, shared-device aliases, distinct filesystems and unreadable
evidence. Actual compiled always-PASS and ignore-reservations variants lose
their committed shortage witnesses. Closed-field tables exercise all policy,
binding, receipt and sample fields plus malformed JSON. A seeded private-path
marker proves the public-output absence check can detect an injected leak.

The limits consumer file imports existing APIs only. On actual pre-change main
7382dcf, its final 31 cases produced 20 meaningful failures and 11 passing
preservation controls: ignored invalid metadata and missing/capped scheduling
and direct planning were exposed, along with the absent declared-mode report.
No absent-module/import error counts as a regression. New headroom
checks qualify a new instrument; its absent API on old main is not red evidence.

Together PR-A, PR-B and PR-C deliver the approved infrastructure slices. They
do not complete #638's original live acceptance: HTTP request/response status
measurement is still unavailable through encrypted CONNECT, the final limit
choice and sizing are open, capped token enforcement is unavailable, physical
storage admission is unjoined, and credentials/live approval remain held. Use
Refs #638 rather than closing the issue on this PR's merge.
