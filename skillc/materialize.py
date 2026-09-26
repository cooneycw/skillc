"""Materialize a declared skill collection natively for one client, and prove it.

`skillc materialize` installs a pinned skill surface into disposable home and
workspace directories, asks the real client what it can see, does the same for
an identical home WITHOUT the treatment, and writes an installation receipt
(records.md, version 2) plus a report. See
docs/specs/evaluation-facility/materialization.md.

Four facts stay separate, because evidence of one does not establish another
(spec.md "Subject acquisition"):

- installed  - the bytes are in the disposable home, with digests
- available  - the client LISTED them (the discovery canary)
- invoked    - not observed here; no model runs
- outcome    - not applicable here; there is no task

Generic by construction. Nothing in this module names a subject: the skills
root, the checksum-manifest convention and the external-reference patterns come
from the subject declaration, and `test_materialize.py` fails if a subject's
name creeps into a string literal here. Layouts other than "a directory whose
children are skill directories" and clients other than Codex are refused by
name, never guessed.

Stdlib only, like the rest of `skillc/`. The client is an external program, run
with an empty environment apart from HOME, CODEX_HOME and PATH, against homes
this module created, and it is never given the host's real home.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .spec import FrontmatterError, parse_frontmatter

ADAPTER = {"name": "skillc-codex-skills", "version": "1"}

#: The one surface and the one client this adapter supports. Anything else is
#: refused by name (spec.md: "unsupported format is named rather than guessed").
SURFACE = "codex-skills"
CLIENT = "codex"

#: The model-free route by which Codex renders what a session would be given.
#: It lists every discovered skill with the file it came from. It is a DEBUG
#: surface: its shape is pinned with the client version, and output this module
#: cannot parse is UNKNOWN, never a pass.
CANARY_ARGV = ("debug", "prompt-input")
CANARY_PROMPT = "skillc discovery canary"

#: The directory the client seeds with its own skills in every home. They are
#: ordinary client state, shared by both arms, never part of a treatment.
CLIENT_SYSTEM_DIR = ".system"

MARKER = ".skillc-owned"

SATISFIED, VIOLATED, UNKNOWN = "SATISFIED", "VIOLATED", "UNKNOWN"

#: records.md requires the first two. The rest are this adapter's own facts; a
#: receipt is only called ready when ALL of them are SATISFIED.
READINESS_FACTS = (
    "discovery_canary", "baseline_absence", "ordinary_parity",
    "source_unchanged", "host_unchanged",
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ROOT_LINE_RE = re.compile(r"^- `(r\d+)` = `(.+)`$")
_SKILL_LINE_RE = re.compile(r"^- (\S[^:]*): .*\(file: (r\d+)/([^)]+)\)$")
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_TICK_RE = re.compile(r"`([^`\s]+)`")

_SUBJECT_KEYS = {
    "subject_schema", "locator", "revision", "surface", "skills_root", "select",
    "checksum_manifest", "external_references", "required_references", "client",
    "capabilities", "notes",
}


class Refused(Exception):
    """Materialization stopped. The message names the reason; nothing is ready."""


# ------------------------------------------------------------------ the subject


@dataclass(frozen=True)
class ExternalPattern:
    pattern: str
    meaning: str

    def finditer(self, text: str) -> Iterator[str]:
        for match in re.finditer(self.pattern, text):
            yield match.group(0)


@dataclass(frozen=True)
class Subject:
    """A declared skill collection. Every convention the adapter honours is here."""

    locator: str
    revision: str
    skills_root: str
    select: tuple[str, ...] | None  # None means every skill found
    checksum_manifest: str | None
    external: tuple[ExternalPattern, ...]
    required: tuple[ExternalPattern, ...]
    client_version: str
    raw: dict[str, object] = field(compare=False, repr=False)

    @classmethod
    def load(cls, path: Path) -> Subject:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"subject declaration unreadable: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise Refused("subject declaration is not a JSON object")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Subject:
        unknown = sorted(set(data) - _SUBJECT_KEYS)
        if unknown:
            # An unread key is a convention the author thinks is honoured and is not.
            raise Refused(f"subject declaration has unknown keys: {unknown}")
        if data.get("subject_schema") != 1:
            raise Refused(f"subject_schema is {data.get('subject_schema')!r}, not 1")
        for key in ("locator", "revision", "skills_root"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise Refused(f"subject declaration lacks {key}")
        if data.get("surface") != SURFACE:
            raise Refused(
                f"unsupported surface {data.get('surface')!r}: this adapter supports "
                f"only {SURFACE!r}"
            )
        client = data.get("client")
        if not isinstance(client, dict) or client.get("name") != CLIENT:
            raise Refused(f"unsupported client {client!r}: this adapter supports only {CLIENT!r}")
        if not isinstance(client.get("version"), str) or not client["version"]:
            raise Refused("subject declaration pins no client version")
        root = str(data["skills_root"])
        if Path(root).is_absolute() or ".." in Path(root).parts:
            raise Refused(f"skills_root {root!r} escapes the subject")
        select = data.get("select", "all")
        if select == "all":
            chosen: tuple[str, ...] | None = None
        elif isinstance(select, list) and select and all(isinstance(s, str) for s in select):
            chosen = tuple(select)
        else:
            raise Refused("select must be \"all\" or a non-empty list of skill names")
        manifest = data.get("checksum_manifest")
        if manifest is not None and (not isinstance(manifest, str) or not manifest):
            raise Refused("checksum_manifest must be a relative path or absent")
        return cls(
            locator=str(data["locator"]),
            revision=str(data["revision"]),
            skills_root=root,
            select=chosen,
            checksum_manifest=manifest if isinstance(manifest, str) else None,
            external=_patterns(data, "external_references", groups=0),
            required=_patterns(data, "required_references", groups=1),
            client_version=str(client["version"]),
            raw=data,
        )


def _patterns(data: dict[str, object], key: str, groups: int) -> tuple[ExternalPattern, ...]:
    declared = data.get(key, [])
    if not isinstance(declared, list):
        raise Refused(f"{key} must be a list")
    patterns = []
    for entry in declared:
        if not isinstance(entry, dict) or not isinstance(entry.get("pattern"), str):
            raise Refused(f"{key} entry malformed: {entry!r}")
        try:
            compiled = re.compile(entry["pattern"])
        except re.error as exc:
            raise Refused(f"{key} pattern invalid: {exc}") from exc
        if compiled.groups != groups:
            # A required-reference pattern captures the path; an external one does not.
            raise Refused(f"{key} pattern must have {groups} capture group(s): {entry['pattern']}")
        patterns.append(ExternalPattern(entry["pattern"], str(entry.get("meaning", ""))))
    return tuple(patterns)


# ----------------------------------------------------------------- digests


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_files(root: Path) -> list[Path]:
    """Every regular file under root, sorted. A symlink anywhere is refused."""
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Refused(f"symlink in subject surface: {path.relative_to(root)}")
        if path.is_file():
            found.append(path)
    return found


def tree_digest(root: Path) -> str:
    """Content identity of a tree: relative path, executable bit and bytes."""
    h = hashlib.sha256()
    for path in tree_files(root):
        rel = path.relative_to(root).as_posix()
        mode = "x" if os.access(path, os.X_OK) else "-"
        h.update(f"{rel}\0{mode}\0{sha256_file(path)}\n".encode())
    return "sha256:" + h.hexdigest()


# ------------------------------------------------------------- acquisition


@dataclass
class Source:
    """The subject surface, copied read-only into controller-owned staging."""

    kind: str  # "git" or "snapshot"
    locator: str
    revision: str  # a full commit SHA, or "snapshot:<digest>" - never a commit it is not
    surface_dir: Path  # staging copy of the skills root
    digest: str
    origin: Path  # the repository or snapshot directory that was read


def _git(repo: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess[bytes]:
    if shutil.which("git") is None:
        raise Refused("git is not installed; a pinned revision cannot be acquired")
    # --no-optional-locks: `status` would otherwise refresh the source's index.
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True, check=False,
    )


def acquire_git(subject: Subject, repo: Path, staging: Path) -> Source:
    """Read the declared skills root at the pinned commit, without touching the checkout."""
    if not _SHA_RE.match(subject.revision):
        raise Refused(
            f"revision {subject.revision!r} is not a full commit SHA; pin the subject "
            f"to an immutable revision"
        )
    if not (repo / ".git").exists():
        raise Refused(f"source is not a git checkout: {repo}")
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{subject.revision}^{{commit}}")
    sha = resolved.stdout.decode().strip()
    if resolved.returncode != 0 or sha != subject.revision:
        raise Refused(f"revision {subject.revision} does not resolve in {repo}")
    probe = _git(repo, "cat-file", "-e", f"{sha}:{subject.skills_root}")
    if probe.returncode != 0:
        raise Refused(f"skills root {subject.skills_root!r} is absent at {sha}")
    archive = _git(repo, "archive", "--format=tar", sha, "--", subject.skills_root)
    if archive.returncode != 0:
        raise Refused(f"git archive failed: {archive.stderr.decode(errors='replace').strip()}")
    target = staging / "surface"
    target.mkdir(parents=True)
    _extract(archive.stdout, subject.skills_root, target)
    return Source("git", subject.locator, sha, target, tree_digest(target), repo)


def _extract(tar_bytes: bytes, prefix: str, target: Path) -> None:
    """Write regular files only. Links are refused, never followed or recreated."""
    base = prefix.rstrip("/") + "/"
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                raise Refused(f"symlink in subject surface: {member.name}")
            if not member.name.startswith(base) or ".." in Path(member.name).parts:
                continue
            rel = member.name[len(base):]
            if not rel:
                continue
            dest = target / rel
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                handle = tar.extractfile(member)
                assert handle is not None
                dest.write_bytes(handle.read())
                dest.chmod(0o755 if member.mode & 0o111 else 0o644)


def acquire_snapshot(subject: Subject, snapshot: Path, staging: Path) -> Source:
    """A local directory holding the skills root. Labelled a snapshot, never a commit."""
    surface = snapshot / subject.skills_root
    if not surface.is_dir():
        raise Refused(f"skills root {subject.skills_root!r} is absent under {snapshot}")
    tree_files(surface)  # refuses symlinks before anything is copied
    target = staging / "surface"
    shutil.copytree(surface, target)
    digest = tree_digest(target)
    return Source("snapshot", subject.locator, f"snapshot:{digest}", target, digest, snapshot)


# --------------------------------------------------------------- inventory


@dataclass
class SkillEntry:
    directory: str
    name: str
    files: list[dict[str, object]]
    required_refs: list[str]
    static_findings: list[str]
    external: list[dict[str, str]]
    checksums: str  # "verified", "absent" or "not-declared"


def _links(text: str) -> set[str]:
    """Relative Markdown link targets: the one generic, explicit reference form."""
    refs = set()
    for target in _LINK_RE.findall(text):
        target = target.split("#", 1)[0]
        if target and ":" not in target and not target.startswith(("/", "~", "$")):
            refs.add(target)
    return refs


def _refs(text: str) -> set[str]:
    """Things that LOOK like file references. A heuristic, so never readiness."""
    found = set(_LINK_RE.findall(text)) | set(_TICK_RE.findall(text))
    refs = set()
    for ref in found:
        ref = ref.split("#", 1)[0]
        if not ref or ref.startswith(("/", "~", "$", "http:", "https:", "-")):
            continue
        if "." not in Path(ref).name or not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
            continue  # a command word, not a file
        refs.add(ref)
    return refs


def _verify_checksums(skill_dir: Path, manifest_rel: str) -> str:
    manifest = skill_dir / manifest_rel
    if not manifest.is_file():
        return "absent"
    listed = 0
    for lineno, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise Refused(f"{skill_dir.name}/{manifest_rel}:{lineno}: malformed checksum line")
        target = manifest.parent / parts[1].strip().lstrip("*")
        if not target.is_file():
            raise Refused(f"{skill_dir.name}: checksum lists a missing file {parts[1].strip()}")
        if sha256_file(target) != "sha256:" + parts[0]:
            raise Refused(f"{skill_dir.name}: checksum mismatch for {parts[1].strip()}")
        listed += 1
    if not listed:
        raise Refused(f"{skill_dir.name}/{manifest_rel} lists nothing")
    return "verified"


def inventory(subject: Subject, source: Source) -> list[SkillEntry]:
    """Every skill directory in the surface, with its closure, or a named refusal."""
    root = source.surface_dir
    if (root / "SKILL.md").exists():
        raise Refused(
            "unsupported layout: a SKILL.md at the skills root itself; this adapter "
            "reads a directory whose children are skill directories"
        )
    entries: list[SkillEntry] = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            nested = sorted(child.rglob("SKILL.md"))
            if nested:
                raise Refused(
                    f"unsupported layout: nested skill {nested[0].relative_to(root)} "
                    f"below a directory with no SKILL.md"
                )
            continue  # not a skill; reported by the caller as a non-skill entry
        text = skill_md.read_text(encoding="utf-8")
        try:
            frontmatter, body = parse_frontmatter(text)
        except FrontmatterError as exc:
            raise Refused(f"{child.name}/SKILL.md: frontmatter does not parse: {exc}") from exc
        name = frontmatter.get("name")
        if not isinstance(name, str) or not name:
            raise Refused(f"{child.name}/SKILL.md declares no name; the client cannot list it")
        files = [
            {
                "path": f.relative_to(child).as_posix(),
                "size": f.stat().st_size,
                "digest": sha256_file(f),
            }
            for f in tree_files(child)
        ]
        present = {str(f["path"]) for f in files}
        # Required: what the ENTRY POINT explicitly points at - a relative Markdown
        # link, or a phrase the subject DECLARED as its "read this file" convention.
        # A missing one is a broken install. Anything merely resembling a path is
        # a static finding below: a heuristic here would refuse sound skills that
        # mention files of the repository they document.
        declared = {m for p in subject.required for m in re.findall(p.pattern, body)}
        required = sorted(_links(body) | declared)
        missing = [r for r in required if r not in present]
        if missing:
            raise Refused(f"{child.name}: SKILL.md references missing file(s) {missing}")
        # Everything else is a static finding. It is recorded and never counts as
        # readiness in either direction; only the client's listing does.
        findings = []
        external: list[dict[str, str]] = []
        for f in tree_files(child):
            if f.suffix != ".md":
                continue
            content = f.read_text(encoding="utf-8", errors="replace")
            for pattern in subject.external:
                for hit in sorted(set(pattern.finditer(content))):
                    external.append({
                        "reference": hit,
                        "in": f.relative_to(child).as_posix(),
                        "status": "external-not-materialized",
                        "meaning": pattern.meaning,
                    })
            for ref in sorted(_refs(content)):
                if ref not in present and ref not in required:
                    findings.append(f"{f.relative_to(child).as_posix()} mentions {ref}, "
                                    f"not in this skill (static; not readiness)")
        checks = (
            _verify_checksums(child, subject.checksum_manifest)
            if subject.checksum_manifest else "not-declared"
        )
        entries.append(SkillEntry(child.name, name, files, required, findings, external, checks))

    names: dict[str, str] = {}
    folded: dict[str, str] = {}
    for entry in entries:
        if entry.name in names:
            raise Refused(
                f"name collision: {names[entry.name]} and {entry.directory} both declare "
                f"{entry.name!r}"
            )
        names[entry.name] = entry.directory
        low = entry.directory.lower()
        if low in folded or low == CLIENT_SYSTEM_DIR:
            raise Refused(f"target collision: {entry.directory!r} and {folded.get(low, low)!r}")
        folded[low] = entry.directory
    if subject.select is not None:
        unknown = sorted(set(subject.select) - set(names))
        if unknown:
            raise Refused(f"selected skill(s) not in the surface: {unknown}")
        entries = [e for e in entries if e.name in subject.select]
    if not entries:
        raise Refused("empty discovery: the surface holds no skill to install")
    return entries


# ------------------------------------------------------------ owned roots


def forbidden_roots(source: Path | None) -> list[Path]:
    """Places a disposable root must never sit inside: the host's client and the source."""
    home = Path.home()
    roots = [home / ".codex", home / ".agents", home / ".claude"]
    if os.environ.get("CODEX_HOME"):
        roots.append(Path(os.environ["CODEX_HOME"]))
    if source is not None:
        roots.append(source)
    return [r.resolve() for r in roots]


