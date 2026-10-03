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

import os
import re
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
    # "credential-token" comes from bad/planted-token/ (#98), scanned here
    # too since scan_path walks the whole bad/ tree recursively - not a
    # separate concern from the original four classes, just a fifth one.
    assert kinds == {
        "home-path", "uid-gid", "private-ip", "denylisted-hostname", "credential-token", "account-id",
    }, kinds

    good = leak.scan_path(CONTROLS / "good", denylist)
    assert good.findings == [], f"leak-check is noisy on its clean twin: {good.findings}"


def test_the_planted_account_id_control_discriminates() -> None:
    """#225's committed control: a Codex `session_meta` line carrying fake
    account identifiers is a finding, by field name only, never the value;
    its redacted twin is clean. Before #225 the bad file scanned clean."""
    bad = leak.scan_path(CONTROLS / "bad" / "planted-account-id", frozenset())
    assert (bad.scanned, bad.skipped) == (1, 0), bad
    assert {f.kind for f in bad.findings} == {"account-id"}, bad.findings
    details = {f.detail for f in bad.findings}
    assert details == {
        "creator_user_id value present (redacted)", "creator_account_id value present (redacted)",
    }, details
    assert not any("PlantedFake" in f.detail or "00000000" in f.detail for f in bad.findings)

    good = leak.scan_path(CONTROLS / "good" / "planted-account-id", frozenset())
    # A missing twin scans zero files and finds nothing: not a clean verdict.
    assert (good.scanned, good.skipped) == (1, 0), good
    assert good.findings == [], good.findings


def test_the_planted_token_control_discriminates() -> None:
    """Dedicated committed control (#98's own acceptance: "a planted fake
    token in an exported transcript or record must be refused"), scanned in
    isolation from the original four-class bundle above so a regression here
    is unambiguous about which fixture pair caught it.

    Asserts BOTH detail strings, not merely "some finding of kind
    credential-token" - cross-model review found that the weaker assertion
    let the fixture's OAuth line go completely undetected (a JSON-escaping
    mismatch between the regex and an earlier, JSON-wrapped fixture) while
    its neighbouring API-key line alone still made the test pass. Checking
    both independently is what would have caught that."""
    denylist = leak.load_denylist(str(CONTROLS / "denylist.txt"))

    bad = leak.scan_path(CONTROLS / "bad" / "planted-token", denylist)
    assert bad.findings, "leak-check is blind on its own planted-token fixture"
    assert {f.kind for f in bad.findings} == {"credential-token"}
    details = {f.detail for f in bad.findings}
    assert "OAuth-shaped token value present (redacted)" in details, details
    assert "API-key-shaped value present (redacted)" in details, details
    for f in bad.findings:
        assert "planted-fake-oauth-token-value-0000" not in f.detail
        assert "sk-ant-api03-planted" not in f.detail

    good = leak.scan_path(CONTROLS / "good" / "planted-token", denylist)
    assert good.findings == [], f"leak-check is noisy on the planted-token control's clean twin: {good.findings}"


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


