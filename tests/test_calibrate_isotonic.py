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
    # Direction-aware: def_pa/def_ya's band tables pay LESS as the raw value
    # climbs (see pool._band_direction), so their curves must come out
    # non-increasing, not non-decreasing like the five ascending stats. Before
    # the direction-aware fix, _pava forced every stat non-decreasing
    # regardless of its table's own direction; that silently collapsed
    # def_pa/def_ya to a flat constant, which happens to also satisfy "<=
    # every step" - so this assertion did not catch the bug until it checked
    # each stat's OWN direction instead of assuming one direction for all.
    import os
    import pytest
    if not os.path.isdir("data/weekly/2025"):
        pytest.skip("weekly data not present (gitignored)")
    from sffl.league import load_league
    from sffl.pool import _band_direction
    from sffl.weekly import load_weekly
    lg = load_league("leagues/sffl/2026.yaml")
    lines = []
    for pos in ("DST", "K", "RB", "TQB", "WR"):
        p = "data/weekly/2025/%s.csv" % pos
        if os.path.exists(p):
            lines.extend(load_weekly(p))
    for stat, curve in build_curves_isotonic(lg, lines).items():
        ys = [y for _x, y in curve]
        direction = _band_direction(lg.bands[stat])
        if direction > 0:
            assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1)), stat
        else:
            assert all(ys[i] >= ys[i + 1] - 1e-9 for i in range(len(ys) - 1)), stat


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


def test_pava_monotone_direction_minus1_gives_descending_fit_not_flat():
    # THE BUG, reproduced directly on _pava_monotone: a genuinely descending
    # series (one interior violation, mirroring a noisy player-season) run
    # through plain `_pava` (always non-decreasing) pools the ENTIRE run into
    # a single flat block - exactly what collapsed the real def_pa/def_ya
    # curves to one constant. `_pava_monotone(pts, -1)` must instead produce
    # a properly descending fit, pooling only the actual violation.
    from sffl.calibrate import _pava_monotone

    pts = [(1.0, 6.0), (2.0, 5.0), (3.0, 5.5), (4.0, 3.0), (5.0, 2.0)]

    # The old, direction-blind behaviour: forcing non-decreasing on a
    # descending series flattens it completely.
    old_buggy = _pava(pts)
    assert len(set(y for _x, y in old_buggy)) == 1

    got = _pava_monotone(pts, -1)
    ys = [y for _x, y in got]
    xs = [x for x, _y in got]
    assert xs == [1.0, 2.0, 3.0, 4.0, 5.0]
    # Properly descending (non-increasing), not flat.
    assert all(ys[i] >= ys[i + 1] - 1e-12 for i in range(len(ys) - 1))
    assert len(set(ys)) > 1
    # Only the genuine violation (5.0 followed by 5.5) pools; 6.0 and the
    # tail (3.0, 2.0) are untouched.
    assert ys == [6.0, 5.25, 5.25, 3.0, 2.0]


def test_pava_monotone_direction_plus1_matches_plain_pava():
    # direction=+1 must be a pure pass-through to the untouched `_pava` -
    # ascending stats (pass_cmp, pass_yds, rec_ct, rec_yds, rush_yds) are
    # unaffected by this fix.
    from sffl.calibrate import _pava_monotone

    pts = [(1.0, 1.0), (2.0, 5.0), (3.0, 2.0), (4.0, 4.0), (5.0, 3.0)]
    assert _pava_monotone(pts, 1) == _pava(pts)


def test_build_curves_isotonic_ascending_stat_pinned_to_current_behaviour():
    # Pin: an ascending stat's curve is byte-for-byte what build_curves_isotonic
    # produced before this fix (direction-awareness must be a no-op for it).
    from sffl.league import load_league
    from sffl.weekly import WeeklyLine

    lg = load_league("leagues/sffl/2026.yaml")
    lines = ([WeeklyLine(player_id="a", name="a", team="XXX", pos="RB", week=w,
                          cbs_fpts=0.0, stats={"rush_yds": v})
              for w, v in enumerate([10, 40, 30, 80, 20, 90], start=1)]
             + [WeeklyLine(player_id="b", name="b", team="XXX", pos="RB", week=w,
                            cbs_fpts=0.0, stats={"rush_yds": v})
                for w, v in enumerate([5, 5, 60, 60, 60, 5], start=1)])
    got = build_curves_isotonic(lg, lines)["rush_yds"]
    # Known-good pin, computed by running plain (pre-fix) _pava on the same
    # raw build_curves() output for rush_yds.
    from sffl.calibrate import build_curves
    expected = _pava(build_curves(lg, lines)["rush_yds"])
    assert got == expected
    ys = [y for _x, y in got]
    assert all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1))


def test_real_def_pa_and_def_ya_no_longer_collapse_to_a_constant():
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
    held_back_dir = "data/weekly/2025/_held_back"
    for pos in ("DST", "TQB", "WR", "TE"):
        p = os.path.join(held_back_dir, "%s.full.csv" % pos)
        if os.path.exists(p):
            lines.extend(load_weekly(p))

    curves = build_curves_isotonic(lg, lines)
    for stat in ("def_pa", "def_ya"):
        ys = [y for _x, y in curves[stat]]
        assert len(ys) > 1, stat
        distinct = set(round(y, 9) for y in ys)
        assert len(distinct) > 1, "{0} collapsed to a constant: {1}".format(stat, distinct)
        # And it must be properly descending, not just "not flat".
        assert all(ys[i] >= ys[i + 1] - 1e-9 for i in range(len(ys) - 1)), stat
