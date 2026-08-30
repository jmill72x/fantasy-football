import pytest

from sffl.calibrate_eval import cross_validate, player_folds, realized
from sffl.league import load_league
from sffl.weekly import load_weekly, WeeklyLine


def _line(pid, pos, week, **stats):
    # WeeklyLine's real fields are (player_id, name, team, pos, week,
    # cbs_fpts, stats) - there is no `season` field. cbs_fpts is not under
    # test here, so it is filled with a placeholder.
    return WeeklyLine(player_id=pid, name=pid, team="XXX", pos=pos, week=week,
                      cbs_fpts=0.0, stats=dict(stats))


def test_folds_are_disjoint_and_cover_every_player():
    lines = [_line("p%d" % i, "RB", w, rush_yds=10.0 * i)
             for i in range(20) for w in range(1, 6)]
    folds = player_folds(lines, k=5)
    assert len(folds) == 5
    allp = set()
    for f in folds:
        assert not (allp & f), "a player appears in two folds - that is the leak"
        allp |= f
    assert allp == {"p%d" % i for i in range(20)}


def test_folds_are_deterministic():
    lines = [_line("p%d" % i, "RB", w) for i in range(20) for w in range(1, 6)]
    assert player_folds(lines, k=5) == player_folds(lines, k=5)


def test_realized_is_the_mean_of_the_banded_weeks_not_the_band_of_the_mean():
    # The whole reason curves exist: E[band(X)] != band(E[X]).
    #
    # NOTE: the brief's original pair (0.0, 100.0) was replaced with
    # (0.0, 60.0). For rush_yds under leagues/sffl/2026.yaml, band(0)=0 and
    # band(100)=4 average to 2, which coincidentally equals band(50)=2 -
    # a property of this league's real band table, not a bug in `realized`.
    # (0.0, 60.0) demonstrates the same inequality without that coincidence:
    # mean(band)=(0+2)/2=1.0 but band(mean)=band(30)=0.
    lg = load_league("leagues/sffl/2026.yaml")
    weeks = [_line("p", "RB", 1, rush_yds=0.0), _line("p", "RB", 2, rush_yds=60.0)]
    from sffl.scoring import band_points
    got = realized(lg, weeks, "rush_yds")
    mean_of_banded = (band_points(lg.bands["rush_yds"], 0.0)
                      + band_points(lg.bands["rush_yds"], 60.0)) / 2.0
    banded_mean = band_points(lg.bands["rush_yds"], 30.0)
    assert got == mean_of_banded
    assert got != banded_mean


def test_cross_validate_never_scores_a_player_against_a_curve_built_from_him():
    # The leak this harness exists to prevent. A builder that memorises its
    # input would score perfectly if the split were by row.
    #
    # A raw player-count assertion (`len(fit_players) < 20`) is a PROXY, not
    # the property: an implementation that leaks every holdout player except
    # one still shrinks the fit set and passes such an assertion. Recording
    # only the LAST builder call also misses leaks in every earlier fold. The
    # actual property is per-fold set disjointness, checked for every fold.
    lg = load_league("leagues/sffl/2026.yaml")
    seen = []

    def spy_builder(lg_, lines_):
        seen.append({l.player_id for l in lines_})
        from sffl.calibrate import build_curves
        return build_curves(lg_, lines_)

    lines = [_line("p%d" % i, "RB", w, rush_yds=5.0 * i)
             for i in range(20) for w in range(1, 6)]
    folds = player_folds(lines, k=5)
    cross_validate(lg, lines, spy_builder, k=5)

    assert len(seen) == len(folds), "builder must be called once per fold"
    for fit_players, fold in zip(seen, folds):
        assert fit_players & fold == set(), (
            "a holdout player's own weeks were present in the fit set "
            "used to build the curve he was scored against - that is the leak")


def test_every_stat_in_the_league_is_present_even_with_zero_predictions():
    # Two builders must be judged over the same population, or the harness
    # must say loudly that it could not be. A stat silently dropped from the
    # result dict (the old `if e` filter) lets that go unnoticed: builder A
    # could report def_pa and builder B could not, and a naive comparison
    # would never know the populations differed.
    lg = load_league("leagues/sffl/2026.yaml")

    def empty_builder(lg_, lines_):
        return {}

    # Lines carry no stats for any banded field, so every held-out player
    # who clears min_weeks still contributes zero real predictions once you
    # exclude the missing-curve case - but the important thing here is that
    # empty_builder returns {} for every stat, so no fold ever has a curve.
    lines = [_line("p%d" % i, "RB", w) for i in range(20) for w in range(1, 6)]
    result = cross_validate(lg, lines, empty_builder, k=5)

    assert set(result.keys()) == set(lg.bands.keys())
    for stat, row in result.items():
        assert row["n"] == 0
        assert row["mae"] is None
        # Every one of the k folds had no curve at all for this stat.
        assert row["empty_curve_folds"] == 5


def test_empty_curve_folds_is_surfaced_when_only_some_folds_have_no_curve():
    # A builder that can only fit a curve when it sees enough players (a
    # realistic stand-in for def_pa's four real defenses) will have some
    # folds with a usable curve and some without. That partial coverage must
    # be visible in the result, not averaged away.
    lg = load_league("leagues/sffl/2026.yaml")

    def sparse_builder(lg_, lines_):
        from sffl.calibrate import build_curves
        curves = build_curves(lg_, lines_, min_weeks=4)
        # Simulate a builder that refuses to trust a rush_yds curve fit
        # from very few players by dropping it below a player-count floor.
        fit_players = {l.player_id for l in lines_}
        if len(fit_players) < 20:
            curves["rush_yds"] = []
        return curves

    lines = [_line("p%d" % i, "RB", w, rush_yds=5.0 * i)
             for i in range(20) for w in range(1, 6)]
    result = cross_validate(lg, lines, sparse_builder, k=5)
    # 20 players split 5 ways leaves 16 fit players per fold - always below
    # 20 - so every fold's rush_yds curve was suppressed.
    assert result["rush_yds"]["empty_curve_folds"] == 5
    assert result["rush_yds"]["n"] == 0
    assert result["rush_yds"]["mae"] is None


def test_the_harness_reproduces_the_shipped_curves():
    # THE VALIDITY GATE. If rebuilding the build set does not reproduce what
    # ships, the harness misunderstands the pipeline and every comparison
    # below it is meaningless.
    import os
    if not os.path.isdir("data/weekly/2025"):
        pytest.skip("weekly data not present (gitignored)")
    from sffl.calibrate import build_curves, load_curves
    lg = load_league("leagues/sffl/2026.yaml")
    lines = []
    for pos in ("DST", "K", "RB", "TQB", "WR"):
        p = "data/weekly/2025/%s.csv" % pos
        if os.path.exists(p):
            lines.extend(load_weekly(p))
    built = build_curves(lg, lines)
    shipped = load_curves("calibration/2025.yaml")
    for stat in shipped:
        assert len(built[stat]) == len(shipped[stat]), stat
        for (m1, e1), (m2, e2) in zip(built[stat], shipped[stat]):
            assert abs(m1 - m2) < 1e-9 and abs(e1 - e2) < 1e-9, stat
