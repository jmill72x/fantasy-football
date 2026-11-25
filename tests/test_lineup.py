import copy
import itertools
import pytest
from sffl.league import load_league
from sffl.lineup import Candidate, best_lineup, delta

LG = load_league("leagues/sffl/2026.yaml")


def c(name, pos, pts):
    return Candidate(name=name, pos=pos, points=float(pts))


def full_roster():
    """Eight startable players, one per slot, plus flex depth."""
    return [c("qb", "TQB", 20), c("rb1", "RB", 12), c("rb2", "RB", 9),
            c("wr1", "WR", 15), c("wr2", "WR", 11), c("te1", "TE", 8),
            c("k", "K", 7), c("d", "DST", 6)]


def test_single_position_slots_take_their_best():
    r = best_lineup(LG, full_roster() + [c("qb2", "TQB", 25)])
    slots = dict(r.slots)
    assert slots["TQB"].name == "qb2"
    assert slots["K"].name == "k"
    assert slots["DST"].name == "d"


def test_the_rb_slot_forces_a_running_back_even_when_receivers_score_more():
    """The RB slot IS the floor. Five receivers outscoring every back must not
    produce a lineup with no RB in it."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 2),
              c("wr1", "WR", 20), c("wr2", "WR", 19), c("wr3", "WR", 18),
              c("wr4", "WR", 17), c("wr5", "WR", 16)]
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert "rb1" in picked
    assert "wr5" not in picked          # the worst receiver is displaced


def test_the_wr_slot_forces_a_receiver_when_backs_score_more():
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("wr1", "WR", 2),
              c("rb1", "RB", 20), c("rb2", "RB", 19), c("rb3", "RB", 18),
              c("rb4", "RB", 17), c("rb5", "RB", 16)]
    r = best_lineup(LG, roster)
    assert dict(r.slots)["WR"].name == "wr1"


def test_a_tight_end_does_not_clear_the_wr_floor():
    """CBS requires at least one WR and lets a TE start only where an RB or
    WR could (its lineup check: WR 1 to 4, TE 0 to 4, board da76847f). The
    floor slot was WR/TE until 11-24, so a TE could stand in for the WR and
    the optimizer would propose a lineup CBS calls illegal."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("te1", "TE", 30), c("te2", "TE", 29),
              c("rb1", "RB", 20), c("rb2", "RB", 19), c("rb3", "RB", 18),
              c("rb4", "RB", 17)]
    r = best_lineup(LG, roster)
    slots = dict(r.slots)
    assert slots["WR"] is None          # nobody may fill it
    assert sorted(x.pos for s, x in r.slots
                  if s.startswith("FLEX") or s == "RB") == [
        "RB", "RB", "TE", "TE"]
    # With one receiver on the roster he starts, however few points.
    r = best_lineup(LG, roster + [c("wr1", "WR", 1)])
    assert dict(r.slots)["WR"].name == "wr1"
    _legal(LG, r)


