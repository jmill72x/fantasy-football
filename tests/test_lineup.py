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


def test_both_floors_bind_at_once():
    """The RB floor forces rb1 in (it is the only RB). te1 must NOT also be
    forced: the WR/TE floor only needs one WR-or-TE, and wr0 (10 pts) clears
    it more cheaply than te1 (1 pt) - forcing te1 in too would leave 10
    points on the table. Verified against brute force rather than a
    hand-derived expectation, since an earlier version of this test asserted
    exactly that wrong claim and passed against a correct implementation only
    by accident of the assertion never being checked against ground truth."""
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
    assert all(x is None for _s, x in r.slots)


def test_ties_break_deterministically_by_name():
    """Two runs must not disagree about an identical roster, or the 'what
    changed since last week' diff reports phantom changes."""
    a = best_lineup(LG, [c("bbb", "RB", 5), c("aaa", "RB", 5)])
    b = best_lineup(LG, [c("aaa", "RB", 5), c("bbb", "RB", 5)])
    assert [x.name for _s, x in a.slots if x] == [x.name for _s, x in b.slots if x]


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
