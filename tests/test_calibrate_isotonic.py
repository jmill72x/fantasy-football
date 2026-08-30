from sffl.calibrate import _pava, build_curves_isotonic


def test_pava_leaves_an_already_monotone_sequence_alone():
    assert _pava([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]) == [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]


def test_pava_pools_a_violation_into_its_average():
    got = _pava([(1.0, 3.0), (2.0, 1.0)])
    assert [y for _x, y in got] == [2.0, 2.0]


def test_pava_output_is_never_decreasing():
    import random
    rnd = random.Random(0)
    pts = sorted((float(i), rnd.uniform(0, 10)) for i in range(50))
    ys = [y for _x, y in _pava(pts)]
    assert all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1))


def test_pava_collapses_a_long_descending_run_to_a_single_average():
    # A run of more than two violators in a row must all pool together into
    # ONE block, not merge pairwise and stop early.
    pts = [(1.0, 5.0), (2.0, 4.0), (3.0, 3.0), (4.0, 2.0), (5.0, 1.0)]
    got = _pava(pts)
    xs = [x for x, _y in got]
    ys = [y for _x, y in got]
    assert xs == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert ys == [3.0, 3.0, 3.0, 3.0, 3.0]


def test_pava_mixed_case_matches_known_isotonic_regression_result():
    # Classic isotonic-regression textbook example: y = [1, 5, 2, 4, 3] fits to
    # [1, 3.5, 3.5, 3.5, 3.5] under pool-adjacent-violators with equal weights.
    pts = [(1.0, 1.0), (2.0, 5.0), (3.0, 2.0), (4.0, 4.0), (5.0, 3.0)]
    got = _pava(pts)
    ys = [y for _x, y in got]
    assert ys == [1.0, 3.5, 3.5, 3.5, 3.5]
    xs = [x for x, _y in got]
    assert xs == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_isotonic_curves_are_monotone_for_every_stat():
    import os
    import pytest
    if not os.path.isdir("data/weekly/2025"):
        pytest.skip("weekly data not present (gitignored)")
    from sffl.league import load_league
    from sffl.weekly import load_weekly
    lg = load_league("leagues/sffl/2026.yaml")
    lines = []
    for pos in ("DST", "K", "RB", "TQB", "WR"):
        p = "data/weekly/2025/%s.csv" % pos
        if os.path.exists(p):
            lines.extend(load_weekly(p))
    for stat, curve in build_curves_isotonic(lg, lines).items():
        ys = [y for _x, y in curve]
        assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1)), stat


def test_build_curves_isotonic_same_shape_as_build_curves():
    # Same input, same set of x's (means) - only the y's may change.
    from sffl.calibrate import build_curves
    from sffl.league import load_league
    from sffl.weekly import WeeklyLine

    lg = load_league("leagues/sffl/2026.yaml")
    lines = ([WeeklyLine(player_id="a", name="a", team="XXX", pos="RB", week=w,
                          cbs_fpts=0.0, stats={"rush_yds": v})
              for w, v in enumerate([0, 0, 80, 80], start=1)]
             + [WeeklyLine(player_id="b", name="b", team="XXX", pos="RB", week=w,
                            cbs_fpts=0.0, stats={"rush_yds": 80})
                for w in range(1, 5)])
    raw = build_curves(lg, lines)
    iso = build_curves_isotonic(lg, lines)
    assert set(raw.keys()) == set(iso.keys())
    for stat in raw:
        assert [x for x, _y in raw[stat]] == [x for x, _y in iso[stat]]
