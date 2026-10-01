"""Tests for skillc/degrade.py (issue #150 acceptance item 2: a degraded CPP
subject expressible from the operator command line).

The `--checkout` leg needs no network and no `git` binary at all
(`materialize.acquire_snapshot`'s own convention). The `--revision` leg needs
`git`, and is tested against a LOCAL repository built with `git init`
(`tests/test_materialize.py`'s own `_git_repo` pattern) with
`demo.acquire_subject_checkout` monkeypatched to skip the real `git clone`
against `https://{locator}` - this module's own docstring is explicit that
the only network call `revision=` makes is that clone, and no real remote
exists for `test/test`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skillc import cli, degrade, demo, materialize

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: A test skill.\n---\nBody text.\n"


def _fixture_collection(tmp_path: Path, skills: dict[str, str], extra_files: dict[str, dict[str, str]] | None = None) -> Path:
    """A plain directory, never a git repository - mirrors
    `tests/test_collection_conformance.py`'s own `_fixture_collection`.
    `extra_files` is `{directory: {relpath: content}}`, for tests that edit a
    file other than SKILL.md itself."""
    collection = tmp_path / "subject-collection"
    skills_root = collection / "skills"
    for name, directory in skills.items():
        skill_dir = skills_root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
    for directory, files in (extra_files or {}).items():
        for relpath, content in files.items():
            path = skills_root / directory / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return collection


def _subject(
    revision: str = "v1", select: object = "all", checksum_manifest: str | None = None,
) -> materialize.Subject:
    data: dict[str, object] = {
        "subject_schema": 1, "locator": "test/test", "revision": revision, "surface": "codex-skills",
        "skills_root": "skills", "select": select, "client": {"name": "codex", "version": "0.157.1"},
    }
    if checksum_manifest is not None:
        data["checksum_manifest"] = checksum_manifest
    return materialize.Subject.from_dict(data)


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def _git_repo(tmp_path: Path, collection: Path) -> tuple[Path, str]:
    """A LOCAL git repo, never cloned from a network - `tests/test_materialize
    .py`'s own `_git_repo` pattern."""
    repo = tmp_path / "repo"
    shutil.copytree(collection, repo)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    return repo, git("rev-parse", "HEAD")


# ------------------------------------------------------------------ checkout


def test_checkout_degradation_removes_the_named_skill_and_labels_the_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd", "other": "other"})
    subject = _subject()
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)

    degraded = degrade.acquire_degraded(
        "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("tdd",)), checkout=collection,
    )

    assert degraded.source.kind == "degraded"
    assert degraded.source.revision != subject.revision
    assert degraded.source.revision.startswith("degraded:mutated=1-location:")
    assert degraded.source.digest != degraded.base.digest
    assert not (degraded.source.surface_dir / "tdd").exists()
    assert (degraded.source.surface_dir / "other").is_dir()


def test_checkout_mutation_naming_an_absent_skill_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case 2: a mutation that names a skill absent from the collection
    must be refused."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    with pytest.raises(degrade.DegradationRefused, match="absent from the collection"):
        degrade.acquire_degraded(
            "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("does-not-exist",)), checkout=collection,
        )


def test_mutation_naming_an_unselected_skill_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`inventory()` scopes "the collection" to `subject.select`; a skill
    present on disk but not selected is not installed, so removing it is not
    a meaningful degradation either - same red case, a different route to it."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd", "other": "other"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    with pytest.raises(degrade.DegradationRefused, match="absent from the collection"):
        degrade.acquire_degraded(
            "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("other",)), checkout=collection,
        )


def test_neither_checkout_nor_revision_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    with pytest.raises(degrade.DegradationRefused, match="exactly one of"):
        degrade.acquire_degraded("whatever", tmp_path / "base", None)


def test_both_checkout_and_revision_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    with pytest.raises(degrade.DegradationRefused, match="exactly one of"):
        degrade.acquire_degraded(
            "whatever", tmp_path / "base", None, checkout=tmp_path, revision="deadbeef" * 5,
        )