def create_root(base: Path, forbidden: list[Path]) -> tuple[Path, str]:
    base = base.resolve()
    for bad in forbidden:
        if base == bad or base.is_relative_to(bad):
            raise Refused(f"refusing to materialize inside {bad}: that is not trial-owned")
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="skillc-materialize-", dir=base))
    nonce = secrets.token_hex(16)
    (root / MARKER).write_text(json.dumps({"nonce": nonce}), encoding="utf-8")
    return root, nonce


def cleanup(root: Path, nonce: str) -> dict[str, object]:
    """Remove a root this run created. Safe to repeat; refuses anything else."""
    if not root.exists():
        return {"status": "already-absent", "errors": []}
    try:
        owner = json.loads((root / MARKER).read_text(encoding="utf-8")).get("nonce")
    except (OSError, ValueError):
        owner = None
    if owner != nonce:
        return {"status": "refused-not-owned", "errors": [f"{root} carries no matching marker"]}
    errors: list[str] = []

    def record(_func: object, path: str, exc: object) -> None:
        errors.append(f"{path}: {exc}")

    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=record)
    else:  # pragma: no cover - 3.11 only
        shutil.rmtree(root, onerror=record)
    return {"status": "removed" if not errors else "partial", "errors": errors}


# ------------------------------------------------------------ fingerprints