def test_four_wrs_and_no_te_is_a_full_lineup():
    """The 11-24 page: TQB, one RB, four WRs, K, DST - eight starters, no
    TE. CBS showed an EMPTY TE row beside it, which is a position nobody
    starts at, not a slot. The yaml agrees: every slot fills."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 9), c("wr1", "WR", 15), c("wr2", "WR", 14),
              c("wr3", "WR", 13), c("wr4", "WR", 12), c("te1", "TE", 0)]
    r = best_lineup(LG, roster)
    assert None not in dict(r.slots).values()
    assert "te1" not in [x.name for _s, x in r.slots]


def test_repairing_the_rb_floor_does_not_force_a_weak_te_when_a_wr_already_clears_wr_te():
    """The RB floor forces rb1 in (it is the only RB). te1 must NOT also be
    forced: the WR floor only needs one WR, and wr0 (10 pts) clears
    it more cheaply than te1 (1 pt) - forcing te1 in too would leave 10
    points on the table. Verified against brute force rather than a
    hand-derived expectation, since an earlier version of this test asserted
    exactly that wrong claim and passed against a correct implementation only
    by accident of the assertion never being checked against ground truth.

    Formerly named test_both_floors_bind_at_once - renamed because a single
    naive top-five can never actually violate both floors at once here (see
    test_the_floor_positions_do_not_overlap_which_is_why_one_cut_cannot_break_both),
    so that name sent readers looking for coverage that cannot exist."""
    roster = [c("rb1", "RB", 1), c("te1", "TE", 1)] + [
        c("wr%d" % i, "WR", 10 + i) for i in range(5)]
    best = 0.0
    for combo in itertools.combinations(roster, 5):
        poss = [x.pos for x in combo]
        if "RB" not in poss:
            continue
        if "WR" not in poss:
            continue
        best = max(best, sum(x.points for x in combo))
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert r.total == pytest.approx(best)
    assert "rb1" in picked              # the sole RB - the floor forces it
    assert "te1" not in picked          # a WR clears the WR floor cheaply


def test_the_floor_positions_do_not_overlap_which_is_why_one_cut_cannot_break_both():
    """_best_flex_five guards against repairing one floor by breaking another.
    That guard is unreachable while the restricted flex slots partition the
    positions with no overlap - violating one floor over-satisfies the other.
    If a future league adds an overlapping slot (an RB/WR flex beside WR),
    the guard becomes load-bearing and has no direct test. Fail here first."""
    restricted = [set(e) for s, e in LG.lineup
                  if set(e) & {"RB", "WR", "TE"} and set(e) != {"RB", "WR", "TE"}]
    for i, a in enumerate(restricted):
        for b in restricted[i + 1:]:
            assert not (a & b), "overlapping floor slots %s and %s" % (a, b)


def test_the_fast_path_agrees_with_brute_force_on_every_legal_combination():
    """A greedy repair that is subtly wrong produces a plausible lineup and
    silently costs points every week. Brute-force the flex pool and confirm."""
    flex = [c("p%d" % i, ("RB", "WR", "TE")[i % 3], 20 - i) for i in range(9)]
    fixed = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6)]
    best = 0.0
    for combo in itertools.combinations(flex, 5):
        poss = [x.pos for x in combo]
        if "RB" not in poss:
            continue
        if "WR" not in poss:
            continue
        best = max(best, sum(x.points for x in combo))
    r = best_lineup(LG, fixed + flex)
    assert r.total == pytest.approx(best + 33.0)   # 20 + 7 + 6 fixed slots


def test_a_roster_too_short_leaves_slots_empty_rather_than_inventing_players():
    r = best_lineup(LG, [c("rb1", "RB", 12)])
    slots = dict(r.slots)
    assert slots["RB"].name == "rb1"
    assert slots["TQB"] is None
    assert r.total == pytest.approx(12.0)


def test_an_empty_candidate_list_scores_zero_and_does_not_raise():
    r = best_lineup(LG, [])
    assert r.total == 0.0
    assert isinstance(r.total, float)   # sum()'s int-0 default would also == 0.0
    assert all(x is None for _s, x in r.slots)


def test_ties_break_deterministically_by_name():
    """Two runs must not disagree about an identical roster, or the 'what
    changed since last week' diff reports phantom changes."""
    a = best_lineup(LG, [c("bbb", "RB", 5), c("aaa", "RB", 5)])
    b = best_lineup(LG, [c("aaa", "RB", 5), c("bbb", "RB", 5)])
    assert [x.name for _s, x in a.slots if x] == [x.name for _s, x in b.slots if x]


def test_the_result_does_not_depend_on_the_order_slots_are_declared():
    """Filling wide slots before narrow ones lets a FLEX consume the only RB and
    leaves the RB slot empty, silently dropping a player and the points with
    him. Nothing validates declaration order, so the optimizer must not care.

    full_roster() does not reproduce this: it carries two RBs, so even if a
    FLEX grabs one, the RB slot still finds the other. This roster has a SOLE
    RB that also happens to be the single highest scorer, so a wide slot
    claims it before floor repair ever has a reason to fire - matching the
    reviewer's reported case.
    """
    roster = [c("rb1", "RB", 100),
              c("wr1", "WR", 50), c("wr2", "WR", 40),
              c("wr3", "WR", 30), c("wr4", "WR", 20)]
    shuffled = copy.deepcopy(LG)
    flex = [s for s in shuffled.lineup if set(s[1]) & {"RB", "WR", "TE"}]
    fixed = [s for s in shuffled.lineup if not set(s[1]) & {"RB", "WR", "TE"}]
    # widest first - the dangerous order
    shuffled.lineup = fixed + sorted(flex, key=lambda se: -len(se[1]))
    assert best_lineup(shuffled, roster).total == best_lineup(LG, roster).total


