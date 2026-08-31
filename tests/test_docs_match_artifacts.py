"""Documentation drift is a defect class in this repo, so it gets a test.

CLAUDE.md mandates NEXT.md as the first thing any session reads: "it carries
the current state, what to work on next, and the facts you must not
re-derive." A wrong number there is not cosmetic - it is acted upon. This
project has already lost real time to a fabricated `top10_bias` of -0.25 that
sat in two docstrings and a test until somebody finally measured it at +5.10,
and to a five-stat isotonic bundle that stayed written down as five for hours
after `pass_yds` was reverted out of it.

Prose cannot be checked mechanically, and most of NEXT.md is prose that
deliberately preserves superseded numbers as a record of what was tried. So
NEXT.md carries ONE machine-checked block of current-state facts, delimited by
`<!-- BEGIN/END MACHINE-CHECKED FACTS -->`, and this module asserts every line
of it against the artifact that owns that fact:

    market coefficients + diagnostics -> market/2026.yaml
    per-stat build method             -> calibration/2025.provenance.yaml
    dataset player/week counts        -> src/sffl/render/intel.py's constants
                                         (themselves pinned to calibration/
                                         2025.yaml's header by
                                         test_render_intel.py)
    weekly projection groups          -> sources/cbs-weekly.yaml
    full suite count                  -> collected test count, this run

The test reads the DOC and compares to the ARTIFACT. It never reads the doc to
decide what is correct: every expectation comes from the artifact, so the only
way to make this pass is to make the doc true.
"""

import os
import re

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_BEGIN = "<!-- BEGIN MACHINE-CHECKED FACTS -->"
_END = "<!-- END MACHINE-CHECKED FACTS -->"


