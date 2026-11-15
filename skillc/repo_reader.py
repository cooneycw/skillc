"""Read-only access to the written intent behind a skill: discussions, issues
and pull requests (#778, #718 build step 4).

`charter evidence` reads what the owner already wrote about a skill's charter
before it asks the owner anything. That evidence lives on GitHub, so this
module is the one place skillc talks to it, behind a seam:

- `RepoReader` is the protocol: read one reference, or search a repository.
- `GhReader` runs the `gh` CLI. **Every call is a GraphQL `query`**, and
  `_gh` refuses anything else before a process starts, so a mutation, a
  `gh issue comment` or a REST write can never be issued from here.
- `FakeReader` serves the tests.

A reference that cannot be read raises `RepoReadError` with the reason, and the
caller reports the source as "not examined: <reason>". Nothing here returns an
empty result for a read that failed.

Repository evidence is **observational** (#718's fixed rules): it shows what
someone wrote, never that the skill behaves that way.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

#: How many comments, and replies per comment, one read fetches. A thread
#: longer than this is reported as truncated, never as complete.
PAGE = 100
REPLY_PAGE = 50

#: A `gh` call that takes longer than this is a failed read.
GH_TIMEOUT = 60

KINDS = ("discussion", "issue", "pr")
REF_RE = re.compile(
    r"^(?:(?P<kind>discussion|issue|pr):)?(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#?(?P<number>[1-9][0-9]{0,8})$"
)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoReadError(RuntimeError):
    """The reference could not be read. The message is the reason."""


class ReadOnlyViolation(AssertionError):
    """A call that is not a read-only GraphQL query was about to run."""


@dataclass(frozen=True)
class Ref:
    """One discussion, issue or pull request. `kind` None means "whichever
    this number is": GitHub numbers issues, PRs and discussions from one
    sequence, so a number names exactly one of them."""

    repo: str
    number: int
    kind: str | None = None

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}"


@dataclass(frozen=True)
class Part:
    """The body, or one comment or reply, with the URL that cites it."""

    url: str
    body: str


@dataclass(frozen=True)
class Document:
    ref: Ref
    kind: str  # discussion | issue | pr
    url: str
    title: str
    parts: tuple[Part, ...]
    truncated: bool = False  # more comments exist than one read fetches


class RepoReader(Protocol):
    def read(self, ref: Ref) -> Document: ...

    def search(self, repo: str, term: str) -> list[Ref]: ...


def parse_ref(text: str, default_repo: str | None) -> Ref:
    """`718`, `#718`, `discussion:718`, `owner/name#718` or `issue:owner/name#5`."""
    match = REF_RE.match(text.strip())
    if not match:
        raise ValueError(f"not a reference: {text!r} (expected [discussion:|issue:|pr:][owner/name]#N)")
    repo = match["repo"] or default_repo
    if not repo:
        raise ValueError(f"{text!r} names no repository, and none was given (--repo owner/name)")
    return Ref(repo, int(match["number"]), match["kind"])


# ---------------------------------------------------------------- gh


_THREAD = f"url title body comments(first:{PAGE}){{pageInfo{{hasNextPage}} nodes{{url body}}}}"
_DISCUSSION = (f"url title body comments(first:{PAGE}){{pageInfo{{hasNextPage}} "
               f"nodes{{url body replies(first:{REPLY_PAGE}){{pageInfo{{hasNextPage}} nodes{{url body}}}}}}}}")
_QUERIES = {
    "discussion": "query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){discussion(number:$k){"
                  + _DISCUSSION + "}}}",
    "issue": "query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){issueOrPullRequest(number:$k){"
             "__typename ... on Issue{" + _THREAD + "} ... on PullRequest{" + _THREAD + "}}}}",
}
_SEARCH = ("query($q:String!){issues:search(query:$q,type:ISSUE,first:20){nodes{... on Issue{number} "
           "... on PullRequest{number}}} discussions:search(query:$q,type:DISCUSSION,first:20){nodes{"
           "... on Discussion{number}}}}")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def assert_read_only(argv: Sequence[str]) -> None:
    """The ONLY shape `GhReader` runs: `gh api graphql -f query=<a query>`
    followed by `-f`/`-F` variables. Anything else is refused by name."""
    if len(argv) < 4 or list(argv[:3]) != ["api", "graphql", "-f"] or not argv[3].startswith("query="):
        raise ReadOnlyViolation(f"refused gh call {list(argv)!r}: only `gh api graphql -f query=...` may run")
    query = argv[3][len("query="):].lstrip()
    if not query.startswith("query") or re.search(r"\bmutation\b|\bsubscription\b", query):
        raise ReadOnlyViolation("refused gh call: the GraphQL document is not a read-only query")
    rest = list(argv[4:])
    if len(rest) % 2 or any(flag not in ("-f", "-F") for flag in rest[0::2]):
        raise ReadOnlyViolation(f"refused gh call: unexpected arguments {rest!r}")
    if any(value.split("=", 1)[0] == "query" for value in rest[1::2]):
        raise ReadOnlyViolation("refused gh call: a second query field")


@dataclass
class GhReader:
    """`RepoReader` over the `gh` CLI. `runner` is `subprocess.run` (tests pass
    a fake); `gh` is looked up on PATH when the reader is made."""

    runner: Runner = subprocess.run
    gh: str | None = field(default_factory=lambda: shutil.which("gh"))

    def _gh(self, argv: list[str]) -> dict[str, object]:
        assert_read_only(argv)
        if not self.gh:
            raise RepoReadError("gh not found on PATH")
        try:
            done = self.runner([self.gh, *argv], capture_output=True, text=True, timeout=GH_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RepoReadError(f"gh could not run ({exc.__class__.__name__})") from None
        try:
            data = json.loads(done.stdout) if done.stdout.strip() else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            reason = (done.stderr or "").strip().splitlines()
            raise RepoReadError(f"gh exited {done.returncode}: {reason[-1] if reason else 'no output'}")
        return data

    def _query(self, kind: str, ref: Ref) -> dict[str, object] | None:
        """The node, or None when the number is not this kind (NOT_FOUND)."""
        owner, name = ref.repo.split("/", 1)
        data = self._gh(["api", "graphql", "-f", f"query={_QUERIES[kind]}",
                         "-f", f"o={owner}", "-f", f"n={name}", "-F", f"k={ref.number}"])
        errors = data.get("errors") or []
        repo = (data.get("data") or {}).get("repository") if isinstance(data.get("data"), dict) else None
        node = repo.get("discussion" if kind == "discussion" else "issueOrPullRequest") if isinstance(repo, dict) else None
        if isinstance(node, dict):
            return node
        if errors and all(isinstance(e, dict) and e.get("type") == "NOT_FOUND" for e in errors) \
                and isinstance(repo, dict):
            return None
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else "no data"
        raise RepoReadError(f"GitHub refused the read: {message}")

    def read(self, ref: Ref) -> Document:
        if not REPO_RE.match(ref.repo):
            raise RepoReadError(f"not a repository: {ref.repo!r}")
        order = [ref.kind] if ref.kind else ["discussion", "issue"]
        for kind in order:
            node = self._query("issue" if kind == "pr" else str(kind), ref)
            if node is not None:
                doc = _document(ref, str(kind), node)
                if ref.kind in ("issue", "pr") and doc.kind != ref.kind:
                    raise RepoReadError(f"{ref} is a {doc.kind}, not a {ref.kind}")
                return doc
        raise RepoReadError(f"{ref} is not a {' or '.join(str(k) for k in order)}")

    def search(self, repo: str, term: str) -> list[Ref]:
        if not REPO_RE.match(repo):
            raise RepoReadError(f"not a repository: {repo!r}")
        data = self._gh(["api", "graphql", "-f", f"query={_SEARCH}", "-f", f"q=repo:{repo} {term}"])
        if data.get("errors") or not isinstance(data.get("data"), dict):
            raise RepoReadError("GitHub refused the search")
        found: list[Ref] = []
        for key, kind in (("discussions", "discussion"), ("issues", None)):
            nodes = (data["data"].get(key) or {}).get("nodes") or []
            for n in nodes:
                if isinstance(n, dict) and isinstance(n.get("number"), int):
                    found.append(Ref(repo, n["number"], kind))
        return sorted(set(found), key=lambda r: r.number)


def _document(ref: Ref, kind: str, node: dict[str, object]) -> Document:
    if kind != "discussion":
        kind = "pr" if node.get("__typename") == "PullRequest" else "issue"
    parts = [Part(str(node.get("url") or ""), str(node.get("body") or ""))]
    comments = node.get("comments") if isinstance(node.get("comments"), dict) else {}
    truncated = bool((comments.get("pageInfo") or {}).get("hasNextPage"))
    for comment in comments.get("nodes") or []:
        if not isinstance(comment, dict):
            continue
        parts.append(Part(str(comment.get("url") or ""), str(comment.get("body") or "")))
        replies = comment.get("replies") if isinstance(comment.get("replies"), dict) else {}
        truncated = truncated or bool((replies.get("pageInfo") or {}).get("hasNextPage"))
        for reply in replies.get("nodes") or []:
            if isinstance(reply, dict):
                parts.append(Part(str(reply.get("url") or ""), str(reply.get("body") or "")))
    return Document(Ref(ref.repo, ref.number, kind), kind, str(node.get("url") or ""), str(node.get("title") or ""),
                    tuple(parts), truncated)


# ---------------------------------------------------------------- fake


@dataclass
class FakeReader:
    """Serves planted documents. A ref with no document raises, as GitHub would;
    `fail` makes every call raise, as a missing or logged-out gh would."""

    documents: dict[tuple[str, int], Document] = field(default_factory=dict)
    fail: str | None = None
    searches: dict[tuple[str, str], list[Ref]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def read(self, ref: Ref) -> Document:
        self.calls.append(f"read {ref}")
        if self.fail:
            raise RepoReadError(self.fail)
        doc = self.documents.get((ref.repo, ref.number))
        if doc is None or (ref.kind and doc.kind != ref.kind):
            raise RepoReadError(f"{ref} is not readable")
        return doc

    def search(self, repo: str, term: str) -> list[Ref]:
        self.calls.append(f"search {repo} {term}")
        if self.fail:
            raise RepoReadError(self.fail)
        return list(self.searches.get((repo, term), []))
