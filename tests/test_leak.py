"""Machine-identity leak detection (issue #63).

`test_the_seeded_bundle_discriminates` IS this instrument's negative control:
skillc is public, and `skillc leak-check` is a gate that lets a PR or a
produced bundle through, so it owes a committed input that makes it report the
other verdict (CLAUDE.md's Negative Control rule; ADR 0001's bound for skillc
itself). The seeded values are obviously fake - `/home/exampleuser`,
`10.0.0.1`, `example-host.internal` - never real identities, and the clean twin
proves the check is not simply refusing everything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillc import cli, leak

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "controls" / "leak-check"


def test_the_seeded_bundle_discriminates() -> None:
    denylist = leak.load_denylist(str(CONTROLS / "denylist.txt"))

    bad = leak.scan_path(CONTROLS / "bad", denylist)
    assert bad.findings, "leak-check is blind on its own seeded-leak bundle"
    kinds = {f.kind for f in bad.findings}
    assert kinds == {"home-path", "uid-gid", "private-ip", "denylisted-hostname"}, kinds

    good = leak.scan_path(CONTROLS / "good", denylist)
    assert good.findings == [], f"leak-check is noisy on its clean twin: {good.findings}"


def test_cli_exits_1_on_the_seeded_bundle_and_0_on_the_clean_twin(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main([
        "leak-check", str(CONTROLS / "bad"), "--denylist", str(CONTROLS / "denylist.txt"),
    ])
    assert rc == 1
    rc = cli.main([
        "leak-check", str(CONTROLS / "good"), "--denylist", str(CONTROLS / "denylist.txt"),
    ])
    assert rc == 0
    capsys.readouterr()


def test_a_nonexistent_path_is_refused_not_a_clean_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["leak-check", str(tmp_path / "does-not-exist")])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


def test_an_empty_directory_is_unknown_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """kyle #10 container-lessons, item 59: a scan that never opened a file
    cannot have "found nothing" - it looked at nothing. `exit 0` here would be
    indistinguishable from a genuinely clean, actually-scanned tree."""
    rc = cli.main(["leak-check", str(tmp_path)])
    assert rc == 3
    assert "unscannable target is UNKNOWN" in capsys.readouterr().err


def test_a_tree_of_only_binary_files_is_unknown_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00\x01/home/exampleuser")
    rc = cli.main(["leak-check", str(tmp_path)])
    assert rc == 3
    err = capsys.readouterr().err
    assert "unscannable target is UNKNOWN" in err


def test_a_single_binary_file_target_is_unknown_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\xff\xfe\x00\x01")
    rc = cli.main(["leak-check", str(path)])
    assert rc == 3


def test_an_unconfigured_denylist_says_so_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hostname not on a list is a class this run cannot see - `check` must
    say that plainly rather than let silence imply full coverage."""
    monkeypatch.delenv(leak.DENYLIST_ENV, raising=False)
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    rc = cli.main(["leak-check", str(tmp_path)])
    assert rc == 0
    assert "no hostname deny-list configured" in capsys.readouterr().err


def test_an_explicit_denylist_silences_the_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(leak.DENYLIST_ENV, raising=False)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    # The deny-list file itself lives OUTSIDE the scanned tree - inside it, its
    # own content ("example-host") would match itself and this test would be
    # asserting the wrong thing.
    deny = tmp_path / "deny.txt"
    deny.write_text("example-host\n", encoding="utf-8")
    rc = cli.main(["leak-check", str(tree), "--denylist", str(deny)])
    assert rc == 0
    assert "no hostname deny-list configured" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("Original file: /home/exampleuser/reports/x.md", "home-path"),
        ("mounted for /Users/exampleuser/Desktop", "home-path"),
        ("running as uid=1000", "uid-gid"),
        ("group gid=1000", "uid-gid"),
        ("internal peer 10.0.0.1", "private-ip"),
        ("internal peer 172.16.4.9", "private-ip"),
        ("internal peer 192.168.1.5", "private-ip"),
    ],
)
def test_each_class_fires_on_its_own_minimal_input(line: str, kind: str) -> None:
    findings = list(leak.scan_text(line, frozenset()))
    assert findings, f"{kind} did not fire on {line!r}"
    assert all(k == kind for _, k, _ in findings), findings


