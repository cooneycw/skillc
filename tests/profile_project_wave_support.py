"""Offline pinned source assembly for #625's combined-profile proof only."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from skillc import profile

ROOT = Path(__file__).resolve().parents[1]
PIN = '87ecb0970f70aace9e0323feee00c9ca57dda133'
DECL = ROOT / 'evals/subjects/cpp-codex-project-wave-auto-87ecb097'
BASE = ROOT / 'tests/fixtures/profile-cpp-codex-flow-auto-87ecb097'
EXTRA = ROOT / 'tests/fixtures/profile-project-wave-auto-87ecb097-extra'


class Source(profile.Tree):
    """Existing immutable public snapshot plus ten pinned missing source files."""
    kind = 'git'
    revision = PIN

    def __init__(self) -> None:
        rows: list[dict[str, Any]] = [{'source': p, 'mode': mode, 'bytes': int(size), 'sha256': digest}
                for p, mode, size, digest in re.findall(
                    r"^\| `([^`]+)` \| (100644|100755) \| (\d+) \| ([0-9a-f]{64}) \|$",
                    (BASE / 'README.md').read_text(), re.MULTILINE)]
        assert len(rows) == 388 and rows[3]['source'] == 'LICENSE'
        rows[3]['reason'] = 'preserve upstream licence notice; existing skillc553'
        # The existing snapshot's committed manifest has this exact meaning.
        assert hashlib.sha256((json.dumps(rows, indent=2) + '\n').encode()).hexdigest() == (
            'a12dce75f62cd1784ff0d426ec1ecdeb9d790cc98f60b22e9c670986a7a44f1c')
        actual = {p.relative_to(BASE).as_posix() for p in BASE.rglob('*') if p.is_file()}
        assert actual == {r['source'] for r in rows} | {'README.md'}
        for row in rows:
            path = BASE / row['source']
            assert not path.is_symlink() and len(path.read_bytes()) == row['bytes']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
            assert ('100755' if path.stat().st_mode & 0o111 else '100644') == row['mode']
        self.base = profile.DirTree(BASE)
        self.extra = profile.DirTree(EXTRA)
        provenance = (EXTRA / 'provenance.json').read_bytes()
        assert hashlib.sha256(provenance).hexdigest() == '26e28e000a115c19f8cec7180a8fe691c314cc93159a59f1f286d54bf854f220'
        manifest = json.loads(provenance)
        assert manifest['commit'] == PIN and manifest['repository'] == 'cooneycw/claude-power-pack'
        self.added = {r['path']: r['mode'] for r in manifest['files']}
        assert len(self.added) == 10
        assert set(self.extra.files()) == set(self.added) | {'provenance.json'}
        for row in manifest['files']:
            data = self.extra.read(row['path'])
            assert hashlib.sha256(data).hexdigest() == row['sha256']
            assert profile.git_blob_id(data) == row['git_blob']
            assert self.extra.files()[row['path']] == row['mode']
            if row['path'] in self.base.files():
                assert data == self.base.read(row['path'])
        self.links = self.base.links | self.extra.links

    def files(self) -> dict[str, str]:
        return {**self.base.files(), **self.added}

    def read(self, path: str) -> bytes:
        return (self.extra if path in self.added else self.base).read(path)


def inventory() -> tuple[dict[str, Any], Source]:
    tree = Source()
    return profile.validate(profile.Profile.load(DECL / 'profile.json'), tree), tree