def _load(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return yaml.safe_load(fh)


def _facts():
    """Parse NEXT.md's machine-checked block into {key: [backticked values]}.

    Deliberately strict. A missing block, a duplicated key, or a line that
    does not parse is a failure, not a skip - the whole point is that this
    block cannot quietly stop being checked.
    """
    with open(os.path.join(ROOT, "NEXT.md")) as fh:
        text = fh.read()
    assert text.count(_BEGIN) == 1, (
        "NEXT.md must contain exactly one %s marker" % _BEGIN)
    assert text.count(_END) == 1, (
        "NEXT.md must contain exactly one %s marker" % _END)
    block = text.split(_BEGIN, 1)[1].split(_END, 1)[0]

    facts = {}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        key, _, rest = line[2:].partition(":")
        key = key.strip()
        values = re.findall(r"`([^`]+)`", rest)
        assert values, (
            "NEXT.md machine-checked line %r has no backticked value" % line)
        assert key not in facts, "duplicate key %r in NEXT.md fact block" % key
        facts[key] = values
    assert facts, "NEXT.md's machine-checked block parsed to nothing"
    return facts


def test_next_md_quotes_the_committed_market_coefficients():
    """The exact failure that motivated this file: a doc quoting a superseded
    (a, b). NEXT.md's history sections still quote the five-stat bundle's
    coefficients on purpose, clearly marked historical; the fact block must
    carry what is actually committed."""
    facts = _facts()
    market = _load("market/2026.yaml")

    assert float(facts["market_curve_a"][0]) == market["curve"]["a"]
    assert float(facts["market_curve_b"][0]) == market["curve"]["b"]
    # Compared as strings too, so a doc quoting a truncated coefficient
    # (2.0284959942) cannot pass on float equality after rounding.
    assert facts["market_curve_a"][0] == repr(market["curve"]["a"])
    assert facts["market_curve_b"][0] == repr(market["curve"]["b"])

    diag = market["diagnostics"]
    assert float(facts["market_mae"][0]) == diag["mae"]
    assert float(facts["market_top10_mae"][0]) == diag["top10_mae"]
    assert float(facts["market_top10_bias"][0]) == diag["top10_bias"]


def test_the_top10_bias_is_positive_and_is_not_the_fabricated_number():
    """A characterization of the specific historical defect. -0.25 was never
    measured; it was invented and then trusted. If a future refit genuinely
    produces a negative bias this test SHOULD be updated - but only alongside
    the measurement that produced it."""
    market = _load("market/2026.yaml")
    assert market["diagnostics"]["top10_bias"] > 0
    assert market["diagnostics"]["top10_bias"] != -0.25


def test_next_md_lists_the_right_stats_under_each_build_method():
    """The five-vs-four defect. Method-per-stat lives in the provenance file;
    NEXT.md must agree with it, exactly, both ways."""
    facts = _facts()
    prov = _load("calibration/2025.provenance.yaml")

    by_method = {}
    for stat, entry in prov.items():
        by_method.setdefault(entry["method"], set()).add(stat)

    assert set(facts["isotonic_stats"]) == by_method["build_curves_isotonic"], (
        "NEXT.md's isotonic_stats disagrees with "
        "calibration/2025.provenance.yaml")
    assert set(facts["interpolated_stats"]) == by_method["build_curves"], (
        "NEXT.md's interpolated_stats disagrees with "
        "calibration/2025.provenance.yaml")
    # And no stat may be missing from the doc entirely.
    assert (set(facts["isotonic_stats"]) | set(facts["interpolated_stats"])
            == set(prov)), "NEXT.md's fact block omits a banded stat"


def test_next_md_agrees_with_the_provenance_on_which_dataset_built_what():
    """Method and dataset are separate fields and have drifted apart in prose
    before ("isotonic on the build set only" is a sentence that has been
    written here). Pin the pairing."""
    prov = _load("calibration/2025.provenance.yaml")
    for stat, entry in prov.items():
        if entry["method"] == "build_curves_isotonic":
            assert entry["dataset"] == "build_set_plus_held_back", stat
        else:
            assert entry["dataset"] == "build_set_only", stat


def test_next_md_dataset_counts_match_the_printed_intel_sheet():
    """127/2339 and 46/777 appear in NEXT.md, in calibration/2025.yaml's
    header comment, and on the printed Key & Intel sheet. test_render_intel
    already ties the sheet to the curve file's header; this ties NEXT.md to
    the same constants, closing the triangle."""
    from sffl.render import intel

    facts = _facts()
    assert facts["isotonic_dataset"] == [
        str(intel.CALIBRATION_PLAYERS_ISOTONIC),
        str(intel.CALIBRATION_PLAYER_WEEKS_ISOTONIC)]
    assert facts["interpolated_dataset"] == [
        str(intel.CALIBRATION_PLAYERS_INTERPOLATED),
        str(intel.CALIBRATION_PLAYER_WEEKS_INTERPOLATED)]


def test_next_md_lists_every_weekly_projection_group():
    """NEXT.md asserted "only the RB-WR-TE group is defined" for a full day
    after TQB/K/DST were wired up and merged into the same file."""
    facts = _facts()
    groups = _load("sources/cbs-weekly.yaml")["groups"]
    assert set(facts["weekly_groups"]) == set(groups), (
        "NEXT.md's weekly_groups disagrees with sources/cbs-weekly.yaml")


def test_every_group_sets_expect_tokens():
    """Documented in NEXT.md and in the plan as the column-shift guard, and
    opt-in rather than schema-required - so a group can be added without it.
    The docs say every group must set it; assert that they do."""
    groups = _load("sources/cbs-weekly.yaml")["groups"]
    missing = sorted(g for g, cfg in groups.items()
                     if not cfg.get("expect_tokens"))
    assert not missing, (
        "groups without the expect_tokens layout guard: %s" % missing)


def test_next_md_quotes_the_real_full_suite_count(request):
    """The count in NEXT.md was 654, then 770, while the suite was 773.

    Compared against the number of tests COLLECTED in this run, which equals
    the passing count whenever the suite is green. Skipped on a filtered run
    (-k / a single file), where the collected count legitimately differs.
    """
    session = request.session
    collected = session.testscollected
    if collected is None or collected < 100:
        pytest.skip("filtered run - collected %s, not the full suite"
                    % collected)
    facts = _facts()
    assert int(facts["full_suite"][0]) == collected, (
        "NEXT.md says the full suite is %s tests; this run collected %d. "
        "Update the machine-checked block in NEXT.md."
        % (facts["full_suite"][0], collected))
