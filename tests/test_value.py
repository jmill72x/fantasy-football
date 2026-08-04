import copy

import pytest

from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.value import (replacement_levels, assign_vorp, assign_dollars,
                        _largest_remainder_allocation, _starter_counts,
                        _select_flex_starters, _sorted_flex_records)

LG = load_league("leagues/sffl/2026.yaml")


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def build_pool_fixture():
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
    lv = replacement_levels(LG, build_pool_fixture(), "starter")
    # 12 teams start one TQB each, so replacement is the 13th best TQB
    assert lv["TQB"] == pytest.approx(300 - 5 * 12)
    # 12 teams * 5 flex slots = 60 starters, so replacement is the 61st best
    assert lv["FLEX"] == pytest.approx(200 - 2 * 60)


def test_draftable_policy_reaches_deeper_than_starter():
    starter = replacement_levels(LG, build_pool_fixture(), "starter")
    draftable = replacement_levels(LG, build_pool_fixture(), "draftable")
    assert draftable["FLEX"] < starter["FLEX"]


def test_wr_and_te_share_one_flex_pool():
    pool = [player("wr", "WR", 100), player("te", "TE", 90), player("rb", "RB", 80),
            player("tqb", "TQB", 150), player("k", "K", 50), player("d", "DST", 40)]
    lv = replacement_levels(LG, pool, "starter")
    assert "WR" not in lv and "TE" not in lv and "RB" not in lv
    assert "FLEX" in lv


