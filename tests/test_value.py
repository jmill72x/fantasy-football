import pytest

from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.value import replacement_levels, assign_vorp, assign_dollars, _largest_remainder_allocation, _starter_counts

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
    pool = [player("wr", "WR", 100), player("te", "TE", 90), player("rb", "RB", 80),
            player("tqb", "TQB", 150), player("k", "K", 50), player("d", "DST", 40)]
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


def test_empty_pool_raises():
    """Empty pool must raise, not silently fall back to 0.0."""
    pool = [player("flex1", "RB", 100), player("flex2", "WR", 90)]
    # Pool has FLEX but no TQB, K, or DST.
    with pytest.raises(ValueError, match="no players in pool 'TQB'"):
        replacement_levels(LG, pool, "starter")


def test_shallow_pool_uses_worst_available():
    """Non-empty but shallow pool falls back to worst available player, not 0.0."""
    pool = []
    # Only 5 FLEX players (much shallower than starter depth of 60).
    for i in range(5):
        pool.append(player("flex%d" % i, "RB" if i % 2 else "WR", 100 - 10 * i))
    # One of each other position to avoid empty-pool raises.
    pool.append(player("tqb", "TQB", 150))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    lv = replacement_levels(LG, pool, "starter")
    # FLEX depth for starter policy is 60, but only 5 available.
    # Should use worst available (flex4 = 100 - 10*4 = 60).
    assert lv["FLEX"] == pytest.approx(60.0)
    # TQB, K, DST all have only 1 player, so use that player.
    assert lv["TQB"] == pytest.approx(150.0)
    assert lv["K"] == pytest.approx(50.0)
    assert lv["DST"] == pytest.approx(40.0)


def test_draftable_depths_sum_to_roster_size():
    """Draftable policy depths must sum exactly to teams * roster_size.

    Directly tests _largest_remainder_allocation to ensure:
    1. Depths sum to exactly 156 for the real league config.
    2. Exact per-pool allocations are deterministic and match expected values.
    3. Allocation is order-independent.
    """
    starters = _starter_counts(LG)

    # Test 1: sum equals 156
    depths = _largest_remainder_allocation(LG, starters)
    assert sum(depths.values()) == LG.teams * LG.roster_size == 156

    # Test 2: exact allocations pin the tie-break behavior
    # With teams=12, roster_size=13, flex_slots=5:
    # total_starters = 96, drafted = 156
    # TQB:  156*12/96 = 19.5 -> floor=19, frac=0.5
    # FLEX: 156*60/96 = 97.5 -> floor=97, frac=0.5
    # K:    156*12/96 = 19.5 -> floor=19, frac=0.5
    # DST:  156*12/96 = 19.5 -> floor=19, frac=0.5
    # sum of floors = 154, leftover = 2
    # Remainders all 0.5; tie-break by (-starters[name], name):
    # FLEX (60 starters, the most fundamental) wins the first leftover unit.
    # The second goes to the next-sorted pool among the three tied at 12
    # starters each (K, DST, TQB alphabetically) - DST, being alphabetically
    # first, wins it.
    assert depths == {"TQB": 19, "FLEX": 98, "K": 19, "DST": 20}

    # Test 3: order-independence
    # Shuffle starters dict order; allocation should not depend on insertion order.
    starters_shuffled = {"DST": starters["DST"], "K": starters["K"],
                         "FLEX": starters["FLEX"], "TQB": starters["TQB"]}
    depths_shuffled = _largest_remainder_allocation(LG, starters_shuffled)
    assert depths_shuffled == depths


def test_assign_vorp_raises_for_missing_pool():
    """assign_vorp must raise if a pool with players is missing from levels."""
    pool = [player("flex1", "RB", 100), player("flex2", "WR", 90),
            player("tqb", "TQB", 150), player("k", "K", 50), player("d", "DST", 40)]
    # Hand-built levels with only FLEX.
    levels = {"FLEX": 50.0}
    with pytest.raises(ValueError, match="has players but is missing from replacement levels"):
        assign_vorp(LG, pool, levels)


def test_dollars_exhaust_the_league_budget():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    # every roster spot costs at least $1, and the surplus is fully distributed
    spent = sum(sorted((p.stats["_dollars"] for p in pool), reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)


def test_zero_vorp_players_cost_one_dollar():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    replacement = [p for p in pool if p.stats["_vorp"] == 0.0]
    assert replacement, "expected some players at or below replacement"
    assert all(p.stats["_dollars"] == pytest.approx(1.0) for p in replacement)


def test_rate_is_positive_and_returned():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    rate = assign_dollars(LG, pool)
    assert rate > 0


def test_a_pool_with_no_vorp_does_not_divide_by_zero():
    pool = [player("x", "RB", 0)]
    assign_vorp(LG, pool, {"FLEX": 0.0})
    rate = assign_dollars(LG, pool)
    assert rate == 0.0
    assert pool[0].stats["_dollars"] == pytest.approx(1.0)


def test_replacement_levels_raises_for_unscored_pool_members():
    """A pool that never went through build_pool/score_season_calibrated
    (e.g. straight out of sffl.consensus.merge, which never writes
    _season_points) must raise rather than silently price everyone at the
    default 0.0 - which would make every replacement level 0.0 and every
    player's dollar value $1.00 with no exception anywhere.
    """
    pool = build_pool()
    del pool[0].stats["_season_points"]
    with pytest.raises(ValueError, match="_season_points"):
        replacement_levels(LG, pool, "starter")


def test_assign_dollars_raises_for_unvalued_pool_members():
    """A pool that skipped assign_vorp must raise rather than silently
    treating every missing _vorp as 0.0 (which would flatten dollars to $1
    for players who may well be above replacement).
    """
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    del pool[0].stats["_vorp"]
    with pytest.raises(ValueError, match="_vorp"):
        assign_dollars(LG, pool)
