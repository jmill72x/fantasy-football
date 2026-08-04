import pytest

from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.value import replacement_levels, assign_vorp

LG = load_league("leagues/sffl/2026.yaml")


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def build_pool():
    pool = []
    # 100 flex players scoring 200 down to 3
    for i in range(100):
        pool.append(player("flex%d" % i, "RB" if i % 2 else "WR", 200 - 2 * i))
    # 32 team QBs scoring 300 down to 145
    for i in range(32):
        pool.append(player("tqb%d" % i, "TQB", 300 - 5 * i))
    # 32 kickers and 32 defenses
    for i in range(32):
        pool.append(player("k%d" % i, "K", 150 - i))
        pool.append(player("d%d" % i, "DST", 120 - i))
    return pool


def test_starter_policy_uses_starting_demand():
    lv = replacement_levels(LG, build_pool(), "starter")
    # 12 teams start one TQB each, so replacement is the 13th best TQB
    assert lv["TQB"] == pytest.approx(300 - 5 * 12)
    # 12 teams * 5 flex slots = 60 starters, so replacement is the 61st best
    assert lv["FLEX"] == pytest.approx(200 - 2 * 60)


def test_draftable_policy_reaches_deeper_than_starter():
    starter = replacement_levels(LG, build_pool(), "starter")
    draftable = replacement_levels(LG, build_pool(), "draftable")
    assert draftable["FLEX"] < starter["FLEX"]


def test_wr_and_te_share_one_flex_pool():
    pool = [player("wr", "WR", 100), player("te", "TE", 90), player("rb", "RB", 80)]
    lv = replacement_levels(LG, pool, "starter")
    assert "WR" not in lv and "TE" not in lv and "RB" not in lv
    assert "FLEX" in lv


def test_vorp_is_points_above_replacement_and_never_negative():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    top = max(pool, key=lambda p: p.stats["_vorp"])
    assert top.stats["_vorp"] > 0
    assert all(p.stats["_vorp"] >= 0 for p in pool)


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        replacement_levels(LG, build_pool(), "vibes")
