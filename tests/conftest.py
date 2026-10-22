"""Repository-wide test fixtures.

Found on PR #117 (issue #106): a test that passed `credential_explicit_path=None`
(intending only "no override"), with no override of its own for the
standard-location fallback either, resolved and READ the operator's own real
Claude subscription credential on the host that ran it - `credential.resolve_path`
did exactly what it is documented to do (fall through to the standard,
DOCUMENTED location), and that location happened to hold a real, live
credential on that particular machine. Nothing was committed - the value
never left the test process - but a test suite able to reach a real secret
at all is a standing hazard independent of whether any run actually leaked
one, and it is silent: the test passed, CI (which has no real credential at
that path) failed it, and the difference was where it ran, not what it
asserted.

`_no_real_credential_defaults` closes this STRUCTURALLY, for every test,
rather than requiring each one to remember to monkeypatch `Path.home()`/
`CODEX_HOME` for itself (several already do, for their own local reasons -
`tests/test_credential.py`'s own standard-location tests - and this fixture
changes nothing for them: a test's own `monkeypatch.setenv`/`setattr` calls
run AFTER this fixture and override it for that test only).

`autouse=True`: the whole point is that a test does not have to ask for
this - the hazard above was a test that had no idea it needed to.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import failure_context as _failure_context
import pytest

from skillc import verify


def pytest_configure(config: pytest.Config) -> None:
    """#462: record the machine context of every real failure (see the module)."""
    _failure_context.register(config)


@pytest.fixture(autouse=True)
def _no_quarantine_leaks_across_tests() -> Iterator[None]:
    """Issue #219: `verify._quarantine` is module-level, and nothing reset it
    between tests. One test whose backend probe containment was lost (a
    genuinely slow fake-docker daemon call under CI host contention, or a
    real lost containment) quarantined the verifier for the rest of the
    pytest PROCESS - every later test that called `verify.grade_files` failed
    with `Refused: this verifier is quarantined`, whatever it actually
    exercised. Main's push pipeline 482 read 18 unrelated tests across two
    files as red from one timing miss.

    Five files already defend themselves with their own identical
    `autouse=True` fixture (`test_calibration.py`, `test_calibration_run.py`,
    `test_verify.py`, `test_verify_backend.py`, `test_verify_judge.py`) -
    checked before adding this one, per the issue's own instruction: none of
    them relies on a quarantine PERSISTING into a later test, including
    `test_verify.py`'s own test of quarantine itself
    (`test_a_candidate_that_kills_the_supervisor_and_stays_alive_is_killed_and_quarantines`),
    which clears it before returning. This fixture is the same clear-before/
    clear-after promoted to every test in the suite, not a new policy, so it
    changes nothing for those five files beyond running a second,
    idempotent `clear_quarantine()` alongside their own."""
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


