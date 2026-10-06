"""Tests for `skillc profile diagnose` (#295).

`profile validate` certifies-or-refuses on the FIRST defect category found,
truncates unresolved references to 8, and gives no per-skill attribution -
exactly right for a gate, useless for "what broke, for which skill" (CPP
#1370's need: re-checking a pinned profile against a newer revision). This
module is the non-certifying twin: it walks the whole closure and reports
EVERY problem, attributed to the skill(s) whose closure reaches it, and it
is schema-distinct from an inventory by construction - never "inventory_schema",
so nothing that expects a certification can mistake one for the other.

Two selected skills share one source tree so the shared-dependency and
cascade cases have something real to attribute to; test_profile.py's
single-skill fixture cannot exercise either.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import cli
from skillc import profile as p


def _write(path: Path, text: str, executable: bool = False) -> None:
    """Local copy of test_profile.py's helper - NOT imported from there, since
    mypy (no `tests/__init__.py`) resolves a cross-test-file import as the
    same source under two different module names ("test_profile" and
    "tests.test_profile") and refuses with 'Source file found twice'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)

# --------------------------------------------------------------------- fixture

SKILL_A_MD = """---
name: skill-a
description: First skill, shares one helper with skill-b
---
# Skill A

Run `~/.helpers/shared.sh` then `~/.helpers/only-a.sh`.
"""

SKILL_B_MD = """---
name: skill-b
description: Second skill, shares one helper with skill-a
---
# Skill B

Run `~/.helpers/shared.sh` then `~/.helpers/only-b.sh`.
"""

SHARED_SH = "#!/usr/bin/env bash\necho shared\n"
ONLY_A_SH = "#!/usr/bin/env bash\necho a\n"
ONLY_B_SH = "#!/usr/bin/env bash\necho b\n"


def _source(root: Path) -> Path:
    _write(root / "pack" / "skills" / "skill-a" / "SKILL.md", SKILL_A_MD)
    _write(root / "pack" / "skills" / "skill-b" / "SKILL.md", SKILL_B_MD)
    _write(root / "tools" / "shared.sh", SHARED_SH, True)
    _write(root / "tools" / "only-a.sh", ONLY_A_SH, True)
    _write(root / "tools" / "only-b.sh", ONLY_B_SH, True)
    return root


SUBJECT = {
    "subject_schema": 1,
    "locator": "example.invalid/two-skills",
    "revision": "0" * 40,
    "surface": "codex-skills",
    "skills_root": "pack/skills",
    "select": "all",
    "client": {"name": "codex", "version": "0.157.1"},
}

PROFILE: dict[str, object] = {
    "profile_schema": 1,
    "name": "two-skills-diagnose",
    "subject": "subject.json",
    "select": ["skill-a", "skill-b"],
    "treatment_question": "product",
    "allowed_destinations": [".codex/skills", ".helpers"],
    "reference_patterns": [
        {"name": "home", "class": "home-relative",
         "pattern": r"~/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"},
    ],
    "dependencies": [
        {"id": "helper-shared", "kind": "helper", "scope": "common",
         "source_root": "tools", "paths": ["shared.sh"], "destination": ".helpers",
         "satisfies": [{"reference": "~/.helpers/shared.sh", "path": "shared.sh"}]},
        {"id": "helper-only-a", "kind": "helper", "scope": "treatment",
         "source_root": "tools", "paths": ["only-a.sh"], "destination": ".helpers",
         "satisfies": [{"reference": "~/.helpers/only-a.sh", "path": "only-a.sh"}]},
        {"id": "helper-only-b", "kind": "helper", "scope": "treatment",
         "source_root": "tools", "paths": ["only-b.sh"], "destination": ".helpers",
         "satisfies": [{"reference": "~/.helpers/only-b.sh", "path": "only-b.sh"}]},
    ],
    "unsupported": [],
    "mirrors": [],
    "generated_from": [],
    "declared_empty_kinds": ["startup-context", "tool", "synthetic", "library"],
    "client_profiles": {
        "codex": {"status": "declared", "reason": "the subject's own surface"},
    },
}


def _profile(tmp_path: Path, subject: dict[str, Any] | None = None, **changes: Any) -> p.Profile:
    data = copy.deepcopy(PROFILE)
    data.update(changes)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "subject.json").write_text(json.dumps(subject or SUBJECT), encoding="utf-8")
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return p.Profile.load(path)


