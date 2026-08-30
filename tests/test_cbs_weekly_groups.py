"""Tests for the TQB, K and DST column maps added to sources/cbs-weekly.yaml.

Every fixture row below is verified byte-identical (apart from the owner
column, which is anonymized - this repo is public) to a real CBS capture
made 2026-08-30 (data/captures/{tqb,k,dst}.txt). The expected values in
these tests were read off that same real capture, not copied from the
implementation plan - see task-2-report.md for the corrections that were
necessary because the plan's three maps were hypotheses, not verified fact.
"""

from sffl.cbs_weekly import parse

TQB_FIXTURE = "tests/fixtures/cbs_weekly_tqb.txt"
K_FIXTURE = "tests/fixtures/cbs_weekly_k.txt"
DST_FIXTURE = "tests/fixtures/cbs_weekly_dst.txt"


def by_name(rows):
    return dict((r.name, r) for r in rows)


# --------------------------------------------------------------------------
# TQB
# --------------------------------------------------------------------------

def test_tqb_every_line_parses():
    rows = parse(TQB_FIXTURE, group="TQB", week=1)
    assert len(rows) == 4


def test_tqb_stats_land_in_the_right_slots():
    # "Player" on this page is the Chargers' aggregate Team-QB line, not an
    # individual - real capture, 2026-08-30.
    r = by_name(parse(TQB_FIXTURE, group="TQB", week=1))["Chargers"]
    assert r.pos == "TQB" and r.team == "LAC"
    assert r.stats["pass_cmp"] == 23.8
    assert r.stats["pass_yds"] == 265.1
    assert r.stats["pass_td"] == 2.3
    assert r.stats["pass_int"] == 0.7
    assert r.stats["rush_yds"] == 35.0
    assert r.stats["rush_td"] == 0.2
    assert r.stats["fum_lost"] == 0.1
    # Sanity per the brief: passing yards in the hundreds, TDs/INTs small.
    assert 100 < r.stats["pass_yds"] < 999
    assert r.stats["pass_td"] < 10
    assert r.stats["pass_int"] < 10


def test_tqb_fpts_reconciles_with_league_scoring():
    """Cross-check required by the task: the page's own trailing FPTS should
    roughly reconcile with the league's own scoring of the mapped stats.

    Chargers row: pass_yds 265.1 -> band [251,350]=4; pass_cmp 23.8 -> band
    [20,24]=3; pass_td 2.3*5=11.5; pass_int 0.7*-1=-0.7; rush_yds 35 is
    below the 50-yard floor=0; rush_td 0.2*3=0.6 (this simplified score_game
    has no TD-length bonus, unlike the full weekly scorer). Total 18.4,
    against the page's own FPTS of 18.45 - CBS's FPTS uses a scoring config
    this project does not control, so exact equality isn't expected, but
    this close a match confirms the columns are aligned, not merely
    plausible.
    """
    from sffl.scoring import band_points
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    r = by_name(parse(TQB_FIXTURE, group="TQB", week=1))["Chargers"]
    total = (band_points(lg.bands["pass_yds"], r.stats["pass_yds"])
             + band_points(lg.bands["pass_cmp"], r.stats["pass_cmp"])
             + r.stats["pass_td"] * lg.points["pass_td"]
             + r.stats["pass_int"] * lg.points["pass_int"]
             + band_points(lg.bands["rush_yds"], r.stats["rush_yds"])
             + r.stats["rush_td"] * lg.points["rush_td"])
    assert abs(total - 18.45) < 1.0


def test_tqb_expect_tokens_refuses_a_column_added(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tChargers TQB • LAC\tARI\t---\t7\t84\t45\tN/R\t33.7\t"
        "23.8\t265.1\t2.3\t0.7\t5.4\t35\t6.5\t0.2\t0.1\t18.45\t99\n")
    import pytest
    with pytest.raises(ValueError, match="18"):
        parse(str(bad), group="TQB", week=1)


def test_tqb_expect_tokens_refuses_a_column_removed(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tChargers TQB • LAC\tARI\t---\t7\t84\t45\tN/R\t33.7\t"
        "23.8\t265.1\t2.3\t0.7\t5.4\t35\t6.5\t0.2\t0.1\n")
    import pytest
    with pytest.raises(ValueError, match="16"):
        parse(str(bad), group="TQB", week=1)


# --------------------------------------------------------------------------
# K
# --------------------------------------------------------------------------

def test_k_every_line_parses():
    rows = parse(K_FIXTURE, group="K", week=1)
    assert len(rows) == 3


def test_k_stats_land_in_the_right_slots():
    r = by_name(parse(K_FIXTURE, group="K", week=1))["Jake Bates"]
    assert r.pos == "K" and r.team == "DET"
    assert r.stats["fg_u30"] == 0.5      # CBS 1-19 (0.0) + 20-29 (0.5)
    assert r.stats["fg_30_39"] == 0.7
    assert r.stats["fg_40_49"] == 0.7
    assert r.stats["xp_made"] == 3.5
    # The two internal total columns must not leak into the scored stats.
    assert "fg_total_made" not in r.stats
    assert "fg_total_att" not in r.stats