def test_delta_is_the_improvement_a_player_makes_to_the_optimal_lineup():
    roster = full_roster()
    base = best_lineup(LG, roster).total
    better_rb = c("stud", "RB", 30)
    assert delta(LG, roster, better_rb) == pytest.approx(
        best_lineup(LG, roster + [better_rb]).total - base)
    assert delta(LG, roster, better_rb) > 0


def test_delta_is_zero_for_a_player_who_would_not_crack_the_lineup():
    """A bench stash improves nothing this week, and the waiver output must be
    able to tell that apart from a claim that starts."""
    roster = full_roster()
    assert delta(LG, roster, c("scrub", "RB", 0.1)) == pytest.approx(0.0)


# ------------------------------------------------------------ add/drop pairs
#
# `--waivers` ranked additions and never named a release, but this league caps
# the roster at 13 and every claim is a swap - so the advice could not be
# submitted without a decision the tool declined to make.

def _full_roster():
    return ([Candidate("RB%d" % i, "RB", 12.0 - i, "NE") for i in range(4)]
            + [Candidate("WR%d" % i, "WR", 11.0 - i, "NE") for i in range(4)]
            + [Candidate("TE1", "TE", 6.0, "NE"),
               Candidate("K1", "K", 8.0, "NE"),
               Candidate("D1", "DST", 5.0, "NE"),
               Candidate("Q1", "TQB", 18.0, "NE"),
               Candidate("SCRUB", "WR", 0.5, "NE")])


def test_the_drop_is_the_weakest_releasable_player():
    from sffl.lineup import Candidate, best_add_drop
    lg = LG
    roster = _full_roster()
    drop, _net = best_add_drop(lg, roster, Candidate("Star", "WR", 14.0, "NE"))
    assert drop is not None and drop.name == "SCRUB"


def test_an_under_cap_roster_drops_nobody():
    from sffl.lineup import Candidate, best_add_drop
    lg = LG
    roster = _full_roster()[:9]
    drop, _net = best_add_drop(lg, roster, Candidate("Star", "WR", 14.0, "NE"))
    assert drop is None


def test_the_only_kicker_is_never_the_drop():
    # Needs no special case: releasing him leaves the K slot unfilled and the
    # optimizer sees that cost directly. Pinned because a future "don't drop
    # starters" shortcut would look equivalent and would not be.
    from sffl.lineup import Candidate, best_add_drop
    lg = LG
    roster = _full_roster()
    for _ in range(3):
        drop, _net = best_add_drop(lg, roster, Candidate("W", "WR", 20.0, "NE"))
        assert drop.pos != "K"


def test_the_drop_is_free_at_this_league_s_roster_size():
    # THE MEASURED CLAIM, pinned. An earlier docstring asserted that `delta`
    # overstates the gain because it charges nothing for the released player.
    # It does not: 8 lineup slots against a 13-man roster leave at least six
    # players outside the optimal lineup, so some release always costs zero
    # and net == delta exactly. If this ever fails, the league's lineup or
    # roster size changed and the waiver board must start showing both
    # numbers - it currently shows one, deliberately.
    import random
    from sffl.lineup import Candidate, best_add_drop, delta
    lg = LG
    random.seed(7)
    positions = ["TQB", "RB", "WR", "TE", "K", "DST"]
    for _ in range(400):
        n = random.choice([9, 11, 13])
        roster = [Candidate("p%d" % i, random.choice(positions),
                            round(random.uniform(0, 20), 2), "NE")
                  for i in range(n)]
        add = Candidate("ADD", random.choice(positions),
                        round(random.uniform(0, 20), 2), "NE")
        _drop, net = best_add_drop(lg, roster, add)
        assert abs(net - delta(lg, roster, add)) < 1e-9


