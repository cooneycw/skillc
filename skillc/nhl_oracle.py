"""Independent NHL source reconciliation under evals/nhl-season/goal.md.

This is controller code, never imported from a delivered project. Unknown or
missing source fields produce unavailable checks, not invented zeroes. It
retains raw values and source pointers; source anomalies are never repaired.
"""

from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Iterator
from typing import Any

from .nhl_snapshot import Json, ReferenceError

FAMILIES = tuple(f"F{n}" for n in range(1, 9))
SCOPE_KEYS = ("team_id", "player_id", "event_id", "period", "game_elapsed_second")


def integer(value: Any) -> int | None:
    if type(value) is int:
        return value
    return None


def seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isascii() and p.isdecimal() for p in parts):
        return None
    minutes, secs = map(int, parts)
    return minutes * 60 + secs if secs < 60 else None


def _object(value: Any) -> Json:
    return value if isinstance(value, dict) else {}


def _sum(values: list[int | None]) -> int | None:
    return sum(v for v in values if v is not None) if all(v is not None for v in values) else None


def _unique(records: Any, key: str) -> tuple[list[Json] | None, bool]:
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        return None, False
    seen: dict[Any, Json] = {}
    conflict = False
    for record in records:
        identity = record.get(key)
        if type(identity) is not int:
            return None, False
        if identity in seen and seen[identity] != record:
            conflict = True
        else:
            seen[identity] = record
    return list(seen.values()), conflict


