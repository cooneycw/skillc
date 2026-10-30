# NHL 2025-26 season data project

Build a working project from an empty directory that retrieves the completed
2025-26 NHL season from the live public NHL API, stores the data in a database,
reconciles it, reconstructs who is on the ice each second, and provides a graph
viewer that plays through game time to show team-versus-team shift dynamics.

This document is the complete public task contract. Evaluation may sample its
requirements, but may not add requirements absent here. Implementation language,
database engine, graph layout and development procedure are your choices.

## Deliverables and operation

Deliver the source, dependency declarations, database schema/migrations and a
README with copyable commands to install, retrieve the season, reconcile it,
export the outputs below and start the viewer. Commands must work from the
project root. Document every required environment setting and the database's
location/connection setting. No proprietary service, paid API or secret is
required to use the public data. Keep downloaded NHL data out of the source
repository; local databases, caches and exports are runtime artifacts.

Persist the retrieved source records and the derived records in a database,
linked by NHL game, team and league player IDs. Names alone are not identities.
Retain source payloads, endpoint URLs, retrieval timestamps and content hashes
so findings can be traced to the exact data used. Fetching or parsing failures
must be visible per source/game; do not turn a failed fetch into empty data.
Re-running retrieval must not duplicate games, events or shifts, and must retain
provenance when a changed response replaces the active version.

Provide a documented API-base override or equivalent endpoint mapping so the
same retriever can run against an HTTP server supplying the same endpoint paths
and response shapes. It must accept additional JSON fields at any depth without
crashing, dropping existing records or losing the added fields from the retained
source payloads. Existing documented facts must still be derived correctly.
Unknown fields need not acquire new database columns or viewer controls.

## Season population and sources

Discover games using the NHL schedule, not a hand-maintained list of game IDs.
The season ID is `20252026`; include regular season (`gameType` 2) and playoffs
(`gameType` 3). Include every game the schedule marks completed (`gameState`
`OFF` or `FINAL`) at the retrieval cutoff, including overtime and shootout games.
Exclude preseason, all-star/exhibition, future, in-progress, postponed and
cancelled games that are not completed. Record the UTC cutoff and the schedule
coverage used to enumerate the season, following schedule dates/pages until
both regular season and playoffs have been covered. A completed game with a
missing detailed source stays in the population with an unavailable finding.

Use these public sources (substitute the selected NHL game ID/date):

| Source | URL |
|---|---|
| Schedule | `https://api-web.nhle.com/v1/schedule/{YYYY-MM-DD}` |
| Boxscore | `https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore` |
| Play-by-play | `https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play` |
| Landing/summary | `https://api-web.nhle.com/v1/gamecenter/{game_id}/landing` |
| Shift chart | `https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}` |

Retain all of these source responses when available. Use the boxscore and
landing summary fields appropriate to each comparison below, and identify the
actual fields used in the report. Do not count the same event twice because it
appears in two endpoints. Deduplicate repeated source identities, while recording
conflicting duplicates. Respect rate limits; use bounded retries and caching.
An unavailable endpoint or unrecognizable required field is not evidence that
its statistic is zero.

## Reconciliation families

For every included game, perform all eight named families below. Compare by
team and, where stated, player; comparing only league-wide or game-wide totals
is insufficient. Use integer event counts and integer seconds, with exact
comparison (no unstated tolerance). Preserve a discrepancy rather than editing
a source value or inventing events/shifts to make the comparison agree.

Each family contains the comparisons listed here. Emit each individual check,
including successful and unavailable ones, with the scope IDs, actual source
fields, values and reason. A missing member of a family does not excuse skipping
its other available comparisons. A zero from a present, complete source is a
value; a missing source or unresolvable interpretation is UNAVAILABLE.

