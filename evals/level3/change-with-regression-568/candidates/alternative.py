"""Alternative: stream under one transaction, update before insert."""
import argparse
import csv
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


def _write(connection, sku, quantity):
    count = connection.execute("UPDATE items SET quantity=? WHERE sku=?", (quantity, sku)).rowcount
    if count == 0:
        connection.execute("INSERT INTO items VALUES (?, ?, '', ?)", (sku, quantity, "item:" + sku))


def set_quantity(db_path, sku, quantity):
    validate(sku, quantity)
    connection = connect(db_path)
    try:
        with connection:
            _write(connection, sku, quantity)
    finally:
        connection.close()


def list_items(db_path):
    c = connect(db_path)
    try:
        return [dict(zip(("sku", "quantity", "note", "created_id"), row))
                for row in c.execute("SELECT sku, quantity, note, created_id FROM items ORDER BY sku COLLATE BINARY")]
    finally:
        c.close()


def _object(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate JSON key")
    return dict(pairs)


def _records(path, kind):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            records = csv.reader(f, strict=True) if kind == "csv" else enumerate(f, 1)
            header = None
            for entry in records:
                if kind == "csv":
                    if not entry:
                        continue
                    number = records.line_num
                    if header is None:
                        if len(entry) != 2 or sorted(entry) != ["quantity", "sku"]:
                            raise ValueError("header: expected sku and quantity")
                        header = entry
                        continue
                    try:
                        if len(entry) != 2:
                            raise ValueError("expected two fields")
                        obj = dict(zip(header, entry))
                        if not obj["quantity"] or any(ch not in "0123456789" for ch in obj["quantity"]):
                            raise ValueError("invalid quantity")
                        quantity, sku = int(obj["quantity"]), obj["sku"]
                        validate(sku, quantity)
                    except ValueError as exc:
                        raise ValueError(f"line {number}: {exc}") from exc
                else:
                    number, line = entry
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line, object_pairs_hook=_object)
                        if type(obj) is not dict or sorted(obj) != ["quantity", "sku"]:
                            raise ValueError("expected sku and quantity")
                        sku, quantity = obj["sku"], obj["quantity"]
                        validate(sku, quantity)
                    except ValueError as exc:
                        raise ValueError(f"line {number}: {exc}") from exc
                yield sku, quantity
            if kind == "csv" and header is None:
                raise ValueError("header: required")
    except csv.Error as exc:
        raise ValueError(f"line {records.line_num}: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError("input: unreadable UTF-8 input") from exc


def import_file(db_path, path, kind):
    connection = connect(db_path)
    seen = set()
    try:
        with connection:
            for sku, quantity in _records(path, kind):
                _write(connection, sku, quantity)
                seen.add(sku)
    finally:
        connection.close()
    return len(seen)


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
