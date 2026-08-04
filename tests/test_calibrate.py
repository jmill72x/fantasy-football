import pytest

from sffl.calibrate import build_curves, expected_points, save_curves, load_curves
from sffl.league import load_league
from sffl.weekly import WeeklyLine

LG = load_league("leagues/sffl/2026.yaml")


def line(pid, week, **stats):
    return WeeklyLine(player_id=pid, name=pid, team="XXX", pos="RB",
                      week=week, cbs_fpts=0.0, stats=dict(stats))


def test_curve_captures_value_the_approximation_throws_away():
    # A player averaging 40 rushing yards per game: two weeks at 0, two at 80.
    # band(40) == 0, so the naive approximation scores him ZERO.
    # But band(80) == 3 in two of four weeks, so E[band] == 1.5.
    lines = [line("a", 1, rush_yds=0), line("a", 2, rush_yds=0),
             line("a", 3, rush_yds=80), line("a", 4, rush_yds=80)]
    curves = build_curves(LG, lines)
    got = expected_points(curves["rush_yds"], 40.0)
    assert got == pytest.approx(1.5)


def test_steady_player_matches_the_naive_approximation():
    # Every week identical, so averaging loses nothing and E[band] == band(mean).
    lines = [line("b", w, rush_yds=80) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    assert expected_points(curves["rush_yds"], 80.0) == pytest.approx(3.0)


def test_interpolates_between_observed_means():
    lines = ([line("a", w, rush_yds=60) for w in range(1, 5)]
             + [line("b", w, rush_yds=100) for w in range(1, 5)])
    curves = build_curves(LG, lines)
    lo = expected_points(curves["rush_yds"], 60.0)
    hi = expected_points(curves["rush_yds"], 100.0)
    mid = expected_points(curves["rush_yds"], 80.0)
    assert lo < mid < hi


def test_clamps_outside_the_observed_range():
    lines = [line("a", w, rush_yds=60) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    assert expected_points(curves["rush_yds"], 0.0) == pytest.approx(2.0)
    assert expected_points(curves["rush_yds"], 9999.0) == pytest.approx(2.0)


def test_round_trips_through_yaml(tmp_path):
    lines = [line("a", w, rush_yds=80) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    p = str(tmp_path / "curves.yaml")
    save_curves(curves, p)
    back = load_curves(p)
    assert expected_points(back["rush_yds"], 80.0) == pytest.approx(3.0)


def test_players_with_too_few_weeks_are_excluded():
    lines = [line("short", 1, rush_yds=80)]
    curves = build_curves(LG, lines, min_weeks=4)
    assert curves.get("rush_yds", []) == []


def test_mixed_position_pool_excludes_off_position_players():
    # Mixed-position pool: RB lines with rush_yds and DST lines with def_pa.
    # The defense curve should NOT contain a (0.0, 6.0) point from RB players'
    # default stats, and should only contain data from DST players.
    rb_lines = [line("rb1", w, rush_yds=80) for w in range(1, 5)]
    dst_lines = [
        WeeklyLine(player_id="dst1", name="dst1", team="XXX", pos="DST",
                   week=1, cbs_fpts=0.0, stats={"def_pa": 20}),
        WeeklyLine(player_id="dst1", name="dst1", team="XXX", pos="DST",
                   week=2, cbs_fpts=0.0, stats={"def_pa": 25}),
        WeeklyLine(player_id="dst1", name="dst1", team="XXX", pos="DST",
                   week=3, cbs_fpts=0.0, stats={"def_pa": 30}),
        WeeklyLine(player_id="dst1", name="dst1", team="XXX", pos="DST",
                   week=4, cbs_fpts=0.0, stats={"def_pa": 20}),
    ]
    curves = build_curves(LG, rb_lines + dst_lines)
    # The def_pa curve should have data only from DST.
    assert len(curves["def_pa"]) > 0
    # Verify no (0.0, 6.0) point exists (the false RB anchor).
    for mean, expected in curves["def_pa"]:
        assert not (mean == pytest.approx(0.0) and expected == pytest.approx(6.0))


def test_unknown_stat_in_bands_raises_error():
    # If lg.bands contains a stat not in STAT_POSITIONS, raise ValueError.
    from sffl.calibrate import STAT_POSITIONS
    from unittest.mock import Mock

    # Create a mock league with an unknown stat.
    bad_lg = Mock()
    bad_lg.bands = {"rush_yds": [[0, 10, 1]], "unknown_stat": [[0, 100, 5]]}

    lines = [line("a", w, rush_yds=80) for w in range(1, 5)]
    with pytest.raises(ValueError) as exc_info:
        build_curves(bad_lg, lines)
    assert "unknown_stat" in str(exc_info.value)
