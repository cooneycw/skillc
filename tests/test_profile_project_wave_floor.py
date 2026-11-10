"""Existing floor consumer controls: new file silence never borrows other greens."""
from pathlib import Path

import pytest

from ci import check_real_docker_ran as floor

ROOT = Path(__file__).resolve().parents[1] / 'controls/profile-project-wave-cold'


@pytest.mark.parametrize(('case', 'expected'), [('passed', 'SUCCESS'), ('missing', 'ERROR'),
                                              ('skipped', 'FAILURE'), ('failed', 'FAILURE'), ('error', 'FAILURE')], ids=['pass', 'missing', 'skip', 'fail', 'error'])
def test_combined_profile_cold_floor_discriminates(case: str, expected: str) -> None:
    observed = floor.verdict(str(ROOT / ('floor-' + case + '.xml')))
    assert observed.status == expected