| ID and name | Summary/source side | Independently derived detailed side |
|---|---|---|
| F1 Goals | Each team's final score and sum of its boxscore skater goals | Count play-by-play goal events credited to that team, excluding shootout attempts. Compare the skater sum to that count and the final score to that count plus the shootout deciding-score adjustment below. |
| F2 Shots on goal | Each team's boxscore SOG, sum of its skaters' SOG, and sum of the opposing goalies' shots against | Count that team's play-by-play shot-on-goal and goal events, excluding shootout attempts. Compare team SOG and skater SOG to that count. Compare opposing goalies' shots against to the count with an opposing goalie present: empty-net shots/goals are not charged to a goalie. Use the event's goalie attribution or readable situation code to determine presence; if neither resolves it, the goalie comparison is unavailable. Missed and blocked attempts are not SOG. |
| F3 Penalty minutes | Sum of boxscore player PIM for each team | Sum the assessed penalty minutes in play-by-play attributed to players on that team. Use assessed duration, not time actually served or time until a power-play goal. Include coincidental penalties and misconducts with their assessed duration; a double minor counts its full assessed minutes. Bench/team-only penalties are listed in the per-game `anomalies` array with their assessed minutes, team ID and source record in `reason`/`scope`/`sources`, and excluded from this player-PIM comparison on both sides. Penalty shots without assessed minutes add no PIM. Uninterpretable duration/attribution makes the affected comparison unavailable, with the raw record identified. |
| F4 Player event counts | Each boxscore player's hits, blocked shots, giveaways and takeaways | Count the corresponding play-by-play events attributed to that player, separately for each statistic. A blocked shot belongs to the blocking player, not the shooter; a hit belongs to the hitter, not the player hit. Missing attribution is recorded and makes affected comparisons unavailable, not silently assigned to a player. |
| F5 Ice time and shifts | Each boxscore player's TOI, and each skater's reported shift count | Sum that player's shift durations and count that player's shift records. Compare TOI in seconds and skater shift counts. Include goalies in TOI. Only actual shift records count as shifts; goal records in the same response do not. Retain and flag overlaps, invalid intervals and conflicting duplicate shifts rather than trimming them to fit the boxscore. |
| F6 Goal records | Goal entries supplied by the shift-chart source | Compare the multiset of goal records to play-by-play goals by credited team, period number and period elapsed time, excluding shootout attempts. Preserve multiplicity. Goal entries are not player shifts. If the shift-chart response does not supply recognizable goal entries, mark this comparison unavailable and identify that limitation; do not manufacture entries from play-by-play and then claim agreement. |
| F7 Strength state | Each non-shootout play-by-play event's situation code | Decode the code's away goalie, away skater, home skater and home goalie counts (in that order) and compare with distinct on-ice players of each role/team from the on-ice table at the event's second, using the boundary convention below. Missing/invalid codes, unknown player roles or unresolvable timing are unavailable for the affected event. A readable code/count mismatch is a discrepancy; a stoppage does not excuse suppressing it. |
| F8 Roster | Boxscore player IDs and play-by-play roster player IDs | Compare those two roster sets, then check every player with a shift against each roster, including team assignment. Report set differences and team conflicts. A rostered player with no shift is allowed when reported TOI is zero (for example an unused backup); positive reported TOI without any shift is a discrepancy. Missing TOI makes that participation comparison unavailable. Do not require all dressed players to have shifts. |

For F1, an NHL final score in a shootout includes one deciding team goal without
a corresponding non-shootout goal event or individual skater goal. Apply exactly
one extra goal to the winning team's score comparison only when the source
identifies a shootout decision. Do not count shootout attempts in F1-F6, TOI,
shift counts or the on-ice table. Preserve the source's shootout records as a
separate phase for inspection. If a shootout decision cannot be determined,
report that score comparison unavailable rather than guessing.

F7 uses the situation code as a count summary; it does not infer which individual
players are present. Roles come from the roster/boxscore. Never assume a goalie
is present just because the game has one rostered, or assume five skaters because
there is no penalty. An empty-net interval must be representable.

## On-ice representation and time conventions

Build a sparse second-by-second relation keyed by
`(game_id, game_elapsed_second, team_id, player_id)` with a player role
(`skater` or `goalie`). One row means that player is on the ice during that
second; no row means absent. Do not create a dense row for every absent player.
The database representation may be compressed internally, but the exported
relation must expose these rows with unique keys.

Time is integer seconds of hockey playing time, not wall-clock time. Period
elapsed times increase from zero. If a source uses time remaining, convert it
using that period's length. Periods 1-3 are 1,200 seconds each; regular-season
overtime is at most 300 seconds; each playoff overtime period is at most 1,200
seconds. Add the full lengths of preceding periods to obtain game-elapsed time.
Use the actual played duration of the final period when the game ends early in
overtime. A full regulation game therefore has sample seconds 0 through 3599.
Intermissions and stoppage wall time add no seconds. Do not assume every game
lasts 3,600 seconds or every overtime lasts its maximum length.

A shift occupies the half-open interval `start <= t < end` after conversion to
game-elapsed seconds. An end second is excluded, so adjacent shifts do not
create an extra overlap. Preserve period identity on shifts and events in the
stored source/derived records. A zero-length shift covers no seconds; flag
invalid negative, reversed or out-of-period intervals and do not guess a repair.
A player with overlapping shifts appears once per second in the relation, but
the overlap remains a reported anomaly and raw shift-duration sums are retained
for F5. Conflicting team/role identity must remain visible as an anomaly.

For F7 and event seeking, an event at period elapsed time `e` uses the table's
second at `period_start + e`. When `e` equals that period's actual played end,
use its final played second (`period_start + e - 1`), not the next period's
first second. Keep the event's original timestamp and report this mapping.
An event at a period's start uses the first second of that period. An event
outside the played interval or in a zero-duration period is unavailable for
this comparison. Multiple events at one clock time use the same sampled second;
do not invent subsecond order from shift endpoints. Flag readable disagreements
at stoppages/boundaries just as other mismatches; do not smooth the source to
fit a situation code.