def _diagnose(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    src = tmp_path / "src"
    if not src.exists():
        _source(src)
    return p.diagnose(_profile(tmp_path, **changes), p.DirTree(src))


def _deps() -> list[dict[str, Any]]:
    deps = copy.deepcopy(PROFILE["dependencies"])
    assert isinstance(deps, list)
    return deps


# ------------------------------------------------------------- golden case 1


def test_one_skill_broken_one_intact(tmp_path: Path) -> None:
    """A single unresolved reference in skill-a's own text; skill-b is clean."""
    skill_a_broken = SKILL_A_MD + "\nAlso needs ~/.helpers/missing-entirely.sh.\n"
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md", skill_a_broken)
    diag = p.diagnose(_profile(tmp_path), p.DirTree(src))
    assert diag["diagnostic_schema"] == 1
    assert diag["structural"] == []
    assert diag["skills"]["skill-a"]["status"] == "broken"
    assert diag["skills"]["skill-b"]["status"] == "intact"
    assert diag["skills"]["skill-b"]["problems"] == []
    [problem] = diag["problems"]
    assert problem["category"] == "unresolved-reference"
    assert problem["skills"] == ["skill-a"]
    assert "missing-entirely.sh" in problem["detail"]

    # validate() on the identical source still refuses - the certifier is
    # unaffected by diagnose() existing.
    with pytest.raises(p.Refused, match="unresolved reference"):
        p.validate(_profile(tmp_path), p.DirTree(src))


# ------------------------------------------------------------- golden case 2


def test_a_shared_helper_broken_attributes_both_skills(tmp_path: Path) -> None:
    """Deleting tools/shared.sh breaks the ONE dependency both skills reference.

    This is the attribution claim #295 exists for: ONE problem, not two,
    with `skills == ["skill-a", "skill-b"]` - not one entry per skill.
    """
    src = tmp_path / "src"
    _source(src)
    (src / "tools" / "shared.sh").unlink()
    diag = p.diagnose(_profile(tmp_path), p.DirTree(src))
    assert diag["skills"]["skill-a"]["status"] == "broken"
    assert diag["skills"]["skill-b"]["status"] == "broken"
    missing = [pr for pr in diag["problems"] if pr["category"] == "missing-dependency-source"]
    assert len(missing) == 1, diag["problems"]
    assert missing[0]["skills"] == ["skill-a", "skill-b"]


def test_the_shared_attribution_union_is_load_bearing(tmp_path: Path) -> None:
    """Mutation check (skillc convention): if the edge for skill-b's reference
    were dropped, the shared-helper problem would attribute only skill-a -
    pinning that `_compute_reach` really unions both, not just whichever
    skill's file the walk happened to drain first."""
    src = tmp_path / "src"
    _source(src)
    (src / "tools" / "shared.sh").unlink()
    walk = p._Walk(_profile(tmp_path), p.DirTree(src), {}, problems=[])
    # Reproduce the attribution computation directly, with skill-b's edge
    # missing, the way a broken `_compute_reach` or a dropped edge-append
    # would leave it.
    walk.edges = [("skill:skill-a", "helper-shared")]
    reach = p._compute_reach(walk)
    assert reach["helper-shared"] == {"skill-a"}, (
        "this is the BAD case the real walk must not produce - confirms the "
        "assertion above is actually discriminating, not vacuously true"
    )


# ------------------------------------------------------------- golden case 3


def test_more_than_eight_unresolved_references_are_all_reported(tmp_path: Path) -> None:
    """validate() truncates to 8 and refuses; diagnose() must drop none."""
    extra = "\n".join(f"Needs ~/.helpers/missing-{i}.sh." for i in range(10))
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md", SKILL_A_MD + "\n" + extra)
    diag = p.diagnose(_profile(tmp_path), p.DirTree(src))
    unresolved = [pr for pr in diag["problems"] if pr["category"] == "unresolved-reference"]
    assert len(unresolved) == 10, diag["problems"]
    assert all(pr["skills"] == ["skill-a"] for pr in unresolved)

    with pytest.raises(p.Refused) as exc:
        p.validate(_profile(tmp_path), p.DirTree(src))
    assert "..." in str(exc.value), "validate()'s own truncation marker must still be there"


# ------------------------------------------------------------- golden case 4


def test_a_fully_intact_profile_reports_zero_problems_and_still_validates(tmp_path: Path) -> None:
    diag = _diagnose(tmp_path)
    assert diag["problems"] == []
    assert diag["problem_count"] == 0
    assert diag["complete"] is True, (
        "a genuinely clean walk - counter-model review (issue #295): this is "
        "the ONLY shape a zero problem_count may legitimately mean"
    )
    assert all(s["status"] == "intact" for s in diag["skills"].values())
    assert diag["skills"].keys() == {"skill-a", "skill-b"}

    src = tmp_path / "src"
    inv = p.validate(_profile(tmp_path), p.DirTree(src))
    assert inv["inventory_schema"] == p.INVENTORY_SCHEMA


def test_the_zero_problem_case_has_a_positive_control(tmp_path: Path) -> None:
    """A planted broken reference must be caught - the zero-problem result
    above is not from a diagnose() that cannot see anything."""
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md",
           SKILL_A_MD + "\nAlso needs ~/.helpers/planted-break.sh.\n")
    diag = p.diagnose(_profile(tmp_path), p.DirTree(src))
    assert diag["problems"] != []
    assert diag["problem_count"] == 1


