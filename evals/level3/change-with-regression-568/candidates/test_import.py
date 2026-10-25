"""Public property tests; use only the documented CLI and SQLite state."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ImportProperties(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "db"
        with sqlite3.connect(self.db) as c:
            c.executescript("""
                CREATE TABLE items(sku TEXT PRIMARY KEY, quantity INTEGER,
                                   note TEXT, created_id TEXT);
                CREATE TABLE audit(event_id INTEGER PRIMARY KEY,
                    sku TEXT REFERENCES items(sku) ON DELETE CASCADE, detail TEXT);
                INSERT INTO items VALUES ('A', 3, 'keep', 'original');
                INSERT INTO audit VALUES (1, 'A', 'history');
            """)

    def run_import(self, kind, text):
        path = Path(self.tmp.name) / "input"
        path.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, "inventory.py", "--db", str(self.db),
                               "import", "--format", kind, str(path)],
                              capture_output=True, text=True, timeout=3, check=False)

    def state(self):
        with sqlite3.connect(self.db) as c:
            return (c.execute("SELECT * FROM items ORDER BY sku").fetchall(),
                    c.execute("SELECT * FROM audit ORDER BY event_id").fetchall())

    def test_csv_preserves_related_history(self):
        p = self.run_import("csv", "sku,quantity\nA," + "0" * 131073 + "8\nB,2\n")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.endswith("\n"))
        self.assertEqual(json.loads(p.stdout), {"imported": 2})
        self.assertEqual(self.state(), ([("A", 8, "keep", "original"), ("B", 2, "", "item:B")],
                                        [(1, "A", "history")]))

    def test_jsonl_preserves_related_history(self):
        p = self.run_import("jsonl", '{"sku":"A","quantity":7}\n')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.state(), ([("A", 7, "keep", "original")], [(1, "A", "history")]))

    def test_csv_late_invalid_rolls_back(self):
        before = self.state()
        p = self.run_import("csv", "sku,quantity\nB,4\nA,-1\n")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.state(), before)

    def test_jsonl_late_invalid_rolls_back(self):
        before = self.state()
        p = self.run_import("jsonl", '{"sku":"B","quantity":4}\n{"sku":"A","quantity":true}\n')
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.state(), before)