Shootouts have a separate phase and no hockey playing-time seconds in this
relation. The viewer must identify the shootout phase and avoid displaying its
attempts as ordinary shifts. Keep pulled-goalie intervals, unusual player counts,
missing shift coverage and other source anomalies visible. Record per-second
team skater/goalie counts, overlapping player shifts, multiple goalies on one
team, unknown identities and missing coverage as findings with source references.
Unexpected counts alone do not authorize inserting or removing players. No
rostered goalie having a shift at a particular second means zero observed goalies,
not permission to fill a goalie in.

## Machine-readable output

Provide a documented command that exports the active database into UTF-8 files.
All IDs below are NHL integers, all times/durations are integer seconds unless
explicitly named UTC, all UTC timestamps are RFC 3339 strings, and all SHA-256
hashes are lowercase hexadecimal. Additional fields are allowed; the following
keys, types and comparison identifiers are the shared machine-readable interface.

`games.json` is an object with `schema_version: 1`, `season_id: 20252026`,
`retrieval_cutoff_utc`, `schedule_coverage` and `games`. `schedule_coverage` is an
array of objects with `start_date`, `end_date` (inclusive ISO dates), and
`sources` (the source objects defined below). Each member of `games` has:

- `game_id`, `game_type`, `home_team_id`, `away_team_id` (integers);
- `game_state` (`OFF` or `FINAL`), `played_duration_seconds` (integer or null
  if unavailable), and `periods` (array of objects with `period`, `phase`
  (`REG` or `OT`), `start_second`, `played_duration_seconds`); the numeric
  period fields are integers, or null when the required timing is unavailable.
  Use an empty `periods` array if no period population can be recovered;
- `sources`, an array of source objects covering schedule, boxscore,
  play-by-play, landing and shifts, including unavailable sources.

A source object has `source_id` (`schedule`, `boxscore`, `play_by_play`,
`landing` or `shifts`), `endpoint` (URL), `retrieved_at_utc` (string or null
when no response was received), `payload_sha256` (string or null when no
payload was retained), `availability` (`AVAILABLE` or `UNAVAILABLE`),
`record_pointer` (RFC 6901 JSON Pointer into the retained payload, empty string
for the whole response), and `reason` (string). A nonempty reason explains
unavailability. A check may have several source objects/pointers to identify
all contributing records. Pointers identify the actual source fields used.

`reconciliation.json` is an object with `schema_version: 1` and `games`, an
array with one object per included `game_id`. Each game object contains
`game_id`, `families` and `anomalies`. `families` has exactly one object for
each F1-F8, with `family_id`, `status` and `checks`. Each check has:

- `comparison`, one of the identifiers in the table below;
- `scope`, an object with `team_id`, `player_id`, `event_id`, `period` and
  `game_elapsed_second`, each an integer or null when not applicable;
- `check_id`, the stable string
  `{family_id}/{comparison}/{team_id}/{player_id}/{event_id}/{period}/{game_elapsed_second}`,
  substituting the literal `null` for each null scope component;
- `status`, `summary_value`, `detail_value`, `unit`, `sources` (array of source
  objects), and `reason` (string, nonempty for discrepancy/unavailability).

Emit one check for every applicable comparison/scope below. Check IDs are unique
within a game and do not change across reruns of the same records. In the table,
set the named scope keys and leave all others null. A whole-source failure may
use the same comparison with all-null scope when its population cannot be
identified; it must not invent a passing empty population.

| Family | `comparison` identifiers | Scope and values |
|---|---|---|
| F1 | `team_score`, `skater_goals_sum` | `team_id`; integer goals. For `team_score`, detail includes the stated shootout adjustment. |
| F2 | `team_sog`, `skater_sog_sum`, `opposing_goalie_shots_against` | `team_id` is the shooting team; integer shots with the empty-net rule above. |
| F3 | `player_pim_sum` | `team_id`; integer assessed minutes. |
| F4 | `hits`, `blocked_shots`, `giveaways`, `takeaways` | `team_id`, `player_id`; integer events. |
| F5 | `toi_seconds`, `shift_count` | `team_id`, `player_id`; integer seconds or shifts respectively. |
| F6 | `goal_records` | All scope keys null; arrays of `{team_id, period, period_elapsed_second}` objects sorted by those keys, retaining duplicates. Shift-chart array is summary, play-by-play array is detail. |
| F7 | `strength_counts` | `event_id`, `period`, `game_elapsed_second` (mapped sample second); objects with integer `away_goalies`, `away_skaters`, `home_skaters`, `home_goalies`. Code counts are summary, table counts are detail. |
| F8 | `roster_sets` | `team_id`; sorted player-ID arrays, boxscore as summary and play-by-play roster as detail; compare equality. |
| F8 | `shift_roster_boxscore`, `shift_roster_play_by_play` | `team_id`, `player_id` for every player/team pair with shifts; boolean membership in the respective roster as summary, `true` as detail. A conflicting assigned team fails membership for the shift's team. |
| F8 | `participation` | `team_id`, `player_id` for each boxscore player; boolean (reported TOI is positive) as summary, boolean (at least one actual shift exists) as detail. Only summary true/detail false is a discrepancy; summary false permits either detail value. |