def fingerprint_host(host_codex: Path) -> dict[str, object]:
    """The host client's install-relevant state: its skills tree and config files.

    Sessions, logs and caches are left out on purpose: another session using the
    client writes those continuously, and a fingerprint that moves for reasons
    unrelated to this run detects nothing.
    """
    state: dict[str, object] = {"path": str(host_codex)}
    skills = host_codex / "skills"
    if skills.is_dir():
        h = hashlib.sha256()
        for path in sorted(skills.rglob("*")):
            rel = path.relative_to(skills).as_posix()
            if path.is_symlink():
                h.update(f"{rel}\0link\0{os.readlink(path)}\n".encode())
            elif path.is_file():
                h.update(f"{rel}\0{sha256_file(path)}\n".encode())
        state["skills"] = "sha256:" + h.hexdigest()
    else:
        state["skills"] = "absent"
    for name in ("config.toml", "AGENTS.md"):
        f = host_codex / name
        state[name] = sha256_file(f) if f.is_file() else "absent"
    return state


def fingerprint_source(source: Source, subject: Subject) -> dict[str, object]:
    if source.kind == "snapshot":
        return {"surface": tree_digest(source.origin / subject.skills_root)}
    head = _git(source.origin, "rev-parse", "HEAD").stdout.decode().strip()
    status = _git(source.origin, "status", "--porcelain=v1", "--untracked-files=all").stdout
    return {"head": head, "status": sha256_bytes(status)}


