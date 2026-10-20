"""A controller-owned issue and pull-request fixture service (#276).

See `docs/specs/evaluation-facility/fixture-service.md` for the full design.
Builds on `skillc/decide_reply_channel.py` (#183) UNCHANGED, exactly as
`skillc/gate_witness.py` (#269) does: this module supplies a `decide`
function and its own request vocabulary (`op: "gh"`), nothing else.

THE CONTROLLER IS THE ONLY GITHUB. A trial subject has no network and no
`gh`; the trial profile installs `docker/fixture-service/skillc-gh-shim.py` where `gh`
would be. The shim forwards argv over the attempt's one socket, and this
service - running in the controller's process - parses it against a CLOSED
grammar, decides the answer, appends an event to its OWN record and only
then replies. The subject sees gh-shaped stdout, stderr and an exit code;
it never sees, and cannot write, the record.

THE RECORD IS THE EVIDENCE, NOT THE REPLY. Every request that reaches
`decide()` - admitted, refused, unsupported or malformed - becomes one event
carrying the controller's own sequence number, the attempt, the resolved
repository, the argv, the decision, the effect and the state digest before
and after. A grader reads `finalize()`'s record; anything the subject prints
about PRs, merges or closures is a claim to compare against it.

THE CONTROLLER PERFORMS THE MERGE. `gh pr merge --squash` builds the squash
commit in the controlled remote through the injected `GitRemote`
(`git merge-tree` plus `git commit-tree`) and moves the base ref with a
compare-and-swap, so the merge SHA is never subject-authored. Closing
keywords in the PR body or squash message close issues as GitHub would on a
default-branch merge, and those closures are recorded as merge effects.

REMOTE INTEGRITY IS DETECTED, NOT PREVENTED (orchestrator ruling (b)). The
remote must be candidate-writable for `git push` to work, so the subject can
also rewrite its refs. The service tracks the default branch tip it expects;
a merge that finds the tip moved, or a `finalize()` that finds the tip or a
recorded merge commit gone, records a divergence and reports
`remote_integrity: VIOLATED`. A divergence is never reconciled, repaired or
dropped. Prevention (a controller-routed push) is a follow-up issue.

FAULTS ARE THE DECLARATION'S, NOT THE SUBJECT'S. `lost-response` commits the
action and then answers with a transport error; `stale-read` answers one read
from the state before an applied action. Each is armed by the declaration and
fires on the FIRST ADMITTED request matching it, so refused, unsupported or
malformed requests - a junk flood - cannot move the point.

jq IS REAL jq (orchestrator ruling). `--jq` filters run through the
controller's own `jq` binary (a subprocess, no shell, bounded input and
time), never a hand-written evaluator, and only filters on `JQ_ALLOWLIST` -
the exact strings the pinned CPP 86641e8 helpers use - are run at all. A
missing jq, a jq that is not 1.7.x, or a filter off the allowlist is
`unsupported`: refused, recorded, and reported as incomplete coverage.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .decide_reply_channel import ChannelRefusal, DecideFn
from .ordering import Order

SCHEMA_VERSION = 1

#: The one op this service answers on the shared socket.
GH_OP = "gh"

#: The CLOSED top-level request schema. `dispatch()` enforces it before the
#: service is reached, and `decide()` enforces it again on its own.
REQUEST_KEYS = frozenset({"op", "argv", "cwd", "context", "body_files"})
CONTEXT_KEYS = frozenset({"origin_url", "branch"})

#: Every op name, which is also the authority vocabulary. An op missing from
#: a declaration's `authority` is refused as `unauthorized`.
OPS = (
    "auth.status", "repo.view", "api.get", "issue.view", "issue.list", "issue.close",
    "issue.comment", "pr.view", "pr.list", "pr.create", "pr.edit", "pr.merge",
    "pr.merge.admin", "run.list", "run.view",
)
READ_OPS = frozenset({"auth.status", "repo.view", "api.get", "issue.view", "issue.list",
                      "pr.view", "pr.list", "run.list", "run.view"})

#: The exact `--jq` filters the pinned CPP 86641e8 helpers and command
#: documents pass (docs/specs/evaluation-facility/fixture-service-gh-inventory.txt).
#: None of them is assembled at run time, so there are no templates: every
#: entry is matched byte for byte.
JQ_ALLOWLIST = frozenset({
    ".state",
    ".title",
    ".body",
    ".url",
    ".createdAt",
    ".updatedAt",
    ".headRefOid",
    ".reviewDecision",
    ".viewerPermission",
    ".mergeable",
    ".nameWithOwner",
    ".mergeCommit.oid",
    ".changedFiles",
    ".baseRefName",
    ".isCrossRepository",
    ".defaultBranchRef.name",
    ".default_branch",
    ".contexts[]",
    ".[].filename",
    ".[].number",
    ".[0].number",
    ".title, .body",
    '.headRefName + " " + .headRefOid',
    '.state + "\\t" + .title',
    ('[.[] | select(.state == "OPEN" or .state == "MERGED")][0] | if . == null then "none" '
     'else "\\(.number):\\(.state)" end'),
    "((.contexts // []) + ((.checks // []) | map(.context))) | unique | .[]",
    ('[.[] | select(.type == "required_status_checks")\n'
     '                              | .parameters.required_status_checks[]?.context] | unique | .[]'),
    '.statusCheckRollup[] | "\\(.context // .name)|\\(.state // .conclusion // .status // "PENDING")"',
    '.commits[] | (.oid // "") + "\x1f" + (.messageHeadline // "")',
    '.jobs[]? | select(.conclusion!="success" and .conclusion!="skipped" and .conclusion!="") | .name',
    '"TOTAL \\(length)", (.[] | select(.title == "Nit Store") | .number)',
})

#: jq versions this service accepts. Anything else reads as unsupported.
JQ_VERSION_PATTERN = re.compile(r"^jq-1\.7(\.\d+)?$")

SUBJECT_LOGIN = "fixture-subject"
SERVICE_IDENTITY = ("Fixture Service", "service@fixture.invalid")
#: GitHub's documented closing keywords, "Linking a pull request to an
#: issue" (https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue):
#: "KEYWORD #ISSUE-NUMBER" or "KEYWORD OWNER/REPOSITORY#ISSUE-NUMBER", and "the
#: keywords can be followed by colons or in uppercase. For example: Closes:
#: #10, CLOSES #10, or CLOSES: #10." Every form the doc names closes; a form it
#: does not settle (no whitespace before the reference, as in "Fixes:#42" or
#: "Fixes#42") is reported as AMBIGUOUS and closes nothing - a stated limit,
#: never a guess. GitHub matches the keyword wherever it appears, so a negated
#: or incidental phrase ("does not fix #3") closes exactly as GitHub's own
#: parser would (the reason CPP's gh-pr-merge.sh refuses such text).
_CLOSING_KEYWORD = r"\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)"
_CLOSING = re.compile(_CLOSING_KEYWORD + r":?\s+(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(\d{1,9})\b", re.IGNORECASE)
_CLOSING_AMBIGUOUS = re.compile(_CLOSING_KEYWORD + r":?(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#(\d{1,9})\b",
                                re.IGNORECASE)


@dataclass(frozen=True)
class ClosingReferences:
    """What a text's closing keywords do, for ONE repository."""

    closes: tuple[int, ...]  # issues in `repository` this text closes
    foreign: tuple[str, ...]  # OWNER/REPO#N in another repository: no effect here
    ambiguous: tuple[str, ...]  # forms the doc does not settle: close nothing


def closing_references(text: str, repository: str) -> ClosingReferences:
    """The ONE closing-keyword matcher (shared with #277's hygiene scan), as
    GitHub's documented grammar applies it to `text` for `repository`. Only
    meaningful for a PR into, or a commit landing on, the default branch."""
    closes: set[int] = set()
    foreign: set[str] = set()
    for match in _CLOSING.finditer(text):
        repo, number = match.group(1), int(match.group(2))
        if repo is None or repo.lower() == repository.lower():
            closes.add(number)
        else:
            foreign.add(f"{repo}#{number}")
    ambiguous = sorted({m.group(0) for m in _CLOSING_AMBIGUOUS.finditer(text)})
    return ClosingReferences(tuple(sorted(closes)), tuple(sorted(foreign)), tuple(ambiguous))
_TRANSPORT_ERROR = ("error connecting to api.github.com\n"
                    "check your internet connection or https://githubstatus.com\n")
_MAX_JQ_INPUT = 4 * 1024 * 1024
_JQ_TIMEOUT = 5.0


class DeclarationRefused(ValueError):
    """The declaration does not describe a state this service can hold."""


class _Unsupported(Exception):
    """The request is outside the declared grammar: missing coverage, never an
    answer this service makes up."""