def test_a_configured_but_missing_denylist_is_refused_not_silently_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cross-model review [MEDIUM]: a typo'd --denylist path used to fall back
    to zero hostname coverage with the same message as never configuring one -
    disabling hostname detection without saying so. Confirmed real on the
    pre-fix code: exit 0, no warning, `example-host.internal` unreported."""
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    rc = cli.main(["leak-check", str(tmp_path), "--denylist", str(tmp_path / "missing.txt")])
    assert rc == 2
    assert "configured deny-list not found" in capsys.readouterr().err


def test_a_configured_denylist_reports_its_entry_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    deny = tmp_path / "deny.txt"
    deny.write_text("a-host\nb-host\n", encoding="utf-8")
    rc = cli.main(["leak-check", str(tree), "--denylist", str(deny)])
    assert rc == 0
    assert "hostname deny-list: 2 entries" in capsys.readouterr().out


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
        ('"access_token": "abcdefghijklmnopqrstuvwxyz123456"', "credential-token"),
        ('"refreshToken":"zzzzzzzzzzzzzzzzzzzzzzzzzzzz"', "credential-token"),
        ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789", "credential-token"),
    ],
)
def test_each_class_fires_on_its_own_minimal_input(line: str, kind: str) -> None:
    findings = list(leak.scan_text(line, frozenset()))
    assert findings, f"{kind} did not fire on {line!r}"
    assert all(k == kind for _, k, _ in findings), findings


@pytest.mark.parametrize(
    "line",
    [
        '"access_token": "abcdefghijklmnopqrstuvwxyz123456"',
        '"refreshToken":"zzzzzzzzzzzzzzzzzzzzzzzzzzzz"',
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_a_credential_token_finding_never_repeats_the_matched_value(line: str) -> None:
    """The whole point of this class is that the scanned line carries a real
    secret (#98, cross-model review) - a finding, log line, or review comment
    that echoed the matched value back would create a second copy of it at
    the exact moment of detection. Every value fragment long enough to be
    the credential itself must be absent from every finding's `detail`."""
    findings = list(leak.scan_text(line, frozenset()))
    assert findings
    secret_fragment = re.search(r"[A-Za-z0-9_.\-]{20,}", line)
    assert secret_fragment is not None
    for _, _, detail in findings:
        assert secret_fragment.group(0) not in detail, (secret_fragment.group(0), detail)


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
        'account_flavoured_path = "/home/some-claude-shaped-account/.venv/bin/python3"',
        # #98: mentioning a credential SCHEMA field name, with no value attached,
        # must never fire - skillc/credential.py's own docstring does exactly this.
        '("claudeAiOauth", "expiresAt") is the field path this module tries first',
        "the key is named access_token in both clients' documentation",
        # A short sk- prefix is not a plausible real key - the 20+ char
        # threshold exists so ordinary prose mentioning "sk-something" once
        # in a while does not become a false positive.
        "a short sk-abc prefix is not long enough to be a real key",
    ],
)
def test_each_non_leak_stays_silent(line: str) -> None:
    assert list(leak.scan_text(line, frozenset())) == []


def test_an_allowlisted_match_does_not_suppress_a_real_leak_on_the_same_line() -> None:
    """Cross-model review [HIGH]: the allowlist used to exempt the whole LINE,
    so a real leak sharing a line with the safe /home/candidate placeholder -
    or with this module's own private-IP range literals - went unreported.
    Confirmed this was real on the pre-fix code before writing this test."""
    line = "fixed logical paths (e.g. /home/candidate, /home/exampleuser)"
    findings = list(leak.scan_text(line, frozenset()))
    assert [k for _, k, _ in findings] == ["home-path"]
    assert findings[0][2] == "home-directory path for 'exampleuser': /home/exampleuser"


def test_allowlist_matches_the_exact_value_not_a_containing_one() -> None:
    """Cross-model review [HIGH]: a substring check on the matched value would
    also exempt an unrelated, longer username merely containing the safe one
    (`/home/candidate-2` is not `/home/candidate`)."""
    findings = list(leak.scan_text("owned by /home/candidate-2", frozenset()))
    assert [k for _, k, _ in findings] == ["home-path"]