# ------------------------------------------------------- cascade (guard-rail 2)


def test_a_cascade_through_a_broken_dependency_is_marked_caused_by(tmp_path: Path) -> None:
    """helper-shared's own `satisfies` already names a specific carried file
    (`"path": "shared.sh"`), so resolving `~/.helpers/shared.sh` always goes
    through `_resolve`'s `sat.path` check - which, once the dependency is
    known broken, must mark its finding a CASCADE of the one root cause
    (`caused_by`) rather than an independent, unrelated-looking complaint.
    """
    src = tmp_path / "src"
    _source(src)
    (src / "tools" / "shared.sh").unlink()
    diag = p.diagnose(_profile(tmp_path), p.DirTree(src))
    roots = [pr for pr in diag["problems"] if pr["category"] == "missing-dependency-source"]
    cascades = [pr for pr in diag["problems"] if pr["category"] == "missing-dependency-file-cascade"]
    assert len(roots) == 1, diag["problems"]
    assert roots[0]["skills"] == ["skill-a", "skill-b"]
    # Both skills independently hit the sat.path check for the same broken
    # dependency, so each gets its OWN cascade entry, pointing at the one root.
    assert len(cascades) == 2, diag["problems"]
    assert {c["caused_by"] for c in cascades} == {roots[0]["id"]}
    assert {tuple(c["skills"]) for c in cascades} == {("skill-a",), ("skill-b",)}


def test_the_root_cause_short_circuit_is_mutation_checked(tmp_path: Path) -> None:
    """Disable the `dep.id in walk.broken` short-circuit in `_source_files`
    (by clearing `walk.broken` between two calls for the SAME dependency)
    and confirm it then reports the root cause TWICE instead of once - the
    duplication this check exists to prevent, and the reason the shared-
    helper case above attributes to one problem rather than two."""
    src = tmp_path / "src"
    _source(src)
    (src / "tools" / "shared.sh").unlink()
    prof = _profile(tmp_path)
    tree = p.DirTree(src)
    walk = p._Walk(prof, tree, {
        s.reference: (d, s) for d in prof.dependencies for s in d.satisfies
    }, problems=[])
    dep = next(d for d in prof.dependencies if d.id == "helper-shared")
    p._source_files(walk, dep)
    assert len(walk.raw) == 1
    assert walk.raw[0]["category"] == "missing-dependency-source"
    # Correct behaviour: a second call for the SAME still-broken dependency
    # adds nothing further - the root's reach (computed from edges, not from
    # this call) already covers whoever asks.
    p._source_files(walk, dep)
    assert len(walk.raw) == 1, "a second caller must not duplicate the one root cause"
    # MUTATION: drop the "already broken" memory - what the short-circuit's
    # absence looks like.
    walk.broken.clear()
    p._source_files(walk, dep)
    assert len(walk.raw) == 2
    assert walk.raw[1]["category"] == "missing-dependency-source", (
        "with walk.broken cleared, the SAME root cause is reported a second "
        "time - the exact duplication the 'already broken' check prevents"
    )


# ------------------------------------------------------- schema distinctness