def test_an_empty_mutation_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    with pytest.raises(degrade.DegradationRefused, match="neither a skill removal nor a file edit"):
        degrade.acquire_degraded("whatever", tmp_path / "base", degrade.Mutation(), checkout=collection)


# --------------------------------------------------------------- multi-location


def test_a_mutation_can_remove_and_override_files_across_several_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors #150-A's own finding: one rule restated across several skills
    and duplicated scripts - a single declared mutation must be able to touch
    all of them at once, some by whole-file removal, some by override."""
    collection = _fixture_collection(
        tmp_path,
        {"flow-finish": "flow-finish", "flow-merge": "flow-merge", "flow-auto": "flow-auto"},
        extra_files={
            "flow-finish": {"reference.md": "the rule, stated once\n"},
            "flow-merge": {
                "reference.md": "the rule, restated\n",
                "scripts/gh-pr-merge.sh": "#!/bin/sh\n# guard_negated_close_keywords\n",
            },
            "flow-auto": {
                "reference.md": "the rule, restated again\n",
                "scripts/gh-pr-merge.sh": "#!/bin/sh\n# guard_negated_close_keywords\n",
            },
        },
    )
    monkeypatch.setattr(
        demo, "load_demo_subject",
        lambda name: _subject(select=["flow-finish", "flow-merge", "flow-auto"]),
    )

    mutation = degrade.Mutation(
        edits=(
            degrade.FileEdit(skill="flow-finish", path="reference.md", content=b"the rule is gone\n"),
            degrade.FileEdit(skill="flow-merge", path="reference.md", content=b"the rule is gone\n"),
            degrade.FileEdit(skill="flow-auto", path="reference.md", content=b"the rule is gone\n"),
            degrade.FileEdit(skill="flow-merge", path="scripts/gh-pr-merge.sh", content=None),
            degrade.FileEdit(skill="flow-auto", path="scripts/gh-pr-merge.sh", content=None),
        ),
    )
    degraded = degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)

    surface = degraded.source.surface_dir
    assert (surface / "flow-finish" / "reference.md").read_text() == "the rule is gone\n"
    assert (surface / "flow-merge" / "reference.md").read_text() == "the rule is gone\n"
    assert (surface / "flow-auto" / "reference.md").read_text() == "the rule is gone\n"
    assert not (surface / "flow-merge" / "scripts" / "gh-pr-merge.sh").exists()
    assert not (surface / "flow-auto" / "scripts" / "gh-pr-merge.sh").exists()
    assert len(mutation.locations()) == 5
    assert degraded.source.revision.startswith("degraded:mutated=5-location:")


def test_an_override_with_byte_identical_content_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(
        tmp_path, {"tdd": "tdd"}, extra_files={"tdd": {"reference.md": "unchanged\n"}},
    )
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    mutation = degrade.Mutation(edits=(degrade.FileEdit(skill="tdd", path="reference.md", content=b"unchanged\n"),))
    with pytest.raises(degrade.DegradationRefused, match="byte-identical"):
        degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)


def test_an_edit_naming_an_absent_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    mutation = degrade.Mutation(edits=(degrade.FileEdit(skill="tdd", path="does-not-exist.md", content=None),))
    with pytest.raises(degrade.DegradationRefused, match="absent from the staged surface"):
        degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)


def test_an_edit_path_that_escapes_its_skill_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd", "other": "other"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    mutation = degrade.Mutation(edits=(degrade.FileEdit(skill="tdd", path="../other/SKILL.md", content=None),))
    with pytest.raises(degrade.DegradationRefused, match="escapes its skill's directory"):
        degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)


def test_a_skill_both_wholly_removed_and_separately_edited_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    mutation = degrade.Mutation(
        remove_skills=("tdd",), edits=(degrade.FileEdit(skill="tdd", path="SKILL.md", content=None),),
    )
    with pytest.raises(degrade.DegradationRefused, match="redundant"):
        degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)


# ------------------------------------------------------------ identical case


@needs_git
def test_a_pin_equal_revision_with_no_mutation_is_refused_as_identical_to_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case 1: a degraded subject whose recorded identity equals the
    normal one must be refused. Reached with a real, public input: the
    subject's OWN pinned revision, given back as `revision=`, with no
    mutation - nothing here differs from an ordinary acquisition."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    repo, sha = _git_repo(tmp_path, collection)
    subject = _subject(revision=sha)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    monkeypatch.setattr(demo, "acquire_subject_checkout", lambda subj, into, timeout=300: repo)

    with pytest.raises(degrade.DegradationRefused, match="would equal the normal one"):
        degrade.acquire_degraded("whatever", tmp_path / "base", None, revision=sha)


@needs_git
def test_a_different_revision_with_no_mutation_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common source-only shape - a distinct revision, no skill removed -
    must NOT be caught by the identical-to-normal guard."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    repo, sha = _git_repo(tmp_path, collection)
    # A second commit gives a genuinely different, still-real revision.
    (repo / "skills" / "tdd" / "extra.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "second"],
        check=True, capture_output=True,
    )
    second_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    subject = _subject(revision=sha)  # pinned to the FIRST commit
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    monkeypatch.setattr(demo, "acquire_subject_checkout", lambda subj, into, timeout=300: repo)

    degraded = degrade.acquire_degraded("whatever", tmp_path / "base", None, revision=second_sha)

    assert degraded.source.kind == "degraded"
    assert degraded.source.revision.startswith("degraded:mutated=none:")


def test_a_checkout_source_override_with_no_mutation_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local snapshot is always structurally distinguishable (kind
    "snapshot" vs "git"), so it is never caught by the identical-to-normal
    guard even with no mutation."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    degraded = degrade.acquire_degraded("whatever", tmp_path / "base", None, checkout=collection)

    assert degraded.source.kind == "degraded"
    assert degraded.source.digest == degraded.base.digest  # no mutation: bytes unchanged
    assert degraded.source.revision != degraded.base.revision  # label still distinguishes it


# ----------------------------------------------------------------- receipt


def test_receipt_lists_every_location_and_both_identities(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(
        tmp_path, {"tdd": "tdd", "other": "other"}, extra_files={"other": {"reference.md": "x\n"}},
    )
    subject = _subject()
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)

    mutation = degrade.Mutation(
        remove_skills=("tdd",),
        edits=(degrade.FileEdit(skill="other", path="reference.md", content=b"y\n"),),
    )
    degraded = degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)
    payload = degrade.receipt(degraded, pinned_revision=subject.revision)

    assert payload["pinned_revision"] == subject.revision
    assert payload["mutation"]["locations"] == [  # type: ignore[index]
        "tdd (whole skill removed)", "other/reference.md (overridden (2 bytes))",
    ]
    assert "tdd" in payload["mutation"]["statement"]  # type: ignore[index]
    assert "other/reference.md" in payload["mutation"]["statement"]  # type: ignore[index]
    assert payload["base"]["kind"] == "snapshot"  # type: ignore[index]
    assert payload["degraded"]["revision"] != subject.revision  # type: ignore[index]


# ------------------------------------------------------- checksum manifests (#198)

_SCRIPT = "#!/bin/sh\n# guard_negated_close_keywords\n"


def _checksummed_collection(tmp_path: Path, *, star: bool = False, indent: str = "") -> Path:
    """One skill whose `scripts/SHA256SUMS` pins `gh-pr-merge.sh` - the shape
    of CPP's flow-auto/flow-merge that #198 found unrunnable once degraded.
    `star=True` uses sha256sum's binary-mode `*` marker; `indent` prefixes the
    line with whitespace the verifier accepts (counter-model finding)."""
    digest = hashlib.sha256(_SCRIPT.encode()).hexdigest()
    marker = "*" if star else " "
    return _fixture_collection(
        tmp_path, {"flow-auto": "flow-auto"},
        extra_files={"flow-auto": {
            "reference.md": "the rule\n",
            "scripts/gh-pr-merge.sh": _SCRIPT,
            "scripts/SHA256SUMS": f"# pinned\n{indent}{digest} {marker}gh-pr-merge.sh\n",
        }},
    )


def _override_script(tmp_path: Path, collection: Path, *extra: degrade.FileEdit) -> degrade.DegradedSource:
    mutation = degrade.Mutation(edits=(
        degrade.FileEdit(skill="flow-auto", path="scripts/gh-pr-merge.sh", content=b"#!/bin/sh\n# rule gone\n"),
        *extra,
    ))
    return degrade.acquire_degraded("whatever", tmp_path / "base", mutation, checkout=collection)


@pytest.mark.parametrize(("star", "indent"), [(False, ""), (True, ""), (False, " "), (False, "\t")])
def test_an_override_of_a_manifest_listed_file_leaves_a_tree_that_prepares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, star: bool, indent: str,
) -> None:
    """Regression for #198: before the fix the manifest kept the original
    hash and `materialize.inventory` refused the degraded tree with
    "checksum mismatch", so `collection-run --degraded` could never launch."""
    subject = _subject(checksum_manifest="scripts/SHA256SUMS")
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)

    degraded = _override_script(tmp_path, _checksummed_collection(tmp_path, star=star, indent=indent))

    entries = materialize.inventory(subject, degraded.source)
    assert [e.checksums for e in entries] == ["verified"]
    manifest = (degraded.source.surface_dir / "flow-auto" / "scripts" / "SHA256SUMS").read_text()
    assert manifest.startswith("# pinned\n")  # comments and layout survive the rewrite
    assert f" {'*' if star else ' '}gh-pr-merge.sh\n" in manifest


def test_a_file_changed_after_degrade_is_still_refused_by_the_rewritten_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control for the #198 rewrite: the manifest now pins the
    OVERRIDE's hash, not nothing - an edit made after degrade-subject must
    still fail preparation exactly as it did before."""
    subject = _subject(checksum_manifest="scripts/SHA256SUMS")
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    degraded = _override_script(tmp_path, _checksummed_collection(tmp_path))

    (degraded.source.surface_dir / "flow-auto" / "scripts" / "gh-pr-merge.sh").write_text("tampered\n")

    with pytest.raises(materialize.Refused, match="checksum mismatch for gh-pr-merge.sh"):
        materialize.inventory(subject, degraded.source)


