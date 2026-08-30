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
    # rush_yds's narrowest band is 25 wide (e.g. [50, 74]); half that is the
    # spacing _stat_grid aims for, so consecutive grid points must never be
    # more than one band width apart.
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    means = [0.0, 300.0]
    grid = _stat_grid(lg.bands["rush_yds"], means)
    gaps = [grid[i + 1] - grid[i] for i in range(len(grid) - 1)]
    assert all(gap <= 25.0 + 1e-9 for gap in gaps)


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


def test_steady_player_matches_the_naive_approximation():
    # Every week identical -> every residual is 1.0 -> E[band(m)] == band(m).
    from sffl.league import load_league
    from sffl.calibrate import expected_points
    lg = load_league("leagues/sffl/2026.yaml")
    lines = [_line("b", "RB", w, rush_yds=80.0) for w in range(1, 5)]
    curves = build_curves_pooled(lg, lines)
    assert expected_points(curves["rush_yds"], 80.0) == 3.0


def test_explicit_grid_overrides_derived_grid():
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    lines = [_line("b", "RB", w, rush_yds=80.0) for w in range(1, 5)]
    curves = build_curves_pooled(lg, lines, grid=[10.0, 20.0, 30.0])
    assert [x for x, _y in curves["rush_yds"]] == [10.0, 20.0, 30.0]
