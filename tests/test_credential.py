"""Tests for skillc/credential.py (#98): resolution, fresh reads, and the
remaining-life refusal. No Docker call anywhere - this module resolves and
reads a HOST file; delivery into a container is
docker_backend.DockerBackend.deliver_home_file, tested separately.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

from skillc import credential as cred

# --------------------------------------------------------------- resolve_path

def test_resolve_path_prefers_the_explicit_argument(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}")
    assert cred.resolve_path("claude", explicit=explicit) == explicit


def test_resolve_path_refuses_a_missing_explicit_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(cred.CredentialRefused, match="no claude credential"):
        cred.resolve_path("claude", explicit=missing)


def test_resolve_path_uses_the_env_override_when_no_explicit_path_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = tmp_path / "named-by-env.json"
    named.write_text("{}")
    monkeypatch.setenv("SKILLC_CODEX_CREDENTIAL", str(named))
    assert cred.resolve_path("codex") == named


def test_resolve_path_falls_back_to_the_standard_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SKILLC_CLAUDE_CREDENTIAL", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    standard = tmp_path / ".claude" / ".credentials.json"
    standard.parent.mkdir(parents=True)
    standard.write_text("{}")
    assert cred.resolve_path("claude") == standard


def test_resolve_path_refuses_when_nothing_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control (#98's own acceptance): BLOCKED with no credential supplied -
    never a fallback to guessing another location."""
    monkeypatch.delenv("SKILLC_CLAUDE_CREDENTIAL", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(cred.CredentialRefused, match="the standard location"):
        cred.resolve_path("claude")


def test_resolve_path_refuses_an_unknown_client() -> None:
    with pytest.raises(cred.CredentialRefused, match="unknown client"):
        cred.resolve_path("some-other-client")


def test_resolve_path_never_follows_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(cred.CredentialRefused):
        cred.resolve_path("claude", explicit=link)


# ----------------------------------------------------------------- read_fresh

def test_read_fresh_reads_the_current_bytes_not_a_cached_copy(tmp_path: Path) -> None:
    path = tmp_path / "cred.json"
    path.write_text("first")
    assert cred.read_fresh(path) == b"first"
    path.write_text("second")
    assert cred.read_fresh(path) == b"second"


# --------------------------------------------------------- remaining_life_seconds

def test_remaining_life_seconds_reads_the_claude_shape() -> None:
    expires_at_ms = int((time.time() + 3600) * 1000)
    data = json.dumps({"claudeAiOauth": {"expiresAt": expires_at_ms}}).encode()
    remaining = cred.remaining_life_seconds("claude", data)
    assert remaining is not None
    assert 3500 < remaining < 3700


def _fake_jwt(payload: dict[str, object]) -> str:
    """A syntactically real JWT (three base64url segments) carrying `payload`
    in its middle segment - never signed, because `_jwt_exp_seconds` never
    verifies a signature (module docstring: reads a credential already
    trusted by its presence on disk, never authenticates one)."""
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    header = seg(json.dumps({"alg": "none"}).encode())
    body = seg(json.dumps(payload).encode())
    return f"{header}.{body}.fake-signature"


def test_remaining_life_seconds_reads_the_codex_shape() -> None:
    """Codex's `auth.json` has no `expires_at` field anywhere (verified
    against a real file, #98, cross-model review) - the expiry lives in the
    `exp` claim of the JWT at `tokens.access_token`."""
    token = _fake_jwt({"exp": int(time.time() + 1800)})
    data = json.dumps({"tokens": {"access_token": token}}).encode()
    remaining = cred.remaining_life_seconds("codex", data)
    assert remaining is not None
    assert 1700 < remaining < 1900


def test_remaining_life_seconds_is_none_for_a_codex_token_that_is_not_a_jwt() -> None:
    data = json.dumps({"tokens": {"access_token": "not-a-jwt"}}).encode()
    assert cred.remaining_life_seconds("codex", data) is None


def test_remaining_life_seconds_is_none_for_a_jwt_missing_the_exp_claim() -> None:
    token = _fake_jwt({"iat": int(time.time())})
    data = json.dumps({"tokens": {"access_token": token}}).encode()
    assert cred.remaining_life_seconds("codex", data) is None


@pytest.mark.parametrize("bad_exp", [float("nan"), float("inf"), float("-inf"), True])
def test_remaining_life_seconds_rejects_non_finite_or_boolean_exp(bad_exp: object) -> None:
    """Control (cross-model review, #98): Python's `json.loads` accepts
    `NaN`/`Infinity`/`-Infinity` by default, and a JSON `bool` is a Python
    `int` subclass - either one must be treated as undeterminable, never as
    a real expiry that happens to compare favorably."""
    token = _fake_jwt({"exp": bad_exp})
    data = json.dumps({"tokens": {"access_token": token}}).encode()
    assert cred.remaining_life_seconds("codex", data) is None


@pytest.mark.parametrize("bad_exp", [float("nan"), float("inf"), True])
def test_remaining_life_seconds_rejects_non_finite_or_boolean_claude_expiry(bad_exp: object) -> None:
    data = json.dumps({"claudeAiOauth": {"expiresAt": bad_exp}}).encode()
    assert cred.remaining_life_seconds("claude", data) is None


def test_remaining_life_seconds_is_none_for_malformed_json() -> None:
    assert cred.remaining_life_seconds("claude", b"not json at all") is None


def test_remaining_life_seconds_is_none_for_an_unrecognized_shape() -> None:
    """Never a guessed number: an unfamiliar shape is UNKNOWN, not assumed
    fine and not assumed expired."""
    data = json.dumps({"some_other_field": 12345}).encode()
    assert cred.remaining_life_seconds("claude", data) is None


# --------------------------------------------------- check_remaining_life_or_refuse

def test_check_remaining_life_returns_the_value_when_sufficient() -> None:
    data = json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 3600) * 1000)}}).encode()
    remaining = cred.check_remaining_life_or_refuse("claude", data, minimum_seconds=300)
    assert remaining > 3000


