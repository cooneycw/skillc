# NHL reference infrastructure (#633)

The participant contract remains [goal.md](goal.md). This document describes
controller preparation. It adds no participant requirements and authorizes no
network acquisition, live model calls, paid spend or machine access.

## Delivery boundary

The stdlib-only `skillc.nhl_snapshot`, `skillc.nhl_oracle` and
`skillc.nhl_reference` modules prepare a private reference and compute F1-F8,
on-ice membership, anomalies, census and declared-sample freshness independently
of any candidate code. Their committed inputs are authored synthetic data.
This is infrastructure preparation, not a measured season oracle. Issue #633
stays open until an authorized declaration-time acquisition on the designated
host produces a verified private season copy and measured census.

The five light live source requests during #632 all returned HTTP 403 from the
worker container. No live NHL response shapes were newly validated here. The
adapter recognizes the gamecenter source fields named in the implementation and
shift-chart types 517 (shift) / 505 (goal); unfamiliar required fields, missing
sources, conflicting identities and incomplete chart populations remain
unavailable. Validation on a private actual sample, and correction of any adapter
mismatch, must precede a season run or scoring claim. Synthetic qualification
alone does not establish that a live season is completely covered or reconciles.

## Explicit acquisition and identity

After separate authorization, choose a new private path outside the checkout
and candidate mounts. Freeze a season-wide date interval in the declaration.
The controller must independently establish that this interval covers the whole
2025-26 regular season and playoffs; the tool proves coverage of the declared
interval, not that a conveniently short interval equals the season. Empty or
incomplete schedule enumeration refuses. Schedule windows are requested every
seven dates and every date in the declared interval must occur in a response.

Use these command shapes, substituting declaration-owned values:

```sh
uv run python -m skillc.nhl_reference selftest
uv run python -m skillc.nhl_reference snapshot --out "$REFERENCE" \
  --start "$START_DATE" --end "$END_DATE"
uv run python -m skillc.nhl_reference derive --reference "$REFERENCE" \
  --manifest-sha256 "$MANIFEST_SHA256" --goal evals/nhl-season/goal.md \
  --out "$EXPECTED"
```

`snapshot` is an explicit network action: fixed NHL HTTPS hosts only, no
redirects, bounded byte size/time/retries, raw bytes retained once per source,
no network on import. No endpoint override is accepted by the real transport;
tests inject a deterministic in-memory fetcher. A snapshot directory must be
new. A failed enumeration leaves no manifest; it cannot look like a completed
snapshot. Each completed game gets boxscore, play-by-play, landing and shifts,
including an unavailable entry when fetching/parsing fails. Missing sources do
not remove a completed game from the population. Responses with extra fields
are retained byte-for-byte. Source payloads, URLs, timestamps and hashes stay
private and are never added to Git.

Capture `snapshot`'s manifest SHA-256 in the controller-owned declaration and
supply it to subsequent commands. `load` rechecks raw payload hashes, source
identities and the game population against schedule records before deriving.
Do not let candidate processes write the reference, its manifest, expected
outputs or live re-check report; a hash kept beside writable data is not a
custody boundary. Existing controller capture/containment supplies that boundary
when this infrastructure is wired into a declared run.

## Independent results and bounded comparison

`derive` writes one private `reconciliation/{game_id}.json` and one streamed
`on_ice/{game_id}.jsonl` per game. It publishes `derivation.json` last, binding
the manifest, goal, oracle and snapshot-code hashes, per-game artifact hashes,
period timing, row count and on-ice availability. An absent completion index
means derivation is incomplete. Exit zero means artifact production completed;
read the actual availability/status/census, not the exit code as a clean-season
claim. An unavailable reconstruction writes no membership rows and is explicitly
UNAVAILABLE, rather than exporting guessed players.

The census accounts for every game and family with PASS, DISCREPANCY and
UNAVAILABLE counts. `planted_cases_required` is true for each family with zero
observed discrepancies, including a family whose inputs were all unavailable.
That is a #634 requirement, not evidence that synthetic cases have measured the
season. A source anomaly is retained and reported; no shift is extended, clipped
or invented to force agreement. Overlapping shifts contribute their raw duration
to F5, while membership deduplicates the player at each second.

The `compare` seam reads a supplied per-game reconciliation object and sorted
per-game on-ice JSONL extracted by the controller from the participant exports:

```sh
uv run python -m skillc.nhl_reference recheck --reference "$REFERENCE" \
  --manifest-sha256 "$MANIFEST_SHA256" --sample "$GAME_ID" --out "$LIVE_REPORT"
uv run python -m skillc.nhl_reference compare --reference "$REFERENCE" \
  --manifest-sha256 "$MANIFEST_SHA256" --game-id "$GAME_ID" \
  --candidate-game "$CANDIDATE_GAME_JSON" --candidate-on-ice "$CANDIDATE_ICE_JSONL" \
  --live-report "$LIVE_REPORT"
```

The declaration chooses the sample before grading; the tool accepts only
nonempty distinct IDs in the reference. Re-check fetches all detailed sources
and every recorded schedule response containing a selected game. A byte change,
reference unavailability or failed re-fetch marks that game UNKNOWN, never FAIL.
An unchanged sample says UNCHANGED, not candidate PASS. Unsampled games remain
UNKNOWN. The comparison verifies the report is bound to the declared manifest,
contains all required source hashes for that game, and matches observed hashes;
source drift vetoes even an otherwise wrong candidate's FAIL for that game.
Only a controller-owned live report is valid evidence of a real fetch.

Reconciliation comparison checks every named comparison/scope, values, units and
status, and refuses missing/duplicate/extra family or check populations. Expected
UNAVAILABLE checks must retain UNAVAILABLE status and the matching null/value
sides; fabricated PASS or DISCREPANCY is a failure. Honest UNAVAILABLE reporting
is graded directly and does not by itself turn reconciliation UNKNOWN. Membership comparison streams the exact
rows, detecting missing, duplicated, extra, reordered or wrong player/role rows.
Comparison exit codes are 0 PASS, 1 FAIL and 2 UNKNOWN. This seam does not execute
candidate code or grade the whole project: source-provenance validity, anomaly
reporting quality, database/retrieval operation, added-field behavior, discrepancy
recall/precision and viewer behavior still need their declared integration under
#634/#635/#639. No full-project verdict follows from this bounded comparator.

## Controls and remaining acceptance

The [committed synthetic controls](../../controls/nhl-reference/README.md) cover
known-wrong output for every family, planted source discrepancies in every
family, missing comparisons, wrong on-ice membership, source drift and an empty
population. The self-test refuses deliberately blind comparators. Unit coverage
also exercises raw-byte retention/tampering, unavailable fetches, manifest pins,
half-open shifts, period-end samples, overtime, shootouts, empty nets, bench PIM,
unused backups, roster role conflicts and unavailable input.

Before closing #633: authorize the actual host/acquisition; freeze source and
goal identities; validate a private actual API sample; acquire and checksum the
whole declared completed-game population; produce the measured F1-F8 census and
expected on-ice/invariant artifacts; retain live-sample re-check evidence.
The preparation self-test and synthetic census do not satisfy these live items.
