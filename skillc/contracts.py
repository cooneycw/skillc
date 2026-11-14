"""Skill contracts: a `CHARTER.md` beside each `SKILL.md`, checked across a collection (#720).

A skill's instructions say what to do; nothing says what it PROMISES, so
"improve this skill" had no definition and a hand-off between two skills had
nothing to check against. A contract is the YAML block at the top of
`CHARTER.md` (docs/specs/contracts.md): intent, purpose, scope, requires,
provides (with readers), consumes, invariants, authority, failure, version and
owner. Every clause carries an id and a test.

The rules here read what contracts DECLARE. A green `skillc contracts` says the
declarations are complete and agree with each other: every clause names a test
that exists, every `never`/`authority` clause names a bad case, every hand-off
is known to both sides at the same version, every reader and every `out` duty
has an owner. It never RUNS a clause's tests - whether a named test can
actually fail is rounds 3 and 4 of the skill-gauntlet (#718). In particular the
"bad case" convention below proves a negative case is PRESENT, not that it can
fail.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .spec import FrontmatterError, parse_contract_block

CHARTER = "CHARTER.md"
SUBSET_DOC = "docs/specs/contracts.md"

#: Required top-level fields; every other section is optional and type-checked
#: when present. `intent` and `purpose` are owner- and purpose-task-checked in
#: #718's table, so they are not clause lists and carry no `test`.
REQUIRED = ("contract", "version", "intent", "purpose", "owner")
#: Clause lists: each entry is a mapping with an `id` and a `test`.
CLAUSE_SECTIONS = ("requires", "provides", "authority", "failure")
INVARIANT_KINDS = ("always", "never")
OPTIONAL = ("scope", "consumes", "invariants", *CLAUSE_SECTIONS)
KNOWN_FIELDS = frozenset((*REQUIRED, *OPTIONAL))

NAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
CLAUSE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CONSUMES_RE = re.compile(rf"({CLAUSE_ID_RE.pattern})@([1-9][0-9]{{0,8}})")  # bounded: int() never sees 4,000 digits
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
BRACE_RE = re.compile(r"\{([^{}]*)\}")
OWNER_READER = "owner"
#: The negative-case convention: a test path with a segment named exactly this.
BAD_SEGMENT = "bad"


@dataclass
class Contract:
    """One CHARTER.md and the contract block it declares."""

    path: Path
    data: dict[str, object] = field(default_factory=dict)
    parse_error: str | None = None

    @property
    def name(self) -> str:
        value = self.data.get("contract")
        return value if isinstance(value, str) else ""

    def version(self) -> int | None:
        value = self.data.get("version")
        return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class Collection:
    """Every CHARTER.md under one root. Test paths resolve from that root."""

    root: Path
    contracts: list[Contract]

    @property
    def parse_error(self) -> str | None:
        broken = [c for c in self.contracts if c.parse_error is not None]
        return f"{broken[0].path.relative_to(self.root)}: {broken[0].parse_error}" if broken else None


def load(path: Path) -> Contract:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Contract(path=path, parse_error=str(exc))
    try:
        data, _body = parse_contract_block(text)
    except FrontmatterError as exc:
        return Contract(path=path, parse_error=f"{exc} [contract YAML subset: {SUBSET_DOC}]")
    return Contract(path=path, data=data)


def load_collection(root: Path) -> Collection:
    found = sorted(p for p in root.rglob(CHARTER) if p.is_file()) if root.is_dir() else []
    return Collection(root=root, contracts=[load(p) for p in found])


# ---------------------------------------------------------------- shape


def _clauses(contract: Contract) -> Iterator[tuple[str, dict[str, object]]]:
    """Every well-formed clause as (section, clause); `invariants.never` etc."""
    data = contract.data
    for section in CLAUSE_SECTIONS:
        entries = data.get(section)
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    yield section, entry
    invariants = data.get("invariants")
    if isinstance(invariants, dict):
        for kind in INVARIANT_KINDS:
            entries = invariants.get(kind)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        yield f"invariants.{kind}", entry


def _str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def _clause_shape(section: str, entry: object, where: str) -> Iterator[str]:
    if not isinstance(entry, dict):
        yield f"{where}: a {section} entry is not a mapping with an id"
        return
    clause_id = entry.get("id")
    if not isinstance(clause_id, str) or not CLAUSE_ID_RE.fullmatch(clause_id):
        yield f"{where}: a {section} clause has no well-formed id ({clause_id!r})"
    test = entry.get("test")
    if test is not None and not (isinstance(test, str) and test.strip()) and not _str_list(test):
        yield f"{where}: {section} clause {clause_id!r} test is not a path or a list of paths"
    if "version" in entry:
        version = entry["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            yield f"{where}: {section} clause {clause_id!r} version {version!r} is not a positive integer"
    if section == "provides" and "readers" in entry and not _str_list(entry["readers"]):
        yield f"{where}: provides clause {clause_id!r} readers is not a list of names"
    if "approved" in entry and not _is_date(entry["approved"]):
        yield f"{where}: {section} clause {clause_id!r} approved {entry['approved']!r} is not a YYYY-MM-DD date"


def _is_date(value: object) -> bool:
    if isinstance(value, _dt.date):
        return True
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _contract_shape_problems(contract: Contract) -> list[str]:
    if contract.parse_error is not None:
        return [f"the contract block does not parse: {contract.parse_error}"]
    data = contract.data
    problems: list[str] = []
    for key in REQUIRED:
        if key not in data or data[key] in (None, ""):
            problems.append(f"required field {key!r} is missing")
    for key in data:
        if key not in KNOWN_FIELDS:
            problems.append(f"unknown field {key!r}; known fields: {sorted(KNOWN_FIELDS)}")
    if "contract" in data and not (isinstance(data["contract"], str) and NAME_RE.fullmatch(data["contract"])):
        problems.append(f"contract name {data['contract']!r} is not a lowercase dash-separated name")
    if "version" in data and data["version"] is not None:
        version = data["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            problems.append(f"version {version!r} is not a positive integer")
    for key in ("purpose", "owner"):
        text = data.get(key)
        if text is not None and not (isinstance(text, str) and text.strip()):
            problems.append(f"{key} is not text")
    intent = data.get("intent")
    if intent is not None and not (isinstance(intent, str) and intent.strip()):
        if not isinstance(intent, dict):
            problems.append("intent is neither text nor a clause mapping")
        else:
            if not (isinstance(intent.get("what"), str) and intent["what"].strip()):
                problems.append("intent clause has no 'what' text")
            if "approved" in intent and not _is_date(intent["approved"]):
                problems.append(f"intent approved {intent['approved']!r} is not a YYYY-MM-DD date")
    scope = data.get("scope")
    if scope is not None:
        if not isinstance(scope, dict) or set(scope) - {"in", "out"}:
            problems.append("scope is not a mapping of 'in' and 'out' lists")
        else:
            for side in ("in", "out"):
                if side in scope and not _str_list(scope[side]):
                    problems.append(f"scope.{side} is not a list of duty ids")
    consumes = data.get("consumes")
    if consumes is not None:
        if not isinstance(consumes, list):
            problems.append("consumes is not a list")
        else:
            for item in consumes:
                if not isinstance(item, str) or not CONSUMES_RE.fullmatch(item):
                    problems.append(f"consumes entry {item!r} is not '<clause-id>@<version>'")
    for section in CLAUSE_SECTIONS:
        entries = data.get(section)
        if entries is None:
            continue
        if not isinstance(entries, list):
            problems.append(f"{section} is not a list of clauses")
            continue
        for entry in entries:
            problems.extend(_clause_shape(section, entry, section))
    invariants = data.get("invariants")
    if invariants is not None:
        if not isinstance(invariants, dict) or set(invariants) - set(INVARIANT_KINDS):
            problems.append("invariants is not a mapping of 'always' and 'never' lists")
        else:
            for kind in INVARIANT_KINDS:
                entries = invariants.get(kind)
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    problems.append(f"invariants.{kind} is not a list of clauses")
                    continue
                for entry in entries:
                    problems.extend(_clause_shape(f"invariants.{kind}", entry, f"invariants.{kind}"))
    ids = Counter(str(c.get("id")) for _s, c in _clauses(contract) if isinstance(c.get("id"), str))
    for clause_id, count in sorted(ids.items()):
        if count > 1:
            problems.append(f"clause id {clause_id!r} is declared {count} times in this contract")
    return problems


def _shape_ok(collection: Collection) -> list[Contract]:
    return [c for c in collection.contracts if not _contract_shape_problems(c)]


def _collection_problems(collection: Collection) -> list[Finding]:
    """Facts that are wrong only BETWEEN contracts: a contract name declared
    twice, or a provided clause id two contracts both provide. Either makes
    every cross-contract lookup depend on file order (counter-model review)."""
    found: list[Finding] = []
    names: Counter[str] = Counter(c.name for c in collection.contracts if c.name)
    for contract in collection.contracts:
        if contract.name and names[contract.name] > 1:
            found.append((contract.path, f"contract name {contract.name!r} is declared by {names[contract.name]} CHARTER.md files"))
    providers: dict[str, list[Contract]] = {}
    for contract in _shape_ok(collection):
        for section, clause in _clauses(contract):
            if section == "provides" and isinstance(clause.get("id"), str):
                providers.setdefault(str(clause["id"]), []).append(contract)
    for clause_id, owners in sorted(providers.items()):
        if len(owners) > 1:
            who = ", ".join(repr(c.name) for c in owners)
            for contract in owners:
                detail = (f"provided clause {clause_id!r} is provided by {len(owners)} contracts "
                          f"({who}); a consumer cannot tell which version it is handed")
                found.append((contract.path, detail))
    return found


def _cross_ready(collection: Collection) -> bool:
    """Cross-contract rules run only when EVERY contract has a valid shape AND
    the collection itself is unambiguous: a hand-off naming a provider that
    failed to parse would otherwise read as "nothing provides it", and a
    duplicate name or provider would let file order pick the answer."""
    return (bool(collection.contracts) and len(_shape_ok(collection)) == len(collection.contracts)
            and not _collection_problems(collection))


Finding = tuple[Path, str]


def contract_shape(collection: Collection) -> Iterator[Finding]:
    """Each block parses and declares the required fields in their types."""
    for contract in collection.contracts:
        for problem in _contract_shape_problems(contract):
            yield contract.path, problem
    yield from _collection_problems(collection)


# ---------------------------------------------------------------- tests named


def expand(test: str) -> tuple[list[str], str | None]:
    """One level of `{a,b}` expansion, or a reason it cannot be read."""
    groups = BRACE_RE.findall(test)
    if "{" in BRACE_RE.sub("", test) or "}" in BRACE_RE.sub("", test):
        return [], f"test path {test!r} has unbalanced or nested braces; expansion is one level only"
    if len(groups) > 1:
        return [], f"test path {test!r} has {len(groups)} brace groups; expansion is one level only"
    if not groups:
        return [test], None
    options = [o.strip() for o in groups[0].split(",")]
    if any(not o for o in options):
        return [], f"test path {test!r} has an empty brace option"
    # Literal concatenation, never a regex replacement: an option is a path
    # fragment, and `\q` in one must not be read as a replacement escape.
    start, end = test.index("{"), test.index("}")
    return [test[:start] + option + test[end + 1:] for option in options], None


def _tests(clause: dict[str, object]) -> list[str]:
    test = clause.get("test")
    if isinstance(test, str) and test.strip():
        return [test]
    if isinstance(test, list) and _str_list(test):
        return [str(t) for t in test]
    return []


def _inside(root: Path, rel: str) -> bool:
    """Lexically AND after symlink resolution: a `checks/external -> /outside`
    link must not let a path outside the collection back a clause."""
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    try:
        return (root / rel).resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def clause_backed(collection: Collection) -> Iterator[Finding]:
    """Every clause names a test, and every path it names exists in the collection."""
    for contract in _shape_ok(collection):
        for section, clause in _clauses(contract):
            clause_id = clause.get("id")
            tests = _tests(clause)
            if not tests:
                yield contract.path, f"{section} clause {clause_id!r} has no test: unbacked"
                continue
            for test in tests:
                expanded, problem = expand(test)
                if problem:
                    yield contract.path, f"{section} clause {clause_id!r}: {problem}: unbacked"
                    continue
                for rel in expanded:
                    if not _inside(collection.root, rel):
                        yield contract.path, f"{section} clause {clause_id!r} test {rel!r} is outside the collection: unbacked"
                    elif not (collection.root / rel).exists():
                        yield contract.path, (
                            f"{section} clause {clause_id!r} test {rel!r} does not exist: unbacked "
                            f"(every path a brace expansion yields must exist)"
                        )


def negative_backed(collection: Collection) -> Iterator[Finding]:
    """A `never` or `authority` clause names a bad case (a path segment `bad`)."""
    for contract in _shape_ok(collection):
        for section, clause in _clauses(contract):
            if section not in ("invariants.never", "authority"):
                continue
            tests = _tests(clause)
            if not tests:
                continue  # clause-backed reports a clause with no test at all
            paths = [rel for test in tests for rel in expand(test)[0]]
            if not any(BAD_SEGMENT in PurePosixPath(rel).parts for rel in paths):
                yield contract.path, (
                    f"{section} clause {clause.get('id')!r} names no bad case (no test path has a "
                    f"'{BAD_SEGMENT}' segment); a safety line needs a failing example"
                )


# ---------------------------------------------------------------- hand-offs


def _providers(collection: Collection) -> dict[str, tuple[Contract, dict[str, object]]]:
    found: dict[str, tuple[Contract, dict[str, object]]] = {}
    for contract in collection.contracts:
        for section, clause in _clauses(contract):
            if section == "provides" and isinstance(clause.get("id"), str):
                found.setdefault(str(clause["id"]), (contract, clause))
    return found


def _consumes(contract: Contract) -> Iterator[tuple[str, str, int]]:
    consumes = contract.data.get("consumes")
    if isinstance(consumes, list):
        for item in consumes:
            match = CONSUMES_RE.fullmatch(item) if isinstance(item, str) else None
            if match:
                yield item, match.group(1), int(match.group(2))


def provided_version(contract: Contract, clause: dict[str, object]) -> int | None:
    """A clause's own `version`, else its contract's."""
    own = clause.get("version")
    if isinstance(own, int) and not isinstance(own, bool):
        return own
    return contract.version()


def handoff_bilateral(collection: Collection) -> Iterator[Finding]:
    """Every consumed clause is provided by some contract in the collection."""
    if not _cross_ready(collection):
        return
    providers = _providers(collection)
    for contract in collection.contracts:
        for item, clause_id, _version in _consumes(contract):
            if clause_id not in providers:
                yield contract.path, f"consumes {item!r}, but no contract in this collection provides {clause_id!r}"


def handoff_version(collection: Collection) -> Iterator[Finding]:
    """A consumer names the version its provider is at now."""
    if not _cross_ready(collection):
        return
    providers = _providers(collection)
    for contract in collection.contracts:
        for item, clause_id, version in _consumes(contract):
            if clause_id not in providers:
                continue
            provider, clause = providers[clause_id]
            current = provided_version(provider, clause)
            if current != version:
                yield contract.path, (
                    f"consumes {item!r}, but {provider.name!r} provides {clause_id!r} at @{current}; "
                    f"the consumer is carrying an older (or newer) copy of what it is handed"
                )


def _clause_ids(contract: Contract) -> set[str]:
    ids = {str(c["id"]) for _s, c in _clauses(contract) if isinstance(c.get("id"), str)}
    intent = contract.data.get("intent")
    if isinstance(intent, dict) and isinstance(intent.get("id"), str):
        ids.add(intent["id"])
    return ids


def reader_exists(collection: Collection) -> Iterator[Finding]:
    """Every reader is `owner`, a contract, or `<contract>.<clause>` that both exist."""
    if not _cross_ready(collection):
        return
    by_name = {c.name: c for c in collection.contracts}
    for contract in collection.contracts:
        for section, clause in _clauses(contract):
            if section != "provides":
                continue
            readers = clause.get("readers")
            for reader in readers if isinstance(readers, list) else []:
                if not isinstance(reader, str) or reader == OWNER_READER or reader in by_name:
                    continue
                name, _, rest = reader.partition(".")
                target = by_name.get(name)
                if not rest or target is None:
                    yield contract.path, (
                        f"provides {clause.get('id')!r} names reader {reader!r}, but no contract "
                        f"{name!r} exists and it is not {OWNER_READER!r}"
                    )
                elif rest not in _clause_ids(target) and reader not in _clause_ids(target):
                    yield contract.path, (
                        f"provides {clause.get('id')!r} names reader {reader!r}: contract {name!r} "
                        f"exists, but declares no clause {rest!r}"
                    )


def _scope(contract: Contract, side: str) -> list[str]:
    scope = contract.data.get("scope")
    values = scope.get(side) if isinstance(scope, dict) else None
    return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []


def scope_owned(collection: Collection) -> Iterator[Finding]:
    """Every `scope.out` duty is in another contract's `scope.in` (no orphans)."""
    if not _cross_ready(collection):
        return
    for contract in collection.contracts:
        owned_elsewhere = {d for other in collection.contracts if other is not contract for d in _scope(other, "in")}
        for duty in _scope(contract, "out"):
            if duty not in owned_elsewhere:
                yield contract.path, f"scope.out {duty!r} is owned by no other contract: an orphan duty"