def test_a_diagnostic_report_is_refused_as_an_inventory(tmp_path: Path) -> None:
    """install() and verify_installed() both read inventory["dependencies"]/
    installed_surface etc.; a diagnostic report has neither key, so passing
    one in fails immediately rather than silently being treated as a
    certification."""
    diag = _diagnose(tmp_path)
    assert "inventory_schema" not in diag
    assert diag["diagnostic_schema"] == 1
    # Whatever shape the failure takes - a missing key, or a type mismatch
    # from `skills` being a dict instead of an inventory's list - the point
    # is that NOTHING treats this as a usable inventory.
    with pytest.raises((p.Refused, KeyError, TypeError)):
        p._install_records(diag)
    with pytest.raises((p.Refused, KeyError, TypeError)):
        p.verify_installed(diag, tmp_path)


def test_structural_refusals_are_not_attributed(tmp_path: Path) -> None:
    """An absent skills root is caught before any skill is even discovered -
    reported once under `structural`, with validate()'s own message, never
    duplicated into `problems`."""
    bad_subject = {**SUBJECT, "skills_root": "nowhere/at/all"}
    diag = _diagnose(tmp_path, subject=bad_subject)
    assert diag["problems"] == []
    assert diag["problem_count"] == 0
    assert diag["complete"] is False, (
        "counter-model review (issue #295): without this, problem_count: 0 "
        "here is indistinguishable from the genuinely clean case above"
    )
    assert diag["skills"] == {}
    assert len(diag["structural"]) == 1
    assert "absent from the source" in diag["structural"][0]["detail"]

    with pytest.raises(p.Refused, match="absent from the source"):
        p.validate(_profile(tmp_path, subject=bad_subject), p.DirTree(tmp_path / "src"))


# ------------------------------------------------------------------------ CLI


