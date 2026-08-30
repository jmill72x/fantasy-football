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
    lg = load_league("leagues/sffl/2026.yaml")
    seen = {}

    def spy_builder(lg_, lines_):
        seen["fit_players"] = {l.player_id for l in lines_}
        from sffl.calibrate import build_curves
        return build_curves(lg_, lines_)

    lines = [_line("p%d" % i, "RB", w, rush_yds=5.0 * i)
             for i in range(20) for w in range(1, 6)]
    cross_validate(lg, lines, spy_builder, k=5)
    # The last fold's fit set must exclude that fold's holdout players.
    assert len(seen["fit_players"]) < 20


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