class GameOracle:
    """Derive one game at a time; on-ice export expands only while streaming."""

    def __init__(self, game: Json, sources: dict[str, tuple[Json, Json | None]]) -> None:
        self.game = game
        self.identity = game["id"]
        self.sources = sources
        self.box = sources["boxscore"][1] or {}
        self.pbp = sources["play_by_play"][1] or {}
        self.landing = sources["landing"][1] or {}
        self.shifts = sources["shifts"][1] or {}
        try:
            self.teams = (game["awayTeam"]["id"], game["homeTeam"]["id"])
        except (KeyError, TypeError) as exc:
            raise ReferenceError("schedule team identities missing") from exc
        if any(type(t) is not int for t in self.teams) or self.teams[0] == self.teams[1]:
            raise ReferenceError("invalid schedule team identities")
        self.anomalies: list[Json] = []
        self.checks: dict[str, list[Json]] = {f: [] for f in FAMILIES}
        self.players: dict[tuple[int, int], Json] = {}
        self.box_rosters: dict[int, set[int] | None] = {}
        self.pbp_rosters: dict[int, set[int] | None] = {}
        self.box_roles: dict[tuple[int, int], str] = {}
        self.roles: dict[tuple[int, int], str] = {}
        self._read_players()
        self.plays, self.play_conflict = _unique(self.pbp.get("plays"), "eventId")
        self.records, self.shift_conflict = _unique(self.shifts.get("data"), "id")
        total = integer(self.shifts.get("total"))
        raw_rows = self.shifts.get("data")
        if total is not None and isinstance(raw_rows, list) and total != len(raw_rows):
            self.shift_conflict = True
            self.anomaly("incomplete-shift-source", "chart total differs from returned record count", ("shifts",))
        self.periods = self._periods()
        self.intervals: list[tuple[int, int, int, int, str]] = []
        self.shift_players: set[tuple[int, int]] = set()
        self.raw_shift_durations: dict[tuple[int, int], list[int | None]] = {}
        self.shift_counts: Counter[tuple[int, int]] = Counter()
        self.on_ice_available = bool(self.periods) and self.records is not None and not self.shift_conflict
        self._read_shifts()
        self._times: list[int] = []
        self._lineups: list[dict[tuple[int, int], str]] = []
        self._build_lineups()

    def refs(self, *names: str, pointer: str = "") -> list[Json]:
        return [{k: v for k, v in self.sources[name][0].items()
                 if k in ("source_id", "endpoint", "retrieved_at_utc", "payload_sha256",
                          "availability", "reason")} | {"record_pointer": pointer}
                for name in names]

    def anomaly(self, code: str, reason: str, names: tuple[str, ...], *,
                pointer: str = "", **scope: Any) -> None:
        self.anomalies.append({"code": code, "reason": reason,
                               "scope": {k: scope.get(k) for k in SCOPE_KEYS},
                               "sources": self.refs(*names, pointer=pointer)})

    def event_pointer(self, event: Json) -> str:
        rows = self.pbp.get("plays", [])
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                if isinstance(row, dict) and row.get("eventId") == event.get("eventId"):
                    return f"/plays/{index}"
        return ""

    def emit(self, family: str, comparison: str, summary: Any, detail: Any, unit: str,
             names: tuple[str, ...], *, reason: str = "", agrees: bool | None = None,
             **scope: Any) -> None:
        status = "UNAVAILABLE" if summary is None or detail is None else (
            "PASS" if (summary == detail if agrees is None else agrees) else "DISCREPANCY")
        if status != "PASS" and not reason:
            reason = "required input unavailable" if status == "UNAVAILABLE" else "source values differ"
        keys = {k: scope.get(k) for k in SCOPE_KEYS}
        check_id = "/".join([family, comparison,
                             *("null" if keys[k] is None else str(keys[k]) for k in SCOPE_KEYS)])
        self.checks[family].append({"check_id": check_id, "comparison": comparison,
                                    "scope": keys, "summary_value": summary,
                                    "detail_value": detail, "status": status, "unit": unit,
                                    "sources": self.refs(*names), "reason": reason})

    def _read_players(self) -> None:
        stats = self.box.get("playerByGameStats", {})
        for side, team in zip(("awayTeam", "homeTeam"), self.teams, strict=True):
            groups = stats.get(side) if isinstance(stats, dict) else None
            valid = isinstance(groups, dict)
            roster: set[int] = set()
            if isinstance(groups, dict):
                for group in ("forwards", "defense", "goalies"):
                    rows = groups.get(group)
                    if not isinstance(rows, list):
                        valid = False
                        continue
                    for row in rows:
                        if not isinstance(row, dict) or type(row.get("playerId")) is not int:
                            valid = False
                            continue
                        player = row["playerId"]
                        key = (team, player)
                        if key in self.players and self.players[key] != row:
                            valid = False
                            self.anomaly("conflicting-player", "conflicting boxscore player", ("boxscore",),
                                         team_id=team, player_id=player)
                        self.players[key] = row
                        self.roles[key] = "goalie" if group == "goalies" else "skater"
                        self.box_roles[key] = self.roles[key]
                        roster.add(player)
            self.box_rosters[team] = roster if valid else None
        roster_rows, conflict = _unique(self.pbp.get("rosterSpots"), "playerId")
        for team in self.teams:
            self.pbp_rosters[team] = ({r["playerId"] for r in roster_rows if r.get("teamId") == team}
                                      if roster_rows is not None and not conflict else None)
        if roster_rows is not None:
            for row in roster_rows:
                key = (row.get("teamId"), row["playerId"])
                role = "goalie" if row.get("positionCode") == "G" else (
                    "skater" if row.get("positionCode") in ("C", "L", "R", "D", "LW", "RW") else None)
                if key[0] not in self.teams or role is None:
                    continue
                if key in self.roles and self.roles[key] != role:
                    self.roles.pop(key)
                    self.anomaly("conflicting-role", "boxscore and play roster roles differ",
                                 ("boxscore", "play_by_play"), team_id=key[0], player_id=key[1])
                else:
                    self.roles[key] = role

    def _periods(self) -> dict[int, tuple[int, int]]:
        descriptor = self.pbp.get("periodDescriptor", self.box.get("periodDescriptor", {}))
        last = integer(descriptor.get("number")) if isinstance(descriptor, dict) else None
        if last is None or last < 3 or not isinstance(descriptor, dict):
            return {}
        phase = descriptor.get("periodType")
        if phase not in ("REG", "OT", "SO") or (last == 3 and phase != "REG"):
            return {}
        if phase == "SO":
            last = 4
        if last > 3 and self.game.get("gameType") == 2 and last != 4:
            return {}
        periods = {p: ((p - 1) * 1200, 1200) for p in range(1, min(last, 3) + 1)}
        for p in range(4, last + 1):
            length = 300 if self.game["gameType"] == 2 else 1200
            duration: int | None = length if p < last or phase == "SO" else None
            if duration is None and self.plays is not None:
                # An ended OT terminates at its winning goal, not at the last
                # recorded stoppage or a guessed five/twenty-minute maximum.
                endings = [seconds(e.get("timeInPeriod")) for e in self.plays
                           if _object(e.get("periodDescriptor")).get("number") == p
                           and e.get("typeDescKey") == "goal"
                           and _object(e.get("periodDescriptor")).get("periodType") == "OT"]
                if len(endings) == 1:
                    duration = endings[0]
            if duration is None or not 0 < duration <= length:
                return {}
            periods[p] = (3600 + (p - 4) * length, duration)
        return periods

    def event_second(self, event: Json) -> int | None:
        desc = _object(event.get("periodDescriptor"))
        if desc.get("periodType") == "SO":
            return None
        period = desc.get("number")
        elapsed = seconds(event.get("timeInPeriod"))
        if period not in self.periods or elapsed is None:
            return None
        start, length = self.periods[period]
        return start + min(elapsed, length - 1) if length > 0 and elapsed <= length else None

    def _read_shifts(self) -> None:
        for record in self.records or []:
            if (_object(self.pbp.get("periodDescriptor")).get("periodType") == "SO"
                    and record.get("period", 0) >= 5):
                continue
            if record.get("typeCode") != 517:
                if record.get("typeCode") != 505:
                    self.on_ice_available = False
                    self.shift_conflict = True
                    self.anomaly("unknown-chart-record", "unrecognized chart record type", ("shifts",))
                continue
            team, player, period = (record.get(k) for k in ("teamId", "playerId", "period"))
            if type(team) is not int or type(player) is not int or type(period) is not int:
                self.on_ice_available = False
                self.anomaly("shift-identity", "shift has missing integer identity", ("shifts",))
                continue
            key = (team, player)
            self.shift_players.add(key)
            self.shift_counts[key] += 1
            duration = seconds(record.get("duration"))
            self.raw_shift_durations.setdefault(key, []).append(duration)
            start, end = seconds(record.get("startTime")), seconds(record.get("endTime"))
            role = self.roles.get(key)
            valid = (period in self.periods and start is not None and end is not None
                     and 0 <= start <= end <= self.periods[period][1])
            if not valid or role is None or team not in self.teams:
                self.on_ice_available = False
                self.anomaly("shift-unavailable", "invalid shift interval or unknown team/player role",
                             ("shifts", "boxscore", "play_by_play"), team_id=team,
                             player_id=player, period=period)
                continue
            assert start is not None and end is not None
            if duration != end - start:
                self.anomaly("shift-duration", "duration differs from end minus start", ("shifts",),
                             team_id=team, player_id=player, period=period)
            offset = self.periods[period][0]
            if start < end:
                self.intervals.append((offset + start, offset + end, team, player, role))

    def _build_lineups(self) -> None:
        changes: dict[int, list[tuple[int, int, str, int]]] = {}
        for start, end, team, player, role in self.intervals:
            changes.setdefault(start, []).append((team, player, role, 1))
            changes.setdefault(end, []).append((team, player, role, -1))
        active: Counter[tuple[int, int, str]] = Counter()
        for second in sorted(changes):
            for team, player, role, delta in changes[second]:
                active[(team, player, role)] += delta
            lineup = {(team, player): role for (team, player, role), count in active.items() if count > 0}
            self._times.append(second)
            self._lineups.append(lineup)
            identities = Counter(player for _, player in lineup)
            for player, count in identities.items():
                if count > 1:
                    self.anomaly("player-two-teams", "player appears on both teams at once", ("shifts",),
                                 player_id=player, game_elapsed_second=second)
            for (team, player, _), count in active.items():
                if count > 1:
                    self.anomaly("overlapping-shifts", "player has overlapping shift records",
                                 ("shifts",), team_id=team, player_id=player,
                                 game_elapsed_second=second)

    def lineup(self, second: int) -> dict[tuple[int, int], str]:
        index = bisect.bisect_right(self._times, second) - 1
        return self._lineups[index] if index >= 0 else {}

    def on_ice(self) -> Iterator[Json]:
        for period, (start, duration) in sorted(self.periods.items()):
            for second in range(start, start + duration):
                lineup = self.lineup(second)
                for (team, player), role in sorted(lineup.items()):
                    yield {"game_id": self.identity, "game_elapsed_second": second,
                           "team_id": team, "player_id": player, "role": role}

    def counts(self, second: int) -> Json:
        lineup = self.lineup(second)
        return {f"{side}_{kind}": sum(t == team and r == role for (t, _), r in lineup.items())
                for side, team in zip(("away", "home"), self.teams, strict=True)
                for kind, role in (("goalies", "goalie"), ("skaters", "skater"))}

    def on_ice_counts(self) -> Iterator[Json]:
        """Retain observed goalie/skater presence, including legitimate empties."""
        for start, duration in self.periods.values():
            for second in range(start, start + duration):
                counts = self.counts(second)
                for side, team in zip(("away", "home"), self.teams, strict=True):
                    yield {"game_id": self.identity, "game_elapsed_second": second, "team_id": team,
                           "skater_count": counts[f"{side}_skaters"], "goalie_count": counts[f"{side}_goalies"]}

    def _events(self, kind: str) -> list[Json] | None:
        if self.plays is None or self.play_conflict:
            return None
        return [e for e in self.plays if e.get("typeDescKey") == kind
                and _object(e.get("periodDescriptor")).get("periodType") != "SO"]

    def _f4_events(self, kind: str) -> list[Json] | None:
        events = self._events(kind)
        if events is None or kind != "blocked-shot":
            return events
        # Boxscore blockedShots excludes teammate blocks. Keep the original
        # play population intact for F7 and retained-source inspection.
        return [e for e in events if _object(e.get("details")).get("reason") != "teammate-blocked"]

    def actor_team(self, event: Json, kind: str) -> int | None:
        owner = _object(event.get("details")).get("eventOwnerTeamId")
        if owner not in self.teams:
            return None
        if kind == "blocked-shot":
            return self.teams[1] if owner == self.teams[0] else self.teams[0]
        return owner

    def _team_summary(self, team: int, field: str) -> int | None:
        side = "awayTeam" if team == self.teams[0] else "homeTeam"
        data = self.box.get(side, {})
        return integer(data.get(field)) if isinstance(data, dict) else None

    def _player_sum(self, team: int, field: str, role: str | None) -> int | None:
        if self.box_rosters[team] is None:
            return None
        rows = [p for key, p in self.players.items()
                if key[0] == team and (role is None or self.box_roles.get(key) == role)]
        values = []
        for row in rows:
            value = integer(row.get(field))
            if field == "shotsAgainst" and value is None:
                text = row.get("saveShotsAgainst")
                if isinstance(text, str) and "/" in text and text.split("/")[-1].isdigit():
                    value = int(text.split("/")[-1])
            values.append(value)
        return _sum(values)

    def reconcile(self) -> Json:
        if any(self.checks.values()):
            raise ReferenceError("oracle instance already derived")
        goals, shots = self._events("goal"), self._events("shot-on-goal")
        decision = self.box.get("gameOutcome", self.landing.get("gameOutcome", {}))
        last_type = decision.get("lastPeriodType") if isinstance(decision, dict) else None
        shootout = last_type == "SO"
        for team in self.teams:
            opposite = next(t for t in self.teams if t != team)
            count = (None if goals is None or any(_object(e.get("details")).get("eventOwnerTeamId") not in self.teams for e in goals)
                     else sum(_object(e.get("details")).get("eventOwnerTeamId") == team for e in goals))
            final = self._team_summary(team, "score")
            other_score = self._team_summary(opposite, "score")
            score_detail = count
            if last_type not in ("REG", "OT", "SO"):
                score_detail = None
            elif shootout:
                score_detail = (count + int(final > other_score)
                                if count is not None and final is not None and other_score is not None
                                and final != other_score else None)
            self.emit("F1", "team_score", final, score_detail, "goals", ("boxscore", "play_by_play"), team_id=team)
            self.emit("F1", "skater_goals_sum", self._player_sum(team, "goals", "skater"), count,
                      "goals", ("boxscore", "play_by_play"), team_id=team)
            attempts = None if goals is None or shots is None else goals + shots
            owned = (None if attempts is None or any(_object(e.get("details")).get("eventOwnerTeamId") not in self.teams for e in attempts)
                     else [e for e in attempts if _object(e.get("details")).get("eventOwnerTeamId") == team])
            shot_count = len(owned) if owned is not None else None
            for comparison, summary in (("team_sog", self._team_summary(team, "sog")),
                                        ("skater_sog_sum", self._player_sum(team, "sog", "skater"))):
                self.emit("F2", comparison, summary, shot_count, "shots", ("boxscore", "play_by_play"), team_id=team)
            goalie_count: int | None = 0 if owned is not None else None
            for event in owned or []:
                details = _object(event.get("details"))
                code = str(event.get("situationCode", ""))
                present = (True if type(details.get("goalieInNetId")) is int else
                           (code[3 if opposite == self.teams[1] else 0] == "1"
                            if len(code) == 4 and code.isascii() and code.isdigit()
                            and code[0] in "01" and code[3] in "01" else None))
                if present is None:
                    goalie_count = None
                elif goalie_count is not None:
                    goalie_count += int(present)
            self.emit("F2", "opposing_goalie_shots_against", self._player_sum(opposite, "shotsAgainst", "goalie"),
                      goalie_count, "shots", ("boxscore", "play_by_play"), team_id=team)
            penalties = self._events("penalty")
            minutes: list[int | None] = []
            for event in penalties or []:
                details = _object(event.get("details"))
                if details.get("eventOwnerTeamId") not in self.teams:
                    minutes.append(None)
                    continue
                if details.get("eventOwnerTeamId") != team:
                    continue
                duration = integer(details.get("duration"))
                if duration is None:
                    self.anomaly("penalty-duration", "assessed penalty duration is unreadable",
                                 ("play_by_play",), pointer=self.event_pointer(event),
                                 team_id=team, event_id=event["eventId"])
                if type(details.get("committedByPlayerId")) is not int:
                    if details.get("descKey") not in ("bench-minor", "bench", "too-many-men-on-the-ice"):
                        minutes.append(None)
                        self.anomaly("penalty-attribution", "penalty player/bench attribution unavailable", ("play_by_play",),
                                     team_id=team, event_id=event["eventId"])
                        continue
                    self.anomaly("bench-penalty", f"team-only assessed minutes: {duration}",
                                 ("play_by_play",), team_id=team, event_id=event["eventId"])
                    continue
                minutes.append(duration)
            self.emit("F3", "player_pim_sum", self._player_sum(team, "pim", None),
                      _sum(minutes) if penalties is not None else None, "minutes", ("boxscore", "play_by_play"), team_id=team)
        event_fields = {"hits": ("hit", "hittingPlayerId"), "blocked_shots": ("blocked-shot", "blockingPlayerId"),
                        "giveaways": ("giveaway", "playerId"), "takeaways": ("takeaway", "playerId")}
        for kind, actor in event_fields.values():
            for event in self._f4_events(kind) or []:
                if type(_object(event.get("details")).get(actor)) is not int:
                    self.anomaly("event-attribution", f"{kind}: unreadable {actor}",
                                 ("play_by_play",), pointer=self.event_pointer(event),
                                 team_id=self.actor_team(event, kind), event_id=event["eventId"])
        for (team, player), row in sorted(self.players.items()):
            role = self.box_roles.get((team, player))
            if role == "skater":
                for comparison, (kind, actor) in event_fields.items():
                    events = self._f4_events(kind)
                    detail = (sum(_object(e.get("details")).get(actor) == player for e in events)
                              if events is not None and all(type(_object(e.get("details")).get(actor)) is int
                                  or self.actor_team(e, kind) not in (None, team) for e in events) else None)
                    field = "blockedShots" if comparison == "blocked_shots" else comparison
                    self.emit("F4", comparison, integer(row.get(field)), detail, "events",
                              ("boxscore", "play_by_play"), team_id=team, player_id=player)
            duration = (_sum(self.raw_shift_durations.get((team, player), []))
                        if self.records is not None and not self.shift_conflict else None)
            self.emit("F5", "toi_seconds", seconds(row.get("toi")), duration, "seconds",
                      ("boxscore", "shifts"), team_id=team, player_id=player)
            if role == "skater":
                self.emit("F5", "shift_count", integer(row.get("shifts")),
                          self.shift_counts[(team, player)] if self.records is not None and not self.shift_conflict else None,
                          "shifts", ("boxscore", "shifts"), team_id=team, player_id=player)
        goal_rows: list[Json] | None = [] if self.records is not None and not self.shift_conflict else None
        for record in self.records or []:
            if record.get("typeCode") != 505:
                continue
            if (_object(self.pbp.get("periodDescriptor")).get("periodType") == "SO"
                    and record.get("period", 0) >= 5):
                continue
            elapsed = seconds(record.get("startTime"))
            if elapsed is None or type(record.get("period")) is not int or record.get("teamId") not in self.teams:
                goal_rows = None
                break
            if goal_rows is not None:
                goal_rows.append({"team_id": record["teamId"], "period": record["period"], "period_elapsed_second": elapsed})
        # Absence of recognizable goal records is not proof of zero goals.
        if not goal_rows:
            goal_rows = None
        play_goals: list[Json] | None = [] if goals is not None else None
        for event in goals or []:
            elapsed = seconds(event.get("timeInPeriod"))
            team = _object(event.get("details")).get("eventOwnerTeamId")
            period = _object(event.get("periodDescriptor")).get("number")
            if elapsed is None or team not in self.teams or type(period) is not int:
                play_goals = None
                break
            if play_goals is not None:
                play_goals.append({"team_id": team, "period": period, "period_elapsed_second": elapsed})
        sort_goals = lambda rows: sorted(rows, key=lambda r: (r["team_id"], r["period"], r["period_elapsed_second"])) if rows is not None else None
        self.emit("F6", "goal_records", sort_goals(goal_rows), sort_goals(play_goals), "goal_records", ("shifts", "play_by_play"))
        events = None if self.plays is None or self.play_conflict else self.plays
        for event in events or []:
            if _object(event.get("periodDescriptor")).get("periodType") == "SO":
                continue
            code = str(event.get("situationCode", ""))
            strength_summary = (dict(zip(("away_goalies", "away_skaters", "home_skaters", "home_goalies"), map(int, code), strict=True))
                       if len(code) == 4 and code.isascii() and code.isdigit() and code[0] in "01" and code[3] in "01" else None)
            second = self.event_second(event)
            strength_detail = self.counts(second) if second is not None and self.on_ice_available else None
            self.emit("F7", "strength_counts", strength_summary, strength_detail, "players", ("play_by_play", "shifts"),
                      event_id=event["eventId"], period=_object(event.get("periodDescriptor")).get("number"), game_elapsed_second=second)
        if not events:
            self.emit("F7", "strength_counts", None, None, "players", ("play_by_play", "shifts"))
        for team in self.teams:
            box_ids, play_ids = self.box_rosters[team], self.pbp_rosters[team]
            self.emit("F8", "roster_sets", sorted(box_ids) if box_ids is not None else None,
                      sorted(play_ids) if play_ids is not None else None, "player_ids", ("boxscore", "play_by_play"), team_id=team)
        for team, player in sorted(self.shift_players):
            for comparison, rosters, source in (("shift_roster_boxscore", self.box_rosters, "boxscore"),
                                                ("shift_roster_play_by_play", self.pbp_rosters, "play_by_play")):
                ids = rosters.get(team)
                self.emit("F8", comparison, player in ids if ids is not None else None, True,
                          "boolean", (source, "shifts"), team_id=team, player_id=player)
        for (team, player), row in sorted(self.players.items()):
            toi = seconds(row.get("toi"))
            positive = toi > 0 if toi is not None else None
            has_shift = (team, player) in self.shift_players if self.records is not None and not self.shift_conflict else None
            self.emit("F8", "participation", positive, has_shift, "boolean", ("boxscore", "shifts"),
                      agrees=not positive or bool(has_shift), reason="only positive TOI without shifts violates participation",
                      team_id=team, player_id=player)
        for family in FAMILIES:
            if not self.checks[family]:
                fallbacks = {"F1": [("team_score", "goals")], "F2": [("team_sog", "shots")],
                             "F3": [("player_pim_sum", "minutes")],
                             "F4": [(c, "events") for c in event_fields],
                             "F5": [("toi_seconds", "seconds"), ("shift_count", "shifts")],
                             "F6": [("goal_records", "goal_records")],
                             "F7": [("strength_counts", "players")], "F8": [("roster_sets", "player_ids")]}
                for comparison, unit in fallbacks[family]:
                    self.emit(family, comparison, None, None, unit, tuple(self.sources))
        if self.play_conflict or self.shift_conflict:
            self.anomaly("conflicting-record", "conflicting repeated event/shift identity", ("play_by_play", "shifts"))
        for second in range(max((s + n for s, n in self.periods.values()), default=0)):
            counts = self.counts(second)
            for side, team in zip(("away", "home"), self.teams, strict=True):
                goalie, skater = counts[f"{side}_goalies"], counts[f"{side}_skaters"]
                if goalie > 1 or skater + goalie > 6 or skater == 0:
                    self.anomaly("on-ice-count", f"observed skaters={skater}, goalies={goalie}", ("shifts",),
                                 team_id=team, game_elapsed_second=second)
        return {"game_id": self.identity,
                "families": [{"family_id": family, "checks": self.checks[family],
                              "status": family_status(self.checks[family])} for family in FAMILIES],
                "anomalies": self.anomalies}


