"""Untrusted behavior observations; no answer key or delivery authority."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
vectors = json.load(sys.stdin)
sys.path.insert(0, str(root / "src"))
rows = []
try:
    quote = importlib.import_module("quote").quote
except Exception as exc:  # noqa: BLE001 - a candidate import failure is an observation
    quote = None
    error = type(exc).__name__
for vector in vectors:
    try:
        value = quote(*vector) if quote is not None else None
        rows.append({"input": vector, "value": value})
    except Exception as exc:  # noqa: BLE001 - candidate behavior, never a verdict
        rows.append({"input": vector, "error": type(exc).__name__})
print(json.dumps({"rows": rows, "source": {
    p: "sha256:" + hashlib.sha256((root / p).read_bytes()).hexdigest()
    for p in ("src/subtotal.py", "src/tax.py", "src/quote.py") if (root / p).is_file()}}))
