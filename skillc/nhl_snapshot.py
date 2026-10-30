"""Private NHL source snapshots and declared-sample drift checks (#633).

No network on import. The caller explicitly chooses acquisition and supplies
the season date interval; real season acquisition is a declaration-time action.
Only raw bytes establish content identity. Missing evidence never means clean.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

SEASON = 20252026
SOURCE_IDS = ("boxscore", "play_by_play", "landing", "shifts")
HOSTS = frozenset({"api-web.nhle.com", "api.nhle.com"})
Fetch = Callable[[str], bytes]
Json = dict[str, Any]


class ReferenceError(ValueError):
    """Invalid or incomplete controller evidence; never a candidate failure."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def endpoint(source: str, identity: int | str) -> str:
    if source == "schedule":
        return f"https://api-web.nhle.com/v1/schedule/{identity}"
    if source == "shifts":
        return f"https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={identity}"
    if source not in SOURCE_IDS:
        raise ReferenceError(f"unknown NHL source: {source}")
    suffix = "play-by-play" if source == "play_by_play" else source
    return f"https://api-web.nhle.com/v1/gamecenter/{identity}/{suffix}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        raise ReferenceError("NHL fetch refused a redirect")


def fetch_public(url: str, *, timeout: float = 30, retries: int = 2,
                 max_bytes: int = 32 * 1024 * 1024) -> bytes:
    """Bounded, host-restricted transport. Inject a Fetch instead in tests."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ReferenceError("NHL fetch requires an approved HTTPS endpoint")
    if timeout <= 0 or retries < 0 or retries > 5 or max_bytes <= 0:
        raise ReferenceError("invalid NHL transport bounds")
    opener = urllib.request.build_opener(_NoRedirect())
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "skillc-nhl-reference/1"})
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ReferenceError("NHL response exceeds declared byte limit")
            return raw
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries:
                raise
            time.sleep(min(2 ** attempt, 4))
    raise AssertionError("unreachable transport loop")


def _json_object(raw: bytes) -> Json:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ReferenceError("source is not JSON") from exc
    if not isinstance(value, dict):
        raise ReferenceError("source is not a JSON object")
    return value


def completed_games(schedules: list[Json]) -> dict[int, Json]:
    """Strict enumeration: a missing/unrecognized schedule is not zero games."""
    games: dict[int, Json] = {}
    for schedule in schedules:
        if not isinstance(schedule.get("gameWeek"), list):
            raise ReferenceError("schedule gameWeek missing")
        for day in schedule["gameWeek"]:
            if not isinstance(day, dict) or not isinstance(day.get("games"), list):
                raise ReferenceError("schedule day/games missing")
            for game in day["games"]:
                if not isinstance(game, dict):
                    raise ReferenceError("malformed schedule game")
                if game.get("season") != SEASON or game.get("gameType") not in (2, 3):
                    continue
                if game.get("gameState") not in ("OFF", "FINAL"):
                    continue
                identity = game.get("id")
                if type(identity) is not int:
                    raise ReferenceError("completed game has no integer ID")
                old = games.get(identity)
                if old is not None and old != game:
                    raise ReferenceError(f"conflicting schedule records for game {identity}")
                games[identity] = game
    if not games:
        raise ReferenceError("empty completed-game population")
    return games


def acquire(root: Path, start: str, end: str, *, fetch: Fetch = fetch_public,
            now: Callable[[], str] = utc_now) -> Json:
    """Fetch once into a fresh private directory; never overwrite a reference.

    Fetching every seventh date covers schedule gameWeek windows. Every date
    in the declared interval must actually occur in a returned schedule day,
    including empty days. Incomplete coverage refuses to publish a manifest.
    The declaration, not this function, establishes that the interval covers
    the whole season. It is retained for an independent completeness review.
    """
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last:
        raise ReferenceError("reversed schedule interval")
    root.mkdir(parents=True, exist_ok=False)
    (root / "sources").mkdir()
    manifest: Json = {"schema_version": 1, "season_id": SEASON,
                      "retrieval_started_utc": now(), "retrieval_cutoff_utc": None,
                      "schedule_start": start, "schedule_end": end,
                      "sources": [], "games": []}

    def retain(source: str, identity: int | str) -> Json:
        url = endpoint(source, identity)
        entry: Json = {"source_id": source, "identity": identity, "endpoint": url,
                       "retrieved_at_utc": None, "payload_sha256": None,
                       "availability": "UNAVAILABLE", "path": None, "reason": ""}
        try:
            raw = fetch(url)
        except (OSError, ValueError) as exc:
            entry["reason"] = f"fetch failed: {type(exc).__name__}"
        else:
            entry["retrieved_at_utc"] = now()
            entry["payload_sha256"] = sha256(raw)
            entry["path"] = f"sources/{source}-{identity}.json"
            (root / entry["path"]).write_bytes(raw)
            try:
                _json_object(raw)
            except ReferenceError as exc:
                entry["reason"] = str(exc)
            else:
                entry["availability"] = "AVAILABLE"
        manifest["sources"].append(entry)
        return entry

    schedules: list[Json] = []
    covered: set[str] = set()
    date = first
    while date <= last:
        entry = retain("schedule", date.isoformat())
        if entry["availability"] != "AVAILABLE":
            raise ReferenceError("schedule unavailable; incomplete reference remains unpublished")
        schedule = _json_object((root / entry["path"]).read_bytes())
        schedules.append(schedule)
        if not isinstance(schedule.get("gameWeek"), list):
            raise ReferenceError("schedule gameWeek missing")
        for day in schedule["gameWeek"]:
            if isinstance(day, dict) and isinstance(day.get("date"), str):
                covered.add(day["date"])
        date += dt.timedelta(days=7)
    required = {(first + dt.timedelta(days=n)).isoformat()
                for n in range((last - first).days + 1)}
    if not required <= covered:
        raise ReferenceError("schedule date coverage incomplete")
    games = completed_games(schedules)
    for identity, game in sorted(games.items()):
        manifest["games"].append(game)
        for source in SOURCE_IDS:
            retain(source, identity)
    manifest["retrieval_cutoff_utc"] = now()
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load(root: Path) -> tuple[Json, dict[int | str, dict[str, tuple[Json, Json | None]]]]:
    """Verify source identities before interpreting any private payload."""
    manifest = _json_object((root / "manifest.json").read_bytes())
    if manifest.get("schema_version") != 1 or manifest.get("season_id") != SEASON:
        raise ReferenceError("unsupported NHL reference manifest")
    if not isinstance(manifest.get("games"), list) or not manifest["games"]:
        raise ReferenceError("empty reference game population")
    if not isinstance(manifest.get("sources"), list) or not manifest["sources"]:
        raise ReferenceError("empty reference source population")
    population: dict[int | str, dict[str, tuple[Json, Json | None]]] = {}
    for entry in manifest["sources"]:
        if not isinstance(entry, dict):
            raise ReferenceError("malformed source entry")
        identity, source = entry.get("identity"), entry.get("source_id")
        if source not in (*SOURCE_IDS, "schedule") or type(identity) not in (int, str):
            raise ReferenceError("invalid reference source identity")
        assert isinstance(identity, (int, str))
        if source == "schedule":
            if not isinstance(identity, str) or dt.date.fromisoformat(identity).isoformat() != identity:
                raise ReferenceError("invalid schedule date identity")
        elif type(identity) is not int:
            raise ReferenceError("game source identity must be an integer")
        if entry.get("endpoint") != endpoint(source, identity):
            raise ReferenceError("reference endpoint does not match source identity")
        bucket = population.setdefault(identity, {})
        if source in bucket:
            raise ReferenceError("duplicate reference source identity")
        data = None
        if entry.get("path") is not None:
            path = entry["path"]
            expected = f"sources/{source}-{identity}.json"
            if path != expected or (root / path).is_symlink():
                raise ReferenceError("reference source path escaped its identity")
            resolved = (root / path).resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ReferenceError("reference source path escapes root")
            raw = resolved.read_bytes()
            if sha256(raw) != entry.get("payload_sha256"):
                raise ReferenceError("reference checksum changed")
            if entry.get("availability") == "AVAILABLE":
                data = _json_object(raw)
        if entry.get("availability") not in ("AVAILABLE", "UNAVAILABLE"):
            raise ReferenceError("invalid source availability")
        if entry["availability"] == "AVAILABLE" and data is None:
            raise ReferenceError("available source has no payload")
        bucket[source] = (entry, data)
    schedule_data = [d for sources in population.values()
                     for s, (_, d) in sources.items() if s == "schedule" and d is not None]
    expected_games = completed_games(schedule_data)
    declared = [g.get("id") for g in manifest["games"] if isinstance(g, dict)]
    if len(declared) != len(set(declared)) or set(declared) != set(expected_games):
        raise ReferenceError("reference game population differs from schedules")
    for identity in expected_games:
        if set(population.get(identity, {})) != set(SOURCE_IDS):
            raise ReferenceError("reference game source population incomplete")
    return manifest, population


def recheck(root: Path, sample: list[int], *, fetch: Fetch = fetch_public) -> Json:
    """A declared sample only. Drift or failed re-fetch makes that game UNKNOWN.

    UNSAMPLED games remain UNKNOWN. This is a freshness observation, never
    evidence that any candidate is correct. A corrupt local reference refuses.
    """
    manifest, population = load(root)
    ids = {game["id"] for game in manifest["games"]}
    if not sample or len(sample) != len(set(sample)) or not set(sample) <= ids:
        raise ReferenceError("sample must name distinct existing reference games")
    result: Json = {"schema_version": 1, "sample": sample, "games": []}
    for identity in sorted(ids):
        checks: list[Json] = []
        if identity in sample:
            # Include each game's schedule source: scope/type/state may change
            # even when all detailed game endpoints still have the same bytes.
            entries = [entry for entry, _ in population[identity].values()]
            entries += [entry for sources in population.values()
                        for source, (entry, data) in sources.items()
                        if source == "schedule" and data is not None
                        and any(g.get("id") == identity for day in data["gameWeek"]
                                for g in day["games"])]
            for entry in entries:
                check: Json = {"source_id": entry["source_id"], "endpoint": entry["endpoint"],
                               "expected_sha256": entry["payload_sha256"],
                               "observed_sha256": None, "status": "UNKNOWN", "reason": ""}
                try:
                    raw = fetch(entry["endpoint"])
                except (OSError, ValueError) as exc:
                    check["reason"] = f"re-fetch failed: {type(exc).__name__}"
                else:
                    check["observed_sha256"] = sha256(raw)
                    if (entry["availability"] == "AVAILABLE"
                            and check["observed_sha256"] == entry["payload_sha256"]):
                        check["status"] = "UNCHANGED"
                    else:
                        check["reason"] = "source changed or reference unavailable"
                checks.append(check)
        status = "UNCHANGED" if checks and all(c["status"] == "UNCHANGED" for c in checks) else "UNKNOWN"
        result["games"].append({"game_id": identity, "status": status, "checks": checks,
                                "reason": "" if checks else "not in declared live sample"})
    return result