def family_status(checks: list[Json]) -> str:
    states = {c["status"] for c in checks}
    return ("DISCREPANCY" if "DISCREPANCY" in states else
            "UNAVAILABLE" if "UNAVAILABLE" in states or not states else "PASS")


def compare(expected: Json, candidate: Json, *, fresh: bool) -> Json:
    """Compare observations, not prose. Source drift vetoes every game verdict."""
    if not fresh:
        return {"game_id": expected["game_id"], "status": "UNKNOWN", "reason": "live source not confirmed unchanged"}
    failures: list[str] = []
    unavailable: list[str] = []
    try:
        families = candidate["families"]
        if candidate["game_id"] != expected["game_id"] or not isinstance(families, list):
            raise ValueError("invalid candidate game")
        by_family = {f["family_id"]: f for f in families}
        if len(by_family) != len(families) or set(by_family) != set(FAMILIES):
            raise ValueError("candidate family population mismatch")
        for family in expected["families"]:
            actual = by_family[family["family_id"]]
            checks = actual["checks"]
            by_id = {c["check_id"]: c for c in checks}
            required = {c["check_id"] for c in family["checks"]}
            if not checks or len(by_id) != len(checks) or set(by_id) != required:
                failures.append(f"{family['family_id']}: check population mismatch")
                continue
            if actual["status"] != family_status(checks):
                failures.append(f"{family['family_id']}: dishonest family status")
            for wanted in family["checks"]:
                if wanted["status"] == "UNAVAILABLE":
                    unavailable.append(wanted["check_id"])
                observed = by_id[wanted["check_id"]]
                keys = ("comparison", "scope", "summary_value", "detail_value", "unit", "status")
                # JSON booleans and integers must not compare equal (True == 1).
                import json
                if any(json.dumps(observed.get(k), sort_keys=True) != json.dumps(wanted[k], sort_keys=True) for k in keys):
                    failures.append(wanted["check_id"])
    except (KeyError, TypeError, ValueError, AttributeError):
        failures.append("malformed candidate reconciliation")
    return {"game_id": expected["game_id"], "status": "FAIL" if failures else "PASS",
            "failures": failures, "unavailable_reference_checks": unavailable}