@pytest.mark.parametrize(
    "line",
    [
        "a public address 8.8.8.8 is not private",
        "loopback bind 127.0.0.1:8000 identifies no specific machine",
        "link-local 169.254.1.1 is not RFC 1918 either",
        "a plain sentence about /home directories in general",
        "~/.local/bin is on PATH",
        "edit .claude/settings.local.json before committing",
        "fixed logical paths (e.g. /work, /home/candidate)",
    ],
)
def test_each_non_leak_stays_silent(line: str) -> None:
    assert list(leak.scan_text(line, frozenset())) == []


def test_an_allowlisted_line_is_skipped_whole_even_with_a_real_leak_on_it() -> None:
    """The allowlist exempts the LINE, not just the matched span - deliberate,
    but worth pinning so a future match-level rewrite is a conscious choice."""
    line = "~/.local/bin also mentions /home/exampleuser in passing"
    assert list(leak.scan_text(line, frozenset())) == []


def test_a_binary_file_is_skipped_and_counted_not_scanned_clean(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00\x01/home/exampleuser")
    result = leak.scan_path(tmp_path, frozenset())
    assert result.scanned == 1
    assert result.skipped == 1
    assert result.findings == []


def test_seeded_values_do_not_collide_with_a_typical_harness_path() -> None:
    """kyle #10 container-lessons item 58: a leak sentinel must not be a
    SUBSTRING of the harness's own paths - a short sentinel once
    false-positived on a worktree name. None of this control's seeded values
    (the denylisted hostname, the private-IP octets, the /home/exampleuser
    username) may be a substring of a realistic worktree, scratch, session or
    container-name path that carries no identity of its own."""
    denylist = leak.load_denylist(str(CONTROLS / "denylist.txt"))
    harness_paths = [
        "/workspace/.claude/skillc-63",
        "/workspace/.claude/skillc-issue-63",
        "/workspace/.claude/scratch/mattpocock-skills",
        "kyle-skillc-worker-w2-g1",
        "kyle-session-testdb",
        "session-testredis",
        "w2-g1",
    ]
    for text in harness_paths:
        findings = list(leak.scan_text(text, denylist))
        assert findings == [], f"{text!r} false-positived on a seeded value: {findings}"


def test_exclude_skips_a_whole_directory_by_relative_prefix(tmp_path: Path) -> None:
    """This is how a CI scan of the WHOLE tree stays clean of the seeded, on-
    purpose-fake controls/leak-check/bad/ fixture without being blind to a
    real leak anywhere else - not a general allowlist for one matched line."""
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    fixtures = tmp_path / "controls" / "leak-check" / "bad"
    fixtures.mkdir(parents=True)
    (fixtures / "receipt.json").write_text("/home/exampleuser\n", encoding="utf-8")

    excluded = leak.scan_path(tmp_path, frozenset(), exclude=frozenset({"controls/leak-check/bad"}))
    assert excluded.findings == []
    assert excluded.scanned == 1  # clean.txt only - the excluded file was never opened

    unexcluded = leak.scan_path(tmp_path, frozenset())
    assert unexcluded.findings, "the fixture must actually contain a real match, or this proves nothing"


def test_denylist_reads_comments_and_blank_lines_as_noise(tmp_path: Path) -> None:
    deny = tmp_path / "deny.txt"
    deny.write_text("# comment\n\nexample-host\n  \n", encoding="utf-8")
    assert leak.load_denylist(str(deny)) == frozenset({"example-host"})


def test_an_absent_denylist_file_is_empty_not_refused(tmp_path: Path) -> None:
    assert leak.load_denylist(str(tmp_path / "missing.txt")) == frozenset()


def test_check_leak_check_is_refused_on_the_current_tree_before_the_scrub() -> None:
    """Regression discipline for the scrub itself (#63): the three files the
    issue names must be clean NOW. Run against a copy of the pre-scrub tree at
    the commit this test was added against to see it go red - see the PR."""
    result = leak.scan_path(ROOT / "docs" / "research", frozenset())
    home_paths = [f for f in result.findings if f.kind == "home-path"]
    assert home_paths == [], f"docs/research still leaks a home-directory path: {home_paths}"
