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

from pathlib import Path

import pytest


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