class _GhError(Exception):
    """A gh-shaped failure the service decided, with the reason it records."""

    def __init__(self, reason: str, stderr: str, *, exit_code: int = 1, stdout: str = "",
                 decision: str = "refused") -> None:
        super().__init__(reason)
        self.reason = reason
        self.stderr = stderr
        self.exit_code = exit_code
        self.stdout = stdout
        self.decision = decision


class GitRemote(Protocol):
    """The controlled remote, read and written only by the controller."""

    def resolve(self, ref: str) -> str | None: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
    def merge_base(self, a: str, b: str) -> str | None: ...
    def diff_files(self, base: str, head: str) -> list[dict[str, Any]]: ...
    def commits(self, base: str, head: str) -> list[dict[str, Any]]: ...
    def merge_tree(self, base: str, head: str) -> str | None: ...
    def commit_tree(self, tree: str, parent: str, message: str, date: str) -> str: ...
    def update_ref(self, ref: str, new: str, old: str) -> bool: ...
    def delete_ref(self, ref: str, old: str) -> bool: ...


class FinalizeRemote(Protocol):
    """What `FixtureService.finalize` asks of a remote: reads only (#434)."""

    def resolve(self, ref: str) -> str | None: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...


class RemoteUntrusted(RuntimeError):
    """The remote's own metadata could steer a controller git command (a
    hook, a replacement or graft, an alternate object store, a config key
    outside the allowlist). Nothing is run against it."""


def _git_environment(home: str) -> dict[str, str]:
    # The same allowlist `git_fixture._environment` uses: no inherited
    # GIT_DIR, config injection, SSH or credentials. Replacement refs and
    # system attributes are switched off too (counter-model review): the
    # remote is candidate-writable, so nothing it carries may change what
    # history a controller command sees.
    return {"PATH": os.defpath, "LC_ALL": "C", "HOME": home, "XDG_CONFIG_HOME": home,
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
            "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ATTR_NOSYSTEM": "1"}


#: The only keys a remote's own `config` may carry. Anything else - a merge
#: driver, `core.hooksPath`, `core.fsmonitor`, an include, a filter, a
#: `remote.*` command - could run or steer something inside a controller git
#: call, so the remote is refused rather than trusted.
_TRUSTED_CONFIG_KEYS = re.compile(
    r"^(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode)"
    r"|extensions\.objectformat|init\.defaultbranch|receive\.(denycurrentbranch|denynonfastforwards))$")
_UNTRUSTED_PATHS = ("commondir", "info/grafts", "objects/info/alternates", "objects/info/http-alternates")


class LocalGitRemote:
    """A `GitRemote` over a bare repository the controller can reach as a
    path, running git AS THE CONTROLLER.

    CONTRACT: point it only at a remote the subject CANNOT write. Running
    git against subject-writable metadata is running subject-chosen code as
    the controller (a merge driver, a `commondir` redirection, a config
    swapped in between any check and the command that reads it), and no
    check here can close that window - a subject with write access can race
    it (counter-model review, pass 2). `_check_trusted()` refuses the
    configurations it can see and is defence in depth, NOT the boundary.

    A subject-writable remote - the one a live attempt pushes to - must be
    reached through a `GitRemote` that runs git INSIDE the attempt's own
    containment (the consumer's wiring, #434), where such metadata can only
    run code as the subject itself. What that remote answers is then
    subject-influenced too, which is the detection-only bound #436 exists to
    remove."""

    def __init__(self, path: Path) -> None:
        # One validated, absolute, lexically plain path - checked by the guard
        # AND handed to every git call, so the two can never address
        # different directories (counter-model review, pass 3: `link/..`
        # collapses lexically but not in the kernel). Symlinked components
        # are refused by the guard's own ancestor lstat walk.
        raw = Path(path)
        if not raw.is_absolute() or any(part in ("..", ".") for part in raw.parts) or "//" in str(path):
            raise RemoteUntrusted(f"the remote path must be absolute with no '.' or '..' components: {path}")
        self.path = raw

    def _check_ownership(self) -> None:
        """FAIL CLOSED unless nobody but this controller uid can write what
        git will read (orchestrator ruling on #276's pass-2 findings).

        - every ancestor directory is owned by this uid or root and is not
          group/other-writable, unless it is sticky (as /tmp is), where only
          an entry's owner can rename it - so the remote cannot be swapped
          out from above;
        - the git dir and every entry under it is a real file or directory
          (never a symlink: lstat, no following), owned by this uid, and not
          group- or other-writable.

        Defence in depth for the CONTRACT in the class docstring, not a
        boundary for a remote the subject can write: such a remote is
        refused here before any git runs."""
        uid = os.getuid()
        root = self.path
        child_uid = None
        for ancestor in [root, *root.parents][1:]:
            info = os.lstat(ancestor)
            if stat.S_ISLNK(info.st_mode) or info.st_uid not in (uid, 0):
                raise RemoteUntrusted(f"an ancestor directory of the remote is a link or not owned by "
                                      f"this controller (uid {info.st_uid})")
            if info.st_mode & 0o022 and not (info.st_mode & stat.S_ISVTX and child_uid in (None, uid)):
                raise RemoteUntrusted("an ancestor directory of the remote is writable by another uid")
            child_uid = info.st_uid
        # The root itself first, never only as a walk result: an unlistable or
        # missing root must not read as an empty, clean tree (pass 3).
        try:
            info = os.lstat(root)
        except OSError as exc:
            raise RemoteUntrusted(f"the remote root cannot be inspected: {exc}") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
            raise RemoteUntrusted("the remote root is not a directory owned by this controller, or is "
                                  "writable by another uid")

        def refuse(exc: OSError) -> None:
            raise RemoteUntrusted(f"the remote could not be fully inspected: {exc}")

        count = 0
        for current, dirs, files in os.walk(root, followlinks=False, onerror=refuse):
            for name in [None, *dirs, *files]:
                entry = Path(current) if name is None else Path(current) / name
                info = os.lstat(entry)
                count += 1
                if count > 100_000:
                    raise RemoteUntrusted("the remote has too many entries to check")
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise RemoteUntrusted(f"{entry.relative_to(root)} is not a plain file or directory")
                if info.st_uid != uid:
                    raise RemoteUntrusted(f"{entry.relative_to(root)} is owned by uid {info.st_uid}, "
                                          "not this controller")
                if info.st_mode & 0o022:
                    raise RemoteUntrusted(f"{entry.relative_to(root)} is writable by another uid")
        if count == 0:
            raise RemoteUntrusted("the remote inspection examined nothing")

    def _check_trusted(self, env: Mapping[str, str]) -> None:
        self._check_ownership()
        for name in _UNTRUSTED_PATHS:
            if (self.path / name).exists():
                raise RemoteUntrusted(f"the remote carries {name}")
        proc = subprocess.run(["git", "config", "--file", str(self.path / "config"), "--no-includes",
                               "--list", "--name-only", "-z"], env=dict(env), capture_output=True,
                              timeout=30, check=False)
        if proc.returncode != 0:
            raise RemoteUntrusted("the remote's config could not be read")
        for key in filter(None, proc.stdout.decode(errors="replace").split("\0")):
            if not _TRUSTED_CONFIG_KEYS.match(key.lower()):
                raise RemoteUntrusted(f"the remote's config carries {key!r}, outside the allowlist")

    def _git(self, *args: str, stdin: bytes | None = None, check: bool = True,
             extra_env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        with tempfile.TemporaryDirectory(prefix="fixture-service-git-") as home:
            env = _git_environment(home)
            self._check_trusted(env)
            if extra_env:
                env.update(extra_env)
            return subprocess.run(
                ["git", "-c", f"user.name={SERVICE_IDENTITY[0]}", "-c", f"user.email={SERVICE_IDENTITY[1]}",
                 "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                 "--git-dir", str(self.path), *args],
                input=stdin, env=env, capture_output=True, timeout=30, check=check,
                umask=0o022)  # what the controller writes stays controller-only

    @staticmethod
    def _answer(proc: subprocess.CompletedProcess[bytes], what: str) -> bool:
        """Exit 0 is yes, exit 1 is git's documented no; anything else is a
        failure to look, never an answer (counter-model review)."""
        if proc.returncode in (0, 1):
            return proc.returncode == 0
        raise RuntimeError(f"git {what} failed (exit {proc.returncode}): {proc.stderr.decode(errors='replace')}")

    def resolve(self, ref: str) -> str | None:
        proc = self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        return (proc.stdout.decode().strip() or None) if self._answer(proc, "rev-parse") else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._answer(self._git("merge-base", "--is-ancestor", ancestor, descendant, check=False),
                            "merge-base --is-ancestor")

    def merge_base(self, a: str, b: str) -> str | None:
        proc = self._git("merge-base", a, b, check=False)
        return (proc.stdout.decode().strip() or None) if self._answer(proc, "merge-base") else None

    def diff_files(self, base: str, head: str) -> list[dict[str, Any]]:
        out = self._git("diff", "--numstat", "--no-renames", "-z", base, head).stdout.decode()
        files = []
        for entry in filter(None, out.split("\0")):
            added, deleted, path = entry.split("\t", 2)
            files.append({"path": path, "additions": int(added) if added != "-" else 0,
                          "deletions": int(deleted) if deleted != "-" else 0})
        return files

    def commits(self, base: str, head: str) -> list[dict[str, Any]]:
        out = self._git("log", "--reverse", "-z", "--format=%H%x1f%s%x1f%b", f"{base}..{head}").stdout.decode()
        result = []
        for entry in filter(None, (e.lstrip("\n") for e in out.split("\0"))):
            oid, headline, body = entry.split("\x1f", 2)
            result.append({"oid": oid, "messageHeadline": headline, "messageBody": body.rstrip("\n")})
        return result

    def merge_tree(self, base: str, head: str) -> str | None:
        proc = self._git("merge-tree", "--write-tree", "--no-messages", base, head, check=False)
        if proc.returncode == 0:
            return proc.stdout.decode().split("\n", 1)[0].strip()
        if proc.returncode == 1:
            return None  # conflicted
        raise RuntimeError(f"git merge-tree failed: {proc.stderr.decode(errors='replace')}")

    def commit_tree(self, tree: str, parent: str, message: str, date: str) -> str:
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        return self._git("commit-tree", tree, "-p", parent, "-F", "-", stdin=message.encode(),
                         extra_env=env).stdout.decode().strip()

    def update_ref(self, ref: str, new: str, old: str) -> bool:
        """`False` only when the CAS genuinely lost: the ref no longer holds
        `old`. Any other failure (a lock, a permission) raises, so it is an
        error event, never a `base-moved` answer (counter-model review)."""
        proc = self._git("update-ref", ref, new, old, check=False)
        if proc.returncode == 0:
            return True
        if self.resolve(ref) != old:
            return False
        raise RuntimeError(f"git update-ref failed with {ref} still at {old}: "
                           f"{proc.stderr.decode(errors='replace')}")

    def delete_ref(self, ref: str, old: str) -> bool:
        return self._git("update-ref", "-d", ref, old, check=False).returncode == 0


def _canonical(value: Any) -> bytes:
    # ensure_ascii keeps this total over every str JSON can carry, lone
    # surrogates included (counter-model review), so no request can make
    # the record unserializable.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _has_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    if isinstance(value, Mapping):
        return any(_has_surrogate(k) or _has_surrogate(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_surrogate(v) for v in value)
    return False


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: object, what: str) -> datetime:
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text):
        raise DeclarationRefused(f"{what} must be YYYY-MM-DDTHH:MM:SSZ")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def measure_jq(jq_path: str | None = None) -> tuple[str | None, str | None]:
    """`(path, version)` of the controller's jq, or `(None, reason)`."""
    path = jq_path or shutil.which("jq")
    if not path:
        return None, "jq is not installed on the controller"
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, timeout=_JQ_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"jq --version failed: {exc}"
    version = proc.stdout.decode(errors="replace").strip()
    if proc.returncode != 0 or not JQ_VERSION_PATTERN.match(version):
        return None, f"jq version {version!r} is not 1.7.x"
    return path, version


def run_jq(jq_path: str, jq_filter: str, value: Any) -> tuple[int, str, str]:
    """Run one allowlisted filter through real jq: `(exit, stdout, stderr)`.
    `-r -c` gives gh's own rendering: strings raw, everything else compact JSON."""
    data = _canonical(value)
    if len(data) > _MAX_JQ_INPUT:
        raise _Unsupported(f"jq input of {len(data)} bytes exceeds the {_MAX_JQ_INPUT}-byte bound")
    try:
        proc = subprocess.run([jq_path, "-r", "-c", jq_filter], input=data, capture_output=True,
                              timeout=_JQ_TIMEOUT, check=False, env={"PATH": os.defpath, "LC_ALL": "C.UTF-8"})
    except subprocess.TimeoutExpired as exc:
        raise _Unsupported(f"jq did not finish within {_JQ_TIMEOUT}s") from exc
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), proc.stderr.decode("utf-8", errors="replace")


