"""Trusted synthetic candidate controls; never used as delivered project code."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from oracle import nhl_oracle, nhl_snapshot


def strict(value):
    if isinstance(value, dict):
        if 'skillc_added_field' in value:
            raise ValueError('unknown JSON field')
        for child in value.values():
            strict(child)
    elif isinstance(value, list):
        for child in value:
            strict(child)


def drop(value):
    if isinstance(value, dict):
        return {k: drop(v) for k, v in value.items() if k != 'skillc_added_field'}
    if isinstance(value, list):
        return [drop(v) for v in value]
    return value


def main():
    mode = os.environ.get('CONTROL_MODE', 'reference')
    base = os.environ['NHL_API_BASE']
    out = Path('exports')
    out.mkdir()
    db = sqlite3.connect('sources.sqlite')
    db.execute('CREATE TABLE sources (endpoint TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    routes = []

    def retrieve(path):
        with urllib.request.urlopen(base + path, timeout=5) as stream:
            payload = json.load(stream)
        if mode == 'strict':
            strict(payload)
        if mode == 'drop-fields':
            payload = drop(payload)
        name = f'payload-{len(routes)}.json'
        routes.append((path, name))
        db.execute('INSERT INTO sources VALUES (?, ?)', (path, json.dumps(payload)))
        return payload

    schedule = retrieve('/v1/schedule/2025-10-07')
    games = nhl_snapshot.completed_games([schedule])
    results = []
    for identity, game in sorted(games.items()):
        sources = {}
        for source in nhl_snapshot.SOURCE_IDS:
            url = nhl_snapshot.endpoint(source, identity)
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            path = parsed.path + ('?' + parsed.query if parsed.query else '')
            payload = retrieve(path)
            sources[source] = ({'source_id': source, 'endpoint': url, 'availability': 'AVAILABLE',
                                'retrieved_at_utc': '2026-10-30T00:00:00Z',
                                'payload_sha256': nhl_snapshot.sha256(json.dumps(payload).encode()),
                                'reason': ''}, payload)
        report = nhl_oracle.GameOracle(game, sources).reconcile()
        if mode == 'never-discrepancy':
            for family in report['families']:
                family['status'] = 'PASS'
                for check in family['checks']:
                    check['status'] = 'PASS'
        results.append(report)
    db.commit()
    for path, name in routes:
        payload = db.execute('SELECT payload FROM sources WHERE endpoint=?', (path,)).fetchone()[0]
        (out / name).write_text(payload)
    (out / 'reconciliation.json').write_text(json.dumps({'schema_version': 1, 'games': results}))
    db.close()


if __name__ == '__main__':
    main()