def census(reports: list[Json]) -> Json:
    if not reports or len({r["game_id"] for r in reports}) != len(reports):
        raise ReferenceError("empty or duplicate census population")
    result = {}
    for report in reports:
        ids = [f.get("family_id") for f in report.get("families", [])]
        if len(ids) != len(FAMILIES) or set(ids) != set(FAMILIES):
            raise ReferenceError("incomplete or duplicate family census")
    for family in FAMILIES:
        statuses = Counter(f["status"] for r in reports for f in r["families"] if f["family_id"] == family)
        if sum(statuses.values()) != len(reports):
            raise ReferenceError("incomplete family census")
        result[family] = {s: statuses[s] for s in ("PASS", "DISCREPANCY", "UNAVAILABLE")}
        result[family]["planted_cases_required"] = statuses["DISCREPANCY"] == 0
    return {"game_count": len(reports), "families": result}


def compare_on_ice(oracle: GameOracle, candidate: Iterator[Json], *, fresh: bool) -> Json:
    """Stream exact membership and order, so missing/duplicate/extra rows fail."""
    if not fresh or not oracle.on_ice_available:
        return {"game_id": oracle.identity, "status": "UNKNOWN", "reason": "source drift or unavailable reconstruction"}
    import json
    from itertools import zip_longest
    sentinel = object()
    keys = ("game_id", "game_elapsed_second", "team_id", "player_id", "role")
    for index, (expected, observed) in enumerate(zip_longest(oracle.on_ice(), candidate, fillvalue=sentinel)):
        if expected is sentinel or not isinstance(observed, dict):
            return {"game_id": oracle.identity, "status": "FAIL", "row": index, "reason": "row population/shape mismatch"}
        assert isinstance(expected, dict)
        if any(json.dumps(observed.get(k)) != json.dumps(expected[k]) for k in keys):
            return {"game_id": oracle.identity, "status": "FAIL", "row": index, "reason": "on-ice row differs"}
    return {"game_id": oracle.identity, "status": "PASS", "reason": ""}
