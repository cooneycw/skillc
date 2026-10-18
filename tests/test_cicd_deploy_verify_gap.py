"""The known gap's instrument and the template transform in
tests/test_cicd_deploy_verify_live.py (#282), checked without Docker.

`check_known_gap_1479` decides whether a live observation still shows
claude-power-pack#1479. Its committed red cases (skillc-400's ruling): a
verdict other than PROCEED under the gap's own setup fails as "gap closed",
and a setup that is not the gap's fails its precondition - never the gap
assertion, and never a pass.
"""

from __future__ import annotations

import pytest
import yaml
from test_cicd_deploy_verify_live import (
    FIXTURE,
    HEALTH_ONLY,
    RELEASE_PROBE,
    GapConfigNotHealthOnly,
    GapReleaseNotMismatched,
    GapRestartNotSkipped,
    KnownGap1479Closed,
    check_known_gap_1479,
    is_health_only,
    uncommented_template,
)

from skillc import deploy_verdict as dv

PROCEEDED = dv.VerifyReading(verdict=dv.PROCEED, has_baseline=True, classes={"health:service health": "ok"})


def test_the_gap_as_observed_passes() -> None:
    check_known_gap_1479(HEALTH_ONLY, "skipped", "mismatched", PROCEEDED)


@pytest.mark.parametrize("verdict", [dv.REVIEW, dv.ROLLBACK, dv.UNKNOWN])
def test_a_changed_verdict_reads_as_gap_closed(verdict: str) -> None:
    with pytest.raises(KnownGap1479Closed, match="gap closed or moved; update deliberately"):
        check_known_gap_1479(HEALTH_ONLY, "skipped", "mismatched", dv.VerifyReading(verdict=verdict))


@pytest.mark.parametrize("restart", ["restarted", "unknown"])
def test_a_restart_that_was_not_skipped_fails_the_precondition_not_the_gap(restart: str) -> None:
    with pytest.raises(GapRestartNotSkipped):
        check_known_gap_1479(HEALTH_ONLY, restart, "mismatched", PROCEEDED)


@pytest.mark.parametrize("identity", ["matched", "unknown"])
def test_a_release_that_is_not_mismatched_fails_the_precondition(identity: str) -> None:
    with pytest.raises(GapReleaseNotMismatched):
        check_known_gap_1479(HEALTH_ONLY, "skipped", identity, PROCEEDED)


def test_a_config_that_can_see_the_release_fails_the_precondition() -> None:
    probed = RELEASE_PROBE.replace("@INTENDED@", "r2").replace("@REQUIRE_BASELINE@", "false")
    assert not is_health_only(probed)
    with pytest.raises(GapConfigNotHealthOnly):
        check_known_gap_1479(probed, "skipped", "mismatched", PROCEEDED)
    assert is_health_only(HEALTH_ONLY)
    assert not is_health_only(HEALTH_ONLY + "  smoke_tests:\n    - name: x\n      command: true\n")


def test_uncommented_template_shows_the_ignored_keys() -> None:
    template = (FIXTURE.parent / "profile-cpp-codex-cicd-86641e8" / "templates" / "cicd.yml.example").read_text()
    verbatim = yaml.safe_load(template) or {}
    assert "health" not in verbatim and "smoke" not in verbatim  # all commented: zero probes as copied
    shown = yaml.safe_load(uncommented_template(template))
    assert shown["health"]["url"] == "http://127.0.0.1:18080/health"
    assert [t["name"] for t in shown["smoke"]["tests"]] == ["Homepage loads", "API responds"]
    assert "endpoints" not in shown["health"] and "smoke_tests" not in shown["health"]  # what lib.cicd reads
