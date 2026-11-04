"""Untrusted delivered behavior observations, with no answer key."""
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "src"
sys.path.insert(0, str(root))
vectors = json.load(sys.stdin)
rows = []
try:
    spec = importlib.util.spec_from_file_location("delivered_quote", root / "quote.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for vector in vectors:
        try:
            rows.append({"input": vector, "value": module.quote(*vector)})
        except Exception as exc:  # noqa: BLE001 - candidate behavior is an observation
            rows.append({"input": vector, "error": type(exc).__name__})
except Exception as exc:  # noqa: BLE001 - missing/import-broken output is observed
    rows = [{"input": vector, "error": type(exc).__name__} for vector in vectors]
print(json.dumps({"rows": rows}))
