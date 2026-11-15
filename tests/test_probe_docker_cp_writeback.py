"""The #761 docker cp probe's parser (scripts/probe_docker_cp_writeback.py).

The probe's own run needs a real daemon; these controls pin what its counts
CAN say, so a failed stat or a loop that ended before the copy can never read
as evidence about the copy (counter-model review, #761)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probe_docker_cp_writeback",
                                               ROOT / "scripts" / "probe_docker_cp_writeback.py")
assert _spec is not None and _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

SEED = len(probe.SEED)


def test_a_covered_run_counts_partial_sizes_and_replacement() -> None:
    lines = [f"S 10 {SEED}", "S 11 0", "S 11 100", "S 11 200"]
    assert probe.summarize(lines, 200) == {"samples": 4, "inodes": 2, "absent": 0, "failed": 0, "sizes": 4,
                                           "covered": True}


def test_a_failed_stat_is_counted_as_failed_never_as_data() -> None:
    """The control for the review's finding: a diagnostic line used to become
    another inode and size, inventing partial content."""
    lines = [f"S 10 {SEED}", "ERR", "stat: can't stat '/w/observations': No such file or directory",
             "S 10 200"]
    got = probe.summarize(lines, 200)
    assert got["failed"] == 2 and got["sizes"] == 2 and got["inodes"] == 1 and got["covered"] is True


def test_an_absent_sample_is_counted() -> None:
    assert probe.summarize([f"S 10 {SEED}", "ABSENT", "S 12 200"], 200)["absent"] == 1


def test_sampling_that_ended_before_the_copy_is_not_covered() -> None:
    """Every sample is the seed: nothing about the copy was observed."""
    assert probe.summarize([f"S 10 {SEED}"] * 5, 200)["covered"] is False


def test_sampling_that_missed_the_seed_is_not_covered() -> None:
    assert probe.summarize(["S 11 100", "S 11 200"], 200)["covered"] is False


def test_no_samples_is_not_covered() -> None:
    assert probe.summarize([], 200)["covered"] is False
