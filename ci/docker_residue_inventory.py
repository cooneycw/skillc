#!/usr/bin/env python3
"""Inspect Docker residue and propose explicit selections; never remove anything.

Exit 0 means a complete, nonempty inventory of matching resources, NOT clean
completion or permission to remove them. Exit 2 means UNKNOWN. No daemon labels
or name prefixes establish that an owner is dead or that an image is disposable.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

Run = Callable[[list[str]], str]
KINDS = ("image", "container", "network")
PIN_NAMES = frozenset({"skillc-375-final", "skillc-279-ca3030d", "skillc-434-rev2"})
LABEL_KEYS = ("skillc.managed", "skillc.attempt-id", "org.skillc.image")
LIST_COMMANDS = {
    "image": ["image", "ls", "--all", "--quiet", "--no-trunc"],
    "container": ["ps", "--all", "--quiet", "--no-trunc"],
    "network": ["network", "ls", "--quiet", "--no-trunc"],
}


class Unreadable(ValueError):
    """A complete observation could not be established."""


def _id(value: object, kind: str) -> str:
    pattern = r"sha256:[0-9a-f]{64}" if kind == "image" else r"[0-9a-f]{64}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise Unreadable(f"{kind}: invalid immutable ID")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise Unreadable("missing or invalid resource name")
    return value


def _repository(tag: str) -> str:
    # Match the final repository component, including registry/namespace aliases.
    return tag.rsplit("/", 1)[-1].split(":", 1)[0].split("@", 1)[0]


def is_pinned(tag: str) -> bool:
    name = _repository(tag)
    return name in PIN_NAMES or name.startswith("skillc-529-")


def _labels(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                               for k, v in value.items()):
        raise Unreadable("unreadable ownership labels")
    return {k: value[k] for k in LABEL_KEYS if k in value}


def _record(info: Any, kind: str) -> dict[str, Any]:
    if not isinstance(info, dict):
        raise Unreadable(f"{kind}: inspection is not an object")
    ident = _id(info.get("Id"), kind)
    if kind == "image":
        tags = info.get("RepoTags")
        if tags is None:
            tags = []
        if not isinstance(tags, list):
            raise Unreadable("unreadable image aliases")
        names = sorted({_text(tag) for tag in tags})
        digests = info.get("RepoDigests")
        if digests is None:
            digests = []
        if not isinstance(digests, list):
            raise Unreadable("unreadable image digest aliases")
        digest_names = sorted({_text(tag) for tag in digests})
        config = info.get("Config")
        if not isinstance(config, dict):
            raise Unreadable("missing image config")
        size = info.get("Size")
        if type(size) is not int or size < 0:
            raise Unreadable("unreadable image size")
        return {"id": ident, "names": sorted(set(names + digest_names)), "tags": names,
                "digest_aliases": digest_names, "labels": _labels(config.get("Labels")), "bytes": size}
    name = _text(info.get("Name")).removeprefix("/")
    if kind == "container":
        config, state = info.get("Config"), info.get("State")
        if not isinstance(config, dict) or not isinstance(state, dict) or type(state.get("Running")) is not bool:
            raise Unreadable("unreadable container config/state")
        return {"id": ident, "names": [name], "labels": _labels(config.get("Labels")),
                "image_id": _id(info.get("Image"), "image"), "running": state["Running"]}
    endpoints = info.get("Containers")
    if not isinstance(endpoints, dict):
        raise Unreadable("unreadable network endpoints")
    return {"id": ident, "names": [name], "labels": _labels(info.get("Labels")),
            "endpoint_ids": sorted(_id(key, "container") for key in endpoints)}


def _list(run: Run, kind: str) -> set[str]:
    rows = run(LIST_COMMANDS[kind]).splitlines()
    if len(rows) > 10000:
        raise Unreadable(f"{kind}: inventory exceeds 10000 entries")
    return {_id(row.strip(), kind) for row in rows}


def inventory(run: Run) -> dict[str, Any]:
    """List ALL IDs, inspect in batches, and repeat ID lists to detect arrivals.

    No label-filtered image enumeration: existing named images have no managed
    label. A stable ID list is not an atomic alias/reference snapshot; every
    proposed action still requires operator approval and fresh inspection.
    """
    errors: list[str] = []
    listed: dict[str, set[str]] = {}
    resources: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for kind in KINDS:
        try:
            listed[kind] = _list(run, kind)
            ids = sorted(listed[kind])
            for start in range(0, len(ids), 64):
                selected = ids[start:start + 64]
                data = json.loads(run([kind, "inspect", *selected]))
                if not isinstance(data, list):
                    raise Unreadable(f"{kind}: inspection is not a list")
                records = [_record(item, kind) for item in data]
                if len(records) != len(selected) or {r["id"] for r in records} != set(selected):
                    raise Unreadable(f"{kind}: inspected IDs do not match listed IDs")
                resources[kind].extend(records)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            errors.append(f"{kind}: {exc}")
    for kind in KINDS:
        if kind not in listed:
            continue
        try:
            if _list(run, kind) != listed[kind]:
                errors.append(f"{kind}: ID population changed during inspection")
        except Unreadable as exc:
            errors.append(str(exc))
    image_ids = {r["id"] for r in resources["image"]}
    if any(r["image_id"] not in image_ids for r in resources["container"]):
        errors.append("container references an image absent from the inspected inventory")
    report = propose(resources, errors)
    report["listed_counts"] = {kind: len(listed[kind]) if kind in listed else None for kind in KINDS}
    return report


def _matches(record: dict[str, Any], kind: str) -> bool:
    if record["labels"].get("skillc.managed") == "true":
        return True
    if kind == "image" and record["labels"].get("org.skillc.image") == "trial-image":
        return True
    return any((_repository(name).startswith("skillc-") if kind == "image"
                else name.startswith("skillc-") or (kind == "network" and name.endswith("-egress")))
               for name in record["names"])


def propose(resources: dict[str, list[dict[str, Any]]], errors: list[str]) -> dict[str, Any]:
    """A proposal is an unapproved selection for review, never deletion authority."""
    matched = {kind: [dict(r) for r in resources[kind] if _matches(r, kind)] for kind in KINDS}
    references: dict[str, list[str]] = {}
    for container in resources["container"]:
        references.setdefault(container["image_id"], []).append(container["id"])
    proposals: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    pins = []
    for kind in KINDS:
        for record in matched[kind]:
            reason = "operator ownership/retention review required"
            blocked = False
            if kind == "image":
                pinned = [name for name in record["names"] if is_pinned(name)]
                record["pinned_aliases"] = pinned
                record["referencing_container_ids"] = sorted(references.get(record["id"], []))
                if pinned:
                    pins.append(record["id"])
                    reason, blocked = "pinned alias protects entire image ID", True
                elif record["referencing_container_ids"]:
                    reason, blocked = "referenced by a container (including foreign/stopped containers)", True
                elif not any(_repository(name).startswith("skillc-") for name in record["names"]):
                    reason, blocked = "label-only or unnamed image: provenance unknown", True
            elif kind == "container" and record["running"]:
                reason, blocked = "running container: owner/stop authorization unknown", True
            elif kind == "network" and record["endpoint_ids"]:
                reason, blocked = "network has attached endpoints", True
            record["disposition"] = reason
            record["ownership"] = "unknown"
            if not blocked:
                proposals[kind].append({"id": record["id"], "names": record["names"],
                                        "reason": reason, "approved": False})
    if not any(matched.values()):
        errors = [*errors, "empty matching population: absence/cleanliness is not established"]
    if errors:
        proposals = {kind: [] for kind in KINDS}
    return {"schema_version": 1, "kind": "docker-residue-inventory", "read_only": True,
            "inventory_status": "unknown" if errors else "complete", "cleanup_status": "unassessed",
            "pin_policy": {"repository_names": sorted(PIN_NAMES), "repository_prefixes": ["skillc-529-"]},
            "atomic_snapshot": False, "operator_approval_and_fresh_inspection_required": True,
            "errors": errors, "inspected_counts": {kind: len(resources[kind]) for kind in KINDS},
            "matched_counts": {kind: len(matched[kind]) for kind in KINDS},
            "matched_image_tag_count": sum(_repository(name).startswith("skillc-")
                                           for image in matched["image"] for name in image["tags"]),
            "protected_image_ids": sorted(pins), "resources": matched, "proposed_removals": proposals}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker", help="Docker executable (no shell evaluation)")
    parser.add_argument("--timeout", type=float, default=120, help="total Docker observation budget in seconds")
    parser.add_argument("--out", type=Path, help="write a new JSON artifact; refuse existing paths")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 600:
        parser.error("--timeout must be greater than zero and at most 600")
    if args.out is not None and args.out.exists():
        parser.error("--out already exists; preserve the previous inventory")
    deadline = time.monotonic() + args.timeout

    def run(command: list[str]) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unreadable("observation budget exhausted")
        try:
            result = subprocess.run([args.docker, *command], capture_output=True, text=True,
                                    timeout=min(30, remaining), check=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise Unreadable(f"Docker observation unavailable ({type(exc).__name__})") from exc
        if result.returncode:
            # Do not copy arbitrary daemon stderr (credentials/hostnames) into an artifact.
            raise Unreadable(f"Docker observation failed (exit {result.returncode})")
        return result.stdout

    report = inventory(run)
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        sys.stdout.write(data)
    else:
        with args.out.open("x", encoding="utf-8") as output:
            output.write(data)
    return 2 if report["inventory_status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