def test_a_starter_can_be_the_drop_when_that_is_actually_better():
    # Two players for one slot: the backup at a single-slot position is
    # releasable even though a "never drop a starter" rule would protect him.
    from sffl.lineup import Candidate, best_add_drop
    lg = LG
    roster = _full_roster()
    drop, _net = best_add_drop(lg, roster, Candidate("Star", "WR", 30.0, "NE"))
    assert drop.name == "SCRUB"


# --- Multi-position players ("RB,WR"), board ef69a845 ----------------------
#
# CBS lists some players under two positions, primary first. `pos` is the
# primary code; `positions` is the full list, and the optimizer may start
# him in any slot one of them is eligible for.

from sffl.lineup import _best_lineup_exact, eligible_positions  # noqa: E402


def dual(name, pts, positions=("RB", "WR")):
    return Candidate(name=name, pos=positions[0], points=float(pts),
                     positions=tuple(positions))


def _brute_force_total(lg, cands):
    """The true optimum: every assignment of players to slots, by brute force
    over the slots in league order. Exponential, so small pools only."""
    slots = [e for _s, e in lg.lineup]
    best = [0.0]

    def go(i, used, total):
        if i == len(slots):
            best[0] = max(best[0], total)
            return
        any_fit = False
        for j, x in enumerate(cands):
            if j in used:
                continue
            if any(p in slots[i] for p in eligible_positions(x)):
                any_fit = True
                go(i + 1, used | {j}, total + x.points)
        if not any_fit:
            go(i + 1, used, total)

    go(0, frozenset(), 0.0)
    return best[0]


def _legal(lg, result):
    """Every filled slot holds a player eligible for it, nobody twice."""
    elig = dict(lg.lineup)
    seen = []
    for slot, x in result.slots:
        if x is None:
            continue
        assert any(p in elig[slot] for p in eligible_positions(x)), (slot, x)
        assert not any(x is y for y in seen), x
        seen.append(x)


def test_eligible_positions_defaults_to_the_one_position():
    assert eligible_positions(c("a", "WR", 1)) == ("WR",)
    assert eligible_positions(dual("b", 1)) == ("RB", "WR")


def test_a_dual_rb_wr_player_fills_the_wr_slot_when_no_receiver_can():
    """The case the primary-code rule got wrong: with no WR rostered,
    an RB,WR player is the only one who can fill WR. Counted as an RB
    only, the slot went empty and his points were lost to a worse RB."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 15), c("rb2", "RB", 14), c("rb3", "RB", 13),
              c("rb4", "RB", 12), dual("flexy", 11)]
    r = best_lineup(LG, roster)
    slots = dict(r.slots)
    assert slots["WR"].name == "flexy"
    assert slots["RB"].name == "rb1"
    assert None not in slots.values()
    assert r.total == pytest.approx(20 + 7 + 6 + 15 + 14 + 13 + 12 + 11)
    _legal(LG, r)


def test_counted_under_his_primary_code_only_the_same_roster_loses_points():
    """The same roster with the dual player stripped to his primary code:
    the WR slot is unfillable. This pins what the field buys."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 15), c("rb2", "RB", 14), c("rb3", "RB", 13),
              c("rb4", "RB", 12), c("flexy", "RB", 11)]
    r = best_lineup(LG, roster)
    assert dict(r.slots)["WR"] is None


def test_a_lone_dual_player_cannot_fill_both_floors_at_once():
    """He satisfies the RB floor AND the WR floor, but fills one slot.
    With nobody else in the flex pool, one of the two slots stays empty."""
    roster = [c("qb", "TQB", 20), dual("flexy", 11)]
    r = best_lineup(LG, roster)
    filled = [x for _s, x in r.slots if x is not None]
    assert sorted(x.name for x in filled) == ["flexy", "qb"]
    assert r.total == pytest.approx(31.0)
    _legal(LG, r)


