"""Fake gate: models the pinned helper's existence-only detection."""
import os
from pathlib import Path

checkout = Path(os.environ["HOME"]) / "checkout"
if checkout.is_dir() and (checkout / "MARKER.md").is_file():
    print("flow-finish-gate: running deterministic gate (lib.cicd run --plan fake)")
else:
    print("NOTE: deterministic runner unavailable; using Makefile fallback")
