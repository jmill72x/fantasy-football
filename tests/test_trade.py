"""Rest-of-season trade valuation.

The property under test throughout is that value is MARGINAL LINEUP value,
not projected points - ranking a trade by raw projection is what makes a
lopsided deal look fair, because it counts production this league's lineup
can never start.
"""
import pytest

from sffl.league import load_league
from sffl.lineup import Candidate
from sffl.trade import (LAST_REGULAR_WEEK, acquisition_value, draft_proposal,
                        evaluate_trade, games_remaining, lineup_value,
                        rank_targets, release_cost)

LG = load_league("leagues/sffl/2026.yaml")


def c(name, pos, pts, team="NE"):
    return Candidate(name, pos, pts, team)


def roster():
    """A legal 13 with a clear worst player and depth at WR."""
    return [c("Q1", "TQB", 300.0), c("RB1", "RB", 200.0), c("RB2", "RB", 150.0),
            c("RB3", "RB", 90.0), c("WR1", "WR", 190.0), c("WR2", "WR", 170.0),
            c("WR3", "WR", 160.0), c("WR4", "WR", 40.0), c("TE1", "TE", 120.0),
            c("TE2", "TE", 30.0), c("K1", "K", 110.0), c("D1", "DST", 100.0),
            c("SCRUB", "WR", 5.0)]


# ------------------------------------------------------------ games remaining
def test_a_bye_still_ahead_costs_one_game():
    assert games_remaining(1, 0) == 18
    assert games_remaining(1, 7) == 17


def test_a_bye_already_past_costs_nothing():
    assert games_remaining(10, 7) == 9
    assert games_remaining(10, 13) == 8


def test_an_unknown_bye_is_not_guessed():
    # 0 means UNKNOWN. Treating it as "no bye" can overcount by one game in a
    # dozen; inventing one would silently remove a game he will really play.
    assert games_remaining(5, 0) == games_remaining(5, 0, LAST_REGULAR_WEEK)
    assert games_remaining(5, 0) == 14


def test_past_the_last_week_nothing_remains():
    assert games_remaining(LAST_REGULAR_WEEK, 0) == 1
    assert games_remaining(LAST_REGULAR_WEEK + 1, 0) == 0


# ------------------------------------------------------- value is MARGINAL
def test_a_fourth_receiver_is_worth_far_less_than_his_projection():
    # The point of the whole module. This league starts one WR/TE and three
    # FLEX; a receiver behind that wall scores nothing he is projected for.
    r = roster()
    depth = c("DEPTH", "WR", 120.0)
    assert depth.points == 120.0
    assert acquisition_value(LG, r, depth) < depth.points / 2


def test_an_upgrade_is_worth_only_the_difference_it_makes():
    # A 220-point receiver does not add 220. He enters the lineup and pushes
    # out its weakest FLEX-eligible starter - RB2 at 150 - so the lineup
    # gains exactly the difference. Pinned to the displaced player's points
    # rather than a loose bound, because the whole module rests on this
    # identity and a range would pass even if the wrong player were displaced.
    r = roster()
    upgrade = c("UP", "WR", 220.0)
    gain = acquisition_value(LG, r, upgrade)
    assert gain == pytest.approx(220.0 - 150.0)
    assert gain < upgrade.points / 2


def test_acquisition_value_is_never_negative():
    assert acquisition_value(LG, roster(), c("BAD", "WR", 0.0)) == 0.0


# --------------------------------------------------------------- release cost
def test_releasing_a_bench_player_costs_nothing():
    assert release_cost(LG, roster(), c("SCRUB", "WR", 5.0)) == 0.0


def test_releasing_a_starter_costs_the_lineup_real_points():
    assert release_cost(LG, roster(), c("Q1", "TQB", 300.0)) > 100.0


def test_pricing_a_player_you_do_not_have_is_refused():
    # Silently returning 0 here would price a trade giving away someone
    # else's player as free.
    with pytest.raises(ValueError) as e:
        release_cost(LG, roster(), c("NOT MINE", "WR", 50.0))
    assert "not on this roster" in str(e.value)


# --------------------------------------------------------------- whole trades
def test_a_trade_is_optimised_once_not_summed_from_parts():
    # Two receivers who each add little alone can add more together, because
    # the second no longer merely displaces the first. Summing per-player
    # values does not compose; this asserts the whole roster is re-optimised.
    r = roster()
    a, b = c("A", "WR", 200.0), c("B", "WR", 195.0)
    apart = acquisition_value(LG, r, a) + acquisition_value(LG, r, b)
    together = evaluate_trade(LG, r, give=[c("SCRUB", "WR", 5.0)], get=[a, b])
    assert together != pytest.approx(apart)


def test_a_bad_trade_returns_a_negative_number_rather_than_zero():
    # The one place in the module where the sign IS the answer.
    net = evaluate_trade(LG, roster(), give=[c("Q1", "TQB", 300.0)],
                         get=[c("JUNK", "WR", 1.0)])
    assert net < 0


def test_giving_away_a_player_you_do_not_have_is_refused():
    with pytest.raises(ValueError) as e:
        evaluate_trade(LG, roster(), give=[c("GHOST", "RB", 10.0)], get=[])
    assert "not on this roster" in str(e.value)


def test_a_pure_bench_dump_for_a_starter_is_positive():
    net = evaluate_trade(LG, roster(), give=[c("SCRUB", "WR", 5.0)],
                         get=[c("STUD", "RB", 260.0)])
    assert net > 0


# -------------------------------------------------------------------- targets
def test_targets_rank_by_lineup_gain_not_by_points():
    r = roster()
    market = [(c("BIGNAME", "WR", 175.0), "Team A"),
              (c("FILLS_A_HOLE", "RB", 210.0), "Team B")]
    ranked = rank_targets(LG, r, market)
    assert ranked[0][0].name == "FILLS_A_HOLE"
    assert ranked[0][1] == "Team B"


def test_targets_carry_the_owner_so_a_claim_can_be_addressed():
    ranked = rank_targets(LG, roster(), [(c("X", "RB", 250.0), "Bravo Company")])
    assert ranked[0][1] == "Bravo Company"


def test_zero_gain_targets_still_break_ties_by_the_better_player():
    r = roster()
    market = [(c("WEAK", "WR", 3.0), "T1"), (c("STRONGER", "WR", 30.0), "T2")]
    ranked = rank_targets(LG, r, market)
    assert [x[0].points for x in ranked] == [30.0, 3.0]


# ------------------------------------------------------------------- proposal
def test_the_proposal_states_both_sides_including_when_they_lose():
    text = draft_proposal("Mine", "Theirs", [c("A", "WR", 10.0)],
                          [c("B", "RB", 20.0)], my_net=5.0, their_net=-3.0)
    assert "Theirs" in text and "Mine" in text
    assert "+5.00" in text and "-3.00" in text
    assert "in my favour" in text


def test_a_mutually_good_trade_says_so():
    text = draft_proposal("Mine", "Theirs", [c("A", "WR", 10.0)],
                          [c("B", "RB", 20.0)], my_net=5.0, their_net=4.0)
    assert "Both lineups improve" in text


def test_the_proposal_never_contains_a_send_instruction():
    # The tool drafts; a human sends. Pinned so a future change that starts
    # posting to CBS has to delete this test on purpose.
    text = draft_proposal("Mine", "Theirs", [], [], 0.0, 0.0)
    assert "nobody" in text