`unit` is `goals` for F1, `shots` for F2, `minutes` for F3, `events` for F4,
`seconds` or `shifts` for F5, `goal_records` for F6, `players` for F7 and
`player_ids` or `boolean` for F8. `reason` explains the relationship used when
it is not simple equality. Missing/unresolvable values are JSON null, not zero;
retain any available side even when the other is null. A missing-TOI F8
participation check is unavailable. Family aggregation is defined below.

`anomalies` is an array of objects with `code` (a stable implementation-defined
string), `scope` (the same five explicit keys as checks), `reason` (nonempty
string) and `sources` (array of source objects). Use it for the time, identity,
source and coverage problems required above. Explain anomaly codes in the
README; graders read scope/reason/sources and may not demand an unstated code
vocabulary. Use a second-specific scope for on-ice count/coverage anomalies.

`on_ice.jsonl` contains one JSON object per present-player second with integer
`game_id`, `game_elapsed_second`, `team_id`, `player_id`, and `role` (`skater`
or `goalie`). Sort by that composite key; no duplicate keys. No rows represent
shootouts.

Check and family statuses are exactly `PASS`, `DISCREPANCY` or `UNAVAILABLE`.
A check passes only when all required inputs are available and the stated
relationship agrees. A family is DISCREPANCY when any check differs, otherwise
UNAVAILABLE when any required check cannot be evaluated, otherwise PASS. Keep
unavailable checks visible even inside a discrepant family. An empty checks list
cannot pass: emit an explicit unavailable check if no comparison can be made.
The report describes the source's data quality, so finding a real discrepancy
is successful reconciliation work, not permission to change the underlying data.

## Graph viewer and observable state

Provide a browser-accessible graph viewer with game selection, play/pause and
seeking to an integer game-elapsed second. Show both teams and the identified
players currently on the ice, distinguish skaters from goalies, label game time
and period, and make lineup changes visible as time advances. Use graph nodes
and relationships to show team-versus-team shift dynamics; a static chart or a
raw JSON dump alone does not satisfy this requirement. Graph layout and the
meaning of any additional edges/weights are your choice and must be explained.
The displayed on-ice player sets must agree with the on-ice table, including
empty-net and anomalous intervals; visibly identify unavailable data.

Expose `window.nhlViewer` on the viewer page with these callable methods:

- `await window.nhlViewer.seek(gameId, gameElapsedSecond)` selects the game,
  pauses playback, seeks to that second and resolves after the displayed state
  has updated. Accept every valid played second; reject invalid game IDs/times
  by rejecting the returned promise and showing an error; leave the rendered
  state and `getState()` result unchanged.
- `window.nhlViewer.getState()` returns a JSON-serializable object describing
  the state actually rendered: `game_id`, `game_elapsed_second`, `period`,
  `phase` (`REG`, `OT` or `SO`), `playing` (boolean), `teams` (two objects with
  `team_id`, `skater_ids`, `goalie_ids`) and `availability` (`AVAILABLE` or
  `UNAVAILABLE`, with a `reason` for the latter). Player ID arrays contain the
  displayed league IDs without duplicates. Include `reason` as a string (empty
  when available). Before selection, return `game_id`, `game_elapsed_second`,
  `period` and `phase` all null, `playing: false`, `teams: []`,
  `availability: "UNAVAILABLE"` and a nonempty `reason`. During shootouts,
  `game_id` is selected, `phase` is `SO`, `game_elapsed_second` and `period`
  are null, `teams` contains the selected teams with empty player arrays,
  `playing` reflects playback, and `availability` is `UNAVAILABLE` with a
  reason explaining that shootouts have no on-ice seconds. During REG/OT,
  game/time/period/phase are non-null; unavailable source coverage keeps those
  coordinates and the two teams but returns empty arrays and a nonempty reason.
  This hook must read the same state the graph renders, rather than calculating
  an independent answer only for evaluation.

Document how to open a shootout phase when present; no integer seek second
represents a shootout attempt. Playback must advance the displayed game clock
and player sets, and pause must stop that advance. Supply screenshots showing
at least a selected game and a changed lineup at a second time, with those game
IDs/times identified in the README. The first evaluation uses the data hook and
screenshots for human review. Automated browser grading may follow, using these
same public behaviors.
