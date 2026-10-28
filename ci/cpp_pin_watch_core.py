"""Verified CPP closure drift; content risk, not semantic equivalence or repinning."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from skillc import leak, profile

CPP_LOCATOR = "github.com/cooneycw/claude-power-pack"
MARKER = "<!-- skillc-cpp-pin-watch-v1\n"
PRIORITY = ("contract", "structural", "library-only")
IDENTITY = re.compile(r"(?i)\b(?:sc-(?:orch|w\d+)|[a-z]+-squad|run\d+|mas" + r"ter|wor" + r"ker)\b")


class WatchRefused(ValueError):
    """An input or public notice cannot support the claimed reading."""


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def policy() -> dict[str, Any]:
    data = json.loads(Path(__file__).with_name("cpp-pin-watch-policy.json").read_text())
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("contract_sources"), dict) \
            or not data["contract_sources"] or not all(isinstance(k, str) and isinstance(v, str) and v
                                                     for k, v in data["contract_sources"].items()):
        raise WatchRefused("contract policy is invalid")
    return data  # type: ignore[no-any-return]


def _contract(path: str, roots: list[str], gates: set[str], rules: dict[str, Any]) -> bool:
    if path in gates:
        return True
    relative = [path] + [path[len(root) + 1:] for root in roots if path.startswith(root + "/")]
    return any(p in rules["contract_sources"] or p in ("SKILL.md", "reference.md") for p in relative) \
        or PurePosixPath(path).name in {PurePosixPath(p).name for p in rules["contract_sources"]
                                              if p.startswith("scripts/")}


def classify(repo: Path, directory: Path, target_revision: str, *, allow_derived: bool = False) -> dict[str, Any]:
    """Re-derive the pinned population; malformed evidence is unknown, never none."""
    result: dict[str, Any] = {"profile": directory.name, "classification": "unknown", "flags": [],
                              "pin": None, "target": target_revision, "error": None}
    try:
        rules = policy()
        declaration = profile.Profile.load(directory / "profile.json")
        result.update(profile=declaration.name, pin=declaration.subject.revision)
        if declaration.subject.locator != CPP_LOCATOR:
            raise WatchRefused("not a CPP profile")
        pin = profile.GitTree(repo, declaration.subject.revision)
        target = profile.GitTree(repo, target_revision)
        evidence = directory / "evidence/inventory.json"
        if not evidence.exists() and not allow_derived:
            raise WatchRefused("committed inventory missing; derivation requires explicit input")
        fresh = profile.validate(declaration, pin)
        if evidence.exists():
            committed = json.loads(evidence.read_text())
            if not isinstance(committed, dict) or profile.inventory_digest(committed) != profile.inventory_digest(fresh):
                raise WatchRefused("committed inventory differs from verified pinned closure")
        result["inventory_source"] = "committed" if evidence.exists() else "derived"
        result["inventory_digest"] = profile.inventory_digest(fresh)
        result["profile_digest"] = fresh["profile_digest"]
        sources: dict[str, dict[str, Any]] = {}
        gates: set[str] = set()
        gate_destinations = {declaration.gate_entrypoint, *declaration.bundled_gate_entrypoints,
                             *declaration.checkout_gate_entrypoints}
        for record in profile._install_records(fresh):
            if record["origin"] == "synthetic":
                continue
            source = record["source"]
            identity = {k: record[k] for k in ("git_blob", "digest", "mode")}
            if source in sources and sources[source] != identity:
                raise WatchRefused("conflicting duplicate source records")
            raw = pin.read(source)
            if profile.git_blob_id(raw) != identity["git_blob"] \
                    or "sha256:" + hashlib.sha256(raw).hexdigest() != identity["digest"] \
                    or pin.files()[source] != identity["mode"]:
                raise WatchRefused("pinned source identity differs")
            sources[source] = identity
            if record["destination"] in gate_destinations:
                gates.add(source)
        if not sources:
            raise WatchRefused("no pinned source population")
        roots = sorted(str(PurePosixPath(declaration.subject.skills_root) / s["directory"]) for s in fresh["skills"])
        changed, removed, added = [], [], []
        kinds: set[str] = set()
        for path, before in sorted(sources.items()):
            if path not in target.files():
                removed.append({"path": path, "before": before, "after": None})
                kinds.add("structural")
                if _contract(path, roots, gates, rules):
                    kinds.add("contract")
            else:
                after = {"git_blob": target._files[path][1], "mode": target.files()[path]}
                if (before["git_blob"], before["mode"]) != (after["git_blob"], after["mode"]):
                    changed.append({"path": path, "before": before, "after": after})
                    kinds.add("contract" if _contract(path, roots, gates, rules) else "library-only")
        for path in sorted(set(target.files()) | target.links):
            if path not in pin.files() and path not in pin.links and any(path.startswith(r + "/") for r in roots):
                added.append({"path": path, "before": None,
                              "after": {"mode": target.files().get(path, "120000")}})
                kinds.add("structural")
        flags = [k for k in PRIORITY if k in kinds]
        result.update(classification=flags[0] if flags else "none", flags=flags, changed=changed,
                      removed=removed, added=added, unique_sources=len(sources), selected_roots=roots,
                      policy_version=rules["version"], policy_digest="sha256:" + hashlib.sha256(_canonical(rules)).hexdigest(),
                      addition_scope="selected skill roots only; undeclared future helpers are not inventoried")
    except (OSError, ValueError, KeyError, TypeError, profile.Refused) as exc:
        # No raw exception or host path enters the public report/notice.
        result.update(classification="unknown", error=f"comparison-input-invalid:{type(exc).__name__}")
    return result


def reading(inputs: list[tuple[Path, str]], repo: Path, target: str, *, source_mode: str = "replay",
            derive_missing: bool = False) -> dict[str, Any]:
    options = {"allow_derived": True} if derive_missing else {}
    profiles = [{**classify(repo, directory, target, **options), "slot": slot} for directory, slot in inputs]
    if not profiles or len({p["slot"] for p in profiles}) != len(profiles):
        raise WatchRefused("empty or duplicate watch population")
    return {"schema": 1, "source_mode": source_mode, "target": target, "profiles": profiles,
            "ok": all(p["classification"] != "unknown" for p in profiles)}


def transition_key(report: dict[str, Any]) -> str:
    vector = sorted((p["slot"], p["classification"], sorted(p["flags"])) for p in report["profiles"])
    return hashlib.sha256(_canonical(vector)).hexdigest()


def assert_public(body: str) -> None:
    if IDENTITY.search(body) or list(leak.scan_text(body, frozenset(), leak.default_host_paths())):
        raise WatchRefused("public notice contains an identity or private path")


def notice(report: dict[str, Any]) -> str:
    lines = ["CPP pin-watch reading", "", f"Compared CPP commit: `{report['target']}` ({report['source_mode']}).", ""]
    for entry in report["profiles"]:
        lines.append(f"- `{entry['profile']}` at `{entry['pin']}`: **{entry['classification']}**; "
                     f"flags={entry['flags']}; verified sources={entry.get('unique_sources', 'unknown')}.")
        for kind in ("changed", "removed", "added"):
            paths = [f"`{e['path']}`" for e in entry.get(kind, [])]
            if paths:
                lines.append(f"  - {kind}: {', '.join(paths)}")
        if entry["error"]:
            lines.append(f"  - {entry['error']}")
    state = {**report, "profiles": [{k: v for k, v in entry.items()
                                     if k not in ("changed", "removed", "added", "selected_roots", "addition_scope")}
                                    for entry in report["profiles"]]}
    lines.extend(["", "Additions cover selected skill roots only. No repin or installation/readiness proof.",
                  "", MARKER + _canonical(state).decode() + "\n-->"])
    body = "\n".join(lines)
    assert_public(body)
    if len(body.encode()) > 60000:
        raise WatchRefused("public notice exceeds the comment size budget")
    return body


def last_reading(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest = None
    for comment in comments:
        author = comment.get("user")
        if not isinstance(author, dict) or author.get("login") != "cooneycw":
            continue
        body = comment.get("body") or ""
        if not isinstance(body, str):
            raise WatchRefused("comment body is not text")
        if MARKER not in body:
            continue
        try:
            raw = body.split(MARKER, 1)[1].split("\n-->", 1)[0]
            candidate = json.loads(raw)
            if candidate["schema"] != 1 or not candidate["profiles"] or any(
                p["classification"] not in (*PRIORITY, "none", "unknown") for p in candidate["profiles"]
            ):
                raise ValueError("invalid machine reading")
            if type(candidate["ok"]) is not bool or candidate["ok"] != all(
                p["classification"] != "unknown" for p in candidate["profiles"]
            ) or len({p["slot"] for p in candidate["profiles"]}) != len(candidate["profiles"]):
                raise ValueError("invalid reading population")
            for entry in candidate["profiles"]:
                flags = entry["flags"]
                if not isinstance(flags, list) or flags != [k for k in PRIORITY if k in flags] \
                        or entry["classification"] != (flags[0] if flags else
                                                       "unknown" if entry["error"] else "none"):
                    raise ValueError("invalid classification flags")
            transition_key(candidate)
        except (ValueError, KeyError, TypeError) as exc:
            raise WatchRefused("last machine-tagged reading is malformed") from exc
        latest = candidate
    return latest



def historical_control(repo: Path, root: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Compare the committed historical input against every recorded evidence path."""
    report = classify(repo, root / expected["profile"], expected["target"])
    observed = {"profile": expected["profile"], **{k: report.get(k) for k in
                ("pin", "target", "classification", "flags", "unique_sources")},
                **{k: [e["path"] for e in report.get(k, [])] for k in ("changed", "removed", "added")}}
    if observed != expected:
        raise WatchRefused("historical control disagrees with its committed expected evidence")
    return report