# --- the closed argv grammar ----------------------------------------------

@dataclass(frozen=True)
class _Flag:
    name: str
    takes_value: bool
    aliases: tuple[str, ...] = ()


_REPO = _Flag("repo", True, ("-R",))
_JSON = _Flag("json", True)
_JQ = _Flag("jq", True, ("-q",))
_LIMIT = _Flag("limit", True, ("-L",))
_SEARCH = _Flag("search", True, ("-S",))
_BODY = _Flag("body", True, ("-b",))
_BODY_FILE = _Flag("body-file", True, ("-F",))

#: (words) -> (op, flags, (min positionals, max positionals))
_COMMANDS: dict[tuple[str, ...], tuple[str, tuple[_Flag, ...], tuple[int, int]]] = {
    ("auth", "status"): ("auth.status", (), (0, 0)),
    ("repo", "view"): ("repo.view", (_REPO, _JSON, _JQ), (0, 0)),
    ("api",): ("api.get", (_JQ, _Flag("paginate", False), _Flag("header", True, ("-H",))), (1, 1)),
    ("issue", "view"): ("issue.view", (_REPO, _JSON, _JQ), (1, 1)),
    ("issue", "list"): ("issue.list", (_REPO, _Flag("state", True, ("-s",)), _SEARCH, _LIMIT, _JSON, _JQ), (0, 0)),
    ("issue", "close"): ("issue.close", (_REPO, _Flag("comment", True, ("-c",)), _Flag("reason", True, ("-r",))),
                         (1, 1)),
    ("issue", "comment"): ("issue.comment", (_REPO, _BODY, _BODY_FILE), (1, 1)),
    ("pr", "view"): ("pr.view", (_REPO, _JSON, _JQ), (0, 1)),
    ("pr", "list"): ("pr.list", (_REPO, _Flag("state", True, ("-s",)), _Flag("head", True, ("-H",)),
                                 _Flag("base", True, ("-B",)), _SEARCH, _LIMIT, _JSON, _JQ), (0, 0)),
    ("pr", "create"): ("pr.create", (_REPO, _Flag("title", True, ("-t",)), _BODY, _BODY_FILE,
                                     _Flag("base", True, ("-B",)), _Flag("head", True, ("-H",))), (0, 0)),
    ("pr", "edit"): ("pr.edit", (_REPO, _Flag("base", True, ("-B",)), _Flag("title", True, ("-t",)), _BODY),
                     (1, 1)),
    ("pr", "merge"): ("pr.merge", (_REPO, _Flag("squash", False, ("-s",)), _Flag("subject", True, ("-t",)),
                                   _BODY, _BODY_FILE, _Flag("delete-branch", False, ("-d",)),
                                   _Flag("admin", False)), (0, 1)),
    ("run", "list"): ("run.list", (_REPO, _Flag("commit", True, ("-c",)), _Flag("branch", True, ("-b",)),
                                   _LIMIT, _JSON, _JQ), (0, 0)),
    ("run", "view"): ("run.view", (_REPO, _JSON, _JQ), (1, 1)),
}


@dataclass(frozen=True)
class Command:
    op: str
    positionals: tuple[str, ...]
    flags: Mapping[str, Any]


def parse_argv(argv: Sequence[str]) -> Command:
    """Parse one gh argv against the closed grammar. Raises `_Unsupported`
    (also exposed as `Unsupported`) for anything outside it."""
    args = list(argv)
    for words in sorted(_COMMANDS, key=len, reverse=True):
        if tuple(args[:len(words)]) == words:
            op, flags, (lo, hi) = _COMMANDS[words]
            rest = args[len(words):]
            break
    else:
        raise _Unsupported(f"gh {' '.join(args[:2])!s}: subcommand outside the declared grammar")
    by_name = {f"--{f.name}": f for f in flags}
    by_name.update({alias: f for f in flags for alias in f.aliases})
    values: dict[str, Any] = {}
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--":
            positionals.extend(rest[i + 1:])
            break
        if token.startswith("-") and token != "-":
            name, eq, inline = token.partition("=")
            flag = by_name.get(name)
            if flag is None:
                raise _Unsupported(f"flag {name!r} is outside the declared grammar for {op}")
            if flag.takes_value:
                if eq:
                    value = inline
                elif i + 1 < len(rest):
                    i += 1
                    value = rest[i]
                else:
                    raise _GhError("usage", f"flag needs an argument: {name}\n")
                if flag.name == "header":
                    values.setdefault("header", []).append(value)
                else:
                    values[flag.name] = value
            else:
                if eq:
                    raise _Unsupported(f"flag {name!r} takes no value")
                values[flag.name] = True
        else:
            positionals.append(token)
        i += 1
    if not lo <= len(positionals) <= hi:
        raise _GhError("usage", f"{op}: expected {lo}..{hi} positional argument(s), got {len(positionals)}\n")
    return Command(op, tuple(positionals), values)


Unsupported = _Unsupported