def duty_single_owner(collection: Collection) -> Iterator[Finding]:
    """No `scope.in` duty is claimed by two contracts."""
    if not _cross_ready(collection):
        return
    owners: dict[str, list[Contract]] = {}
    for contract in collection.contracts:
        for duty in dict.fromkeys(_scope(contract, "in")):
            owners.setdefault(duty, []).append(contract)
    for duty, claimants in sorted(owners.items()):
        if len(claimants) > 1:
            names = ", ".join(repr(c.name) for c in claimants)
            for contract in claimants:
                yield contract.path, f"scope.in {duty!r} is claimed by {len(claimants)} contracts ({names}); pick one owner"


def approval_present(collection: Collection) -> Iterator[Finding]:
    """`intent` and `authority` clauses carry an owner `approved` date (warn only)."""
    for contract in _shape_ok(collection):
        intent = contract.data.get("intent")
        if not (isinstance(intent, dict) and _is_date(intent.get("approved"))):
            yield contract.path, "intent has no owner 'approved: YYYY-MM-DD'; it is a draft until the owner signs it"
        for section, clause in _clauses(contract):
            if section == "authority" and not _is_date(clause.get("approved")):
                yield contract.path, f"authority clause {clause.get('id')!r} has no owner 'approved' date; it is a draft"


#: Exit codes for `skillc contracts`, documented in docs/specs/contracts.md and README.
EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, EXIT_NONE_DECLARED = 0, 1, 2, 3

WHAT_WAS_EXAMINED = (
    "declared structure only; no clause's test was run, and a 'bad' path segment "
    "shows a negative case is present, not that it can fail (rounds 3 and 4, #718)"
)
