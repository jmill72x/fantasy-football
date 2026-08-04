import pytest

from sffl.league import load_league
from sffl.render.rows import BoardRow, assign_tiers, build_rows, load_byes
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
BYES = "leagues/nfl-byes-2026.yaml"


def player(name, pos, team, dollars, pts=100.0, games=17.0, est=None):
    stats = {"_season_points": float(pts), "_dollars": float(dollars)}
    if est is not None:
        stats["_est_price"] = float(est)
    return PlayerProjection(name=name, team=team, pos=pos, source="t",
                            source_year=2026, games=games, stats=stats,
                            raw_name=name)


def test_byes_load_for_all_32_teams():
    byes = load_byes(BYES)
    assert len(byes) == 32
    assert byes["NO"] == 8, "unquoted NO parses as boolean false in YAML 1.1"
    assert byes["KC"] == 5


def test_rows_are_ranked_by_dollars_descending():
    pool = [player("c", "WR", "KC", 5.0), player("a", "RB", "GB", 30.0),
            player("b", "WR", "NO", 12.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert [r.name for r in rows] == ["a", "b", "c"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_bye_is_joined_by_team_code():
    pool = [player("x", "RB", "NO", 10.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].bye == 8


def test_unknown_team_raises_rather_than_rendering_a_blank_bye():
    pool = [player("x", "RB", "ZZZ", 10.0)]
    with pytest.raises(ValueError) as e:
        build_rows(LG, pool, load_byes(BYES))
    assert "ZZZ" in str(e.value)


def test_avg_pts_is_season_points_over_games():
    pool = [player("x", "RB", "GB", 10.0, pts=170.0, games=17.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].avg_pts == pytest.approx(10.0)


def test_zero_games_does_not_divide_by_zero():
    pool = [player("x", "RB", "GB", 10.0, pts=0.0, games=0.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].avg_pts == pytest.approx(0.0)


def test_est_price_is_none_when_absent_rather_than_zero():
    pool = [player("x", "RB", "GB", 10.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].est_price is None


def test_tiers_split_at_the_largest_gaps():
    # dollars 40, 39, 38 | 20, 19 | 5  -> three clear clusters
    vals = [40.0, 39.0, 38.0, 20.0, 19.0, 5.0]
    pool = [player("p%d" % i, "RB", "GB", v) for i, v in enumerate(vals)]
    assign_tiers(pool, n_tiers=3)
    tiers = [p.stats["_tier"] for p in
             sorted(pool, key=lambda p: -p.stats["_dollars"])]
    assert tiers == [1, 1, 1, 2, 2, 3]


def test_wr_and_te_share_one_tier_ladder():
    pool = [player("wr1", "WR", "GB", 40.0), player("te1", "TE", "KC", 39.0),
            player("wr2", "WR", "NO", 5.0)]
    assign_tiers(pool, n_tiers=2)
    by = dict((p.name, p.stats["_tier"]) for p in pool)
    assert by["wr1"] == by["te1"] == 1
    assert by["wr2"] == 2


def test_a_flat_priced_pool_is_all_one_tier():
    pool = [player("k%d" % i, "K", "GB", 1.0) for i in range(12)]
    assign_tiers(pool, n_tiers=6)
    assert set(p.stats["_tier"] for p in pool) == {1}


def test_a_group_smaller_than_the_tier_count_gets_one_tier_each():
    pool = [player("a", "TQB", "GB", 30.0), player("b", "TQB", "KC", 10.0)]
    assign_tiers(pool, n_tiers=6)
    tiers = sorted(p.stats["_tier"] for p in pool)
    assert tiers == [1, 2]


def test_missing_dollars_raises():
    p = player("x", "RB", "GB", 10.0)
    del p.stats["_dollars"]
    with pytest.raises(ValueError) as e:
        build_rows(LG, [p], load_byes(BYES))
    assert "_dollars" in str(e.value)
