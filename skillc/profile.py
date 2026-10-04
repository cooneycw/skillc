"""Declare and validate a transitive installation profile for a subject (#265).

A subject declaration (`subject.json`, materialize.py) pins WHICH skills are the
treatment. It records the helpers, libraries and tools those skills point at as
"external, not materialized" and stops there - an honest boundary, but one that
cannot say what a working installation of a given workflow actually needs.

A profile (`profile.json`) layers on one subject and names every dependency of a
selected workflow, transitively: the bundled files of each selected skill, the
helpers and libraries their text points at, the files THOSE point at, the tools
they run and any startup context, each with its source, its content digest and
the one place under the client's home it may be installed. `validate()` walks
that closure from the pinned source and either returns a content-addressed
inventory or refuses with a named reason.

What a valid inventory does NOT establish: that anything was installed, that the
installed helper runs, or that a client can use it. Installation and readiness
are a later, separate proof (#266); this module never writes into a home.

Generic by construction, like materialize.py: nothing here names a subject. The
reference patterns, the dependency map and the unsupported list are all data in
the profile, and `tests/test_materialize.py`'s genericity guard scans this
module too. The vocabulary - treatment question `product`/`prose`, helper
parity, `common`/`treatment` scope - is protocol.md section 10.4's (#264).

Stdlib only. Spec: docs/specs/evaluation-facility/profiles.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import materialize as m
from .spec import FrontmatterError, parse_frontmatter

PROFILE_SCHEMA = 1
INVENTORY_SCHEMA = 1

#: Every kind of dependency a profile can declare (#247's list). A kind with no
#: entries must be named in `declared_empty_kinds`, so "none" is a declaration
#: and never an omission.
KINDS = ("reference", "helper", "library", "startup-context", "tool")

#: protocol.md 10.4: product = the skill as installed, prose plus bundled
#: helpers; prose = identical helpers in every arm, only the instructions differ.
TREATMENT_QUESTIONS = ("product", "prose")

#: protocol.md 10.3's scope: `common` reaches every arm, `treatment` only the arm
#: that was given the treatment.
SCOPES = ("common", "treatment")

#: How a reference pattern's hits are classified. An `absolute` hit names a path
#: outside any disposable home and can never be satisfied by an installation
#: into one - it has to be declared unsupported.
REFERENCE_CLASSES = ("home-relative", "variable-rooted", "absolute")

#: A manifest can describe a client surface; it cannot prove one ready. So the
#: subject's own client is `declared`, every other client profile is
#: `unsupported`, and there is no `ready`/`supported` value to claim.
CLIENT_STATUSES = ("declared", "unsupported")

_PROFILE_KEYS = {
    "profile_schema", "name", "subject", "select", "treatment_question",
    "allowed_destinations", "reference_patterns", "dependencies", "unsupported",
    "mirrors", "generated_from", "declared_empty_kinds", "client_profiles", "notes",
}
_DEP_KEYS = {
    "id", "kind", "scope", "source_root", "paths", "destination", "satisfies",
    "traverse", "no_traverse_reason", "unreferenced_reason", "version", "supply",
    "role",
}

Refused = m.Refused


# ------------------------------------------------------------------ the profile


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: str
    klass: str
    meaning: str


@dataclass(frozen=True)
class Satisfies:
    reference: str
    path: str | None  # relative to the dependency's source root; None = its destination root


@dataclass(frozen=True)
class Dependency:
    id: str
    kind: str
    scope: str
    source_root: str
    paths: tuple[str, ...]
    destination: str | None
    satisfies: tuple[Satisfies, ...]
    traverse: bool
    no_traverse_reason: str
    unreferenced_reason: str
    version: str | None
    supply: str | None
    role: str


@dataclass(frozen=True)
class Profile:
    name: str
    subject: m.Subject
    subject_path: Path
    select: tuple[str, ...] | None  # None = every skill (full-pack)
    treatment_question: str
    allowed_destinations: tuple[str, ...]
    patterns: tuple[Pattern, ...]
    dependencies: tuple[Dependency, ...]
    unsupported: dict[str, str]  # reference -> reason
    mirrors: dict[str, str]  # generated repo path -> upstream repo path
    generated_from: dict[str, str]  # generated repo path -> upstream repo path (transformed)
    declared_empty_kinds: tuple[str, ...]
    client_profiles: dict[str, dict[str, str]]
    raw: dict[str, object] = field(compare=False, repr=False)

    @property
    def treatment(self) -> str:
        return "full-pack" if self.select is None else "targeted"

    @classmethod
    def load(cls, path: Path) -> Profile:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"profile declaration unreadable: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise Refused("profile declaration is not a JSON object")
        return cls.from_dict(data, path.resolve().parent)

    @classmethod
    def from_dict(cls, data: dict[str, object], base: Path) -> Profile:
        unknown = sorted(set(data) - _PROFILE_KEYS)
        if unknown:
            raise Refused(f"profile declaration has unknown keys: {unknown}")
        if data.get("profile_schema") != PROFILE_SCHEMA:
            raise Refused(f"profile_schema is {data.get('profile_schema')!r}, not {PROFILE_SCHEMA}")
        name = _str(data, "name")
        subject_path = (base / _str(data, "subject")).resolve()
        subject = m.Subject.load(subject_path)

        select_raw = data.get("select")
        if select_raw == "all":
            select: tuple[str, ...] | None = None
        elif isinstance(select_raw, list) and all(isinstance(s, str) and s for s in select_raw):
            if not select_raw:
                raise Refused("empty selection: the profile selects no skill")
            if len(set(select_raw)) != len(select_raw):
                raise Refused(f"selection names a skill twice: {select_raw}")
            select = tuple(select_raw)
        else:
            raise Refused('select must be "all" or a list of skill names')

        question = data.get("treatment_question")
        if question not in TREATMENT_QUESTIONS:
            raise Refused(f"treatment_question must be one of {TREATMENT_QUESTIONS}, not {question!r}")

        allowed = _str_list(data, "allowed_destinations")
        if not allowed:
            raise Refused("allowed_destinations is empty: nothing could be installed anywhere")
        for root in allowed:
            if m._escapes(root) or root in ("", "."):
                raise Refused(f"allowed destination {root!r} is not a relative path inside the home")

        patterns = []
        for entry in _list(data, "reference_patterns"):
            if not isinstance(entry, dict):
                raise Refused(f"reference_patterns entry malformed: {entry!r}")
            klass = entry.get("class")
            if klass not in REFERENCE_CLASSES:
                raise Refused(f"reference pattern class must be one of {REFERENCE_CLASSES}: {entry!r}")
            regex = entry.get("pattern")
            if not isinstance(regex, str) or not regex:
                raise Refused(f"reference pattern has no pattern: {entry!r}")
            try:
                compiled = re.compile(regex)
            except re.error as exc:
                raise Refused(f"reference pattern invalid: {exc}") from exc
            if compiled.groups:
                raise Refused(f"reference pattern must not capture; the whole match is the reference: {regex}")
            patterns.append(Pattern(str(entry.get("name", regex)), regex, str(klass),
                                    str(entry.get("meaning", ""))))
        if not patterns:
            # A walk with nothing to look for finds nothing, and "nothing" would
            # read exactly like a closure with no external dependency.
            raise Refused("reference_patterns is empty: the closure walk could find no dependency")

        deps = tuple(_dependency(e) for e in _list(data, "dependencies"))
        ids = [d.id for d in deps]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise Refused(f"dependency id declared twice: {dupes}")

        unsupported: dict[str, str] = {}
        for entry in _list(data, "unsupported"):
            if not isinstance(entry, dict) or not isinstance(entry.get("reference"), str) \
                    or not isinstance(entry.get("reason"), str) or not entry["reason"]:
                raise Refused(f"unsupported entry needs a reference and a reason: {entry!r}")
            unsupported[entry["reference"]] = entry["reason"]
        satisfied = {s.reference for d in deps for s in d.satisfies}
        both = sorted(satisfied & set(unsupported))
        if both:
            raise Refused(f"reference both satisfied and declared unsupported: {both}")

        mirrors = _pairs(data, "mirrors")
        generated_from = _pairs(data, "generated_from")
        overlap = sorted(set(mirrors) & set(generated_from))
        if overlap:
            raise Refused(f"a file is declared both a byte mirror and a transform: {overlap}")

        empty = tuple(_str_list(data, "declared_empty_kinds"))
        bad_kinds = sorted(set(empty) - set(KINDS))
        if bad_kinds:
            raise Refused(f"declared_empty_kinds names unknown kinds: {bad_kinds}")
        present = {d.kind for d in deps}
        contradicted = sorted(set(empty) & present)
        if contradicted:
            raise Refused(f"kind(s) declared empty but have dependencies: {contradicted}")
        silent = sorted(set(KINDS) - present - set(empty) - {"reference"})
        if silent:
            # `reference` is always present: the selected skills' bundled files.
            raise Refused(
                f"kind(s) neither declared nor declared empty: {silent}; say 'none' explicitly"
            )

        clients = data.get("client_profiles")
        if not isinstance(clients, dict) or not clients:
            raise Refused("client_profiles must name at least the subject's own client")
        profiles: dict[str, dict[str, str]] = {}
        for client_name, entry in clients.items():
            if not isinstance(entry, dict) or entry.get("status") not in CLIENT_STATUSES:
                raise Refused(
                    f"client profile {client_name!r} status must be one of {CLIENT_STATUSES}; "
                    f"readiness is established by a proof, never by a manifest"
                )
            if not isinstance(entry.get("reason"), str) or not entry["reason"]:
                raise Refused(f"client profile {client_name!r} gives no reason")
            if entry["status"] == "declared" and client_name != subject.client:
                raise Refused(
                    f"client profile {client_name!r} is declared, but this profile's subject is "
                    f"native to {subject.client!r}; another client needs its own readiness proof"
                )
            profiles[str(client_name)] = {k: str(v) for k, v in entry.items()}
        if profiles.get(subject.client, {}).get("status") != "declared":
            raise Refused(f"client_profiles does not declare the subject's own client {subject.client!r}")

        return cls(
            name=name, subject=subject, subject_path=subject_path, select=select,
            treatment_question=str(question), allowed_destinations=tuple(allowed),
            patterns=tuple(patterns), dependencies=deps, unsupported=unsupported,
            mirrors=mirrors, generated_from=generated_from, declared_empty_kinds=empty,
            client_profiles=profiles, raw=data,
        )


def _str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise Refused(f"profile declaration lacks {key}")
    return value


def _list(data: dict[str, object], key: str) -> list[object]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise Refused(f"{key} must be a list")
    return value


def _str_list(data: dict[str, object], key: str) -> list[str]:
    value = _list(data, key)
    if not all(isinstance(v, str) for v in value):
        raise Refused(f"{key} must be a list of strings")
    return [str(v) for v in value]


def _pairs(data: dict[str, object], key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in _list(data, key):
        if not isinstance(entry, dict) or not isinstance(entry.get("generated"), str) \
                or not isinstance(entry.get("source"), str):
            raise Refused(f"{key} entry needs generated and source paths: {entry!r}")
        for path in (entry["generated"], entry["source"]):
            if m._escapes(path):
                raise Refused(f"{key} path {path!r} escapes the source")
        if entry["generated"] in out:
            raise Refused(f"{key} names {entry['generated']} twice")
        out[entry["generated"]] = entry["source"]
    return out


def _dependency(entry: object) -> Dependency:
    if not isinstance(entry, dict):
        raise Refused(f"dependency entry malformed: {entry!r}")
    unknown = sorted(set(entry) - _DEP_KEYS)
    if unknown:
        raise Refused(f"dependency {entry.get('id')!r} has unknown keys: {unknown}")
    dep_id = entry.get("id")
    if not isinstance(dep_id, str) or not dep_id:
        raise Refused(f"dependency has no id: {entry!r}")
    kind = entry.get("kind")
    if kind not in KINDS or kind == "reference":
        # A skill's bundled files are its references; they come from the subject,
        # not from a dependency entry that could name a different file.
        raise Refused(f"dependency {dep_id}: kind must be one of {KINDS[1:]}, not {kind!r}")
    scope = entry.get("scope")
    if scope not in SCOPES:
        raise Refused(f"dependency {dep_id}: scope must be one of {SCOPES}")
    source_root = posixpath.normpath(str(entry.get("source_root") or "."))
    if m._escapes(source_root):
        raise Refused(f"dependency {dep_id}: source_root escapes the source")
    paths = entry.get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
        raise Refused(f"dependency {dep_id}: paths must be a list of relative paths")
    for p in paths:
        if m._escapes(p):
            raise Refused(f"dependency {dep_id}: path {p!r} escapes its source root")
    destination = entry.get("destination")
    if kind == "tool":
        if paths or destination is not None:
            raise Refused(f"dependency {dep_id}: a tool is supplied, not installed from the source")
        for key in ("version", "supply"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise Refused(f"dependency {dep_id}: a tool must declare {key}")
        if entry.get("satisfies"):
            # A tool carries no file, so a reference it "satisfied" would point at
            # nothing this inventory installs.
            raise Refused(f"dependency {dep_id}: a tool carries no path and cannot satisfy a reference")
    else:
        if not paths:
            raise Refused(f"dependency {dep_id}: names no source path")
        if not isinstance(destination, str) or not destination or m._escapes(destination):
            raise Refused(f"dependency {dep_id}: destination must be a relative path inside the home")
    satisfies = []
    for item in entry.get("satisfies", []):
        if isinstance(item, str):
            satisfies.append(Satisfies(item, None))
        elif isinstance(item, dict) and isinstance(item.get("reference"), str):
            path = item.get("path")
            if path is not None and (not isinstance(path, str) or m._escapes(path)):
                raise Refused(f"dependency {dep_id}: satisfies path {path!r} is not relative")
            satisfies.append(Satisfies(item["reference"], path))
        else:
            raise Refused(f"dependency {dep_id}: satisfies entry malformed: {item!r}")
    traverse = entry.get("traverse", kind != "tool")
    if not isinstance(traverse, bool):
        raise Refused(f"dependency {dep_id}: traverse must be true or false")
    no_traverse_reason = str(entry.get("no_traverse_reason", ""))
    if kind != "tool" and not traverse and not no_traverse_reason:
        # An untraversed tree is a hole in the transitive closure. It may be a
        # deliberate one; it may not be a silent one.
        raise Refused(f"dependency {dep_id}: traverse is false with no no_traverse_reason")
    return Dependency(
        id=dep_id, kind=str(kind), scope=str(scope), source_root=source_root,
        paths=tuple(posixpath.normpath(p) for p in paths),
        destination=posixpath.normpath(destination) if isinstance(destination, str) else None,
        satisfies=tuple(satisfies), traverse=traverse,
        no_traverse_reason=no_traverse_reason,
        unreferenced_reason=str(entry.get("unreferenced_reason", "")),
        version=entry.get("version") if isinstance(entry.get("version"), str) else None,
        supply=entry.get("supply") if isinstance(entry.get("supply"), str) else None,
        role=str(entry.get("role", "")),
    )


# ---------------------------------------------------------------- the source


class Tree:
    """Read-only view of the whole pinned source: path -> (mode, bytes).

    A symlink is recorded, not refused, when the tree is opened: a repository
    may hold one anywhere. It is refused the moment the closure reaches it,
    because a link is neither installed nor followed.
    """

    kind = "tree"
    revision = ""
    links: set[str]

    def _refuse_links(self, path: str) -> None:
        norm = posixpath.normpath(path)
        if norm == "." and self.links:
            raise Refused(f"symlink in the closure: {sorted(self.links)[0]}")
        for link in self.links:
            if norm == link or norm.startswith(link + "/") or link.startswith(norm + "/"):
                raise Refused(f"symlink in the closure: {link}")

    def files(self) -> dict[str, str]:  # path -> mode ("100644" / "100755")
        raise NotImplementedError

    def read(self, path: str) -> bytes:
        raise NotImplementedError

    def under(self, path: str) -> list[str]:
        """Every file at `path` or below it, sorted. Empty when absent."""
        norm = posixpath.normpath(path)
        self._refuse_links(norm)
        if norm == ".":
            return sorted(self.files())
        return sorted(p for p in self.files() if p == norm or p.startswith(norm + "/"))


class GitTree(Tree):
    kind = "git"

    def __init__(self, repo: Path, revision: str) -> None:
        if shutil.which("git") is None:
            raise Refused("git is not installed; a pinned revision cannot be read")
        self.repo = repo
        self.revision = revision
        if not m._SHA_RE.match(revision):
            raise Refused(f"revision {revision!r} is not a full commit SHA")
        try:
            resolved = self._git("rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
        except Refused:
            resolved = b""
        if resolved.decode().strip() != revision:
            raise Refused(f"revision {revision} does not resolve in {repo}")
        listing = self._git("ls-tree", "-r", "-z", "--full-tree", revision)
        self._files: dict[str, tuple[str, str]] = {}
        self.links = set()
        for record in listing.split(b"\0"):
            if not record:
                continue
            meta, path = record.decode().split("\t", 1)
            mode, otype, blob = meta.split()
            if otype != "blob":
                continue  # a submodule is not content this source carries
            if mode == "120000":
                self.links.add(path)
                continue
            self._files[path] = (mode, blob)
        self._modes = {p: mode for p, (mode, _) in self._files.items()}

    def _git(self, *args: str) -> bytes:
        proc = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(self.repo), *args],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise Refused(f"git {args[0]} failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.stdout

    def files(self) -> dict[str, str]:
        return self._modes

    def read(self, path: str) -> bytes:
        self._refuse_links(path)
        data = self._git("cat-file", "blob", self._files[path][1])
        if git_blob_id(data) != self._files[path][1]:
            raise Refused(f"{path}: bytes read do not hash to git's blob id")
        return data


class DirTree(Tree):
    kind = "snapshot"

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[str, str] = {}
        self.links = set()
        h = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if rel.split("/", 1)[0] == ".git":
                continue
            if path.is_symlink():
                self.links.add(rel)
            elif path.is_file() and not any(rel.startswith(link + "/") for link in self.links):
                mode = "100755" if os.access(path, os.X_OK) else "100644"
                self._files[rel] = mode
                h.update(f"{rel}\0{mode}\0{m.sha256_file(path)}\n".encode())
        self.revision = f"snapshot:sha256:{h.hexdigest()}"

    def files(self) -> dict[str, str]:
        return self._files

    def read(self, path: str) -> bytes:
        self._refuse_links(path)
        return (self.root / path).read_bytes()


# ---------------------------------------------------------------- validation


@dataclass
class _Walk:
    profile: Profile
    tree: Tree
    by_reference: dict[str, tuple[Dependency, Satisfies]]
    scanned: set[str] = field(default_factory=set)
    references: list[dict[str, object]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    referenced: set[str] = field(default_factory=set)
    visited: set[str] = field(default_factory=set)
    queue: list[tuple[str, str]] = field(default_factory=list)  # (repo path, owner)


def validate(profile: Profile, tree: Tree) -> dict[str, Any]:
    """The content-addressed inventory, or Refused naming the first defect class found."""
    subject = profile.subject
    if tree.kind == "git" and tree.revision != subject.revision:
        raise Refused(f"source is at {tree.revision}, the subject pins {subject.revision}")
    root = subject.skills_root

    # The selected skills, through materialize's own inventory: name parsing,
    # selection, collisions, declared required references and checksums.
    selected_subject = m.Subject.from_dict({
        **subject.raw, "select": "all" if profile.select is None else list(profile.select),
    })
    with tempfile.TemporaryDirectory(prefix="skillc-profile-") as staging:
        surface = Path(staging) / "surface"
        surface.mkdir()
        prefix = "" if root == "." else root + "/"
        # A link that hides a skill's name (a linked skill directory, or a linked
        # SKILL.md) blocks discovery for EVERY selection, so it is refused here.
        # Any other link is refused only if the closure reaches it (below): a
        # neighbour's ancillary link says nothing about this treatment.
        for link in sorted(tree.links):
            if link.startswith(prefix) or root == ".":
                rel = link[len(prefix):]
                top, _, rest = rel.partition("/")
                hides = (
                    not rest  # a linked skill directory
                    or rest == "SKILL.md"  # a linked entry point
                    # a deeper SKILL.md decides a nested layout only where the
                    # directory has no entry point of its own (materialize's rule)
                    or (posixpath.basename(rest) == "SKILL.md"
                        and f"{prefix}{top}/SKILL.md" not in tree.files())
                )
                if hides:
                    raise Refused(f"symlink in the skills root blocks name discovery: {link}")
        surface_files = [p for p in tree.files() if root == "." or p.startswith(prefix)]
        if not surface_files:
            raise Refused(f"skills root {root!r} is absent from the source")
        for path in surface_files:
            target = surface / path[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tree.read(path))
            target.chmod(0o755 if tree.files()[path] == "100755" else 0o644)
        source = m.Source(tree.kind, subject.locator, tree.revision, surface,
                          m.tree_digest(surface), Path(staging))
        entries = m.inventory(selected_subject, source)

    walk = _Walk(profile, tree, {
        s.reference: (d, s) for d in profile.dependencies for s in d.satisfies
    })
    files = tree.files()
    installed: dict[str, dict[str, object]] = {}  # destination -> record
    skills = []
    home_skills = subject.surface_spec.home_skills_relpath
    for entry in entries:
        skill_dir = f"{prefix}{entry.directory}"
        tree._refuse_links(skill_dir)  # a link inside a SELECTED skill is in the closure
        body_text = tree.read(f"{skill_dir}/SKILL.md").decode("utf-8", errors="replace")
        try:
            frontmatter, body = parse_frontmatter(body_text)
        except FrontmatterError as exc:  # pragma: no cover - inventory() already parsed it
            raise Refused(f"{entry.directory}/SKILL.md: {exc}") from exc
        description = str(frontmatter.get("description", ""))
        skill_files = []
        for f in entry.files:
            repo_path = f"{skill_dir}/{f['path']}"
            dest = f"{home_skills}/{entry.directory}/{f['path']}"
            record = _file_record(tree, repo_path, dest, owner=f"skill:{entry.name}")
            _claim(installed, dest, record)
            skill_files.append(record)
            walk.queue.append((repo_path, f"skill:{entry.name}"))
        skills.append({
            "name": entry.name,
            "directory": entry.directory,
            "description_digest": m.sha256_bytes(description.encode()),
            "body_digest": m.sha256_bytes(body.encode()),
            "required_references": entry.required_refs,
            "checksums": entry.checksums,
            "files": skill_files,
        })

    # The transitive walk: every text file reached is scanned for declared
    # reference patterns; every hit resolves to a dependency, to an explicit
    # unsupported entry, or the profile is refused.
    _drain(walk, installed)
    # Dependencies no reference reaches (a tool, a startup file the client loads
    # by itself) are seeded only AFTER the referenced closure is complete, so
    # "referenced" keeps its meaning - and then walked like any other, because
    # a startup file can name a helper too.
    for dep in profile.dependencies:
        if dep.id not in walk.visited and dep.unreferenced_reason:
            _visit(walk, dep, installed)
            _drain(walk, installed)
    for dep in profile.dependencies:
        if dep.id not in walk.visited:
            raise Refused(
                f"dependency {dep.id} is satisfied by no reference in the closure; "
                f"declare unreferenced_reason or remove it"
            )

    if walk.unresolved:
        shown = sorted(set(walk.unresolved))
        raise Refused(
            f"unresolved reference(s): {shown[:8]}{' ...' if len(shown) > 8 else ''}; "
            f"each needs a dependency that satisfies it or an unsupported entry with a reason"
        )

    dependencies = [_dep_record(walk, dep, installed) for dep in profile.dependencies]
    bundled_parity = _bundled_parity(profile, skills, installed)
    # Helper parity (protocol.md 10.4): a prose question gives every arm the same
    # helpers, so nothing but the instructions may be treatment-scoped.
    if profile.treatment_question == "prose":
        scoped = sorted(d.id for d in profile.dependencies if d.scope == "treatment")
        if scoped:
            raise Refused(
                f"prose treatment question but dependencies {scoped} are treatment-scoped; "
                f"helper parity requires identical helpers in every arm"
            )
        orphans = sorted(str(b["path"]) for b in bundled_parity if b["supplied_by"] is None)
        if orphans:
            # Under a prose question the arm given expanded instructions has no
            # skill directory, so a helper that lives only inside the skill never
            # reaches it. Only the instructions may differ.
            raise Refused(
                f"prose treatment question but bundled file(s) {orphans} reach only the skill "
                f"arm; declare a common-scoped dependency carrying identical bytes"
            )

    # Every destination sits under an allowed root.
    for dest in installed:
        if not any(dest == r or dest.startswith(r.rstrip("/") + "/") for r in profile.allowed_destinations):
            raise Refused(f"destination {dest} is outside allowed_destinations {list(profile.allowed_destinations)}")

    mirrors = [_mirror(tree, files, gen, src, exact=True) for gen, src in sorted(profile.mirrors.items())]
    transforms = [_mirror(tree, files, gen, src, exact=False)
                  for gen, src in sorted(profile.generated_from.items())]

    inventory_body: dict[str, Any] = {
        "inventory_schema": INVENTORY_SCHEMA,
        "profile": profile.name,
        "profile_digest": m.sha256_bytes(_canonical(profile.raw)),
        "subject": {
            "declaration_digest": m.sha256_bytes(_canonical(subject.raw)),
            "locator": subject.locator,
            "revision": tree.revision,
            "source_kind": tree.kind,
            "surface": subject.surface,
            "client": {"name": subject.client, "version": subject.client_version},
        },
        "treatment": profile.treatment,
        "treatment_question": profile.treatment_question,
        "selection": [s["name"] for s in skills],
        "skills": skills,
        "dependencies": dependencies,
        "references": sorted(walk.references, key=lambda r: (str(r["in"]), str(r["reference"]))),
        "unsupported": [
            {"reference": ref, "reason": reason}
            for ref, reason in sorted({
                str(r["reference"]): str(r["reason"])
                for r in walk.references if r["status"] == "unsupported"
            }.items())
        ],
        "mirrors": mirrors,
        "generated_from": transforms,
        "helper_parity": {
            "common": sorted(d.id for d in profile.dependencies if d.scope == "common"),
            "treatment": sorted(d.id for d in profile.dependencies if d.scope == "treatment"),
            "bundled": bundled_parity,
        },
        "declared_empty_kinds": list(profile.declared_empty_kinds),
        "client_profiles": profile.client_profiles,
        "installed_surface": {
            "files": len(installed),
            "digest": m.sha256_bytes("".join(
                f"{d}\0{r['mode']}\0{r['digest']}\n" for d, r in sorted(installed.items())
            ).encode()),
        },
        "establishes": "a declared, closed dependency inventory at this source revision",
        "does_not_establish": [
            "installation into any home",
            "that any helper, library or tool runs",
            "client availability, invocation or task outcome",
            "parity for any client profile other than the declared one",
        ],
    }
    return inventory_body


def _drain(walk: _Walk, installed: dict[str, dict[str, object]]) -> None:
    """Scan every queued text file for declared reference patterns; each hit
    resolves to a dependency, to an explicit unsupported entry, or is recorded
    as unresolved. Visiting a dependency queues its files, so this reaches the
    transitive closure."""
    while walk.queue:
        path, _owner = walk.queue.pop(0)
        if path in walk.scanned:
            continue
        walk.scanned.add(path)
        raw = walk.tree.read(path)
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for pattern in walk.profile.patterns:
            for hit in sorted(set(re.findall(pattern.regex, text))):
                _resolve(walk, hit, path, pattern, installed)


def _bundled_parity(profile: Profile, skills: list[dict[str, Any]],
                    installed: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    """Every non-Markdown file bundled in a selected skill, and which common-scoped
    dependency (if any) supplies identical bytes outside the skill. Markdown is
    the instructions - the one thing a prose question lets differ."""
    common = {d.id for d in profile.dependencies if d.scope == "common"}
    # Bytes AND mode: an identical script that is not executable in the other
    # arm is not the same helper.
    by_digest: dict[tuple[object, object], list[str]] = {}
    for record in installed.values():
        if record["owner"] in common:
            by_digest.setdefault((record["digest"], record["mode"]), []).append(str(record["owner"]))
    out: list[dict[str, object]] = []
    for skill in skills:
        for f in skill["files"]:
            if str(f["source"]).endswith(".md"):
                continue
            owners = sorted(set(by_digest.get((f["digest"], f["mode"]), [])))
            out.append({"path": f["source"], "supplied_by": owners[0] if owners else None})
    return out


_HOME_PREFIXES = ("~/", "$HOME/", "${HOME}/")


def _home_target(reference: str) -> str | None:
    """The path under HOME a home-relative reference names, or None if it is not
    spelled relative to HOME."""
    for prefix in _HOME_PREFIXES:
        if reference.startswith(prefix):
            return posixpath.normpath(reference[len(prefix):])
    return None


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def git_blob_id(data: bytes) -> str:
    """Git's object id for these bytes as a blob. Computed, not asked of git, so a
    snapshot source carries the same identity a git source does - and an
    inventory keyed by blob id (#264's case contract) can be cross-checked
    against this one rather than compared by eye."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _file_record(tree: Tree, repo_path: str, dest: str, owner: str) -> dict[str, object]:
    data = tree.read(repo_path)
    return {
        "source": repo_path,
        "destination": dest,
        "mode": tree.files()[repo_path],
        "size": len(data),
        "digest": m.sha256_bytes(data),
        "git_blob": git_blob_id(data),
        "owner": owner,
    }


def _claim(installed: dict[str, dict[str, object]], dest: str, record: dict[str, object]) -> None:
    """One owner per installed path. Two claimants are a conflict even when their
    bytes agree: which one an installer writes last is not a declaration."""
    if dest in installed:
        other = installed[dest]
        same = other["digest"] == record["digest"]
        raise Refused(
            f"conflicting destination {dest}: claimed by {other['owner']} and {record['owner']}"
            f"{' (identical bytes, still two owners)' if same else ' with different content'}"
        )
    # A file may not be installed where another claimant installs a directory.
    for existing in installed:
        if existing.startswith(dest + "/") or dest.startswith(existing + "/"):
            raise Refused(f"conflicting destination {dest}: overlaps {existing}")
    installed[dest] = record


def _source_files(walk: _Walk, dep: Dependency) -> list[tuple[str, str]]:
    """(repo path, path relative to source root) for every file the dependency carries."""
    out: list[tuple[str, str]] = []
    for p in dep.paths:
        full = p if dep.source_root == "." else posixpath.join(dep.source_root, p)
        found = walk.tree.under(full)
        if not found:
            raise Refused(f"missing {dep.kind} {dep.id}: {full} is absent from the source")
        base = "" if dep.source_root == "." else dep.source_root + "/"
        out.extend((f, f[len(base):]) for f in found)
    return out


def _visit(walk: _Walk, dep: Dependency, installed: dict[str, dict[str, object]]) -> None:
    if dep.id in walk.visited:
        return
    walk.visited.add(dep.id)
    if dep.kind == "tool":
        return
    assert dep.destination is not None
    for repo_path, rel in _source_files(walk, dep):
        dest = posixpath.join(dep.destination, rel)
        _claim(installed, dest, _file_record(walk.tree, repo_path, dest, owner=dep.id))
        if dep.traverse:
            walk.queue.append((repo_path, dep.id))


def _resolve(walk: _Walk, hit: str, path: str, pattern: Pattern,
             installed: dict[str, dict[str, object]]) -> None:
    record: dict[str, object] = {"reference": hit, "in": path, "pattern": pattern.name,
                                 "class": pattern.klass}
    if hit in walk.profile.unsupported:
        record.update(status="unsupported", reason=walk.profile.unsupported[hit])
    elif hit in walk.by_reference:
        dep, sat = walk.by_reference[hit]
        if pattern.klass == "absolute":
            raise Refused(
                f"absolute reference {hit} (in {path}) is satisfied by {dep.id}, but an absolute "
                f"path cannot be installed into a disposable home; declare it unsupported"
            )
        _visit(walk, dep, installed)
        if sat.path is not None:
            full = sat.path if dep.source_root == "." else posixpath.join(dep.source_root, sat.path)
            carried = {rp for rp, _ in _source_files(walk, dep)} if dep.kind != "tool" else set()
            if not any(c == full or c.startswith(full + "/") for c in carried):
                raise Refused(
                    f"missing {dep.kind} file: {hit} (in {path}) resolves to {full}, "
                    f"which {dep.id} does not carry"
                )
        resolves_to = (posixpath.join(dep.destination, sat.path)
                       if dep.destination and sat.path else dep.destination)
        target = _home_target(hit) if pattern.klass == "home-relative" else None
        if target is not None and resolves_to is not None and target != resolves_to:
            # The reference names a place under HOME; the dependency installs
            # somewhere else. An installer following this inventory could not
            # supply the path the text actually uses.
            raise Refused(
                f"{hit} (in {path}) names ~/{target}, but {dep.id} installs it at ~/{resolves_to}"
            )
        record.update(status="satisfied", dependency=dep.id, resolves_to=resolves_to)
    else:
        walk.unresolved.append(f"{hit} (in {path}, {pattern.klass})")
        return
    walk.references.append(record)


def _dep_record(walk: _Walk, dep: Dependency, installed: dict[str, dict[str, object]]) -> dict[str, object]:
    files = sorted((r for r in installed.values() if r["owner"] == dep.id),
                   key=lambda r: str(r["destination"]))
    return {
        "id": dep.id,
        "kind": dep.kind,
        "scope": dep.scope,
        "role": dep.role,
        "destination": dep.destination,
        "version": dep.version,
        "supply": dep.supply,
        "traversed": dep.traverse if dep.kind != "tool" else None,
        "no_traverse_reason": dep.no_traverse_reason or None,
        "referenced_by": sorted({str(r["in"]) for r in walk.references if r.get("dependency") == dep.id}),
        "unreferenced_reason": dep.unreferenced_reason or None,
        "files": files,
        "digest": m.sha256_bytes("".join(
            f"{r['destination']}\0{r['mode']}\0{r['digest']}\n" for r in files
        ).encode()) if files else None,
    }


def _mirror(tree: Tree, files: dict[str, str], generated: str, source: str,
            exact: bool) -> dict[str, object]:
    for path in (generated, source):
        if path not in files:
            raise Refused(f"{'mirror' if exact else 'generated_from'} names {path}, absent from the source")
    gen, src = tree.read(generated), tree.read(source)
    record: dict[str, object] = {
        "generated": generated, "generated_digest": m.sha256_bytes(gen),
        "source": source, "source_digest": m.sha256_bytes(src),
    }
    if exact:
        if gen != src or files[generated] != files[source]:
            raise Refused(
                f"stale mirror: {generated} is declared a copy of {source} but "
                f"{'the modes differ' if gen == src else 'the bytes differ'}"
            )
        record["status"] = "identical"
    else:
        # A transform's freshness cannot be read off bytes; both digests are
        # recorded so a later change on either side is visible, and nothing more
        # is claimed.
        record["status"] = "transform-not-verified"
    return record


def load_tree(profile: Profile, repo: Path | None, snapshot: Path | None) -> Tree:
    if repo is not None:
        if not (repo / ".git").exists():
            raise Refused(f"source is not a git checkout: {repo}")
        return GitTree(repo, profile.subject.revision)
    assert snapshot is not None
    return DirTree(snapshot)