def test_the_cli_exits_0_with_a_nonzero_problem_count(tmp_path: Path) -> None:
    """`skillc profile diagnose` is non-certifying: exit 0 whenever a report
    was produced, whatever `problem_count` says - the count is what a caller
    checks, never the process exit status."""
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md",
           SKILL_A_MD + "\nAlso needs ~/.helpers/missing-entirely.sh.\n")
    _profile(tmp_path)
    out = tmp_path / "diag.json"
    args = ["profile", "diagnose", str(tmp_path / "profile.json"), "--snapshot", str(src)]
    assert cli.main([*args, "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["diagnostic_schema"] == 1
    assert report["problem_count"] == 1
    assert cli.main([*args, "--out", str(out)]) == 2  # no silent overwrite
    assert cli.main([*args, "--out", str(out), "--overwrite"]) == 0


def test_the_cli_refuses_only_when_the_profile_itself_cannot_load(tmp_path: Path) -> None:
    """A malformed profile.json is a usage error (exit 2); a closure problem
    inside an otherwise-loadable profile is not - that is the whole point of
    a diagnostic exiting 0."""
    (tmp_path / "profile.json").write_text("not json", encoding="utf-8")
    assert cli.main(["profile", "diagnose", str(tmp_path / "profile.json"), "--snapshot", str(tmp_path)]) == 2


# ------------------------------------------------------- a cyclic dependency graph


def test_a_dependency_cycle_terminates_and_attributes_correctly(tmp_path: Path) -> None:
    """helper-x's own text references helper-y, and helper-y's references
    helper-x right back - a cycle in the DEPENDENCY graph (distinct from a
    skill-level cycle, which cannot exist: skills are never dependencies).

    `_visit`'s pre-existing `dep.id in walk.visited` guard already stops the
    walk itself from recursing forever - unchanged by #295. What #295 adds is
    `_compute_reach`'s fixed-point over `walk.edges`, and THAT needs its own
    proof: does the cycle make it loop forever, or let either side's
    attribution leak into the other's where it should not?

    skill-a reaches helper-x directly; skill-b reaches helper-y directly;
    neither reaches the other's helper by any OTHER path. If the cycle is
    handled correctly, attribution still flows across it - a real,
    non-worthless case, not just a termination probe - so both helpers end
    up co-owned by both skills, and the walk completes in finite time either
    way.
    """
    skill_a_md = ("---\nname: skill-a\ndescription: reaches helper-x\n---\n"
                  "Run `~/.helpers/x.sh`.\n")
    skill_b_md = ("---\nname: skill-b\ndescription: reaches helper-y\n---\n"
                  "Run `~/.helpers/y.sh`.\n")
    # Each helper's OWN text references the other - the cycle.
    x_sh = "#!/usr/bin/env bash\n# also uses ~/.helpers/y.sh\n"
    y_sh = "#!/usr/bin/env bash\n# also uses ~/.helpers/x.sh\n"

    src = tmp_path / "src"
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md", skill_a_md)
    _write(src / "pack" / "skills" / "skill-b" / "SKILL.md", skill_b_md)
    _write(src / "tools" / "x.sh", x_sh, True)
    _write(src / "tools" / "y.sh", y_sh, True)

    subject = {**SUBJECT, "locator": "example.invalid/cycle"}
    profile_data = {
        **PROFILE,
        "name": "cycle-diagnose",
        "dependencies": [
            {"id": "helper-x", "kind": "helper", "scope": "treatment",
             "source_root": "tools", "paths": ["x.sh"], "destination": ".helpers",
             "satisfies": [{"reference": "~/.helpers/x.sh", "path": "x.sh"}]},
            {"id": "helper-y", "kind": "helper", "scope": "treatment",
             "source_root": "tools", "paths": ["y.sh"], "destination": ".helpers",
             "satisfies": [{"reference": "~/.helpers/y.sh", "path": "y.sh"}]},
        ],
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "subject.json").write_text(json.dumps(subject), encoding="utf-8")
    (tmp_path / "profile.json").write_text(json.dumps(profile_data), encoding="utf-8")
    prof = p.Profile.load(tmp_path / "profile.json")

    import signal

    def _alarm(signum: int, frame: object) -> None:
        raise TimeoutError("diagnose() did not terminate - possible infinite loop on a cycle")

    old_handler = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(10)
    try:
        diag = p.diagnose(prof, p.DirTree(src))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    assert diag["problems"] == [], diag["problems"]
    assert diag["skills"]["skill-a"]["status"] == "intact"
    assert diag["skills"]["skill-b"]["status"] == "intact"

    # Direct unit check on the propagation itself: both sides of the cycle
    # end up attributed to BOTH skills, neither more nor less.
    walk = p._Walk(prof, p.DirTree(src), {}, problems=[])
    walk.edges = [
        ("skill:skill-a", "helper-x"),
        ("skill:skill-b", "helper-y"),
        ("helper-x", "helper-y"),
        ("helper-y", "helper-x"),
    ]
    reach = p._compute_reach(walk)
    assert reach["helper-x"] == {"skill-a", "skill-b"}
    assert reach["helper-y"] == {"skill-a", "skill-b"}


def test_compute_reach_needs_more_than_one_pass(tmp_path: Path) -> None:
    """Mutation check: a THREE-hop chain (skill -> A -> B -> C) whose edges are
    deliberately listed in an order a SINGLE sweep cannot resolve - the edge
    supplying B's reach (`A -> B`) is listed AFTER the edge that consumes it
    (`B -> C`). A single-pass propagation (the mutation `_compute_reach`'s
    `while changed` loop guards against) gets `reach["B"]` right but misses
    `reach["C"]` entirely, because C was computed from B's state before B had
    been updated. The real walk's edge order is not under this test's
    control (it depends on queue/scan order), so the fixed-point has to hold
    for ANY order, not just the lucky one the end-to-end case above happens
    to produce.
    """
    src = tmp_path / "src"
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md",
           "---\nname: skill-a\ndescription: d\n---\nx\n")
    subject = {**SUBJECT, "locator": "example.invalid/chain"}
    profile_data = {
        **PROFILE, "name": "chain-diagnose", "select": ["skill-a"], "dependencies": [],
        "declared_empty_kinds": ["startup-context", "tool", "synthetic", "library", "helper"],
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "subject.json").write_text(json.dumps(subject), encoding="utf-8")
    (tmp_path / "profile.json").write_text(json.dumps(profile_data), encoding="utf-8")
    prof = p.Profile.load(tmp_path / "profile.json")
    walk = p._Walk(prof, p.DirTree(src), {}, problems=[])
    walk.edges = [
        ("B", "C"),             # consumes B's reach BEFORE it is ever set
        ("skill:skill-a", "A"),
        ("A", "B"),             # supplies B's reach, but only after the above
    ]
    reach = p._compute_reach(walk)
    assert reach["A"] == {"skill-a"}
    assert reach["B"] == {"skill-a"}
    assert reach["C"] == {"skill-a"}, (
        "a single, non-repeated sweep would leave this empty - the edge "
        "that supplies it runs after the edge that reads it"
    )


# -------------------------------------- a source file shared by TWO dependencies


def test_a_file_shared_by_two_dependencies_attributes_both_reaching_skills(
    tmp_path: Path,
) -> None:
    """Counter-model review finding (issue #295): two DISTINCT dependencies
    can legitimately declare the same `source_root`/`paths`, carrying the
    IDENTICAL file to two different destinations under two different ids.
    `_drain` scans that content only once (`scanned` dedups on path), but a
    finding inside it must still be attributed to EVERY skill whose closure
    reaches it through EITHER dependency - not only whichever dependency's
    queue entry happened to be scanned first.
    """
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md",
           "---\nname: skill-a\ndescription: reaches helper-p\n---\nRun `~/.helpers/via-p.sh`.\n")
    _write(src / "pack" / "skills" / "skill-b" / "SKILL.md",
           "---\nname: skill-b\ndescription: reaches helper-q\n---\nRun `~/.other/via-q.sh`.\n")
    # ONE physical file, carried by TWO dependency declarations.
    _write(src / "tools" / "shared2.sh",
           "#!/usr/bin/env bash\n# also needs ~/.helpers/never-declared.sh\n", True)

    changes: dict[str, Any] = {
        "allowed_destinations": [".codex/skills", ".helpers", ".other"],
        "dependencies": [
            {"id": "helper-p", "kind": "helper", "scope": "treatment",
             "source_root": "tools", "paths": ["shared2.sh"], "destination": ".helpers",
             "satisfies": [{"reference": "~/.helpers/via-p.sh", "path": "shared2.sh"}]},
            {"id": "helper-q", "kind": "helper", "scope": "treatment",
             "source_root": "tools", "paths": ["shared2.sh"], "destination": ".other",
             "satisfies": [{"reference": "~/.other/via-q.sh", "path": "shared2.sh"}]},
        ],
    }
    diag = p.diagnose(_profile(tmp_path, **changes), p.DirTree(src))
    unresolved = [pr for pr in diag["problems"] if pr["category"] == "unresolved-reference"]
    assert len(unresolved) == 1, diag["problems"]
    assert unresolved[0]["skills"] == ["skill-a", "skill-b"], (
        "the shared file was scanned once, but BOTH dependencies that carry "
        f"it (and therefore both reaching skills) must be attributed: {diag['problems']}"
    )
    assert diag["skills"]["skill-a"]["status"] == "broken"
    assert diag["skills"]["skill-b"]["status"] == "broken"


