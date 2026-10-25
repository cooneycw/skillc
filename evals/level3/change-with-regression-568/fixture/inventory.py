"""Existing inventory project; batch import is the requested missing feature."""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys


def validate(sku, quantity):
    if not isinstance(sku, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", sku) is None:
        raise ValueError("invalid SKU")
    if type(quantity) is not int or not 0 <= quantity <= 2147483647:
        raise ValueError("invalid quantity")


def connect(db_path):
    try:
        c = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=rw", uri=True)
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("SELECT sku, quantity, note, created_id FROM items LIMIT 0")
        return c
    except (OSError, sqlite3.Error) as exc:
        raise ValueError("input: database unavailable") from exc


def set_quantity(db_path, sku, quantity):
    validate(sku, quantity)
    c = connect(db_path)
    try:
        with c:
            c.execute("INSERT INTO items VALUES (?, ?, '', ?) ON CONFLICT(sku) DO UPDATE SET quantity=excluded.quantity",
                      (sku, quantity, "item:" + sku))
    finally:
        c.close()


def list_items(db_path):
    c = connect(db_path)
    try:
        return [dict(zip(("sku", "quantity", "note", "created_id"), row))
                for row in c.execute("SELECT sku, quantity, note, created_id FROM items ORDER BY sku COLLATE BINARY")]
    finally:
        c.close()


def import_file(db_path, path, kind):
    raise ValueError("input: batch import is not implemented")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    commands = p.add_subparsers(dest="command", required=True)
    put = commands.add_parser("put")
    put.add_argument("sku")
    put.add_argument("quantity", type=int)
    commands.add_parser("list")
    imp = commands.add_parser("import")
    imp.add_argument("--format", choices=("csv", "jsonl"), required=True)
    imp.add_argument("input")
    args = p.parse_args()
    try:
        if args.command == "put":
            set_quantity(args.db, args.sku, args.quantity)
            result = {"updated": 1}
        elif args.command == "list":
            result = list_items(args.db)
        else:
            result = {"imported": import_file(args.db, args.input, args.format)}
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        text = str(exc)
        if not text.startswith(("line ", "header:", "input:")):
            text = "input: " + text
        print("error: " + text, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
