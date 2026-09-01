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


def test_the_wr_te_slot_forces_a_receiver_when_backs_score_more():
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("te1", "TE", 2),
              c("rb1", "RB", 20), c("rb2", "RB", 19), c("rb3", "RB", 18),
              c("rb4", "RB", 17), c("rb5", "RB", 16)]
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert "te1" in picked


def test_repairing_the_rb_floor_does_not_force_a_weak_te_when_a_wr_already_clears_wr_te():
    """The RB floor forces rb1 in (it is the only RB). te1 must NOT also be
    forced: the WR/TE floor only needs one WR-or-TE, and wr0 (10 pts) clears
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
        if not ({"WR", "TE"} & set(poss)):
            continue
        best = max(best, sum(x.points for x in combo))
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert r.total == pytest.approx(best)
    assert "rb1" in picked              # the sole RB - the floor forces it
    assert "te1" not in picked          # a WR clears WR/TE more cheaply


def test_the_floor_positions_do_not_overlap_which_is_why_one_cut_cannot_break_both():
    """_best_flex_five guards against repairing one floor by breaking another.
    That guard is unreachable while the restricted flex slots partition the
    positions with no overlap - violating one floor over-satisfies the other.
    If a future league adds an overlapping slot (an RB/WR flex beside WR/TE),
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
        if not ({"WR", "TE"} & set(poss)):
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
