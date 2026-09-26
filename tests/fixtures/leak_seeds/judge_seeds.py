"""Seeded machine-identity strings for the judge-seam tests (#69). Holds
nothing but these constants - narrowly excluded from CI's leak-check scan
(`.woodpecker/ci.yml`'s `SKILLC_EXCLUDE_ARGS`), so a real leak added anywhere
ELSE in `tests/test_judge.py` or `tests/test_verify_judge.py` is still
caught. An earlier version excluded those whole test files instead
(476 lines, of which 7 carried a seed) - found by orchestrator review of
PR #92 as a gate widened past its purpose: excluding a whole file is
indistinguishable, to the leak-check instrument, from excluding the file
because nothing in it will ever need scanning again.
"""

from __future__ import annotations

#: Matches `skillc.leak.HOME_PATH_RE` regardless of what follows - each
#: caller appends its own suffix (e.g. f"{HOME_PATH_LEAK}/notes.txt").
HOME_PATH_LEAK = "/home/alice"

#: Two distinct private (RFC 1918) IPv4 addresses, matching
#: `skillc.leak.IPV4_RE` - kept as two constants only because the tests that
#: use them were already written against two different literals; either
#: would equally trigger the same finding class.
PRIVATE_IP_LEAK = "10.0.0.5"
PRIVATE_IP_LEAK_2 = "192.168.1.50"
