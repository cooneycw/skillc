"""Explicit CPP reading; --post alone opts into a serialized #384 comment."""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ci import cpp_pin_watch_core as watch
from skillc import profile

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "https://github.com/cooneycw/claude-power-pack.git"
COMMENTS = "repos/cooneycw/skillc/issues/384/comments"


def _run(argv: list[str], *, data: str | None = None) -> str:
    try:
        result = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise watch.WatchRefused(f"{argv[0]} unavailable") from exc
    if result.returncode:
        raise watch.WatchRefused(f"{argv[0]} operation failed")
    return result.stdout.strip()


def fetch_target(repo: Path) -> str:
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", REPOSITORY, str(repo)])
    origin = _run(["git", "-C", str(repo), "remote", "get-url", "origin"])
    if origin not in (REPOSITORY, REPOSITORY.removesuffix(".git"), "git@github.com:cooneycw/claude-power-pack.git"):
        raise watch.WatchRefused("CPP origin does not match the declared GitHub repository")
    _run(["git", "-C", str(repo), "fetch", "origin", "main"])
    target = _run(["git", "-C", str(repo), "rev-parse", "--verify", "FETCH_HEAD^{commit}"])
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise watch.WatchRefused("CPP main did not resolve to an immutable commit")
    return target


def inputs(root: Path, explicit: list[Path]) -> list[tuple[Path, str]]:
    if explicit:
        return [(path, "explicit:" + profile.Profile.load(path / "profile.json").name) for path in explicit]
    base = json.loads((root / "skillc/runtime-policy.json").read_text())
    extra = json.loads((root / "skillc/runtime-policy-extra.json").read_text())["profile_runtimes"]
    selected = []
    for source, entry in [("base", base), *(("extra", e) for e in extra)]:
        name = entry["runtime_id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise watch.WatchRefused("invalid policy runtime ID")
        directory = root / "evals/subjects" / name
        declared = profile.Profile.load(directory / "profile.json")
        if entry["subject_locator"] != watch.CPP_LOCATOR \
                or declared.subject.locator != watch.CPP_LOCATOR \
                or declared.subject.revision != entry["subject_revision"] \
                or declared.gate_entrypoint != entry["gate_entrypoint"]:
            raise watch.WatchRefused("policy and CPP subject identity disagree")
        slot = source + ":" + ",".join(declared.select or ("all",))
        selected.append((directory, slot))
    if not selected or len({slot for _, slot in selected}) != len(selected):
        raise watch.WatchRefused("empty or ambiguous policy population")
    return selected


def comments() -> list[dict[str, Any]]:
    pages = json.loads(_run(["gh", "api", COMMENTS, "--paginate", "--slurp"]))
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        raise watch.WatchRefused("GitHub comments response is invalid")
    if any(not isinstance(c, dict) for page in pages for c in page):
        raise watch.WatchRefused("GitHub comment entry is invalid")
    return [c for page in pages for c in page]


def create_comment(body: str) -> dict[str, Any]:
    watch.assert_public(body)
    # Only the same author whose machine markers we read may post this stream.
    if _run(["gh", "api", "user", "--jq", ".login"]) != "cooneycw":
        raise watch.WatchRefused("posting identity does not match the watch stream author")
    # Structured stdin, no shell escaping or command substitution.
    result = json.loads(_run(["gh", "api", "-X", "POST", COMMENTS, "--input", "-"],
                             data=json.dumps({"body": body})))
    if not isinstance(result, dict) or type(result.get("id")) is not int or result.get("body") != body:
        raise watch.WatchRefused("GitHub did not return the expected durable comment receipt")
    return result


def publish(report: dict[str, Any], read: Callable[[], list[dict[str, Any]]] = comments,
            write: Callable[[str], dict[str, Any]] = create_comment) -> dict[str, Any]:
    """Call only inside the operational command's exclusive lock.

    A remote recheck handles sequential retry after a lost acknowledgement.
    Independent concurrent posters are unsupported; there is no GitHub CAS.
    """
    body = watch.notice(report)
    previous = watch.last_reading(read())
    if previous is not None and watch.transition_key(previous) == watch.transition_key(report):
        return {"posted": False, "reason": "classification unchanged"}
    receipt = write(body)
    return {"posted": True, "comment_id": receipt["id"], "url": receipt.get("html_url")}


def _unknown(selected: list[tuple[Path, str]], target: str | None, mode: str) -> dict[str, Any]:
    population = selected or [(Path("CPP-policy"), "policy")]
    return {"schema": 1, "source_mode": mode, "target": target, "ok": False,
            "profiles": [{"profile": path.name, "slot": slot, "pin": None, "target": target,
                          "classification": "unknown", "flags": [], "error": "source-or-policy-unavailable"}
                         for path, slot in population]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp-repo", type=Path, default=ROOT / "reports/cpp-pin-watch/source")
    parser.add_argument("--profile", type=Path, action="append", default=[])
    parser.add_argument("--target", help="full immutable replay commit; does not fetch moving main")
    parser.add_argument("--historical-control", action="store_true", help="check the committed historical pair")
    parser.add_argument("--post", action="store_true", help="operator opt-in to write a #384 transition comment")
    parser.add_argument("--output", type=Path, help="also save the reading JSON")
    parser.add_argument("--lock", type=Path, default=ROOT / "reports/cpp-pin-watch/post.lock")
    args = parser.parse_args(argv)
    if args.historical_control:
        if args.post or args.target or args.profile:
            parser.error("historical control cannot post or override its committed inputs")
        try:
            expected = json.loads((ROOT / "controls/cpp-pin-watch/historical.json").read_text())
            report = watch.historical_control(args.cpp_repo, ROOT, expected)
            print(json.dumps(report, indent=2))
            print("cpp-pin-watch-control: exact historical evidence matches")
            return 0
        except (OSError, ValueError, KeyError, TypeError):
            print("cpp-pin-watch-control: historical evidence mismatch or unavailable")
            return 2
    if args.post and (args.target or args.profile):
        parser.error("--post requires a fresh default-policy reading, not an explicit profile/replay")
    selected: list[tuple[Path, str]] = []
    target = args.target
    try:
        selected = inputs(ROOT, args.profile)
        if target is None:
            target = fetch_target(args.cpp_repo)
        report = watch.reading(selected, args.cpp_repo, target, source_mode="replay" if args.target else "fetched",
                               derive_missing=bool(args.profile))
    except (OSError, ValueError, KeyError, TypeError, profile.Refused):
        report = _unknown(selected, target, "replay" if args.target else "fetch-failed")
    try:
        body = watch.notice(report)  # Privacy check also applies to dry runs and JSON output.
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        print("\nWould-post transition body (posting is opt-in):\n" + body)
        if args.post:
            args.lock.parent.mkdir(parents=True, exist_ok=True)
            with args.lock.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                receipt = publish(report, read=comments, write=create_comment)
            print(json.dumps(receipt, sort_keys=True))
        else:
            previous = watch.last_reading(comments())
            transition = previous is None or watch.transition_key(previous) != watch.transition_key(report)
            print(json.dumps({"posted": False, "would_post": transition}, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        detail = str(exc) if isinstance(exc, watch.WatchRefused) else type(exc).__name__
        print(f"cpp-pin-watch: refused ({detail})")
        return 2
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
