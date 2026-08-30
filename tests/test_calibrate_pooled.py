from sffl.calibrate import _pooled_residuals, _stat_grid, build_curves_pooled


def _line(pid, pos, week, **stats):
    from sffl.weekly import WeeklyLine
    return WeeklyLine(player_id=pid, name=pid, team="XXX", pos=pos, week=week,
                       cbs_fpts=0.0, stats=dict(stats))


def test_residuals_are_centred_on_one_for_a_stable_player():
    lines = [_line("p", "RB", w, rush_yds=100.0) for w in range(1, 6)]
    rs = _pooled_residuals(lines, "rush_yds")
    assert all(abs(r - 1.0) < 1e-9 for r in rs)


def test_residuals_pool_across_players_regardless_of_scale():
    # A player averaging 20 and one averaging 200, each varying +/-50%,
    # must contribute the SAME residuals - that is what makes pooling valid.
    a = [_line("a", "RB", 1, rush_yds=10.0), _line("a", "RB", 2, rush_yds=30.0)]
    b = [_line("b", "RB", 1, rush_yds=100.0), _line("b", "RB", 2, rush_yds=300.0)]
    assert sorted(_pooled_residuals(a, "rush_yds")) == sorted(_pooled_residuals(b, "rush_yds"))


def test_pooled_curve_is_non_decreasing():
    lines = []
    for i in range(1, 11):
        for w in range(1, 6):
            lines.append(_line("p%d" % i, "RB", w, rush_yds=10.0 * i * (0.5 + 0.2 * w)))
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    curve = build_curves_pooled(lg, lines)["rush_yds"]
    ys = [y for _x, y in curve]
    assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))


def test_pooled_curve_is_non_increasing_for_a_descending_stat():
    # def_pa's band table pays LESS as the raw value climbs (allowing more
    # points is worse defense - see pool._band_direction), so its pooled
    # curve must run the OPPOSITE direction from rush_yds's. This is the
    # direction that surprised review: the prior version of this test suite
    # only ever exercised an ascending stat (rush_yds above), so a
    # regression that assumed every pooled curve rises with the mean would
    # have gone uncaught.
    lines = []
    for i in range(1, 11):
        for w in range(1, 6):
            lines.append(_line("d%d" % i, "DST", w, def_pa=2.0 * i * (0.5 + 0.2 * w)))
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    curve = build_curves_pooled(lg, lines)["def_pa"]
    ys = [y for _x, y in curve]
    assert all(ys[i] >= ys[i + 1] - 1e-9 for i in range(len(ys) - 1))
    # Not a degenerate flat curve - it actually falls across the range.
    assert ys[0] > ys[-1] + 1e-9


def test_a_zero_mean_player_contributes_no_residuals():
    lines = [_line("z", "RB", w, rush_yds=0.0) for w in range(1, 6)]
    assert _pooled_residuals(lines, "rush_yds") == []


def test_a_near_zero_mean_player_is_excluded_by_the_floor():
    # Below the min_mean floor, one incidental play blows the ratio up; the
    # floor exists specifically to keep such a player's weeks out of the pool.
    lines = [_line("z", "RB", 1, rush_yds=0.05), _line("z", "RB", 2, rush_yds=3.0),
             _line("z", "RB", 3, rush_yds=0.05), _line("z", "RB", 4, rush_yds=0.05)]
    assert _pooled_residuals(lines, "rush_yds", min_mean=1.0) == []
    # But the same weeks DO contribute below that floor - min_mean is a choice,
    # not an intrinsic property of the data.
    assert _pooled_residuals(lines, "rush_yds", min_mean=1e-6) != []


def test_grid_endpoints_match_observed_mean_range():
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    means = [12.0, 40.0, 88.0]
    grid = _stat_grid(lg.bands["rush_yds"], means)
    assert grid[0] == 12.0
    assert grid[-1] == 88.0
    assert grid == sorted(grid)


def test_grid_spacing_does_not_skip_a_band():
    # rush_yds's narrowest band is 25 wide (e.g. [50, 74]); _stat_grid aims
    # for HALF that (12.5), not the full width - pin the exact value so a
    # regression that drops the halving (spacing -> 25.0) is caught, not
    # just a regression that exceeds the full band width.
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    means = [0.0, 300.0]
    grid = _stat_grid(lg.bands["rush_yds"], means)
    gaps = [grid[i + 1] - grid[i] for i in range(len(grid) - 1)]
    assert all(abs(gap - 12.5) < 1e-9 for gap in gaps)


def test_single_observed_mean_yields_a_single_point_grid():
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    grid = _stat_grid(lg.bands["rush_yds"], [42.0, 42.0])
    assert grid == [42.0]


def test_build_curves_pooled_matches_build_curves_shape():
    # Same {stat: [...]} shape, every stat present even if empty, for a
    # dataset too small to pass min_weeks.
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    lines = [_line("short", "RB", 1, rush_yds=80.0)]
    curves = build_curves_pooled(lg, lines, min_weeks=4)
    for stat in lg.bands:
        assert stat in curves
    assert curves["rush_yds"] == []


def test_pooled_expectation_matches_hand_computed_value_across_multiple_players():
    # A single steady player collapses to residual 1.0 for every week, which
    # would pass under implementations that never actually average over a
    # pool (e.g. one that just returns band(m)). Use two players so pooling
    # is load-bearing: player "a" swings between 0 and 80 around a mean of
    # 40 (residuals 0, 0, 2, 2); player "b" is steady at 80 (residuals all
    # 1). Pooled: [0, 0, 2, 2, 1, 1, 1, 1] (8 residuals).
    #
    # At m=80: values = m*r = [0, 0, 160, 160, 80, 80, 80, 80].
    # band(0)=0, band(160)=6 ([150,174]), band(80)=3 ([75,99]).
    # mean = (0+0+6+6+3+3+3+3) / 8 = 24/8 = 3.0.
    #
    # At m=40: values = [0, 0, 80, 80, 40, 40, 40, 40].
    # band(0)=0, band(80)=3, band(40)=0 (below the [50,74] floor).
    # mean = (0+0+3+3+0+0+0+0) / 8 = 6/8 = 0.75.
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    lines = ([_line("a", "RB", w, rush_yds=v) for w, v in enumerate([0.0, 0.0, 80.0, 80.0], 1)]
             + [_line("b", "RB", w, rush_yds=80.0) for w in range(1, 5)])
    curves = build_curves_pooled(lg, lines, grid=[40.0, 80.0])
    assert curves["rush_yds"] == [(40.0, 0.75), (80.0, 3.0)]


def test_explicit_grid_overrides_derived_grid():
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    lines = [_line("b", "RB", w, rush_yds=80.0) for w in range(1, 5)]
    curves = build_curves_pooled(lg, lines, grid=[10.0, 20.0, 30.0])
    assert [x for x, _y in curves["rush_yds"]] == [10.0, 20.0, 30.0]
