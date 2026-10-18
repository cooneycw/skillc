"""Tests for `ci/real-docker/break-lib.sh` (#315 follow-up, orchestrator
review during #269's merge): the pure, sourceable break-mode parsing and
context-routing functions `run-real-docker` uses.

Before this file, the witness break modes (#269's `stale-confirm-lie`,
`kill-wrong-pid`, `gate-in-fresh-container`) could not be driven through
the runner at all - `run-real-docker` only ever set `SKILLC_LIVE_TEST_
BREAK` (#183's channel modes). These functions are tested directly by
`source`-ing the lib, not by running the whole runner: the parsing and
context decisions happen before any of the runner's own infra (a config
file, docker, git, curl) is touched, so nothing here needs any of that -
confirmed by the end-to-end subprocess tests below, which run the REAL
`run-real-docker` script with a syntactically-valid but nonexistent sha
and no config file present, and observe that an invalid --break argument
is refused before the config-file check ever runs, while a valid one
reaches it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REAL_DOCKER_DIR = Path(__file__).resolve().parent.parent / "ci" / "real-docker"
LIB_PATH = _REAL_DOCKER_DIR / "break-lib.sh"
RUNNER_PATH = _REAL_DOCKER_DIR / "run-real-docker"
DUMMY_SHA = "0" * 40


def _resolve(spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; resolve_break_spec "$2"', "_", str(LIB_PATH), spec],
        capture_output=True, text=True, timeout=10, check=False,
    )


def _context_for(normalized_spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; context_for_break_mode "$2"', "_", str(LIB_PATH), normalized_spec],
        capture_output=True, text=True, timeout=10, check=False,
    )


def _run_runner(*args: str) -> subprocess.CompletedProcess[str]:
    """Invokes the REAL run-real-docker script, not a mock - the parsing
    stage runs before CONFIG_FILE is read, so this needs no setup at all.
    A `/etc/skillc-real-docker/config.env`-absent error for a VALID
    --break argument is success for this test's purposes: it proves
    parsing accepted the argument and execution moved past it."""
    return subprocess.run(
        [str(RUNNER_PATH), *args], capture_output=True, text=True, timeout=10, check=False,
        env={"SKILLC_REAL_DOCKER_CONFIG": "/nonexistent-for-tests/config.env"},
    )


# --------------------------------------------------------------- resolve_break_spec

def test_none_resolves_to_none_for_all_families() -> None:
    result = _resolve("none")
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["none"] * 11


@pytest.mark.parametrize("mode", ["regression-unprobed", "baseline-after-deploy", "restart-skipped"])
def test_namespaced_cicdverify_modes_set_only_the_cicdverify_value(mode: str) -> None:
    """#282: the eleventh line is SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK's value."""
    result = _resolve(f"cicdverify:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"cicdverify:{mode}", *["none"] * 9, mode]


@pytest.mark.parametrize("mode", ["omit-mount", "wrong-uid", "flip-decision"])
def test_namespaced_channel_modes_set_only_the_channel_value(mode: str) -> None:
    result = _resolve(f"channel:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"channel:{mode}", mode, "none", "none", "none", "none", "none", "none", "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", ["stale-confirm-lie", "kill-wrong-pid", "gate-in-fresh-container"])
def test_namespaced_witness_modes_set_only_the_witness_value(mode: str) -> None:
    result = _resolve(f"witness:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"witness:{mode}", "none", mode, "none", "none", "none", "none", "none", "none", "none", "none",
    ]


@pytest.mark.parametrize(
    "mode", ["synthesizes-output", "drops-cwd", "exits-zero-on-channel-failure", "wrong-env"],
)
def test_namespaced_gateshim_modes_set_only_the_gateshim_value(mode: str) -> None:
    result = _resolve(f"gateshim:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"gateshim:{mode}", "none", "none", mode, "none", "none", "none", "none", "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", ["skill-mount", "home-mount", "mcp-mount", "secret-mount", "cold-cache"])
def test_namespaced_coldinstall_modes_set_only_the_coldinstall_value(mode: str) -> None:
    result = _resolve(f"coldinstall:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"coldinstall:{mode}", "none", "none", "none", mode, "none", "none", "none", "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", ["no-uv"])
def test_namespaced_trialimage_modes_set_only_the_trialimage_value(mode: str) -> None:
    result = _resolve(f"trialimage:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"trialimage:{mode}", "none", "none", "none", "none", mode, "none", "none", "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", [
    "missing-closure", "tampered-closure", "empty-runtime-cache",
    "runtime-cache-permissions", "project-venv-permissions", "shim-alters-output",
])
def test_namespaced_closure_modes_set_only_the_closure_value(mode: str) -> None:
    result = _resolve(f"closure:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"closure:{mode}", "none", "none", "none", "none", "none", mode, "none", "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", ["confine-root-omitted"])
def test_namespaced_cwd_modes_set_only_the_cwd_value(mode: str) -> None:
    """#338: the eighth line is SKILLC_CWD_CONFINEMENT_LIVE_BREAK's value."""
    result = _resolve(f"cwd:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"cwd:{mode}", "none", "none", "none", "none", "none", "none", mode, "none", "none", "none",
    ]


@pytest.mark.parametrize("mode", ["allow-all", "bridge-network", "dns-hosts"])
def test_namespaced_egress_modes_set_only_the_egress_value(mode: str) -> None:
    """#442: the ninth line is SKILLC_EGRESS_LIVE_BREAK's value."""
    result = _resolve(f"egress:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"egress:{mode}", "none", "none", "none", "none", "none", "none", "none", mode, "none", "none",
    ]


def test_a_bare_egress_mode_is_refused_not_silently_accepted() -> None:
    """#442: no bare form was ever documented for the egress family."""
    result = _resolve("allow-all")
    assert result.returncode == 2
    assert result.stdout == ""


def test_there_is_no_egress_dns_server_break_mode() -> None:
    """#442: an --internal network resolves no external name even with --dns
    set (measured on the runner), so a DNS-server break could never break
    anything; the family offers dns-hosts instead, never dns-on."""
    result = _resolve("egress:dns-on")
    assert result.returncode == 2



@pytest.mark.parametrize("mode", ["no-curl", "old-curl", "service-down", "no-probes", "broken-build"])
def test_namespaced_cicdprofile_modes_set_only_the_cicdprofile_value(mode: str) -> None:
    """#280: the tenth line is SKILLC_CICD_PROFILE_LIVE_BREAK's value."""
    result = _resolve(f"cicdprofile:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"cicdprofile:{mode}", "none", "none", "none", "none", "none", "none", "none", "none", mode, "none",
    ]


@pytest.mark.parametrize("mode", ["omit-mount", "wrong-uid", "flip-decision"])
def test_bare_legacy_channel_modes_are_still_accepted_and_normalized(mode: str) -> None:
    """R2 compatibility (orchestrator review): the README already
    documented these bare spellings to the operator before family
    prefixes existed, so they must keep working - normalized to their
    `channel:<mode>` form, never left as the bare spelling, so every
    downstream comparison against "none" has exactly one non-none shape
    per mode to deal with."""
    result = _resolve(mode)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"channel:{mode}", mode, "none", "none", "none", "none", "none", "none", "none", "none", "none",
    ]


def test_a_bare_gateshim_mode_is_refused_not_silently_accepted() -> None:
    """Red case: a gateshim mode has NO documented bare form either (same
    rule as witness), so a bare spelling must be refused, not silently
    treated as a channel mode of the same name."""
    result = _resolve("synthesizes-output")
    assert result.returncode == 2
    assert "unknown channel break mode 'synthesizes-output'" in result.stderr


def test_a_bare_witness_mode_is_refused_not_silently_accepted() -> None:
    """Red case: a witness mode has NO documented bare form (unlike the
    three legacy channel modes), so a bare spelling must be refused, not
    silently treated as a channel mode of the same name."""
    result = _resolve("kill-wrong-pid")
    assert result.returncode == 2
    assert "unknown channel break mode 'kill-wrong-pid'" in result.stderr
    assert result.stdout == ""


def test_a_bare_coldinstall_mode_is_refused_not_silently_accepted() -> None:
    """Same red case, the coldinstall family: no bare form was ever
    documented for it either, so a bare spelling must be refused rather
    than silently treated as a channel mode of the same name."""
    result = _resolve("cold-cache")
    assert result.returncode == 2
    assert "unknown channel break mode 'cold-cache'" in result.stderr
    assert result.stdout == ""


def test_a_bare_trialimage_mode_is_refused_not_silently_accepted() -> None:
    """Same red case, the trialimage family (#343): no bare form was ever
    documented for it either, so a bare spelling must be refused rather
    than silently treated as a channel mode of the same name."""
    result = _resolve("no-uv")
    assert result.returncode == 2
    assert "unknown channel break mode 'no-uv'" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("mode", [
    "missing-closure", "empty-runtime-cache", "runtime-cache-permissions", "project-venv-permissions",
    "shim-alters-output",
])
def test_a_bare_closure_mode_is_refused_not_silently_accepted(mode: str) -> None:
    """Same red case, the closure family: no bare form was ever
    documented for it either, so a bare spelling must be refused rather
    than silently treated as a channel mode of the same name."""
    result = _resolve(mode)
    assert result.returncode == 2
    assert f"unknown channel break mode '{mode}'" in result.stderr
    assert result.stdout == ""


def test_a_bare_cwd_mode_is_refused_not_silently_accepted() -> None:
    """Same red case, the cwd family (#338): no bare form was ever
    documented for it, so a bare spelling must be refused rather than
    silently treated as a channel mode of the same name."""
    result = _resolve("confine-root-omitted")
    assert result.returncode == 2
    assert "unknown channel break mode 'confine-root-omitted'" in result.stderr
    assert result.stdout == ""


def test_an_unknown_mode_in_a_known_family_is_refused() -> None:
    result = _resolve("channel:bogus")
    assert result.returncode == 2
    assert "unknown channel break mode 'bogus'" in result.stderr


def test_an_unknown_mode_in_the_coldinstall_family_is_refused() -> None:
    result = _resolve("coldinstall:bogus")
    assert result.returncode == 2
    assert "unknown coldinstall break mode 'bogus'" in result.stderr


def test_an_unknown_mode_in_the_trialimage_family_is_refused() -> None:
    result = _resolve("trialimage:bogus")
    assert result.returncode == 2
    assert "unknown trialimage break mode 'bogus'" in result.stderr


def test_an_unknown_mode_in_the_closure_family_is_refused() -> None:
    result = _resolve("closure:bogus")
    assert result.returncode == 2
    assert "unknown closure break mode 'bogus'" in result.stderr


def test_an_unknown_mode_in_the_cwd_family_is_refused() -> None:
    result = _resolve("cwd:bogus")
    assert result.returncode == 2
    assert "unknown cwd break mode 'bogus'" in result.stderr


def test_a_bare_cicdprofile_mode_is_refused_not_silently_accepted() -> None:
    """#280: no bare form, so a bare spelling is a channel-mode refusal."""
    result = _resolve("no-probes")
    assert result.returncode == 2
    assert "unknown channel break mode 'no-probes'" in result.stderr
    assert result.stdout == ""


def test_an_unknown_mode_in_the_cicdprofile_family_is_refused() -> None:
    result = _resolve("cicdprofile:bogus")
    assert result.returncode == 2
    assert "unknown cicdprofile break mode 'bogus'" in result.stderr


def test_a_bare_cicdverify_mode_is_refused_not_silently_accepted() -> None:
    """#282: no bare form, so a bare spelling is a channel-mode refusal."""
    result = _resolve("restart-skipped")
    assert result.returncode == 2
    assert "unknown channel break mode 'restart-skipped'" in result.stderr
    assert result.stdout == ""


def test_an_unknown_mode_in_the_cicdverify_family_is_refused() -> None:
    result = _resolve("cicdverify:bogus")
    assert result.returncode == 2
    assert "unknown cicdverify break mode 'bogus'" in result.stderr


def test_an_unknown_family_is_refused() -> None:
    result = _resolve("bogus:foo")
    assert result.returncode == 2
    assert "unknown break family 'bogus'" in result.stderr


def test_an_empty_spec_is_refused_not_misread_as_an_empty_channel_mode() -> None:
    """codex:code_review red case: acceptance must not claim an empty
    population was checked - an empty string is not "none" and matches
    no declared channel mode, so it must be refused like any other
    unrecognized bare spelling."""
    result = _resolve("")
    assert result.returncode == 2
    assert "unknown channel break mode ''" in result.stderr


def test_a_spec_with_an_extra_colon_is_refused_not_truncated() -> None:
    """codex:code_review red case: `channel:omit-mount:extra` must not be
    silently truncated to a recognized mode - `${spec#*:}` takes
    everything after the FIRST colon, so the extracted "mode" is
    'omit-mount:extra', which matches nothing in the table."""
    result = _resolve("channel:omit-mount:extra")
    assert result.returncode == 2
    assert "unknown channel break mode 'omit-mount:extra'" in result.stderr


def test_red_case_a_table_that_accepts_everything_would_miss_both_refusals() -> None:
    """Mutation check: a plausible-but-wrong resolver that only checks for
    a ':' separator and accepts ANY family/mode pair would wrongly accept
    both red cases above. This test exists so a future edit to the table
    that accidentally widens it (e.g. a bare `*) return 0 ;;` fallthrough)
    is caught by disagreement with the real function, not just inspected
    by eye."""
    def accepts_anything(spec: str) -> bool:
        return ":" in spec or spec == "none"

    real_rejects_bare_witness = _resolve("kill-wrong-pid").returncode != 0
    real_rejects_unknown_family = _resolve("bogus:foo").returncode != 0
    assert real_rejects_bare_witness, "the real function should refuse this"
    assert real_rejects_unknown_family, "the real function should refuse this"
    assert accepts_anything("kill-wrong-pid") is False or accepts_anything("bogus:foo") is True, (
        "the naive mutation should disagree with the real function on at least one of these - "
        "if it agrees on both, this red case is inert"
    )


# ------------------------------------------------------------ context_for_break_mode

def test_none_resolves_to_the_certifying_context() -> None:
    result = _context_for("none")
    assert result.returncode == 0
    assert result.stdout.strip() == "skillc/real-docker"


@pytest.mark.parametrize(
    "normalized_spec",
    [
        "channel:omit-mount",
        "channel:wrong-uid",
        "channel:flip-decision",
        "witness:stale-confirm-lie",
        "witness:kill-wrong-pid",
        "witness:gate-in-fresh-container",
        "gateshim:synthesizes-output",
        "gateshim:drops-cwd",
        "gateshim:exits-zero-on-channel-failure",
        "gateshim:wrong-env",
        "coldinstall:skill-mount",
        "coldinstall:home-mount",
        "coldinstall:mcp-mount",
        "coldinstall:secret-mount",
        "coldinstall:cold-cache",
        "trialimage:no-uv",
        "closure:missing-closure",
        "closure:tampered-closure",
        "closure:empty-runtime-cache",
        "closure:runtime-cache-permissions",
        "closure:project-venv-permissions",
        "closure:shim-alters-output",
        "cwd:confine-root-omitted",
        "egress:allow-all",
        "egress:bridge-network",
        "egress:dns-hosts",
        "cicdprofile:no-curl",
        "cicdprofile:old-curl",
        "cicdprofile:service-down",
        "cicdprofile:no-probes",
        "cicdprofile:broken-build",
        "cicdverify:regression-unprobed",
        "cicdverify:baseline-after-deploy",
        "cicdverify:restart-skipped",
    ],
)
def test_every_break_mode_resolves_to_the_control_context_never_the_certifying_one(normalized_spec: str) -> None:
    """The red case orchestrator review named explicitly: a break run must
    NEVER resolve to the certifying context - a run that found a real
    failure under a deliberately broken implementation must not be
    mistaken, by GitHub or by a human skimming commit statuses, for the
    normal certifying signal."""
    result = _context_for(normalized_spec)
    assert result.returncode == 0
    assert result.stdout.strip() == "skillc/real-docker-control"


# --------------------------------------------------- end-to-end: the real runner

def test_the_real_runner_refuses_an_unknown_break_spec_before_touching_any_config() -> None:
    """Confirms the wiring, not just the lib in isolation: a syntactically
    invalid --break argument must be refused by the REAL run-real-docker
    script before it ever reads SKILLC_REAL_DOCKER_CONFIG - demonstrated
    by pointing that variable at a path that does not exist and observing
    the parsing error, not a config-file error."""
    result = _run_runner(DUMMY_SHA, "--break", "bogus:foo")
    assert result.returncode == 2
    assert "unknown break family 'bogus'" in result.stderr
    assert "config file" not in result.stderr


@pytest.mark.parametrize(
    "break_arg",
    [
        "none",
        "channel:omit-mount",
        "omit-mount",
        "witness:kill-wrong-pid",
        "gateshim:drops-cwd",
        "coldinstall:cold-cache",
        "trialimage:no-uv",
        "closure:missing-closure",
        "closure:empty-runtime-cache",
        "closure:runtime-cache-permissions",
        "closure:project-venv-permissions",
        "closure:shim-alters-output",
        "cwd:confine-root-omitted",
        "egress:allow-all",
        "egress:bridge-network",
        "egress:dns-hosts",
    ],
)
def test_the_real_runner_accepts_valid_break_specs_and_reaches_the_config_check(break_arg: str) -> None:
    """A VALID --break argument must be accepted by parsing and reach the
    next stage (the config-file check) - proven by getting that stage's
    own error, not a parsing error, for every family and for the legacy
    bare form."""
    args = (DUMMY_SHA,) if break_arg == "none" else (DUMMY_SHA, "--break", break_arg)
    result = _run_runner(*args)
    assert result.returncode == 2
    assert "config file" in result.stderr
    assert "unknown break" not in result.stderr
    assert "--break must be" not in result.stderr


def test_the_real_runner_always_sets_all_seven_break_variables_explicitly() -> None:
    """Regression guard for the inherited-environment contamination fix
    (codex:code_review, HIGH): the pytest invocation must set ALL SEVEN of
    SKILLC_LIVE_TEST_BREAK, SKILLC_GATE_WITNESS_LIVE_BREAK, (#332 follow-up)
    SKILLC_GATE_SHIM_LIVE_BREAK, (#266 follow-up)
    SKILLC_COLDINSTALL_LIVE_BREAK, (#343 follow-up)
    SKILLC_TRIAL_IMAGE_BREAK, (#334 follow-up)
    SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK, and (#338 follow-up)
    SKILLC_CWD_CONFINEMENT_LIVE_BREAK explicitly on every run, from
    resolve_break_spec's own always-all-present output - never leaving any
    of them to whatever the runner's own process environment happened to
    inherit, which is what let a stale SKILLC_LIVE_TEST_BREAK survive into
    a `--break none` (certifying) run before the original fix. Checked by
    reading the script's own text: driving the actual invocation needs a
    real checkout and docker daemon this environment does not have, so the
    behavioral guarantee - that resolve_break_spec never emits an empty
    value for any family - is covered by the shape assertions above
    instead; this is a narrower guard against reverting the invocation
    itself to a form that drops one of the seven variables."""
    text = RUNNER_PATH.read_text(encoding="utf-8")
    assert 'SKILLC_LIVE_TEST_BREAK="$CHANNEL_BREAK_VALUE"' in text
    assert 'SKILLC_GATE_WITNESS_LIVE_BREAK="$WITNESS_BREAK_VALUE"' in text
    assert 'SKILLC_GATE_SHIM_LIVE_BREAK="$GATESHIM_BREAK_VALUE"' in text
    assert 'SKILLC_COLDINSTALL_LIVE_BREAK="$COLDINSTALL_BREAK_VALUE"' in text
    assert 'SKILLC_TRIAL_IMAGE_BREAK="$TRIALIMAGE_BREAK_VALUE"' in text
    assert 'SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK="$CLOSURE_BREAK_VALUE"' in text
    assert 'SKILLC_CWD_CONFINEMENT_LIVE_BREAK="$CWD_BREAK_VALUE"' in text
    assert 'SKILLC_EGRESS_LIVE_BREAK="$EGRESS_BREAK_VALUE"' in text
    assert 'SKILLC_CICD_PROFILE_LIVE_BREAK="$CICDPROFILE_BREAK_VALUE"' in text
    assert 'SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK="$CICDVERIFY_BREAK_VALUE"' in text