# ---------------------------------------------------------------- the client


@dataclass
class Listing:
    """What the client said it can see, or why that is unknown."""

    status: str  # "ok", "absent", "failed", "unparseable", "timeout"
    detail: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)  # (name, absolute file)
    normalized: str = ""  # everything else the client would be given, arm paths removed


def run_client(argv: list[str], home: Path, codex_home: Path, cwd: Path,
               extra: tuple[str, ...], timeout: float) -> tuple[int | None, str, str]:
    path_dirs = [str(Path(argv[0]).parent), "/usr/local/bin", "/usr/bin", "/bin"]
    env = {"HOME": str(home), "CODEX_HOME": str(codex_home), "PATH": ":".join(path_dirs),
           "LANG": "C.UTF-8"}
    proc = subprocess.Popen(
        [*argv, *extra], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Stop the whole process group this run started, not just the direct child.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return None, "", "timeout"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def client_version(argv: list[str], home: Path, codex_home: Path, cwd: Path) -> str:
    code, out, _ = run_client(argv, home, codex_home, cwd, ("--version",), 30)
    if code != 0:
        return "unknown"
    match = re.search(r"(\d+\.\d+\.\d+\S*)", out)
    return match.group(1) if match else "unknown"


def parse_listing(stdout: str, arm_dir: Path) -> Listing:
    """Pull the skill listing out of the rendered prompt input.

    No listing block is UNPARSEABLE, not "no skills": the client seeds its own
    skills in every home, so a missing block means the output changed shape.
    """
    try:
        items = json.loads(stdout)
    except ValueError as exc:
        return Listing("unparseable", f"client output is not JSON: {exc}")
    if not isinstance(items, list):
        return Listing("unparseable", "client output is not a list")
    entries: list[tuple[str, str]] = []
    texts: list[str] = []
    seen_block = False
    for item in items:
        if not isinstance(item, dict):
            return Listing("unparseable", "client output item is not an object")
        for content in item.get("content", []) or []:
            text = str(content.get("text", "")) if isinstance(content, dict) else ""
            if "<skills_instructions>" in text:
                seen_block = True
                roots: dict[str, str] = {}
                for line in text.splitlines():
                    root = _ROOT_LINE_RE.match(line)
                    if root:
                        roots[root.group(1)] = root.group(2)
                        continue
                    skill = _SKILL_LINE_RE.match(line)
                    if skill:
                        base = roots.get(skill.group(2))
                        if base is None:
                            return Listing("unparseable", f"skill {skill.group(1)} names an "
                                           f"undeclared root {skill.group(2)}")
                        entries.append((skill.group(1), f"{base}/{skill.group(3)}"))
                text = "<skills_instructions/>"  # compared separately, as entries
            texts.append(f"{item.get('role')}|{content.get('type') if isinstance(content, dict) else ''}|{text}")
    if not seen_block:
        return Listing("unparseable", "no skills listing in the client output")
    normalized = "\n".join(texts).replace(str(arm_dir), "<ARM>")
    return Listing("ok", entries=entries, normalized=normalized)


def canary(argv: list[str] | None, arm: Arm, timeout: float) -> Listing:
    if argv is None:
        return Listing("absent", f"client {CLIENT!r} not found")
    code, out, err = run_client(argv, arm.home, arm.codex_home, arm.workspace,
                                (*CANARY_ARGV, CANARY_PROMPT), timeout)
    if code is None:
        return Listing("timeout", f"client did not finish within {timeout}s")
    if code != 0:
        return Listing("failed", f"client exited {code}: {err.strip()[:400]}")
    return parse_listing(out, arm.directory)


# -------------------------------------------------------------------- arms


@dataclass
class Arm:
    name: str
    directory: Path

    @property
    def home(self) -> Path:
        return self.directory / "home"

    @property
    def codex_home(self) -> Path:
        return self.home / ".codex"

    @property
    def skills(self) -> Path:
        return self.codex_home / "skills"

    @property
    def workspace(self) -> Path:
        return self.directory / "workspace"


def prepare_arm(root: Path, name: str, workspace_fixture: Path | None) -> Arm:
    arm = Arm(name, root / name)
    arm.skills.mkdir(parents=True)
    if workspace_fixture is not None:
        shutil.copytree(workspace_fixture, arm.workspace)
    else:
        arm.workspace.mkdir()
    return arm


def install(arm: Arm, source: Source, entries: list[SkillEntry]) -> list[dict[str, str]]:
    """Copy each selected skill directory to <CODEX_HOME>/skills/<dir>, then re-digest."""
    installed: list[dict[str, str]] = []
    for entry in entries:
        dest = arm.skills / entry.directory
        if dest.exists():
            raise Refused(f"target collision: {dest.relative_to(arm.home)} already exists")
        shutil.copytree(source.surface_dir / entry.directory, dest)
        for f in entry.files:
            target = dest / str(f["path"])
            if sha256_file(target) != f["digest"]:
                raise Refused(f"installed copy differs from the source: {target}")
            installed.append({
                "path": target.relative_to(arm.home).as_posix(),
                "digest": str(f["digest"]),
            })
    return installed


def _expected(arm: Arm, entries: list[SkillEntry]) -> set[tuple[str, str]]:
    return {(e.name, str((arm.skills / e.directory / "SKILL.md").resolve())) for e in entries}


def _resolved(listing: Listing) -> set[tuple[str, str]]:
    return {(n, str(Path(p).resolve())) for n, p in listing.entries}


def _relative(listing: Listing, arm: Arm) -> set[tuple[str, str]]:
    home = str(arm.home.resolve())
    return {(n, p.replace(home, "<HOME>")) for n, p in _resolved(listing)}


@dataclass
class Readiness:
    discovery_canary: str
    baseline_absence: str
    ordinary_parity: str
    reasons: dict[str, str]


def derive_readiness(
    subject: Subject, observed_version: str, entries: list[SkillEntry],
    treatment: Arm, t_list: Listing, baseline: Arm, b_list: Listing,
    control: Arm, c_list: Listing,
) -> Readiness:
    """Readiness comes from what the client listed. Nothing static enters here."""
    reasons: dict[str, str] = {}
    names = {e.name for e in entries}

    def unusable(listing: Listing, arm: str) -> str | None:
        if listing.status != "ok":
            return f"{arm} canary {listing.status}: {listing.detail}"
        if observed_version != subject.client_version:
            return (f"client version {observed_version} is not the declared "
                    f"{subject.client_version}")
        return None

    # Discovery: every selected skill is listed, from the file this run installed.
    why = unusable(t_list, "treatment")
    if why:
        discovery, reasons["discovery_canary"] = UNKNOWN, why
    else:
        missing = sorted(n for n, _ in _expected(treatment, entries) - _resolved(t_list))
        if missing:
            discovery = VIOLATED
            reasons["discovery_canary"] = f"installed but not listed: {missing}"
        else:
            discovery = SATISFIED
            reasons["discovery_canary"] = f"all {len(entries)} installed skill(s) listed"

    # Baseline absence, and the planted control that proves this check can fail.
    why = unusable(b_list, "baseline") or unusable(c_list, "control")
    if why:
        absence, reasons["baseline_absence"] = UNKNOWN, why
    else:
        planted = _expected(control, entries[:1])
        contaminated = sorted(n for n, _ in _resolved(b_list) if n in names)
        foreign = sorted(
            n for n, p in _resolved(b_list)
            if Path(p).is_relative_to(baseline.skills.resolve())
            and not Path(p).is_relative_to((baseline.skills / CLIENT_SYSTEM_DIR).resolve())
        )
        if not planted <= _resolved(c_list):
            absence = UNKNOWN
            reasons["baseline_absence"] = (
                "negative control failed: a treatment skill planted in a baseline home "
                "was not listed, so absence from the baseline proves nothing"
            )
        elif contaminated or foreign:
            absence = VIOLATED
            reasons["baseline_absence"] = (
                f"baseline lists treatment or non-client skill(s): "
                f"{sorted(set(contaminated) | set(foreign))}"
            )
        else:
            absence = SATISFIED
            reasons["baseline_absence"] = (
                "no treatment skill listed in the baseline; the planted control was listed"
            )

    # Parity: the baseline sees exactly what the treatment sees, minus the treatment.
    why = unusable(t_list, "treatment") or unusable(b_list, "baseline")
    if why:
        parity, reasons["ordinary_parity"] = UNKNOWN, why
    else:
        home = str(treatment.home.resolve())
        treated = {(n, p.replace(home, "<HOME>")) for n, p in _expected(treatment, entries)}
        ordinary_t = _relative(t_list, treatment) - treated
        ordinary_b = _relative(b_list, baseline)
        if ordinary_t != ordinary_b:
            parity = VIOLATED
            reasons["ordinary_parity"] = (
                f"skill listings differ outside the treatment: only treatment "
                f"{sorted(ordinary_t - ordinary_b)}, only baseline "
                f"{sorted(ordinary_b - ordinary_t)}"
            )
        elif t_list.normalized != b_list.normalized:
            parity = VIOLATED
            reasons["ordinary_parity"] = "the rest of the client input differs between arms"
        else:
            parity = SATISFIED
            reasons["ordinary_parity"] = "identical client input apart from the treatment"
    return Readiness(discovery, absence, parity, reasons)


# ------------------------------------------------------------------- the run


@dataclass
class Result:
    receipt: dict[str, object] | None
    report: dict[str, object]

    @property
    def ready(self) -> bool:
        """Every readiness fact SATISFIED. Anything UNKNOWN is not ready."""
        if self.receipt is None:
            return False
        readiness = self.receipt["readiness"]
        assert isinstance(readiness, dict)
        return all(readiness.get(k) == SATISFIED for k in READINESS_FACTS)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def materialize(
    subject: Subject,
    *,
    attempt_id: str,
    trial_id: str,
    base: Path,
    repo: Path | None = None,
    snapshot: Path | None = None,
    client: list[str] | None = None,
    workspace_fixture: Path | None = None,
    host_codex: Path | None = None,
    keep: bool = False,
    timeout: float = 120,
) -> Result:
    """Acquire, install, probe both arms and a planted control, then clean up.

    Never raises for a subject problem: a refusal comes back as a report with no
    receipt, and the root is cleaned whatever happened.
    """
    if (repo is None) == (snapshot is None):
        raise ValueError("exactly one of repo or snapshot")
    origin = (repo or snapshot)
    assert origin is not None
    origin = origin.resolve()
    host_codex = (host_codex or Path.home() / ".codex").resolve()
    observations: dict[str, object] = {
        "installed": "NOT_OBSERVED", "available": UNKNOWN,
        "invoked": "NOT_OBSERVED", "task_outcome": "NOT_APPLICABLE",
    }
    report: dict[str, object] = {
        "started": _now(),
        "adapter": ADAPTER,
        "subject": {k: v for k, v in subject.raw.items() if k != "notes"},
        "observations": observations,
    }
    host_before = fingerprint_host(host_codex)
    root, nonce = create_root(base, [*forbidden_roots(origin), host_codex])
    receipt: dict[str, object] | None = None
    facts: dict[str, str] = {}
    reasons: dict[str, str] = {}
    try:
        staging = root / "staging"
        staging.mkdir()
        source = (acquire_git(subject, origin, staging) if repo is not None
                  else acquire_snapshot(subject, origin, staging))
        source_before = fingerprint_source(source, subject)
        entries = inventory(subject, source)
        chosen = {e.directory for e in entries}
        report["source"] = {"kind": source.kind, "revision": source.revision,
                            "digest": source.digest}
        report["inventory"] = {
            "skills": [
                {"directory": e.directory, "name": e.name, "files": len(e.files),
                 "checksums": e.checksums, "required_refs": e.required_refs}
                for e in entries
            ],
            "not_installed_entries": sorted(
                p.name for p in source.surface_dir.iterdir() if p.name not in chosen
            ),
        }
        report["static_findings"] = {
            "note": "static observations only; they never establish or refute readiness",
            "unresolved_mentions": [f"{e.directory}: {s}" for e in entries
                                    for s in e.static_findings],
        }

        treatment = prepare_arm(root, "treatment", workspace_fixture)
        baseline = prepare_arm(root, "baseline", workspace_fixture)
        control = prepare_arm(root, "control", workspace_fixture)
        installed = install(treatment, source, entries)
        install(control, source, entries[:1])
        observations["installed"] = f"{len(installed)} file(s) in {len(entries)} skill(s)"

        version = (client_version(client, treatment.home, treatment.codex_home,
                                  treatment.workspace) if client else "unknown")
        t_list = canary(client, treatment, timeout)
        b_list = canary(client, baseline, timeout)
        c_list = canary(client, control, timeout)
        for f in installed:
            if sha256_file(treatment.home / f["path"]) != f["digest"]:
                raise Refused(f"client altered an installed file: {f['path']}")
        readiness = derive_readiness(subject, version, entries, treatment, t_list,
                                     baseline, b_list, control, c_list)
        facts.update(discovery_canary=readiness.discovery_canary,
                     baseline_absence=readiness.baseline_absence,
                     ordinary_parity=readiness.ordinary_parity)
        reasons.update(readiness.reasons)
        observations["available"] = readiness.discovery_canary
        report["client"] = {"name": CLIENT, "declared": subject.client_version,
                            "observed": version,
                            "argv": [Path(a).name for a in client] if client else None}
        report["canary"] = {
            arm.name: {"status": lst.status, "detail": lst.detail,
                       "listed": sorted(f"{n} {p}" for n, p in _relative(lst, arm))}
            for arm, lst in ((treatment, t_list), (baseline, b_list), (control, c_list))
        }
        report["control"] = {
            "planted": entries[0].name,
            "listed": c_list.status == "ok"
            and _expected(control, entries[:1]) <= _resolved(c_list),
        }
        source_after = fingerprint_source(source, subject)
        report["source_immutability"] = {"before": source_before, "after": source_after}
        facts["source_unchanged"] = SATISFIED if source_before == source_after else VIOLATED
        reasons["source_unchanged"] = ("source fingerprint identical before and after"
                                       if source_before == source_after
                                       else "the source changed during the run")
        layer = treatment.workspace / "AGENTS.md"
        receipt = {
            "version": 2,
            "kind": "installation-receipt",
            "producer": "subject-adapter",
            "checked_by": "controller",
            "attempt_id": attempt_id,
            "trial_id": trial_id,
            "subject": {"locator": subject.locator, "revision": source.revision,
                        "digest": source.digest},
            "surface": SURFACE,
            "treatment": "native-install",
            "adapter": dict(ADAPTER),
            "client": {"name": CLIENT, "version": version},
            "layers": [
                {"name": "client input, normalized (treatment arm)",
                 "digest": (sha256_bytes(t_list.normalized.encode())
                            if t_list.status == "ok" else None)},
                {"name": "CODEX_HOME/config.toml", "digest": None, "state": "absent"},
                {"name": "CODEX_HOME/AGENTS.md", "digest": None, "state": "absent"},
                {"name": "workspace/AGENTS.md",
                 "digest": sha256_file(layer) if layer.is_file() else None,
                 "state": "present" if layer.is_file() else "absent"},
            ],
            "dependencies": [{"skill": e.directory, **x} for e in entries for x in e.external],
            "allowed_writes": ["home/", "workspace/"],
            "installed": installed,
            "readiness": facts,
            "observations": observations,
        }
    except Refused as exc:
        report["refused"] = str(exc)
        receipt = None
    finally:
        report["cleanup"] = {"status": "kept", "errors": []} if keep else cleanup(root, nonce)
        host_after = fingerprint_host(host_codex)
        report["host_immutability"] = {"before": host_before, "after": host_after}
        report["finished"] = _now()
    # Set after the finally, so it covers everything the run did, cleanup included.
    facts["host_unchanged"] = SATISFIED if host_before == host_after else VIOLATED
    reasons["host_unchanged"] = ("host client state identical before and after"
                                 if host_before == host_after
                                 else "the host client state changed during the run")
    report["readiness"] = {**facts, "reasons": reasons}
    text = json.dumps(report)
    if not keep:
        text = text.replace(str(root), "<ROOT>")
    return Result(receipt, json.loads(text))


def find_client(explicit: str | None) -> list[str] | None:
    if explicit:
        return [str(Path(explicit).resolve())]
    found = shutil.which(CLIENT)
    return [found] if found else None