def test_delta_credits_a_dual_waiver_player_with_the_slot_he_can_fill():
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 15), c("rb2", "RB", 14), c("rb3", "RB", 13),
              c("rb4", "RB", 12)]
    assert delta(LG, roster, dual("flexy", 11)) == pytest.approx(11.0)
    assert delta(LG, roster, c("flexy", "RB", 11)) == pytest.approx(0.0)


def test_the_exact_path_agrees_with_brute_force_on_random_dual_pools():
    import random
    rng = random.Random(20261124)
    singles = ("RB", "WR", "TE")
    duals = (("RB", "WR"), ("WR", "RB"), ("RB", "TE"), ("WR", "TE"))
    for trial in range(300):
        n = rng.randint(1, 8)
        cands = [c("qb", "TQB", rng.randint(0, 25)),
                 c("k", "K", rng.randint(0, 12))]
        for i in range(n):
            pts = rng.randint(0, 25)
            if rng.random() < 0.35:
                cands.append(dual("p%d" % i, pts, rng.choice(duals)))
            else:
                cands.append(c("p%d" % i, rng.choice(singles), pts))
        r = best_lineup(LG, cands)
        _legal(LG, r)
        assert r.total == pytest.approx(_brute_force_total(LG, cands)), cands


def test_the_exact_path_matches_the_subset_search_on_single_position_pools():
    """Single-position pools still take the original path (unchanged), and
    the exact search gives the same total on them - so the two paths cannot
    disagree about what a roster is worth."""
    import random
    rng = random.Random(7)
    for trial in range(300):
        cands = [c("qb", "TQB", rng.randint(0, 25)),
                 c("k", "K", rng.randint(0, 12)),
                 c("d", "DST", rng.randint(0, 12))]
        for i in range(rng.randint(0, 10)):
            cands.append(c("p%d" % i, rng.choice(("RB", "WR", "TE")),
                           rng.randint(0, 25)))
        fast = best_lineup(LG, cands)
        exact = _best_lineup_exact(LG, cands)
        assert exact.total == pytest.approx(fast.total)
        _legal(LG, exact)


def test_the_exact_path_is_deterministic_on_ties():
    roster = [c("qb", "TQB", 20), dual("b", 10), dual("a", 10),
              c("r", "RB", 10), c("w", "WR", 10)]
    first = best_lineup(LG, roster)
    for _ in range(5):
        again = best_lineup(LG, list(reversed(roster)))
        assert [(s, x and x.name) for s, x in again.slots] == [
            (s, x and x.name) for s, x in first.slots]


def _cbs_allows(result):
    """CBS's own lineup check, as its team page's `is_roster_legal` script
    states it (saved 2026-10-20, board da76847f): 5 to 8 active, TQB 1, RB
    1 to 4, WR 1 to 4, TE at most 4, K 1, DST 1."""
    n = {}
    for _slot, x in result.slots:
        if x is not None:
            n[x.pos] = n.get(x.pos, 0) + 1
    active = sum(n.values())
    return (5 <= active <= 8 and n.get("TQB", 0) == 1
            and 1 <= n.get("RB", 0) <= 4 and 1 <= n.get("WR", 0) <= 4
            and n.get("TE", 0) <= 4 and n.get("K", 0) == 1
            and n.get("DST", 0) == 1)


def test_every_lineup_the_optimizer_picks_passes_cbs_s_own_check():
    """Rosters that hold at least one player at every position: the optimum
    must be a lineup CBS accepts. Under the old WR/TE floor slot a roster
    whose receivers were all TEs gave a lineup with no WR, which CBS
    refuses."""
    import random
    rng = random.Random(20261124)
    for _ in range(500):
        cands = [c("qb", "TQB", rng.randint(0, 25)),
                 c("k", "K", rng.randint(0, 12)),
                 c("d", "DST", rng.randint(0, 12)),
                 c("rb0", "RB", rng.randint(0, 25)),
                 c("wr0", "WR", rng.randint(0, 25))]
        for i in range(rng.randint(3, 8)):
            cands.append(c("p%d" % i, rng.choice(("RB", "WR", "TE", "TE")),
                           rng.randint(0, 40)))
        r = best_lineup(LG, cands)
        assert None not in dict(r.slots).values(), cands
        assert _cbs_allows(r), [(s, x.pos) for s, x in r.slots]