def test_a_carried_file_in_a_partially_broken_dependency_has_no_cascade(
    tmp_path: Path,
) -> None:
    """Counter-model review finding (issue #295): a dependency declaring
    `paths: ["present.sh", "missing.sh"]` is broken (missing.sh is absent),
    but a reference resolving to `present.sh` specifically must NOT be
    reported at all - that file genuinely IS carried, so it is not a
    cascade of the OTHER path's absence, and not a finding of its own.
    """
    src = tmp_path / "src"
    _source(src)
    _write(src / "pack" / "skills" / "skill-a" / "SKILL.md",
           "---\nname: skill-a\ndescription: d\n---\nUses `~/.helpers/present.sh`.\n")
    _write(src / "tools" / "present.sh", "#!/usr/bin/env bash\necho present\n", True)
    # "missing.sh" is deliberately never created.

    changes: dict[str, Any] = {
        "select": ["skill-a"],
        "declared_empty_kinds": ["startup-context", "tool", "synthetic", "library"],
        "dependencies": [
            {"id": "helper-multi", "kind": "helper", "scope": "treatment",
             "source_root": "tools", "paths": ["present.sh", "missing.sh"],
             "destination": ".helpers",
             "satisfies": [
                 {"reference": "~/.helpers/present.sh", "path": "present.sh"},
             ]},
        ],
    }
    diag = p.diagnose(_profile(tmp_path, **changes), p.DirTree(src))
    categories = [pr["category"] for pr in diag["problems"]]
    assert "missing-dependency-source" in categories, diag["problems"]
    assert "missing-dependency-file-cascade" not in categories, (
        f"present.sh IS carried - this must not read as a cascade: {diag['problems']}"
    )
    assert "missing-dependency-file" not in categories, (
        f"present.sh IS carried - this must not read as a fresh miss either: {diag['problems']}"
    )