@pytest.fixture(autouse=True)
def _no_real_credential_defaults(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Makes every REAL standard credential location, and both named
    env-var overrides, unreachable by default: `HOME` points at a fresh,
    empty per-test directory (so `Path.home() / ".claude" / ".credentials.json"`
    and the bare `Path.home() / ".codex"` fallback both resolve under it and
    find nothing), `CODEX_HOME` points at a second fresh, empty directory,
    and `SKILLC_CLAUDE_CREDENTIAL`/`SKILLC_CODEX_CREDENTIAL` are set to
    explicit, guaranteed-nonexistent paths - set, not merely deleted, so a
    test cannot end up reading a value some earlier, unrelated shell session
    exported into the ambient environment either."""
    fake_home = tmp_path_factory.mktemp("no-real-home")
    fake_codex_home = tmp_path_factory.mktemp("no-real-codex-home")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CODEX_HOME", str(fake_codex_home))
    monkeypatch.setenv("SKILLC_CLAUDE_CREDENTIAL", str(fake_home / "does-not-exist-claude-credential.json"))
    monkeypatch.setenv("SKILLC_CODEX_CREDENTIAL", str(fake_home / "does-not-exist-codex-credential.json"))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


#: A `DockerBackend.daemon_timeout` for tests that construct one against the
#: fake `docker` CLI (`tests/fixtures/docker-backend/fake_docker.py`), a
#: real subprocess spawned once per daemon call. Production's own default
#: (`docker_backend.DAEMON_TIMEOUT`, 5.0s) is unchanged - it bounds a call to
#: a REAL daemon, and item 1/2's own acceptance criterion (issue #174) is
#: that a genuinely slow/unreachable daemon must still read as
#: `Confirmation.UNKNOWN` (never a guess) at whatever bound production uses.
#: This constant instead widens the TEST-ONLY margin against ordinary host
#: scheduling contention around the FAKE CLI's own process-spawn overhead,
#: which is not a containment question at all - see
#: `tests/test_selection_probe.py`'s and `tests/test_degrade_collection_run.py`'s
#: own DockerBackend constructions, and the fault-injection tests proving
#: both sides: a delay under this bound still reports captured/confirmed,
#: and a delay past it still reports UNKNOWN/inconclusive/quarantined.
FAKE_DOCKER_DAEMON_TIMEOUT = 30.0

#: Daemon budget for the REAL-Docker live tests (`tests/*_live.py`, #390). Not
#: the fake-CLI margin above: this one answers a real daemon's stalls. On
#: #315's dedicated runner a `docker run -d` with the live tests' arguments
#: took 0.13-0.62 s in 26 of 27 starts and 7.61 s once, right after a slow
#: fresh-tag image build (measured 2026-10-14). On the 5 s module default that
#: stall failed two campaign-1 negative controls in setup, before their
#: planted fault, so they proved nothing. Production is unaffected: every CLI
#: path passes its own `daemon_timeout`. A daemon that never answers is still
#: refused at this bound; `tests/test_live_docker_budget.py` checks both.
LIVE_DOCKER_DAEMON_TIMEOUT = 30.0

#: #280: the local CI/CD fixture project carries its OWN unittest suite, run
#: inside the trial container by `make test`. It imports `calc` from the
#: project's `src/`, so this repository's collection must never import it.
collect_ignore_glob = ["fixtures/cicd-local/*"]


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep shared real-Docker resources on one worker; retain canonical JUnit ids.

    xdist's later collection hook appends the combined group name to worker
    nodeids. Record that exact suffix so the population checker can reconcile
    worker reports with independent serial collection without guessing at '@'.
    """
    for item in items:
        if item.get_closest_marker("real_docker") is not None:
            item.add_marker(pytest.mark.xdist_group("real_docker"))
        groups = {str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                  for mark in item.iter_markers("xdist_group")}
        if groups:
            item.user_properties.append(("skillc_xdist_group", "_".join(sorted(groups))))


def stamp_approval(data: dict) -> dict:
    """Bind a test declaration's approval to its exact content (#287 P2,
    D-P2a): sets `approval.declaration_digest` to the declaration's own
    digest, as a real approval must. Call it LAST, after every edit the test
    means to approve; a field edited afterwards is then a genuine
    changed-after-approval case. A null approval is left null."""
    from skillc import calibration
    if isinstance(data.get("approval"), dict):
        data["approval"]["declaration_digest"] = calibration.declaration_digest(data)
    return data


def p3_bindings(data: dict) -> dict:
    """Give a test declaration the fields #287 P3 requires of a new-kind
    declaration (every discrimination declaration, and a calibration
    declaration with an outcome endpoint): the code's own provider-only egress
    policy (C4), a durable `run_store` (C5), a tolerance (C2) and a runtime
    receipt digest (C3; synthetic unless the test supplies one). Call it
    before `stamp_approval`."""
    from skillc import collection_conformance, egress
    data["shared"]["agent_network"] = {
        "policy": collection_conformance.AGENT_NETWORK_POLICY,
        "allowlist_digest": egress.allowlist_digest(),
        "codex_server_side_off": list(egress.CODEX_SERVER_SIDE_OFF),
    }
    data["shared"]["image"].setdefault("receipt_sha256", "sha256:" + "e" * 64)
    data["run_store"] = "~/skillc-evidence/test"
    data.setdefault("tolerance", {"non_evaluable_per_arm": 1})
    return data


class FakeStewardDriver:
    """#518: a well-behaved credential steward for every non-live test, which
    has no container in which a real one could run. It emits the real
    protocol's events into the session: start -> armed, withdrawn; a resume
    -> armed, withdrawn; stop -> stopped. A test that needs a steward that
    misbehaves sets `mode` (or builds its own)."""

    mode = "held"  # "held" | "never-arms" | "refreshed"

    def __init__(self, session: object, backend: object, handle: object) -> None:
        from skillc import credential_steward as cs
        assert isinstance(session, cs.CredentialStewardSession)
        self.session, self.backend, self.handle, self.arms, self.seq = session, backend, handle, 0, 0
        if FakeStewardDriver.mode == "never-arms":
            raise cs.StewardFailed("the credential steward never reported armed")
        self._arm()
        if FakeStewardDriver.mode == "refreshed":
            self._emit("refreshed-captured")

    def _emit(self, event: str) -> None:
        self.seq += 1
        self.session.decide({"op": "credential_steward", "event": event, "seq": self.seq,  # type: ignore[attr-defined]
                             "opens": 4, "closes": 4})

    def _arm(self) -> None:
        self.arms += 1
        self._emit("armed")
        self._emit("withdrawn")

    def restore_for_turn(self, backend: object, handle: object) -> None:
        self._arm()

    def stop(self, backend: object, handle: object) -> None:
        self._emit("stopped")

    def vault_bytes(self, backend: object, handle: object) -> bytes | None:
        # No real withdrawal happened, so the home still holds the credential.
        return backend.read_home_file(handle, ".codex/auth.json")  # type: ignore[attr-defined, no-any-return]

    def record(self) -> dict[str, object]:
        return self.session.finalize(expected_arms=self.arms)  # type: ignore[attr-defined, no-any-return]


@pytest.fixture(autouse=True)
def _fake_credential_steward(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Non-live tests get `FakeStewardDriver`; live (`real_docker`) tests run the real steward."""
    if request.node.get_closest_marker("real_docker") is None:
        from skillc import credential_steward as cs
        monkeypatch.setattr(cs, "start_for", FakeStewardDriver)
    FakeStewardDriver.mode = "held"
    yield
    FakeStewardDriver.mode = "held"