def test_a_binary_file_is_skipped_and_counted_not_scanned_clean(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00\x01/home/exampleuser")
    result = leak.scan_path(tmp_path, frozenset())
    assert result.scanned == 1
    assert result.skipped == 1
    assert result.findings == []


def test_a_linked_worktree_git_pointer_file_is_not_a_leak(tmp_path: Path) -> None:
    """#134 item 4: `SKIP_DIRS` filters DIRECTORIES only, so a linked
    worktree's top-level `.git` - a pointer FILE holding an absolute path
    like `gitdir: /home/exampleuser/repo/.git/worktrees/foo` - went unfiltered
    and every scan of a worktree checkout reported a spurious home-path leak.
    Confirmed real on the pre-fix code: this fixture reported exactly that
    finding before `_files` learned to skip it (see PR)."""
    (tmp_path / ".git").write_text(
        "gitdir: /home/exampleuser/repo/.git/worktrees/foo\n", encoding="utf-8"
    )
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")

    result = leak.scan_path(tmp_path, frozenset())
    assert result.findings == []
    assert result.scanned == 1  # clean.txt only - the pointer file is invisible
    assert result.skipped == 0  # not merely skipped-and-counted; never yielded


def test_a_nested_git_named_file_is_still_scanned(tmp_path: Path) -> None:
    """The skip is for the TOP-LEVEL `.git` pointer only - a same-named file
    elsewhere in the tree is ordinary content and must still be read."""
    nested = tmp_path / "fixtures"
    nested.mkdir()
    (nested / ".git").write_text("/home/exampleuser\n", encoding="utf-8")

    result = leak.scan_path(tmp_path, frozenset())
    assert [f.kind for f in result.findings] == ["home-path"]
    assert result.scanned == 1


def test_a_symlink_outside_the_scanned_tree_is_skipped_not_followed(tmp_path: Path) -> None:
    """Cross-model review [MEDIUM]: following an out-of-tree symlink reads host
    state this run was never asked to look at, and the verdict could then
    change without the reviewed tree changing at all. Confirmed real on the
    pre-fix code: this symlink was followed and its target's leak reported."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.txt").write_text("/home/exampleuser\n", encoding="utf-8")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    (tree / "link.txt").symlink_to(outside / "external.txt")

    result = leak.scan_path(tree, frozenset())
    assert result.findings == []
    assert result.scanned == 1  # clean.txt only
    assert result.skipped == 1  # the out-of-tree symlink, not opened


def test_a_symlink_inside_the_scanned_tree_is_followed(tmp_path: Path) -> None:
    """The exclusion is specifically for pointing OUTSIDE the tree - a symlink
    to a sibling file within the same scan is ordinary content."""
    (tmp_path / "real.txt").write_text("/home/exampleuser\n", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")

    result = leak.scan_path(tmp_path, frozenset())
    assert result.skipped == 0
    assert result.scanned == 2
    assert len(result.findings) == 2


def test_a_broken_symlink_is_skipped_not_an_error(tmp_path: Path) -> None:
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")
    (tmp_path / "dangling.txt").symlink_to(tmp_path / "does-not-exist")

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


# #134 item 5: home-path only recognizes /home/ and /Users/, so a checkout
# under /workspace, /opt or /srv - every session in this fleet - went
# unflagged. `default_host_paths` catches this SCANNING PROCESS's own live
# home/cwd instead of guessing at a fixed prefix list (see its docstring for
# why a blind /workspace|/opt|/srv regex was rejected: it would misread a
# generic mount's project name as a leaked username, exactly the false
# positive `test_seeded_values_do_not_collide_with_a_typical_harness_path`
# above exists to catch).


def test_default_host_paths_reports_this_processs_live_home_and_cwd() -> None:
    host_paths = leak.default_host_paths()
    assert str(Path.home()) in host_paths
    assert os.getcwd() in host_paths
    assert "" not in host_paths
    assert "/" not in host_paths


def test_a_host_path_fires_on_an_explicit_match_never_on_an_unrelated_line() -> None:
    host_paths = frozenset({"/workspace/.claude/skillc-148"})
    hit = list(
        leak.scan_text(
            "evidence exported to /workspace/.claude/skillc-148/reports\n", frozenset(),
            host_paths,
        )
    )
    assert [k for _, k, _ in hit] == ["host-path"]

    miss = list(
        leak.scan_text("evidence exported to /workspace/.claude/skillc-63/reports\n",
                        frozenset(), host_paths)
    )
    assert miss == [], f"a DIFFERENT worktree path must not match: {miss}"


def test_scan_path_does_not_check_host_paths_unless_given_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default stays empty (#134 item 5 docstring): scan_text/scan_path
    remain pure and reproducible given explicit inputs, exactly like
    load_denylist's environment fallback is read once at the CLI boundary
    rather than inside the scanner. Confirmed real on the pre-fix code (no
    `host_paths` parameter existed at all): see the PR for the TypeError.

    Chdir to a deterministic path outside `/home` and `/Users`, with at
    least two segments below root (Nit Store, issue #20, found while
    working #174: https://github.com/cooneycw/skillc/issues/20#issuecomment-5870416444).
    The previous version wrote the ambient, unmodified `os.getcwd()`, so
    this test's own two assertions disagreed depending on where the
    repository happened to be checked out: from a `/home/<user>/...`
    checkout, `HOME_PATH_RE` (`scan_text`'s own always-on rule, independent
    of `host_paths`) already matches that text, so the FIRST assertion
    (no findings with no `host_paths`) failed; from a bare, one-segment cwd
    like `/tmp`, `default_host_paths()`'s own `_is_specific_enough` guard
    (see `test_default_host_paths_drops_a_bare_mount_point` just below)
    drops it, so the SECOND assertion (a finding once `host_paths` names it)
    failed instead. This mirrors `test_cli_leak_check_flags_a_checkout_
    under_the_running_hosts_own_cwd`'s own fixture shape for the same
    reason: neither failure mode can reproduce from a value that is both
    outside `/home`/`/Users` and at least two segments deep."""
    checkout = tmp_path / "srv-like" / "checkout"
    checkout.mkdir(parents=True)
    monkeypatch.chdir(checkout)
    (tmp_path / "f.txt").write_text(f"{os.getcwd()}\n", encoding="utf-8")
    assert leak.scan_path(tmp_path, frozenset()).findings == []
    assert leak.scan_path(
        tmp_path, frozenset(), host_paths=leak.default_host_paths()
    ).findings != []


def test_cli_leak_check_flags_a_checkout_under_the_running_hosts_own_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end: the real `skillc leak-check` gate, wired to
    `leak.default_host_paths()`, must catch a reference to ITS OWN running
    location - the exact shape of #150's export gate scanning agent output
    produced from inside a /workspace container.

    Chdir to a path NOT under /home or /Users (cross-model review on PR #154:
    the first version of this test wrote the real, unmodified os.getcwd() -
    on a host checkout under /home/<user> that is ALREADY caught by the
    pre-fix home-path rule, so the test passed on the UNFIXED code there and
    only ever went red inside a container. Confirmed real on the pre-fix
    code with this chdir in place: TypeError/AttributeError, same as the
    other item-5 cases - see the PR). This version is red wherever it runs."""
    checkout = tmp_path / "srv-like" / "checkout"
    checkout.mkdir(parents=True)
    monkeypatch.chdir(checkout)
    monkeypatch.delenv(leak.DENYLIST_ENV, raising=False)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "evidence.txt").write_text(f"produced in {os.getcwd()}\n", encoding="utf-8")
    rc = cli.main(["leak-check", str(evidence_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "host-path" in out, out


def test_default_host_paths_drops_a_bare_mount_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """#134 item 5, cross-model review on PR #154: running `skillc leak-check`
    with cwd=/workspace - every container session's default before it `cd`s
    into a checkout - measured 17 false positives, all `host-path: this
    host's own path: /workspace`, matching the bare word anywhere it was
    merely MENTIONED in prose (this module's own docstring, AGENTS.md). A
    live value with fewer than two path segments below root must not become
    a host-path candidate at all."""
    monkeypatch.chdir("/")
    monkeypatch.setattr(leak.os, "getcwd", lambda: "/workspace")
    monkeypatch.setattr(leak.Path, "home", staticmethod(lambda: Path("/workspace")))
    host_paths = leak.default_host_paths()
    assert host_paths == frozenset(), host_paths

    findings = list(
        leak.scan_text(
            "a checkout under /workspace, /opt or /srv\n", frozenset(),
            frozenset({"/workspace"}),
        )
    )
    assert findings == [], findings


def test_a_host_path_only_fires_at_a_path_boundary() -> None:
    """Cross-model review on PR #154: a raw substring check let a shorter
    host path match inside a longer, unrelated one sharing its prefix
    (e.g. /home/al matching inside /home/alice) - the same false-positive
    shape ALLOWLIST's exact-match comparison exists to avoid elsewhere in
    this module."""
    host_paths = frozenset({"/srv/checkout"})
    same_prefix_but_longer = list(
        leak.scan_text("under /srv/checkout-extended/evidence\n", frozenset(), host_paths)
    )
    assert same_prefix_but_longer == [], same_prefix_but_longer

    at_a_real_boundary = [
        "produced in /srv/checkout\n",
        "produced in /srv/checkout/evidence.txt\n",
        'path: "/srv/checkout"\n',
        "path /srv/checkout ends here\n",
    ]
    for line in at_a_real_boundary:
        findings = list(leak.scan_text(line, frozenset(), host_paths))
        assert [k for _, k, _ in findings] == ["host-path"], (line, findings)