def test_vorp_is_points_above_replacement_and_never_negative():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    top = max(pool, key=lambda p: p.stats["_vorp"])
    assert top.stats["_vorp"] > 0
    assert all(p.stats["_vorp"] >= 0 for p in pool)


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        replacement_levels(LG, build_pool_fixture(), "vibes")


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
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    # every roster spot costs at least $1, and the surplus is fully distributed
    spent = sum(sorted((p.stats["_dollars"] for p in pool), reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)


def test_zero_vorp_players_cost_one_dollar():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    replacement = [p for p in pool if p.stats["_vorp"] == 0.0]
    assert replacement, "expected some players at or below replacement"
    assert all(p.stats["_dollars"] == pytest.approx(1.0) for p in replacement)


def test_rate_is_positive_and_returned():
    pool = build_pool_fixture()
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
    pool = build_pool_fixture()
    del pool[0].stats["_season_points"]
    with pytest.raises(ValueError, match="_season_points"):
        replacement_levels(LG, pool, "starter")


def test_assign_dollars_raises_for_unvalued_pool_members():
    """A pool that skipped assign_vorp must raise rather than silently
    treating every missing _vorp as 0.0 (which would flatten dollars to $1
    for players who may well be above replacement).
    """
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    del pool[0].stats["_vorp"]
    with pytest.raises(ValueError, match="_vorp"):
        assign_dollars(LG, pool)


def test_flat_priced_pools_are_configured():
    assert LG.flat_priced_pools == {"K": 1.0, "DST": 1.0}


def test_kickers_and_defenses_cost_their_flat_price():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    for p in pool:
        if p.pos in ("K", "DST"):
            assert p.stats["_dollars"] == pytest.approx(1.0), p.name
            assert p.stats["_vorp"] == pytest.approx(0.0), p.name


def test_the_best_kicker_is_not_worth_more_than_the_worst():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    ks = [p.stats["_dollars"] for p in pool if p.pos == "K"]
    assert max(ks) == pytest.approx(min(ks))


def test_flat_pools_free_surplus_for_skill_players():
    # With K and DST removed from the VORP pool, the dollars-per-VORP rate and
    # the top flex player's price should both be strictly higher than they
    # would be if K/DST VORP claimed a share of the surplus too. A bare
    # `rate > 0` / `flex_top > 1.0` assertion (the previous version of this
    # test) passes even with flat pricing reverted entirely - verified:
    # rate 0.2767, flex_top $34.21 with flat_priced_pools = {}. So compare
    # the configured behaviour against the same pool valued with
    # flat_priced_pools cleared, and restore LG's state afterward since it is
    # a module-level fixture shared by every other test in this file.
    original_flat = LG.flat_priced_pools
    try:
        pool_flat = build_pool_fixture()
        lv_flat = replacement_levels(LG, pool_flat, "starter")
        assign_vorp(LG, pool_flat, lv_flat)
        rate_flat = assign_dollars(LG, pool_flat)
        flex_top_flat = max(p.stats["_dollars"] for p in pool_flat
                             if p.pos in ("RB", "WR", "TE"))

        LG.flat_priced_pools = {}
        pool_unflat = build_pool_fixture()
        lv_unflat = replacement_levels(LG, pool_unflat, "starter")
        assign_vorp(LG, pool_unflat, lv_unflat)
        rate_unflat = assign_dollars(LG, pool_unflat)
        flex_top_unflat = max(p.stats["_dollars"] for p in pool_unflat
                               if p.pos in ("RB", "WR", "TE"))
    finally:
        LG.flat_priced_pools = original_flat

    assert rate_flat > rate_unflat
    assert flex_top_flat > flex_top_unflat


# --- Lineup floors: 1 RB and 1 WR/TE per team, hard requirements at flex ---
#
# NOTE on direction: forcing extra RB (or WR/TE) into the starting set can
# only ever raise the FLEX replacement level relative to the naive
# position-blind top-`depth` cut, never lower it. Reserving a floor slot
# for a player who was NOT going to make the naive cut necessarily bumps a
# player who WAS going to make it (their points must be >= the naive
# replacement's, by definition of "naive top-depth cut"), so the new best
# excluded player can only be worth the same or more. Every test below that
# exercises a binding floor is written and independently hand-verified
# against that direction.

def build_rb_floor_binds_pool():
    """50 WR/TE outscore all 15 RB, so the natural top 60 holds only 10 RB -
    below the 12-team floor - even though 15 RB exist overall (>=12, so the
    floor is satisfiable, not a data failure)."""
    pool = []
    for i in range(50):
        pool.append(player("wr%d" % i, "WR", 200 - i))
    for i in range(15):
        pool.append(player("rb%d" % i, "RB", 149 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))
    return pool


def build_wrte_floor_binds_pool():
    """Mirror of build_rb_floor_binds_pool: 50 RB outscore 15 WR/TE (split
    across both positions), so the natural top 60 holds only 10 WR/TE."""
    pool = []
    for i in range(50):
        pool.append(player("rb%d" % i, "RB", 200 - i))
    for i in range(15):
        pos = "WR" if i % 2 == 0 else "TE"
        pool.append(player("wt%d" % i, pos, 149 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))
    return pool


def test_rb_floor_binds():
    """Natural top-60 flex holds only 10 RB; the floor forces 12 in.

    Hand-verified: reserving the top 12 RB (149..138) and top 12 WR
    (200..189), then filling the remaining 36 slots with the best
    unselected players regardless of position, yields a selected set of
    RB1-12 + WR1-48. The best player left out is WR49 at 152 points - NOT
    the naive top-60 cut, which is RB11 at 139 points (the 61st-best player
    overall). This assertion would fail against the pre-floor code, which
    returns 139.0.
    """
    pool = build_rb_floor_binds_pool()
    recs = _sorted_flex_records(pool)
    selected = _select_flex_starters(LG, recs, 60)
    rb_selected = sum(1 for i in selected if recs[i].pos == "RB")
    assert rb_selected == LG.teams == 12

    lv = replacement_levels(LG, pool, "starter")
    naive_cut = sorted((p.stats["_season_points"] for p in pool
                        if p.pos in ("RB", "WR", "TE")), reverse=True)[60]
    assert naive_cut == pytest.approx(139.0)
    assert lv["FLEX"] == pytest.approx(152.0)
    assert lv["FLEX"] > naive_cut


def test_wrte_floor_binds():
    """Mirror of test_rb_floor_binds: natural top-60 holds only 10 WR/TE."""
    pool = build_wrte_floor_binds_pool()
    recs = _sorted_flex_records(pool)
    selected = _select_flex_starters(LG, recs, 60)
    wrte_selected = sum(1 for i in selected if recs[i].pos in ("WR", "TE"))
    assert wrte_selected == LG.teams == 12

    lv = replacement_levels(LG, pool, "starter")
    naive_cut = sorted((p.stats["_season_points"] for p in pool
                        if p.pos in ("RB", "WR", "TE")), reverse=True)[60]
    assert naive_cut == pytest.approx(139.0)
    assert lv["FLEX"] == pytest.approx(152.0)
    assert lv["FLEX"] > naive_cut


def test_neither_floor_binds_matches_naive_cut():
    """When the natural top-depth already clears both floors, the floored
    selection must be a no-op: same replacement level as the naive
    position-blind top-`depth` cut. This pins the "inert on today's board"
    property - the 2026 Draft Sharks extract's top 60 flex is 19 RB / 41
    WR/TE, comfortably above 12/12, so this is the real-world case.
    """
    pool = []
    for i in range(65):
        pool.append(player("flex%d" % i, "RB" if i % 2 else "WR", 200 - 2 * i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    lv = replacement_levels(LG, pool, "starter")
    naive_cut = sorted((p.stats["_season_points"] for p in pool
                        if p.pos in ("RB", "WR", "TE")), reverse=True)[60]
    assert lv["FLEX"] == pytest.approx(naive_cut)


def test_wr_and_te_share_one_floor_not_one_each():
    """12 WR and zero TE must satisfy the single shared WR/TE floor - the
    code must not demand 12 of each position separately."""
    pool = []
    for i in range(60):
        pool.append(player("rb%d" % i, "RB", 200 - i))
    for i in range(12):
        pool.append(player("wr%d" % i, "WR", 140 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    recs = _sorted_flex_records(pool)
    selected = _select_flex_starters(LG, recs, 60)
    wr_selected = sum(1 for i in selected if recs[i].pos == "WR")
    te_selected = sum(1 for i in selected if recs[i].pos == "TE")
    assert wr_selected == 12
    assert te_selected == 0

    # Must not raise even though TE is entirely absent.
    lv = replacement_levels(LG, pool, "starter")
    assert "FLEX" in lv


def test_flex_pool_raises_for_too_few_rb():
    pool = []
    for i in range(5):
        pool.append(player("rb%d" % i, "RB", 200 - i))
    for i in range(60):
        pool.append(player("wr%d" % i, "WR", 190 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    with pytest.raises(ValueError, match=r"only 5 RB.*requires 12"):
        replacement_levels(LG, pool, "starter")


def test_flex_pool_raises_for_too_few_wrte():
    pool = []
    for i in range(60):
        pool.append(player("rb%d" % i, "RB", 200 - i))
    for i in range(5):
        pool.append(player("wr%d" % i, "WR", 140 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    with pytest.raises(ValueError, match=r"only 5 WR/TE.*requires 12"):
        replacement_levels(LG, pool, "starter")


def test_flex_depth_below_twice_teams_raises():
    """A league config where flex_slots is too small for the floors to fit
    (depth < 2 * teams) must raise, naming the depth and the requirement."""
    lg_tiny_flex = copy.copy(LG)
    lg_tiny_flex.flex_slots = 1  # depth = teams * 1 = 12, needs >= 24

    pool = []
    for i in range(20):
        pool.append(player("flex%d" % i, "RB" if i % 2 else "WR", 100 - i))
    pool.append(player("tqb", "TQB", 300))
    pool.append(player("k", "K", 50))
    pool.append(player("d", "DST", 40))

    with pytest.raises(ValueError, match=r"depth 12 is less than 2 \* lg\.teams \(24\)"):
        replacement_levels(lg_tiny_flex, pool, "starter")
