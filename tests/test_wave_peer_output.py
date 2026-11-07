"""CPP's list --json output is a leading JSON document plus a verdict trailer."""
from pathlib import Path

import pytest
from wave_role_diagnostics import parse_cpp_peers

# Captured from the pinned CPP helper using disposable local role registrations.
# The host label is the synthetic 'fixture'; no physical liveness is claimed.
FIXTURE = Path(__file__).parent / 'fixtures/docker-wave-live/cpp-peers-listed.stdout'
LISTED = FIXTURE.read_text()


def test_real_cpp_list_output_retains_roster_and_liveness() -> None:
    peers = parse_cpp_peers(LISTED, exit_code='0\n')
    roles = {'orchestrator', 'worker-a', 'worker-b'}
    assert roles <= peers.keys()
    assert all({'liveness', 'liveness_basis'} <= peers[role].keys() for role in roles)
    assert peers['worker-a']['liveness_basis'] == 'pid-gone'


@pytest.mark.parametrize('broken', [
    LISTED.replace('FLOW_WAVE_POLICY=absent', 'unexpected garbage'),
    LISTED.replace('FLOW_WAVE: listed\n', ''),
    LISTED.replace('FLOW_WAVE: listed', 'FLOW_WAVE: error'),
    LISTED + 'unexpected garbage\n',
    LISTED + 'FLOW_WAVE_EXTRA=after-verdict\n',
    'FLOW_WAVE: listed\n',
    '',
    '{}\nFLOW_WAVE: listed\n',
    '[]\nFLOW_WAVE: listed\n',
    'null\nFLOW_WAVE: listed\n',
    'noise before JSON\n' + LISTED,
    LISTED.replace('FLOW_WAVE_POLICY=absent', '{"another": "document"}'),
    LISTED.replace('FLOW_WAVE_POLICY=absent', 'FLOW_WAVE_BAD'),
    LISTED.replace('FLOW_WAVE_POLICY=absent', 'FLOW_WAVE_=absent'),
    LISTED.replace('FLOW_WAVE_POLICY=absent', 'FLOW_WAVE_POLICY: absent'),
    LISTED.replace('}\nFLOW_WAVE_POLICY=absent', '}FLOW_WAVE_POLICY=absent'),
], ids=['garbage-detail', 'missing-verdict', 'error-verdict', 'garbage-after-verdict',
        'detail-after-verdict', 'missing-json', 'empty-output', 'empty-object',
        'array', 'null', 'json-not-leading', 'second-json', 'missing-equals',
        'empty-key', 'wrong-separator', 'missing-line-boundary'])
def test_cpp_list_parser_refuses_malformed_output(broken: str) -> None:
    with pytest.raises(ValueError):
        parse_cpp_peers(broken, exit_code='0')


@pytest.mark.parametrize('exit_code', ['1', '7\n', '', '0\n1', '-1'])
def test_cpp_list_parser_requires_successful_exit(exit_code: str) -> None:
    with pytest.raises(ValueError, match='exit successfully'):
        parse_cpp_peers(LISTED, exit_code=exit_code)