def test_manifest_rewrites_are_recorded_apart_from_the_declared_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rewrite is bookkeeping, not rule removal: `mutation.locations`
    stays exactly what the operator declared, and the manifest change is
    listed separately. An override the manifest does not list (reference.md)
    produces no rewrite."""
    subject = _subject(checksum_manifest="scripts/SHA256SUMS")
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    degraded = _override_script(
        tmp_path, _checksummed_collection(tmp_path),
        degrade.FileEdit(skill="flow-auto", path="reference.md", content=b"gone\n"),
    )
    payload = degrade.receipt(degraded, pinned_revision=subject.revision)

    assert payload["mutation"]["locations"] == [  # type: ignore[index]
        "flow-auto/scripts/gh-pr-merge.sh (overridden (22 bytes))",
        "flow-auto/reference.md (overridden (5 bytes))",
    ]
    old = hashlib.sha256(_SCRIPT.encode()).hexdigest()
    new = hashlib.sha256(b"#!/bin/sh\n# rule gone\n").hexdigest()
    assert payload["manifest_rewrites"] == [
        f"flow-auto/scripts/SHA256SUMS: gh-pr-merge.sh sha256:{old} -> sha256:{new}",
    ]


def test_no_manifest_rewrite_when_the_subject_declares_no_manifest_or_the_operator_overrides_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    assert _override_script(tmp_path / "a", _checksummed_collection(tmp_path / "a")).manifest_rewrites == ()

    subject = _subject(checksum_manifest="scripts/SHA256SUMS")
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    own = degrade.FileEdit(skill="flow-auto", path="scripts/SHA256SUMS", content=b"# operator-owned\n")
    degraded = _override_script(tmp_path / "b", _checksummed_collection(tmp_path / "b"), own)
    assert degraded.manifest_rewrites == ()
    assert (degraded.source.surface_dir / "flow-auto" / "scripts" / "SHA256SUMS").read_bytes() == b"# operator-owned\n"


def test_receipt_with_no_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    subject = _subject()
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)

    degraded = degrade.acquire_degraded("whatever", tmp_path / "base", None, checkout=collection)
    payload = degrade.receipt(degraded, pinned_revision=subject.revision)

    assert payload["mutation"] == {
        "locations": [], "statement": "no skill removed; this degradation is a source override only",
    }


# --------------------------------------------------------------------- CLI


def test_cli_writes_a_receipt_and_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    out = tmp_path / "out"

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 0
    payload = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    assert payload["mutation"]["locations"] == ["tdd (whole skill removed)"]
    assert payload["degraded"]["kind"] == "degraded"
    # The degraded tree itself is persisted, not only described - #155
    # review: a receipt describing a tree that was then discarded from the
    # disposable staging root could never be installed by a runner.
    assert not (out / "skills" / "tdd").exists()
    assert degrade.materialize.tree_digest(out / "skills") == payload["degraded"]["digest"]


def test_cli_supports_repeatable_remove_skill_remove_file_and_override_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(
        tmp_path,
        {"a": "a", "b": "b", "c": "c"},
        extra_files={"b": {"reference.md": "old\n"}, "c": {"scripts/x.sh": "old\n"}},
    )
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["a", "b", "c"]))
    out = tmp_path / "out"
    replacement = tmp_path / "replacement.md"
    replacement.write_text("new\n", encoding="utf-8")

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection),
        "--remove-skill", "a",
        "--override-file", f"b:reference.md={replacement}",
        "--remove-file", "c:scripts/x.sh",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 0
    payload = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    # Order follows construction (remove-skill, then remove-file, then
    # override-file), not the order flags were typed on the command line.
    assert payload["mutation"]["locations"] == [
        "a (whole skill removed)", "c/scripts/x.sh (removed)", "b/reference.md (overridden (4 bytes))",
    ]


def test_cli_exits_two_on_a_malformed_remove_file_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    out = tmp_path / "out"

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-file", "no-colon-here",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 2
    assert not (out / "receipt.json").exists()


def test_cli_exits_two_and_writes_nothing_when_the_mutation_names_an_absent_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    out = tmp_path / "out"

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "does-not-exist",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 2
    assert not (out / "receipt.json").exists()


def test_cli_refuses_a_non_empty_out_holding_a_stale_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    out = tmp_path / "out"
    out.mkdir()
    (out / "receipt.json").write_text("{}", encoding="utf-8")

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 2


def test_cli_refuses_a_non_empty_out_holding_anything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not just a stale receipt - ANY existing content, since `--out` now
    also receives the `skills/` tree and a partial prior write must not be
    silently built on top of."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    out = tmp_path / "out"
    out.mkdir()
    (out / "unrelated.txt").write_text("hello\n", encoding="utf-8")

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
        "--out", str(out), "--base", str(tmp_path / "base"),
    ])

    assert code == 2
    assert not (out / "receipt.json").exists()


def test_cli_requires_exactly_one_of_checkout_or_revision(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["degrade-subject", "whatever", "--remove-skill", "tdd", "--out", str(tmp_path / "out")])


def test_cli_rerun_with_the_same_base_does_not_collide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #199: `acquire_degraded` staged into the fixed path
    `<base>/<subject>-degraded-staging` and never removed it, so a second run
    against the same `--base` hit `materialize.acquire_snapshot`'s
    `shutil.copytree` over the leftover `<staging>/base/surface` and died with
    an uncaught `FileExistsError` - not the CLI's documented exit 2. A fixed
    CLI gives every run its own staging tree and leaves none behind."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    base = tmp_path / "base"

    first = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
        "--out", str(tmp_path / "out1"), "--base", str(base),
    ])
    second = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
        "--out", str(tmp_path / "out2"), "--base", str(base),
    ])

    assert first == 0
    assert second == 0
    assert (tmp_path / "out1" / "receipt.json").exists()
    assert (tmp_path / "out2" / "receipt.json").exists()
    # Neither run's staging tree is left behind under --base.
    assert list(base.iterdir()) == []


def test_cli_cleans_up_staging_when_the_mutation_is_refused_mid_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Every exit path" includes a refusal raised from inside
    `acquire_degraded` itself (here, `_apply_mutation` naming an absent
    skill), not only the CLI's own normal-return and top-level except paths -
    orchestrator review of #199. `acquire_degraded`'s own try/except must
    remove the staging it created before the refusal propagates."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    base = tmp_path / "base"

    code = cli.main([
        "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "does-not-exist",
        "--out", str(tmp_path / "out"), "--base", str(base),
    ])

    assert code == 2
    assert list(base.iterdir()) == []


def test_cli_cleans_up_staging_when_persist_skills_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """"Every exit path" also includes an exception raised by `persist_skills`
    itself, after `acquire_degraded` already succeeded and handed back a live
    staging tree - orchestrator review of #199. Cleanup that only ran after
    `persist_skills` returned would leak here, since it never returns."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    base = tmp_path / "base"

    def _boom(degraded: object, out: Path) -> Path:
        raise RuntimeError("boom")

    monkeypatch.setattr(degrade, "persist_skills", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        cli.main([
            "degrade-subject", "whatever", "--checkout", str(collection), "--remove-skill", "tdd",
            "--out", str(tmp_path / "out"), "--base", str(base),
        ])

    assert list(base.iterdir()) == []


# ------------------------------------------------------------ persisted tree


def test_persist_skills_writes_the_installable_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd", "other": "other"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    degraded = degrade.acquire_degraded(
        "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("tdd",)), checkout=collection,
    )
    out = tmp_path / "out"
    out.mkdir()

    target = degrade.persist_skills(degraded, out)

    assert target == out / "skills"
    assert not (target / "tdd").exists()
    assert (target / "other").is_dir()
    assert degrade.materialize.tree_digest(target) == degraded.source.digest


def test_verify_persisted_skills_accepts_a_matching_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    degraded = degrade.acquire_degraded(
        "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("tdd",)), checkout=collection,
    )
    out = tmp_path / "out"
    out.mkdir()
    degrade.persist_skills(degraded, out)

    verified = degrade.verify_persisted_skills(out, degraded.source.digest)

    assert verified == out / "skills"


def test_verify_persisted_skills_refuses_a_tampered_byte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The red case the orchestrator's review named directly: tamper with one
    byte of the persisted tree after it was built, and whatever reads it must
    refuse on a digest mismatch."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd", "other": "other"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    degraded = degrade.acquire_degraded(
        "whatever", tmp_path / "base", degrade.Mutation(remove_skills=("tdd",)), checkout=collection,
    )
    out = tmp_path / "out"
    out.mkdir()
    degrade.persist_skills(degraded, out)

    tampered = out / "skills" / "other" / "SKILL.md"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

    with pytest.raises(degrade.DegradationRefused, match="digest"):
        degrade.verify_persisted_skills(out, degraded.source.digest)


def test_verify_persisted_skills_refuses_a_missing_tree(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(degrade.DegradationRefused, match="no persisted skills tree"):
        degrade.verify_persisted_skills(out, "sha256:" + "00" * 32)