def test_check_remaining_life_refuses_below_the_threshold() -> None:
    """Control (#98's own acceptance): BLOCKED when the token's remaining
    life is below the stated threshold."""
    data = json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 60) * 1000)}}).encode()
    with pytest.raises(cred.CredentialRefused, match="below the required"):
        cred.check_remaining_life_or_refuse("claude", data, minimum_seconds=300)


def test_check_remaining_life_refuses_when_undeterminable() -> None:
    """An UNKNOWN remaining life is refused, never treated as 'probably
    fine' - the same discipline this codebase applies to every other
    unconfirmable fact (Confirmation.UNKNOWN never reaps, never confirms)."""
    with pytest.raises(cred.CredentialRefused, match="could not be determined"):
        cred.check_remaining_life_or_refuse("claude", b"{}", minimum_seconds=300)


# --------------------------------------------------- refresh_observed

def test_refresh_observed_is_false_on_identical_bytes() -> None:
    assert cred.refresh_observed(b"same-bytes", b"same-bytes") is False


def test_refresh_observed_is_true_on_any_difference() -> None:
    assert cred.refresh_observed(b"original-bytes", b"refreshed-bytes") is True


# --------------------------------------------------- CredentialUsage

def test_credential_usage_names_the_client_and_subscription_never_the_token() -> None:
    """Control (#98's own acceptance): "records name the client and
    'subscription', never the token" - built entirely from facts the caller
    already holds, with no field a token value could occupy."""
    usage = cred.CredentialUsage(client="claude", delivered=True, refresh_observed_in_container=False)
    fields = usage.to_record_fields()
    assert fields == {
        "credential_client": "claude",
        "credential_source": "subscription",
        "credential_delivered": True,
        "credential_refresh_observed_in_container": False,
    }
    assert "token" not in str(fields).lower()


def test_credential_usage_defaults_refresh_observed_to_none_when_never_compared() -> None:
    """`None` means "not observed" - a caller that never called
    `read_home_file` must not report `False` (which would claim "confirmed
    no refresh happened") for a comparison it never made."""
    usage = cred.CredentialUsage(client="codex")
    assert usage.to_record_fields()["credential_refresh_observed_in_container"] is None


@pytest.mark.parametrize("bad_minimum", [float("nan"), float("inf"), float("-inf"), -1.0, True])
def test_check_remaining_life_rejects_an_invalid_threshold(bad_minimum: object) -> None:
    """Control (cross-model review, #98): the threshold is a caller-supplied
    parameter, not credential data - a non-finite, negative, or boolean
    value is a programming error and must raise `ValueError`, never be
    silently compared against (a NaN threshold makes every comparison
    False, which would let ANY remaining life "pass")."""
    data = json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 3600) * 1000)}}).encode()
    with pytest.raises(ValueError, match="minimum_seconds"):
        cred.check_remaining_life_or_refuse("claude", data, minimum_seconds=bad_minimum)  # type: ignore[arg-type]
