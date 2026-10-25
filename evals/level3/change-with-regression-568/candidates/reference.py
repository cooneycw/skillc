"""Reference: prevalidate, then atomically upsert quantities."""
import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path


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


def _put(c, sku, quantity):
    c.execute("INSERT INTO items VALUES (?, ?, '', ?) ON CONFLICT(sku) DO UPDATE SET quantity=excluded.quantity",
              (sku, quantity, "item:" + sku))


def set_quantity(db_path, sku, quantity):
    validate(sku, quantity)
    c = connect(db_path)
    try:
        with c:
            _put(c, sku, quantity)
    finally:
        c.close()


def list_items(db_path):
    c = connect(db_path)
    try:
        return [dict(zip(("sku", "quantity", "note", "created_id"), row))
                for row in c.execute("SELECT sku, quantity, note, created_id FROM items ORDER BY sku COLLATE BINARY")]
    finally:
        c.close()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _rows(path, kind):
    try:
        with open(path, encoding="utf-8", newline="") as stream:
            if kind == "csv":
                reader = csv.reader(stream, strict=True)
                header = next((row for row in reader if row), None)
                if header is None or len(header) != 2 or set(header) != {"sku", "quantity"}:
                    raise ValueError("header: expected sku and quantity")
                for row in reader:
                    if not row:
                        continue
                    try:
                        if len(row) != 2:
                            raise ValueError("expected two fields")
                        record = dict(zip(header, row))
                        raw = record["quantity"]
                        if re.fullmatch(r"[0-9]+", raw) is None:
                            raise ValueError("invalid quantity")
                        sku, quantity = record["sku"], int(raw)
                        validate(sku, quantity)
                    except ValueError as exc:
                        raise ValueError(f"line {reader.line_num}: {exc}") from exc
                    yield sku, quantity
            else:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line, object_pairs_hook=_unique)
                        if not isinstance(record, dict) or set(record) != {"sku", "quantity"}:
                            raise ValueError("expected sku and quantity")
                        sku, quantity = record["sku"], record["quantity"]
                        validate(sku, quantity)
                    except ValueError as exc:
                        raise ValueError(f"line {number}: {exc}") from exc
                    yield sku, quantity
    except csv.Error as exc:
        raise ValueError(f"line {reader.line_num}: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError("input: unreadable UTF-8 input") from exc


def import_file(db_path, path, kind):
    rows = list(_rows(path, kind))
    c = connect(db_path)
    try:
        with c:
            for sku, quantity in rows:
                _put(c, sku, quantity)
    finally:
        c.close()
    return len({sku for sku, _ in rows})


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
