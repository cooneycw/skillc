import sqlite3
import tempfile
import unittest
from pathlib import Path

import inventory


class Legacy(unittest.TestCase):
    def test_public_api_preserves_history(self):
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "db"
            with sqlite3.connect(db) as c:
                c.executescript("""
                    CREATE TABLE items(sku TEXT PRIMARY KEY, quantity INTEGER,
                                       note TEXT, created_id TEXT);
                    CREATE TABLE audit(event_id INTEGER PRIMARY KEY,
                        sku TEXT REFERENCES items(sku) ON DELETE CASCADE, detail TEXT);
                    INSERT INTO items VALUES ('A', 3, 'keep', 'original');
                    INSERT INTO audit VALUES (1, 'A', 'history');
                """)
            inventory.set_quantity(db, "A", 8)
            self.assertEqual(inventory.list_items(db),
                             [{"sku": "A", "quantity": 8, "note": "keep", "created_id": "original"}])
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute("SELECT * FROM audit").fetchall(), [(1, "A", "history")])
            inventory.set_quantity(db, "B", 2)
            self.assertEqual(inventory.list_items(db)[1],
                             {"sku": "B", "quantity": 2, "note": "", "created_id": "item:B"})