def test_k_distance_bands_sum_to_the_total_fg_column():
    """The strong alignment check named in the task: the five distance
    bands' FG-made values should approximately SUM to the page's own TOTAL
    FG column. Real capture: 0.0+0.5+0.7+0.7+0.3 = 2.2 against a stated
    total of 2.1 - rounding, not a misalignment."""
    row_line = None
    for line in open(K_FIXTURE):
        if "Jake Bates" in line:
            row_line = line
    rest = row_line.rstrip("\n").split("\t")[-21:]
    block = rest[-15:]
    total_fg = float(block[0])
    band_sum = float(block[2]) + float(block[4]) + float(block[6]) \
        + float(block[8]) + float(block[10])
    assert abs(band_sum - total_fg) <= 0.15


def test_k_fg_under_30_sums_1_19_and_20_29():
    r = by_name(parse(K_FIXTURE, group="K", week=1))["Jake Bates"]
    # From the real row: 1-19 FG = 0.0, 20-29 FG = 0.5.
    assert r.stats["fg_u30"] == 0.0 + 0.5


def test_k_a_nonzero_50_plus_scores_as_fg_50_59_and_fg_60_is_absent():
    """Pins the repo owner's decision: CBS's single 50+ column scores as
    fg_50_59 (an under-statement of a 60+ yard kick), never as fg_60_plus.
    Jake Bates's real capture row has a non-zero 50+ value (0.3)."""
    r = by_name(parse(K_FIXTURE, group="K", week=1))["Jake Bates"]
    assert r.stats["fg_50_59"] == 0.3
    assert r.stats["fg_50_59"] != 0
    assert r.stats.get("fg_60", 0) == 0
    assert r.stats.get("fg_60_plus", 0) == 0


def test_k_fg_missed_is_derived_from_the_two_total_columns():
    """fg_missed = total ATT - total FG. Jake Bates: 2.6 - 2.1 = 0.5."""
    r = by_name(parse(K_FIXTURE, group="K", week=1))["Jake Bates"]
    assert r.stats["fg_missed"] == 0.5


def test_k_expect_tokens_refuses_a_column_added(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tJake Bates K • DET\tNO\t21\t6\t84\t75\t12\t2.1\t2.6\t"
        "0.0\t0.0\t0.5\t0.5\t0.7\t0.7\t0.7\t0.8\t0.3\t0.7\t3.5\t3.6\t5.60\t9\n")
    import pytest
    with pytest.raises(ValueError, match="22"):
        parse(str(bad), group="K", week=1)


def test_k_expect_tokens_refuses_a_column_removed(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tJake Bates K • DET\tNO\t21\t6\t84\t75\t12\t2.1\t2.6\t"
        "0.0\t0.0\t0.5\t0.5\t0.7\t0.7\t0.7\t0.8\t0.3\t0.7\t3.5\t3.6\n")
    import pytest
    with pytest.raises(ValueError, match="20"):
        parse(str(bad), group="K", week=1)


# --------------------------------------------------------------------------
# DST
# --------------------------------------------------------------------------

def test_dst_every_line_parses():
    rows = parse(DST_FIXTURE, group="DST", week=1)
    assert len(rows) == 3


def test_dst_stats_land_in_the_right_slots():
    r = by_name(parse(DST_FIXTURE, group="DST", week=1))["Broncos"]
    assert r.pos == "DST" and r.team == "DEN"
    assert r.stats["def_sack"] == 4.4
    assert r.stats["def_fum_rec"] == 0.3
    assert r.stats["def_int"] == 0.8
    assert r.stats["def_td"] == 0.1
    assert r.stats["def_safety"] == 0.0
    assert r.stats["def_ya"] == 248.0
    assert r.stats["def_pa"] == 19.6
    # Sanity per the brief: yards-against in the hundreds, points-against
    # in the tens.
    assert 100 < r.stats["def_ya"] < 999
    assert 0 < r.stats["def_pa"] < 99


def test_dst_dwn_column_is_unidentified_and_not_scored():
    """DWN could not be identified with confidence (see the profile
    comment and task-2-report.md for the week-1-vs-week-2 comparison) and
    must not have been guessed into a scoring key."""
    r = by_name(parse(DST_FIXTURE, group="DST", week=1))["Broncos"]
    assert "dwn" not in r.stats
    assert "DWN" not in r.stats
    # 0.7 is the real DWN value for this row - it must not have landed
    # under any other key either.
    assert 0.7 not in r.stats.values()


def test_dst_expect_tokens_refuses_a_column_added(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tBroncos DST • DEN\t@KC\t12\t10\t100\t92\t4.4\t0.3\t"
        "0.8\t0.7\t0.1\t0.0\t248.00\t248\t19.60\t19.6\t9.70\t3\n")
    import pytest
    with pytest.raises(ValueError, match="17"):
        parse(str(bad), group="DST", week=1)


def test_dst_expect_tokens_refuses_a_column_removed(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "\tW (9/16)\tBroncos DST • DEN\t@KC\t12\t10\t100\t92\t4.4\t0.3\t"
        "0.8\t0.7\t0.1\t0.0\t248.00\t248\t19.60\t19.6\n")
    import pytest
    with pytest.raises(ValueError, match="15"):
        parse(str(bad), group="DST", week=1)
