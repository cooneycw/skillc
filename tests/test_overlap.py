"""`skillc charter overlap` (#726, round 1, PR B): shared, shadowed and orphan
duties, behind a comparator seam. FakeComparator only: no model call."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from skillc import cli, contracts, overlap
from skillc.overlap import DIFFERENT, SAME, UNKNOWN, FakeComparator

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "evals/subjects/overlap-controls"
PARAPHRASE = CONTROLS / "shared-paraphrase"
VOCABULARY = CONTROLS / "distinct-vocabulary"


def _collection(root: Path) -> contracts.Collection:
    return contracts.load_collection(root)


# ---------------------------------------------------------------- the planted controls (acceptance 1)


def test_the_paraphrase_control_is_shared_under_a_comparator_that_says_so() -> None:
    fake = FakeComparator({("alpha.always-1", "beta.always-1"): [SAME]})
    report = overlap.compare(_collection(PARAPHRASE), fake)
    assert overlap.ids(report.overlaps) == [("shared", "alpha.always-1", "beta.always-1")]


def test_the_vocabulary_control_has_no_overlap_under_a_comparator_that_says_so() -> None:
    report = overlap.compare(_collection(VOCABULARY), FakeComparator({}))
    assert report.overlaps == [] and report.examined


class WordOverlap:
    """A strawman comparator: Jaccard similarity of the duties' words. It
    exists to show the controls separate MEANING from WORDING."""

    source = "word overlap (test strawman)"

    def compare(self, a: overlap.Duty, b: overlap.Duty) -> str:
        words = [set(re.findall(r"[a-z]+", d.text.lower())) - {"the", "a", "of", "to", "and", "any", "each"} for d in (a, b)]
        jaccard = len(words[0] & words[1]) / len(words[0] | words[1])
        return SAME if jaccard >= 0.25 else DIFFERENT


def test_a_word_overlap_comparator_gets_both_controls_wrong() -> None:
    """The controls are designed so wording cannot pass them: the strawman
    misses the paraphrase AND flags the shared vocabulary. A comparator that
    passes both must be reading meaning."""
    missed = overlap.compare(_collection(PARAPHRASE), WordOverlap())
    flagged = overlap.compare(_collection(VOCABULARY), WordOverlap())
    assert ("shared", "alpha.always-1", "beta.always-1") not in overlap.ids(missed.overlaps)
    assert ("shared", "delta.always-1", "gamma.always-1") in overlap.ids(flagged.overlaps)


# ---------------------------------------------------------------- replicates and UNKNOWN


def test_replicates_that_disagree_make_the_pair_unknown() -> None:
    fake = FakeComparator({("alpha.always-1", "beta.always-1"): [SAME, DIFFERENT, SAME]})
    report = overlap.compare(_collection(PARAPHRASE), fake, replicates=3)
    assert report.overlaps == []
    assert [(p.a.clause_id, p.b.clause_id, p.answers) for p in report.unknown_pairs] == [
        ("alpha.always-1", "beta.always-1", (SAME, DIFFERENT, SAME))]


def test_an_unknown_or_invalid_answer_is_never_a_verdict() -> None:
    for answer in (UNKNOWN, "maybe"):
        fake = FakeComparator({("alpha.always-1", "beta.always-1"): [answer]})
        report = overlap.compare(_collection(PARAPHRASE), fake, replicates=1)
        assert report.overlaps == [] and len(report.unknown_pairs) == 1


def test_a_comparator_that_raises_answered_nothing() -> None:
    class Broken:
        source = "broken"

        def compare(self, a: overlap.Duty, b: overlap.Duty) -> str:
            raise RuntimeError("model down")

    report = overlap.compare(_collection(PARAPHRASE), Broken(), replicates=2)
    assert report.overlaps == [] and len(report.unknown_pairs) == len(report.pairs) > 0


def test_replicates_must_be_positive() -> None:
    with pytest.raises(ValueError):
        overlap.compare(_collection(PARAPHRASE), FakeComparator({}), replicates=0)


# ---------------------------------------------------------------- shared, shadowed, orphan


def _observed(tmp_path: Path, extra_beta: str = "") -> Path:
    """alpha claims a duty; beta is only OBSERVED doing it (charter draft's
    observed-not-stated column), plus one more observed duty."""
    shutil.copytree(PARAPHRASE, tmp_path / "c")
    beta = tmp_path / "c/beta/CHARTER.md"
    text = beta.read_text(encoding="utf-8")
    text = text.replace('    - id: beta.always-1\n', '    - id: beta.always-1\n      column: observed-not-stated\n', 1)
    text = text.replace('    - id: beta.always-2\n', '    - id: beta.always-2\n      column: observed-not-stated\n', 1)
    beta.write_text(text + extra_beta, encoding="utf-8")
    return tmp_path / "c"


def test_an_observed_only_duty_another_charter_claims_is_shadowed(tmp_path: Path) -> None:
    fake = FakeComparator({("alpha.always-1", "beta.always-1"): [SAME]})
    report = overlap.compare(_collection(_observed(tmp_path)), fake)
    assert ("shadowed", "alpha.always-1", "beta.always-1") in overlap.ids(report.overlaps)


def test_an_observed_duty_matched_by_nothing_is_an_orphan(tmp_path: Path) -> None:
    fake = FakeComparator({("alpha.always-1", "beta.always-1"): [SAME]})
    report = overlap.compare(_collection(_observed(tmp_path)), fake)
    assert ("orphan", "beta.always-2") in overlap.ids(report.overlaps)


def test_one_unknown_pair_leaves_an_orphan_unknown(tmp_path: Path) -> None:
    fake = FakeComparator({("alpha.always-2", "beta.always-2"): [SAME, DIFFERENT]})
    report = overlap.compare(_collection(_observed(tmp_path)), fake, replicates=2)
    assert ("orphan", "beta.always-2") not in overlap.ids(report.overlaps)
    assert [d.clause_id for d in report.unknown_orphans] == ["beta.always-2"]


def test_an_observed_duty_with_nothing_to_compare_is_not_an_orphan(tmp_path: Path) -> None:
    shutil.copytree(PARAPHRASE / "beta", tmp_path / "c/beta")
    beta = tmp_path / "c/beta/CHARTER.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace(
        "    - id: beta.always-2\n", "    - id: beta.always-2\n      column: observed-not-stated\n", 1), encoding="utf-8")
    report = overlap.compare(_collection(tmp_path / "c"), FakeComparator({}))
    assert ("orphan", "beta.always-2") not in overlap.ids(report.overlaps)
    assert [d.clause_id for d in report.unknown_orphans] == ["beta.always-2"]


def test_the_same_clause_id_is_left_to_duty_single_owner(tmp_path: Path) -> None:
    shutil.copytree(PARAPHRASE, tmp_path / "c")
    beta = tmp_path / "c/beta/CHARTER.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace("id: beta.always-1", "id: alpha.always-1"), encoding="utf-8")
    calls: list[tuple[str, str]] = []

    class Spy:
        source = "spy"

        def compare(self, a: overlap.Duty, b: overlap.Duty) -> str:
            calls.append((a.clause_id, b.clause_id))
            return DIFFERENT

    report = overlap.compare(_collection(tmp_path / "c"), Spy(), replicates=1)
    assert ("alpha.always-1", "alpha.always-1") not in calls
    assert len(report.skipped_same_id) == 1


def test_duties_within_one_charter_are_never_compared() -> None:
    report = overlap.compare(_collection(PARAPHRASE), FakeComparator({}), replicates=1)
    assert all(p.a.contract != p.b.contract for p in report.pairs) and len(report.pairs) == 4


# ---------------------------------------------------------------- the command


def test_no_comparator_is_not_examined_with_no_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["charter", "overlap", str(PARAPHRASE)]) == overlap.EXIT_NOT_EXAMINED == 3
    captured = capsys.readouterr()
    assert "not examined" in captured.out and "shared 0" not in captured.out and "shared 0" not in captured.err


def test_recorded_verdicts_drive_the_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    verdicts = tmp_path / "verdicts.txt"
    verdicts.write_text("alpha.always-1 beta.always-1: same\n" * 3 + "# everything else: different\n"
                        + "".join(f"{a} {b}: different\n" * 3 for a, b in (
                            ("alpha.always-1", "beta.always-2"), ("alpha.always-2", "beta.always-1"),
                            ("alpha.always-2", "beta.always-2"))), encoding="utf-8")
    assert cli.main(["charter", "overlap", str(PARAPHRASE), "--verdicts", str(verdicts)]) == overlap.EXIT_REPORTED
    out = capsys.readouterr().out
    assert "## shared (1)" in out and "recorded verdicts: verdicts.txt" in out and "```mermaid" in out


def test_a_short_recording_is_unknown_not_a_verdict(tmp_path: Path) -> None:
    comparator = overlap.RecordedComparator("alpha.always-1 beta.always-1: same\n", "rec")
    report = overlap.compare(_collection(PARAPHRASE), comparator, replicates=3)
    assert report.overlaps == [] and len(report.unknown_pairs) == len(report.pairs)


@pytest.mark.parametrize("text", ["alpha.always-1 beta.always-1 same\n", "a a: same\n", "a b: maybe\n"])
def test_an_unreadable_verdicts_file_is_refused(text: str) -> None:
    with pytest.raises(overlap.VerdictsError):
        overlap.RecordedComparator(text, "rec")


def test_the_command_refuses_bad_input(tmp_path: Path) -> None:
    assert cli.main(["charter", "overlap", str(tmp_path / "absent")]) == overlap.EXIT_USAGE
    assert cli.main(["charter", "overlap", str(PARAPHRASE), "--replicates", "0"]) == overlap.EXIT_USAGE
    (tmp_path / "empty").mkdir()
    assert cli.main(["charter", "overlap", str(tmp_path / "empty")]) == overlap.EXIT_NOT_EXAMINED
    out = tmp_path / "report.md"
    out.write_text("kept\n", encoding="utf-8")
    assert cli.main(["charter", "overlap", str(PARAPHRASE), "--out", str(out)]) == overlap.EXIT_USAGE
    assert out.read_text(encoding="utf-8") == "kept\n"


def test_every_overlap_is_framed_as_a_proposal() -> None:
    fake = FakeComparator({("alpha.always-1", "beta.always-1"): [SAME]})
    text = overlap.render(overlap.compare(_collection(PARAPHRASE), fake))
    assert "proposal for the owner" in text and "never a finding" in text