# --- dispatch on the one socket ---------------------------------------------

def dispatch(routes: Mapping[str, tuple[DecideFn, frozenset[str]]]) -> DecideFn:
    """One `decide` for one attempt's one socket (orchestrator ruling (a)).
    A request is routed by `op` ALONE to exactly one route, and refused unless
    every one of its keys is in THAT route's closed key set - so a request
    carrying another route's fields (a mixed request) is refused, never
    forwarded with the foreign fields ignored. An op no route enables is
    refused. No route ever sees another route's request."""
    frozen: dict[str, tuple[DecideFn, frozenset[str]]] = {}
    for op, (fn, keys) in routes.items():
        if "op" not in keys:
            raise ValueError(f"route {op!r}: its key set must include 'op'")
        frozen[op] = (fn, frozenset(keys))

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        op = request.get("op")
        if not isinstance(op, str) or op not in frozen:
            raise ChannelRefusal(f"op {op!r} is not enabled for this attempt")
        fn, keys = frozen[op]
        extra = sorted(set(request) - keys)
        if extra:
            raise ChannelRefusal(f"op {op!r} does not accept field(s) {extra}")
        return fn(request)

    return decide


# --- the service --------------------------------------------------------------

@dataclass(frozen=True)
class FixtureServiceRecord:
    attempt_id: str
    repository: str
    declaration_digest: str
    jq: Mapping[str, Any]
    coverage: str  # "witnessed" | "no-controller-witness" | "channel-unavailable"
    coverage_complete: bool
    unsupported_events: tuple[int, ...]
    error_events: tuple[int, ...]
    events: tuple[Mapping[str, Any], ...]
    final_state: Mapping[str, Any]
    faults: tuple[Mapping[str, Any], ...]
    remote_integrity: str  # "SATISFIED" | "VIOLATED" | "UNKNOWN"
    divergence: tuple[Mapping[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        payload = {
            "fixture_service_schema": SCHEMA_VERSION, "attempt_id": self.attempt_id,
            "repository": self.repository, "declaration_digest": self.declaration_digest,
            "jq": dict(self.jq), "coverage": self.coverage, "coverage_complete": self.coverage_complete,
            "unsupported_events": list(self.unsupported_events), "error_events": list(self.error_events),
            "events": [dict(e) for e in self.events],
            "final_state": dict(self.final_state), "faults": [dict(f) for f in self.faults],
            "remote_integrity": self.remote_integrity, "divergence": [dict(d) for d in self.divergence],
        }
        payload["record_digest"] = _digest(payload)
        return payload

    def to_json_bytes(self) -> bytes:
        return _canonical(self.to_json())


_PR_FIELDS = frozenset({
    "number", "title", "body", "state", "url", "headRefName", "headRefOid", "baseRefName", "mergeCommit",
    "mergedAt", "createdAt", "updatedAt", "closedAt", "isCrossRepository", "changedFiles", "files", "commits",
    "mergeable", "reviewDecision", "statusCheckRollup", "author",
})
_ISSUE_FIELDS = frozenset({"number", "title", "body", "state", "url", "createdAt", "updatedAt", "closedAt",
                           "labels", "comments", "author"})
_REPO_FIELDS = frozenset({"nameWithOwner", "name", "owner", "url", "viewerPermission", "defaultBranchRef"})
_RUN_FIELDS = frozenset({"status", "conclusion", "databaseId", "url", "event", "name", "headSha", "jobs"})
_SEARCH_QUALIFIER = re.compile(r"^(merged|created|closed):(>=|<=|>|<)?(\d{4}-\d\d-\d\d)$")


class FixtureService:
    """Declared GitHub state for ONE repository, answered over #183's channel.

    Usage:

        service = FixtureService(declaration, LocalGitRemote(bare), "attempt-1")
        channel = DecideReplyChannel(socket, dispatch({"gh": (service.decide, REQUEST_KEYS)}), "attempt-1")
        ... run the attempt ...
        channel.stop_and_finalize()
        record = service.finalize("attempt-1")
    """

    def __init__(self, declaration: Mapping[str, Any], remote: GitRemote, attempt_id: str, *,
                 jq_path: str | None = None, order: Order | None = None) -> None:
        self._declaration = copy.deepcopy(dict(declaration))
        #: #279 PR-2a: the attempt's controller-owned ordering counter, or None.
        #: Supplied only for a multi-turn attempt; then every event (a malformed
        #: request's too) carries `order`, taken here, in the controller.
        self._order = order
        self._remote = remote
        self.attempt_id = attempt_id
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._finalized: FixtureServiceRecord | None = None
        self.channel_unavailable = False
        self._jq_path, jq_detail = measure_jq(jq_path)
        self._jq = {"path_found": self._jq_path is not None,
                    "version": jq_detail if self._jq_path else None,
                    "unavailable_reason": None if self._jq_path else jq_detail}
        self._load(self._declaration)

    # -- declaration --------------------------------------------------------

    def _load(self, decl: dict[str, Any]) -> None:
        if decl.get("fixture_service_schema") != SCHEMA_VERSION:
            raise DeclarationRefused("fixture_service_schema must be 1")
        allowed = {"fixture_service_schema", "repository", "authority", "clock", "issues", "pull_requests", "faults"}
        if set(decl) - allowed:
            raise DeclarationRefused(f"unknown declaration key(s): {sorted(set(decl) - allowed)}")
        repo = decl.get("repository")
        if not isinstance(repo, dict) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
                                                         str(repo.get("name_with_owner", ""))):
            raise DeclarationRefused("repository.name_with_owner must be OWNER/NAME")
        self.repository = repo["name_with_owner"]
        self._default = str(repo.get("default_branch") or "")
        if not self._default:
            raise DeclarationRefused("repository.default_branch is required")
        urls = repo.get("remote_urls")
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) and u for u in urls):
            raise DeclarationRefused("repository.remote_urls must be a non-empty list of strings")
        self._remote_urls = frozenset(u.rstrip("/") for u in urls)
        self._permission = repo.get("viewer_permission", "WRITE")
        authority = decl.get("authority")
        if not isinstance(authority, list) or set(authority) - set(OPS):
            raise DeclarationRefused(f"authority must be a list drawn from {OPS}")
        self._authority = frozenset(authority)
        clock = decl.get("clock") or {}
        self._clock_start = _parse_iso(clock.get("start"), "clock.start")
        self._clock_step = int(clock.get("step_seconds", 60))
        if self._clock_step <= 0:
            raise DeclarationRefused("clock.step_seconds must be positive")
        tip = self._remote.resolve(f"refs/heads/{self._default}")
        if tip is None:
            raise DeclarationRefused(f"the remote has no refs/heads/{self._default}")
        self._expected_tip = tip
        self._recorded_merges: list[str] = []
        issues: dict[int, dict[str, Any]] = {}
        prs: dict[int, dict[str, Any]] = {}
        for entry in decl.get("issues", []):
            n = self._number(entry, issues, prs)
            state = entry.get("state", "OPEN")
            if state not in ("OPEN", "CLOSED"):
                raise DeclarationRefused(f"issue #{n}: state must be OPEN or CLOSED")
            created = _iso(_parse_iso(entry.get("created_at"), f"issue #{n} created_at"))
            issues[n] = {"number": n, "title": str(entry.get("title", "")), "body": str(entry.get("body", "")),
                         "state": state, "created_at": created, "updated_at": created,
                         "closed_at": entry.get("closed_at") if state == "CLOSED" else None,
                         "labels": [str(x) for x in entry.get("labels", [])],
                         "comments": [], "closed_by": {"kind": "declared"} if state == "CLOSED" else None}
        for entry in decl.get("pull_requests", []):
            n = self._number(entry, issues, prs)
            state = entry.get("state")
            if state != "MERGED":
                raise DeclarationRefused(f"PR #{n}: only already-MERGED pull requests may be declared")
            merge_commit = str(entry.get("merge_commit", ""))
            if not merge_commit or not self._remote.resolve(merge_commit) \
                    or not self._remote.is_ancestor(merge_commit, tip):
                raise DeclarationRefused(f"PR #{n}: declared-merge-not-in-remote ({merge_commit!r} is not on "
                                         f"{self._default})")
            parent = self._remote.resolve(f"{merge_commit}^")
            created = _iso(_parse_iso(entry.get("created_at"), f"PR #{n} created_at"))
            merged = _iso(_parse_iso(entry.get("merged_at"), f"PR #{n} merged_at"))
            prs[n] = {"number": n, "title": str(entry.get("title", "")), "body": str(entry.get("body", "")),
                      "head_ref": str(entry.get("head_ref", f"issue-{n}")), "base_ref": self._default,
                      "state": "MERGED", "created_at": created, "updated_at": merged, "merged_at": merged,
                      "closed_at": merged, "merge_commit": merge_commit,
                      "head_oid": str(entry.get("head_oid") or merge_commit),
                      "files": self._remote.diff_files(parent, merge_commit) if parent else [],
                      "commits": [{"oid": str(entry.get("head_oid") or merge_commit),
                                   "messageHeadline": str(entry.get("title", "")), "messageBody": ""}]}
            self._recorded_merges.append(merge_commit)
        top = max([*issues, *prs], default=0)
        self._state: dict[str, Any] = {"issues": issues, "prs": prs, "next_number": top + 1, "next_comment": 1}
        self._faults = []
        for raw in decl.get("faults", []):
            kind = raw.get("kind")
            if kind == "lost-response" and raw.get("op") in OPS and set(raw) <= {"kind", "op", "number"}:
                self._faults.append({**raw, "fired": False, "fired_at_seq": None})
            elif kind == "stale-read" and raw.get("after") in OPS and raw.get("read") in READ_OPS \
                    and set(raw) <= {"kind", "after", "read"}:
                self._faults.append({**raw, "fired": False, "fired_at_seq": None, "armed_at_seq": None})
            else:
                raise DeclarationRefused(f"unsupported fault declaration: {raw!r}")
        self._pending_stale: dict[str, Any] | None = None
        self._divergence: list[dict[str, Any]] = []

    @staticmethod
    def _number(entry: Mapping[str, Any], issues: Mapping[int, Any], prs: Mapping[int, Any]) -> int:
        n = entry.get("number")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0 or n in issues or n in prs:
            raise DeclarationRefused(f"number {n!r} must be a unique positive integer")
        return n

    # -- the channel's decide ----------------------------------------------

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        with self._lock:
            if self._finalized is not None:
                raise ChannelRefusal("fixture service is finalized")
            seq = len(self._events) + 1
            problem = self._schema_problem(request)
            if problem is not None:
                self._events.append({"seq": seq, "attempt_id": self.attempt_id, "decision": "malformed",
                                     "reason": problem, "request_digest": _digest(_jsonable(request)),
                                     **({"order": self._order.next()} if self._order is not None else {})})
                raise ChannelRefusal(f"fixture service: {problem}")
            raw_argv = request["argv"]
            assert isinstance(raw_argv, list)  # established by _schema_problem
            argv = [str(a) for a in raw_argv]
            context = dict(request.get("context") or {})  # type: ignore[call-overload]
            body_files = dict(request.get("body_files") or {})  # type: ignore[call-overload]
            at = _iso(self._clock_start + timedelta(seconds=self._clock_step * seq))
            before = _digest(_jsonable(self._state))
            event: dict[str, Any] = {"seq": seq, "attempt_id": self.attempt_id, "argv": argv,
                                     "argv_digest": _digest(argv), "context": context, "at": at,
                                     "repository": None, "op": None, "effect": None, "fault": None,
                                     "state_before": before}
            if self._order is not None:
                event["order"] = self._order.next()
            try:
                command = parse_argv(argv)
                event["op"] = command.op
                event["repository"] = self._resolve_repository(command, context)
                if command.op not in self._authority or (command.op == "pr.merge" and command.flags.get("admin")
                                                          and "pr.merge.admin" not in self._authority):
                    raise _GhError("unauthorized", "GraphQL: fixture-subject does not have the correct "
                                   f"permissions to execute this operation ({command.op})\n")
                stale = self._stale_for(command.op)
                if stale is not None:
                    stale_fault, snapshot = stale
                    live, self._state = self._state, snapshot
                    try:
                        reply, decision, effect = self._handle(command, context, body_files, at)
                    except _GhError as exc:
                        # A stale "not found" IS the stale answer (pass 2): the
                        # fault is consumed. A usage refusal is not an answer
                        # from the snapshot and must not move the fault point
                        # (pass 3), and neither is an unsupported request.
                        if exc.reason == "not-found":
                            event["fault"] = "stale-read"
                            stale_fault["fired"], stale_fault["fired_at_seq"] = True, seq
                        raise
                    finally:
                        self._state = live
                    event["fault"] = "stale-read"
                    stale_fault["fired"], stale_fault["fired_at_seq"] = True, seq
                else:
                    reply, decision, effect = self._handle(command, context, body_files, at)
                event["reason"] = None
            except _Unsupported as exc:
                reply = {"exit_code": 1, "stdout": "",
                         "stderr": f"skillc fixture service: unsupported: {exc}\n"}
                decision, effect = "unsupported", None
                event["reason"] = str(exc)
            except _GhError as exc:
                reply = {"exit_code": exc.exit_code, "stdout": exc.stdout, "stderr": exc.stderr}
                decision, effect = exc.decision, None
                event["reason"] = exc.reason
            except Exception as exc:  # noqa: BLE001 - recorded, never lost (counter-model review)
                # A failure inside a handler - an untrusted or unreadable
                # remote, a bug - is still an event: its state digests show
                # whatever DID change, and coverage reads incomplete.
                reply = {"exit_code": 1, "stdout": "", "stderr": "skillc fixture service: internal error\n"}
                decision, effect = "error", None
                event["reason"] = f"{type(exc).__name__}: {exc}"
            event["decision"] = decision
            event["effect"] = effect
            if decision == "applied":
                self._arm_stale(event["op"], seq, before)
                lost = self._lost_response_for(event["op"], effect)
                if lost is not None:
                    lost["fired"], lost["fired_at_seq"] = True, seq
                    event["fault"] = "lost-response"
                    event["suppressed_reply"] = reply
                    reply = {"exit_code": 1, "stdout": "", "stderr": _TRANSPORT_ERROR}
            event["state_after"] = _digest(_jsonable(self._state))
            event["reply"] = reply
            self._events.append(event)
            return dict(reply)

    @staticmethod
    def _schema_problem(request: Mapping[str, object]) -> str | None:
        if request.get("op") != GH_OP:
            return f"op {request.get('op')!r} is not {GH_OP!r}"
        extra = set(request) - REQUEST_KEYS
        if extra:
            return f"request field(s) outside the closed schema: {sorted(extra)}"
        argv = request.get("argv")
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            return "argv must be a list of strings"
        context = request.get("context", {})
        if not isinstance(context, dict) or set(context) - CONTEXT_KEYS \
                or not all(v is None or isinstance(v, str) for v in context.values()):
            return "context must map origin_url/branch to strings"
        files = request.get("body_files", {})
        if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in files.items()):
            return "body_files must map paths to base64 strings"
        for value in files.values():
            try:
                base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                return "body_files values must be valid base64"
        if "cwd" in request and not isinstance(request["cwd"], str):
            return "cwd must be a string"
        if _has_surrogate(dict(request)):
            return "request strings must be valid Unicode (a lone surrogate is not)"
        return None

    # -- faults -------------------------------------------------------------

    def _arm_stale(self, op: str, seq: int, before: str) -> None:
        """Give each stale-read fault waiting on `op` its OWN snapshot, taken
        before `op` applied (counter-model review: one shared snapshot let a
        second fault overwrite the first)."""
        for fault in self._faults:
            if fault["kind"] == "stale-read" and fault["after"] == op and fault["armed_at_seq"] is None:
                fault["armed_at_seq"] = seq
                fault["snapshot_digest"] = before
                fault["_snapshot"] = copy.deepcopy(self._pending_stale)

    def _stale_for(self, op: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for fault in self._faults:
            if (fault["kind"] == "stale-read" and fault["read"] == op and fault["armed_at_seq"] is not None
                    and not fault["fired"]):
                return fault, copy.deepcopy(fault["_snapshot"])
        return None

    def _freeze_for_stale(self, op: str) -> None:
        """Before an op some stale-read fault waits on, capture the state AND
        each open PR's remote-derived view, so a stale answer reproduces the
        old payload instead of mixing old state with the live remote."""
        self._pending_stale = None
        if any(f["kind"] == "stale-read" and f["after"] == op and f["armed_at_seq"] is None for f in self._faults):
            snapshot = copy.deepcopy(self._state)
            for n, pr in snapshot["prs"].items():
                if pr["state"] == "OPEN":
                    pr["frozen_view"] = self._pr_json(self._state["prs"][n])
            self._pending_stale = snapshot

    def _lost_response_for(self, op: str, effect: Mapping[str, Any] | None) -> dict[str, Any] | None:
        for fault in self._faults:
            if fault["kind"] == "lost-response" and fault["op"] == op and not fault["fired"]:
                if "number" in fault and (effect or {}).get("number") != fault["number"]:
                    continue
                return fault
        return None

    # -- repository resolution ---------------------------------------------

    def _resolve_repository(self, command: Command, context: Mapping[str, Any]) -> str:
        named = command.flags.get("repo")
        if command.op == "api.get":
            match = re.match(r"^/?repos/([^/{}]+)/([^/{}]+)(/|$)", command.positionals[0])
            if match:
                named = f"{match.group(1)}/{match.group(2)}"
        if named is not None:
            normalized = re.sub(r"^(https://)?github\.com/", "", str(named)).rstrip("/")
            if normalized != self.repository:
                raise _GhError("wrong-repository", f"GraphQL: Could not resolve to a Repository with the name "
                               f"'{normalized}'. (repository)\n")
            return self.repository
        origin = (context.get("origin_url") or "").rstrip("/")
        if origin not in self._remote_urls:
            raise _GhError("wrong-repository", "none of the git remotes configured for this repository point "
                           "to a known GitHub host. To tell gh about a new GitHub host, please use "
                           "`gh auth login`\n")
        return self.repository

    # -- handlers -------------------------------------------------------------

    def _handle(self, command: Command, context: Mapping[str, Any], body_files: Mapping[str, str],
                at: str) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        if command.op not in READ_OPS:
            self._freeze_for_stale(command.op)
        handler: Callable[..., tuple[dict[str, Any], str, dict[str, Any] | None]] = getattr(
            self, "_op_" + command.op.replace(".", "_"))
        return handler(command, context, body_files, at)

    def _output(self, command: Command, value: Any, allowed: frozenset[str], plain: Callable[[], str]
                ) -> dict[str, Any]:
        json_fields = command.flags.get("json")
        jq_filter = command.flags.get("jq")
        if json_fields is None:
            if jq_filter is not None:
                raise _GhError("usage", "cannot use `--jq` without specifying `--json`\n")
            return {"exit_code": 0, "stdout": plain(), "stderr": ""}
        fields = [f for f in str(json_fields).split(",") if f]
        unknown = sorted(set(fields) - allowed)
        if not fields or unknown:
            raise _Unsupported(f"--json field(s) outside the modelled set: {unknown or '(none given)'}")
        if isinstance(value, list):
            shaped: Any = [{f: item[f] for f in fields} for item in value]
        else:
            shaped = {f: value[f] for f in fields}
        return self._render(shaped, jq_filter)

    def _render(self, value: Any, jq_filter: str | None) -> dict[str, Any]:
        if jq_filter is None:
            return {"exit_code": 0, "stdout": json.dumps(value, ensure_ascii=False) + "\n", "stderr": ""}
        if jq_filter not in JQ_ALLOWLIST:
            raise _Unsupported(f"--jq filter outside the allowlist: {jq_filter!r}")
        if self._jq_path is None:
            raise _Unsupported(f"real jq is unavailable on the controller: {self._jq['unavailable_reason']}")
        code, out, err = run_jq(self._jq_path, jq_filter, value)
        return {"exit_code": 0 if code == 0 else 1, "stdout": out, "stderr": err}

    def _url(self, kind: str, n: int) -> str:
        return f"https://github.com/{self.repository}/{kind}/{n}"

    def _issue(self, n: int) -> dict[str, Any]:
        issue = self._state["issues"].get(n)
        if issue is None:
            if n in self._state["prs"]:
                raise _GhError("not-found", f"#{n} is a pull request, not an issue\n")
            raise _GhError("not-found", f"GraphQL: Could not resolve to an issue with the number of {n}. "
                           "(repository.issue)\n")
        return issue

    def _pr(self, n: int) -> dict[str, Any]:
        pr = self._state["prs"].get(n)
        if pr is None:
            raise _GhError("not-found", f"GraphQL: Could not resolve to a PullRequest with the number of {n}. "
                           "(repository.pullRequest)\n")
        return pr

    @staticmethod
    def _int(token: str) -> int:
        token = token.lstrip("#")
        if not token.isdigit():
            raise _Unsupported(f"{token!r} is not a number (URL and branch forms are outside the grammar here)")
        return int(token)

    def _issue_json(self, issue: Mapping[str, Any]) -> dict[str, Any]:
        return {"number": issue["number"], "title": issue["title"], "body": issue["body"],
                "state": issue["state"], "url": self._url("issues", issue["number"]),
                "createdAt": issue["created_at"], "updatedAt": issue["updated_at"], "closedAt": issue["closed_at"],
                "labels": [{"name": name} for name in issue["labels"]],
                "comments": [{"author": {"login": c["author"]}, "body": c["body"], "createdAt": c["created_at"]}
                             for c in issue["comments"]],
                "author": {"login": SUBJECT_LOGIN}}

    def _pr_live(self, pr: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """`(head, base)` SHAs as the remote holds them now, for an open PR."""
        return (self._remote.resolve(f"refs/heads/{pr['head_ref']}"),
                self._remote.resolve(f"refs/heads/{pr['base_ref']}"))

    def _pr_json(self, pr: Mapping[str, Any]) -> dict[str, Any]:
        if "frozen_view" in pr:
            return copy.deepcopy(pr["frozen_view"])
        files, commits, head_oid, mergeable = pr["files"], pr["commits"], pr["head_oid"], "UNKNOWN"
        if pr["state"] == "OPEN":
            head, base = self._pr_live(pr)
            if head and base:
                head_oid = head
                fork = self._remote.merge_base(base, head) or base
                files, commits = self._remote.diff_files(fork, head), self._remote.commits(fork, head)
                mergeable = "MERGEABLE" if self._remote.merge_tree(base, head) else "CONFLICTING"
        return {"number": pr["number"], "title": pr["title"], "body": pr["body"], "state": pr["state"],
                "url": self._url("pull", pr["number"]), "headRefName": pr["head_ref"], "headRefOid": head_oid,
                "baseRefName": pr["base_ref"],
                "mergeCommit": {"oid": pr["merge_commit"]} if pr["merge_commit"] else None,
                "mergedAt": pr["merged_at"], "createdAt": pr["created_at"], "updatedAt": pr["updated_at"],
                "closedAt": pr["closed_at"], "isCrossRepository": False, "changedFiles": len(files),
                "files": files, "commits": commits, "mergeable": mergeable, "reviewDecision": "",
                "statusCheckRollup": [], "author": {"login": SUBJECT_LOGIN}}

    def _repo_json(self) -> dict[str, Any]:
        owner, name = self.repository.split("/")
        return {"nameWithOwner": self.repository, "name": name, "owner": {"login": owner},
                "url": f"https://github.com/{self.repository}", "viewerPermission": self._permission,
                "defaultBranchRef": {"name": self._default}}

    def _op_auth_status(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        return ({"exit_code": 0, "stdout": "", "stderr": f"github.com\n  Logged in to github.com account "
                 f"{SUBJECT_LOGIN} (skillc fixture service)\n"}, "read", None)

    def _op_repo_view(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        repo = self._repo_json()
        return (self._output(command, repo, _REPO_FIELDS, lambda: f"name:\t{self.repository}\ndescription:\t\n"),
                "read", None)

    def _op_api_get(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        path = command.positionals[0].lstrip("/").replace("{owner}/{repo}", self.repository)
        base = f"repos/{self.repository}"
        branch_tail = re.fullmatch(re.escape(base) + r"/branches/([^/]+)/protection/required_status_checks", path)
        rules = re.fullmatch(re.escape(base) + r"/rules/branches/([^/]+)", path)
        files = re.fullmatch(re.escape(base) + r"/pulls/(\d+)/files", path)
        if path == base:
            value: Any = {"default_branch": self._default, "full_name": self.repository,
                          "name": self.repository.split("/")[1], "private": True}
        elif branch_tail:
            body = {"message": "Branch not protected", "status": "404"}
            raise _GhError("simulated-absent", "gh: Branch not protected (HTTP 404)\n",
                           stdout=json.dumps(body) + "\n", decision="read")
        elif rules:
            value = []
        elif files:
            value = [{"filename": f["path"], "status": "modified", "additions": f["additions"],
                      "deletions": f["deletions"], "changes": f["additions"] + f["deletions"]}
                     for f in self._pr_json(self._pr(int(files.group(1))))["files"]]
        else:
            raise _Unsupported(f"api path outside the declared set: {path!r}")
        return self._render(value, command.flags.get("jq")), "read", None

    def _op_issue_view(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        issue = self._issue_json(self._issue(self._int(command.positionals[0])))
        plain = lambda: (f"title:\t{issue['title']}\nstate:\t{issue['state']}\nauthor:\t{SUBJECT_LOGIN}\n"
                         f"labels:\t{', '.join(x['name'] for x in issue['labels'])}\n"
                         f"comments:\t{len(issue['comments'])}\nnumber:\t{issue['number']}\n--\n{issue['body']}\n")
        return self._output(command, issue, _ISSUE_FIELDS, plain), "read", None

    def _limit(self, command: Command) -> int:
        raw = command.flags.get("limit", "30")
        if not str(raw).isdigit() or int(raw) <= 0:
            raise _GhError("usage", f"invalid value for --limit: {raw}\n")
        return int(raw)

    def _search(self, query: str | None, items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        if not query:
            return items
        try:
            tokens = shlex.split(query)
        except ValueError as exc:
            raise _Unsupported(f"search query does not tokenize: {exc}") from exc
        fields: tuple[str, ...] = ("title", "body")
        terms: list[str] = []
        dates: list[tuple[str, str, str]] = []
        states: list[str] = []
        for token in tokens:
            if token in ("in:title", "in:body"):
                fields = (token[3:],) if fields == ("title", "body") else tuple({*fields, token[3:]})
            elif (match := _SEARCH_QUALIFIER.match(token)):
                dates.append((match.group(1), match.group(2) or "=", match.group(3)))
            elif token in ("is:open", "is:closed", "is:merged"):
                states.append(token[3:].upper())
            elif ":" in token:
                raise _Unsupported(f"search qualifier outside the declared set: {token!r}")
            else:
                terms.append(token.lower())

        def keep(item: Mapping[str, Any]) -> bool:
            haystack = " ".join(str(item[f]) for f in fields).lower()
            if not all(t in haystack for t in terms):
                return False
            for want in states:
                if want == "CLOSED" and item["state"] not in ("CLOSED", "MERGED"):
                    return False
                if want != "CLOSED" and item["state"] != want:
                    return False
            for which, op, day in dates:
                stamp = item.get(f"{which}_at")
                if not stamp:
                    return False
                value = stamp[:10]
                if not {"=": value == day, ">=": value >= day, "<=": value <= day,
                        ">": value > day, "<": value < day}[op]:
                    return False
            return True

        return [item for item in items if keep(item)]

    def _op_issue_list(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        state = str(command.flags.get("state", "open")).lower()
        if state not in ("open", "closed", "all"):
            raise _GhError("usage", f"invalid argument \"{state}\" for \"--state\"\n")
        items = [i for _, i in sorted(self._state["issues"].items(), reverse=True)
                 if state == "all" or i["state"] == state.upper()]
        items = self._search(command.flags.get("search"), items, "issue")[: self._limit(command)]
        shaped = [self._issue_json(i) for i in items]
        plain = lambda: "".join(f"{i['number']}\t{i['state']}\t{i['title']}\n" for i in shaped)
        return self._output(command, shaped, _ISSUE_FIELDS, plain), "read", None

    def _body(self, command: Command, body_files: Mapping[str, str], flag: str = "body") -> str | None:
        if command.flags.get(flag) is not None:
            return str(command.flags[flag])
        path = command.flags.get("body-file")
        if path is None:
            return None
        if path not in body_files:
            raise _GhError("usage", f"open {path}: no such file or directory\n")
        return base64.b64decode(body_files[path]).decode("utf-8", errors="replace")

    def _comment(self, issue: dict[str, Any], body: str, at: str) -> int:
        comment_id = self._state["next_comment"]
        self._state["next_comment"] += 1
        issue["comments"].append({"id": comment_id, "author": SUBJECT_LOGIN, "body": body, "created_at": at})
        issue["updated_at"] = at
        return comment_id

    def _op_issue_close(self, command: Command, context: Any, body_files: Any, at: str
                        ) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        n = self._int(command.positionals[0])
        issue = self._issue(n)
        reason = command.flags.get("reason")
        if reason is not None and reason not in ("completed", "not planned"):
            raise _GhError("usage", f"invalid argument \"{reason}\" for \"--reason\"\n")
        if issue["state"] == "CLOSED":
            return ({"exit_code": 0, "stdout": "",
                     "stderr": f"! Issue {self.repository}#{n} ({issue['title']}) is already closed\n"},
                    "read", None)
        effect: dict[str, Any] = {"number": n, "closed": True, "reason": reason or "completed"}
        comment = command.flags.get("comment")
        if comment is not None:
            effect["comment_id"] = self._comment(issue, str(comment), at)
        issue.update(state="CLOSED", closed_at=at, updated_at=at, closed_by={"kind": "command", "at": at})
        return ({"exit_code": 0, "stdout": "",
                 "stderr": f"✓ Closed issue {self.repository}#{n} ({issue['title']})\n"}, "applied", effect)

    def _op_issue_comment(self, command: Command, context: Any, body_files: Mapping[str, str], at: str
                          ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        n = self._int(command.positionals[0])
        issue = self._issue(n)
        body = self._body(command, body_files)
        if not body:
            raise _GhError("usage", "`--body` or `--body-file` required when not running interactively\n")
        comment_id = self._comment(issue, body, at)
        return ({"exit_code": 0, "stdout": f"{self._url('issues', n)}#issuecomment-{comment_id}\n", "stderr": ""},
                "applied", {"number": n, "comment_id": comment_id})

    def _pr_for_branch(self, branch: str | None) -> dict[str, Any]:
        if not branch:
            raise _GhError("not-found", "could not determine current branch: not on any branch\n")
        candidates = [p for _, p in sorted(self._state["prs"].items(), reverse=True) if p["head_ref"] == branch]
        open_first = [p for p in candidates if p["state"] == "OPEN"] or candidates
        if not open_first:
            raise _GhError("not-found", f"no pull requests found for branch \"{branch}\"\n")
        return open_first[0]

    def _select_pr(self, command: Command, context: Mapping[str, Any]) -> dict[str, Any]:
        if command.positionals:
            token = command.positionals[0]
            if token.lstrip("#").isdigit():
                return self._pr(int(token.lstrip("#")))
            return self._pr_for_branch(token)
        return self._pr_for_branch(context.get("branch"))

    def _op_pr_view(self, command: Command, context: Mapping[str, Any], *_: Any) -> tuple[dict[str, Any], str, None]:
        pr = self._pr_json(self._select_pr(command, context))
        plain = lambda: (f"title:\t{pr['title']}\nstate:\t{pr['state']}\nauthor:\t{SUBJECT_LOGIN}\n"
                         f"number:\t{pr['number']}\nurl:\t{pr['url']}\n--\n{pr['body']}\n")
        return self._output(command, pr, _PR_FIELDS, plain), "read", None

    def _op_pr_list(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        state = str(command.flags.get("state", "open")).lower()
        wanted = {"open": ("OPEN",), "closed": ("CLOSED", "MERGED"), "merged": ("MERGED",),
                  "all": ("OPEN", "CLOSED", "MERGED")}.get(state)
        if wanted is None:
            raise _GhError("usage", f"invalid argument \"{state}\" for \"--state\"\n")
        items = [p for _, p in sorted(self._state["prs"].items(), reverse=True) if p["state"] in wanted
                 and command.flags.get("head") in (None, p["head_ref"])
                 and command.flags.get("base") in (None, p["base_ref"])]
        items = self._search(command.flags.get("search"), items, "pr")[: self._limit(command)]
        shaped = [self._pr_json(p) for p in items]
        plain = lambda: "".join(f"{p['number']}\t{p['title']}\t{p['headRefName']}\t{p['state']}\n"
                                for p in shaped)
        return self._output(command, shaped, _PR_FIELDS, plain), "read", None

    def _op_pr_create(self, command: Command, context: Mapping[str, Any], body_files: Mapping[str, str], at: str
                      ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        title = command.flags.get("title")
        body = self._body(command, body_files)
        if title is None or body is None:
            raise _GhError("usage", "must provide `--title` and `--body` (or `--fill`) when not running "
                           "interactively\n")
        head_ref = command.flags.get("head") or context.get("branch")
        base_ref = command.flags.get("base") or self._default
        if not head_ref:
            raise _GhError("usage", "could not determine the current branch\n")
        for p in self._state["prs"].values():
            if p["head_ref"] == head_ref and p["base_ref"] == base_ref and p["state"] == "OPEN":
                raise _GhError("duplicate-create", f"a pull request for branch \"{head_ref}\" into branch "
                               f"\"{base_ref}\" already exists:\n{self._url('pull', p['number'])}\n")
        head = self._remote.resolve(f"refs/heads/{head_ref}")
        base = self._remote.resolve(f"refs/heads/{base_ref}")
        if head is None or base is None or self._remote.is_ancestor(head, base):
            raise _GhError("no-commits", f"pull request create failed: GraphQL: No commits between {base_ref} and "
                           f"{head_ref} (createPullRequest)\n")
        n = self._state["next_number"]
        self._state["next_number"] += 1
        self._state["prs"][n] = {"number": n, "title": str(title), "body": body, "head_ref": head_ref,
                                 "base_ref": base_ref, "state": "OPEN", "created_at": at, "updated_at": at,
                                 "merged_at": None, "closed_at": None, "merge_commit": None, "head_oid": head,
                                 "files": [], "commits": []}
        return ({"exit_code": 0, "stdout": self._url("pull", n) + "\n", "stderr": ""}, "applied",
                {"number": n, "head_ref": head_ref, "head_oid": head, "base_ref": base_ref, "title": str(title)})

    def _op_pr_edit(self, command: Command, context: Any, body_files: Mapping[str, str], at: str
                    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        pr = self._pr(self._int(command.positionals[0]))
        if pr["state"] != "OPEN":
            raise _GhError("invalid-transition", f"pull request #{pr['number']} is {pr['state'].lower()}\n")
        changes: dict[str, Any] = {}
        if command.flags.get("base") is not None:
            if self._remote.resolve(f"refs/heads/{command.flags['base']}") is None:
                raise _GhError("not-found", f"base branch {command.flags['base']!r} does not exist\n")
            changes["base_ref"] = command.flags["base"]
        for key in ("title", "body"):
            if command.flags.get(key) is not None:
                changes[key] = str(command.flags[key])
        if not changes:
            raise _GhError("usage", "nothing to edit\n")
        pr.update(changes, updated_at=at)
        return ({"exit_code": 0, "stdout": self._url("pull", pr["number"]) + "\n", "stderr": ""}, "applied",
                {"number": pr["number"], **changes})

    def _op_pr_merge(self, command: Command, context: Mapping[str, Any], body_files: Mapping[str, str], at: str
                     ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        pr = self._select_pr(command, context)
        n = pr["number"]
        if not command.flags.get("squash"):
            raise _GhError("usage", "--merge, --rebase, or --squash required when not running interactively\n")
        if pr["state"] != "OPEN":
            raise _GhError("invalid-transition", f"X Pull request {self.repository}#{n} ({pr['title']}) "
                           f"is not open: it is {pr['state'].lower()}\n")
        head, base = self._pr_live(pr)
        if head is None or base is None:
            raise _GhError("not-mergeable", f"X Pull request {self.repository}#{n} is not mergeable: "
                           "its head or base branch is gone\n")
        base_ref = f"refs/heads/{pr['base_ref']}"
        if pr["base_ref"] == self._default and base != self._expected_tip:
            self._divergence.append({"kind": "default-branch-moved-outside-service", "ref": base_ref,
                                     "expected": self._expected_tip, "actual": base, "detected_at": at})
        tree = self._remote.merge_tree(base, head)
        if tree is None:
            raise _GhError("not-mergeable", f"X Pull request {self.repository}#{n} is not mergeable: the merge "
                           "commit cannot be cleanly created.\n")
        fork = self._remote.merge_base(base, head) or base
        files, commits = self._remote.diff_files(fork, head), self._remote.commits(fork, head)
        subject = command.flags.get("subject") or f"{pr['title']} (#{n})"
        squash_body = self._body(command, body_files) or ""
        message = subject + ("\n\n" + squash_body if squash_body else "") + "\n"
        refs = (closing_references(pr["body"] + "\n" + message, self.repository)
                if pr["base_ref"] == self._default else ClosingReferences((), (), ()))
        closing = list(refs.closes)
        merge_commit = self._remote.commit_tree(tree, base, message, at.replace("Z", "+0000"))
        # Everything that can fail is above this line: past the CAS only
        # in-memory bookkeeping and the recorded branch deletion remain.
        if not self._remote.update_ref(base_ref, merge_commit, base):
            raise _GhError("base-moved", f"X Pull request {self.repository}#{n} could not be merged: "
                           "Base branch was modified. Review and try the merge again.\n")
        pr.update(state="MERGED", merged_at=at, closed_at=at, updated_at=at, merge_commit=merge_commit,
                  head_oid=head, files=files, commits=commits)
        if pr["base_ref"] == self._default:
            self._expected_tip = merge_commit
            self._recorded_merges.append(merge_commit)
        effect: dict[str, Any] = {"number": n, "merge_commit": merge_commit, "base_ref": pr["base_ref"],
                                  "base_oid": base, "head_oid": head, "subject": subject, "body": squash_body,
                                  "closed_issues": [], "deleted_branch": None,
                                  "foreign_closing_refs": list(refs.foreign),
                                  "ambiguous_closing_refs": list(refs.ambiguous)}
        if closing:
            for ref in closing:
                issue = self._state["issues"].get(ref)
                if issue is not None and issue["state"] == "OPEN":
                    issue.update(state="CLOSED", closed_at=at, updated_at=at,
                                 closed_by={"kind": "pull_request", "number": n, "at": at})
                    effect["closed_issues"].append(ref)
        stderr = f"✓ Squashed and merged pull request {self.repository}#{n} ({pr['title']})\n"
        if command.flags.get("delete-branch") and pr["head_ref"] != self._default:
            try:
                deleted = self._remote.delete_ref(f"refs/heads/{pr['head_ref']}", head)
            except Exception:  # noqa: BLE001 - the merge stands; the deletion is what failed
                deleted = False
            if deleted:
                effect["deleted_branch"] = pr["head_ref"]
            else:
                effect["branch_delete_failed"] = pr["head_ref"]
                stderr += f"failed to delete remote branch {pr['head_ref']}\n"
        return {"exit_code": 0, "stdout": "", "stderr": stderr}, "applied", effect

    def _op_run_list(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, dict[str, Any]]:
        # No CI is simulated: an empty run list, flagged in the effect so a
        # grader never reads it as "CI ran and found nothing".
        reply = self._output(command, [], _RUN_FIELDS, lambda: "")
        return reply, "read", {"simulated": "no-ci"}

    def _op_run_view(self, command: Command, *_: Any) -> tuple[dict[str, Any], str, None]:
        raise _GhError("simulated-absent", f"could not find any workflow run with ID {command.positionals[0]}\n",
                       decision="read")

    # -- finalize -------------------------------------------------------------

    def finalize(self, attempt_id: str, *, remote: FinalizeRemote | None = None) -> FixtureServiceRecord:
        """The controller's record. Idempotent; refuses a different attempt.

        `remote` (#434) answers the finalize-time divergence check in place of
        the service's own remote. A live attempt's in-containment remote cannot
        exec once the attempt has stopped, so its finalize reads a read-only
        `git_snapshot.SnapshotGitRemote` over the exported copy instead."""
        if attempt_id != self.attempt_id:
            raise ValueError(f"this service belongs to attempt {self.attempt_id!r}, not {attempt_id!r}")
        checked: FinalizeRemote = remote if remote is not None else self._remote
        with self._lock:
            if self._finalized is not None:
                return self._finalized
            divergence = list(self._divergence)
            integrity = "SATISFIED"
            try:
                tip = checked.resolve(f"refs/heads/{self._default}")
                if tip is None:
                    divergence.append({"kind": "default-branch-missing", "ref": f"refs/heads/{self._default}",
                                       "expected": self._expected_tip, "actual": None})
                else:
                    if tip != self._expected_tip:
                        divergence.append({"kind": "default-branch-moved-outside-service",
                                           "ref": f"refs/heads/{self._default}", "expected": self._expected_tip,
                                           "actual": tip, "detected_at": "finalize"})
                    for commit in self._recorded_merges:
                        if not checked.is_ancestor(commit, tip):
                            divergence.append({"kind": "recorded-merge-not-reachable", "commit": commit,
                                               "ref": f"refs/heads/{self._default}", "actual": tip})
            except Exception as exc:  # noqa: BLE001 - an unreadable remote is UNKNOWN, never SATISFIED
                integrity = "UNKNOWN"
                divergence.append({"kind": "remote-unreadable", "detail": str(exc)})
            if integrity != "UNKNOWN" and divergence:
                integrity = "VIOLATED"
            admitted = [e for e in self._events if e["decision"] != "malformed"]
            if self.channel_unavailable:
                coverage = "channel-unavailable"
            elif not admitted:
                coverage = "no-controller-witness"
            else:
                coverage = "witnessed"
            unsupported = tuple(e["seq"] for e in self._events if e["decision"] == "unsupported")
            errors = tuple(e["seq"] for e in self._events if e["decision"] == "error")
            faults = tuple({**{k: v for k, v in f.items() if k != "_snapshot"},
                            "coverage": "fired" if f["fired"] else "UNKNOWN"} for f in self._faults)
            self._finalized = FixtureServiceRecord(
                attempt_id=self.attempt_id, repository=self.repository,
                declaration_digest=_digest(self._declaration), jq=dict(self._jq), coverage=coverage,
                coverage_complete=not unsupported and not errors, unsupported_events=unsupported,
                error_events=errors,
                events=tuple(copy.deepcopy(self._events)), final_state=copy.deepcopy(_jsonable(self._state)),
                faults=faults, remote_integrity=integrity, divergence=tuple(divergence),
            )
            return self._finalized


def _jsonable(value: Any) -> Any:
    """JSON-safe copy: int dict keys become strings, so the record's digest is
    over the same bytes a reader will parse."""
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


__all__ = [
    "CONTEXT_KEYS",
    "GH_OP",
    "JQ_ALLOWLIST",
    "OPS",
    "REQUEST_KEYS",
    "SCHEMA_VERSION",
    "ClosingReferences",
    "Command",
    "DeclarationRefused",
    "FinalizeRemote",
    "FixtureService",
    "FixtureServiceRecord",
    "GitRemote",
    "LocalGitRemote",
    "RemoteUntrusted",
    "Unsupported",
    "closing_references",
    "dispatch",
    "measure_jq",
    "parse_argv",
    "run_jq",
]
