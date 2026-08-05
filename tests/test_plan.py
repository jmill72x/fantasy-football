import pytest

from sffl.league import LeagueProfile, load_league
from sffl.plan import BidOutcome, plan_bids
from sffl.render.rows import BoardRow
from sffl.silent import load_bid_history, observations_at

LG = load_league("leagues/sffl/2026.yaml")
REAL = "data/league/silent-auction-bids.csv"


def row(rank, name, pos, dollars, est):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=float(est))


def board():
    return [row(i, "Player %d" % i, "RB" if i % 2 else "WR",
                60.0 - 1.5 * i, 40.0 - 1.0 * i) for i in range(1, 40)]


def test_every_outcome_is_at_or_above_the_floor():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    assert out
    assert all(o.bid >= LG.silent_auction["bid_floor"] for o in out)


def test_budget_arithmetic_matches_the_league_config():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    o = [x for x in out if x.bid == 26][0]
    assert o.budget_left == LG.budget - 26
    assert o.discretionary == (LG.budget - 26) - (LG.roster_size - 1)


def test_a_higher_bid_never_buys_a_worse_rank():
    out = sorted(plan_bids(LG, board(), load_bid_history(REAL)),
                 key=lambda o: o.bid)
    medians = [o.median_rank for o in out]
    assert medians == sorted(medians, reverse=True), \
        "median rank must improve (fall) as the bid rises"


def test_the_floor_bid_reports_a_tie_every_year():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    o = [x for x in out if x.bid == 26][0]
    assert o.tie_rate == pytest.approx(1.0)
    assert o.winning_bumps, "a floor bid has always needed a bump"


def test_only_skill_positions_are_offered_as_the_likely_pick():
    rows = board() + [row(99, "Some Kicker", "K", 1.0, 1.0),
                      row(98, "Some Defense", "DST", 1.0, 1.0)]
    out = plan_bids(LG, rows, load_bid_history(REAL))
    assert all(o.likely_player not in ("Some Kicker", "Some Defense")
               for o in out)


def test_an_empty_board_raises():
    with pytest.raises(ValueError):
        plan_bids(LG, [], load_bid_history(REAL))


def test_a_board_shallower_than_the_rank_reports_no_player_rather_than_guessing():
    out = plan_bids(LG, [row(1, "Only Guy", "RB", 50.0, 30.0)],
                    load_bid_history(REAL))
    deep = [o for o in out if o.median_rank > 1]
    assert deep, "expected some bid whose median rank is past the board"
    assert all(o.likely_player is None for o in deep)


# --- the unobserved-bid cases the brief's seven tests do not reach -----------

def test_an_unobserved_bid_reports_no_tie_evidence_rather_than_a_fabricated_zero():
    """$36 has never been submitted. 0.0 would read as "never ties"."""
    history = load_bid_history(REAL)
    assert observations_at(history, 36) == 0
    o = [x for x in plan_bids(LG, board(), history) if x.bid == 36][0]
    assert o.tie_rate is None
    assert o.winning_bumps is None
    assert o.escalated_years is None
    assert o.observations == 0


def test_an_observed_level_that_never_tied_reports_zero_not_no_data():
    """The other side of the same distinction, and the one that regresses.

    $27 was bid in 2022 and 2025, never twice in one year. "0%" and "no data"
    are different facts on the auction-day page, and any shortcut that
    collapses them - `tie_rate_at(...) or None` being the obvious one - would
    pass every other test in this file while flipping this row to unknown.
    """
    history = load_bid_history(REAL)
    o = [x for x in plan_bids(LG, board(), history) if x.bid == 27][0]
    assert observations_at(history, 27) == 2
    assert o.observations == 2
    assert o.tie_rate == pytest.approx(0.0)
    assert o.winning_bumps == []
    assert o.escalated_years == []


def test_every_observed_level_that_never_tied_is_zero_and_every_unobserved_is_none():
    """The invariant behind the two tests above, over the whole table."""
    history = load_bid_history(REAL)
    out = plan_bids(LG, board(), history)
    assert [o.bid for o in out if o.observations and o.tie_rate == 0.0] \
        == [27, 32, 34, 37, 42, 43, 44, 45]
    assert [o.bid for o in out if o.tie_rate is None] == [28, 29, 36]
    for o in out:
        none_fields = (o.tie_rate, o.winning_bumps, o.escalated_years)
        assert all(f is None for f in none_fields) == (o.observations == 0), \
            "$%d: tie evidence must be None exactly when unobserved" % o.bid


def test_an_unobserved_bid_still_reports_a_rank_because_every_year_votes_on_it():
    """Rank evidence is counterfactual insertion, so $36 is fully evidenced."""
    o = [x for x in plan_bids(LG, board(), load_bid_history(REAL))
         if x.bid == 36][0]
    assert (o.best_rank, o.worst_rank, o.median_rank) == (5, 7, 6.0)
    assert o.likely_player is not None


def test_the_candidate_range_spans_the_floor_to_the_highest_bid_ever_made():
    history = load_bid_history(REAL)
    bids = [o.bid for o in plan_bids(LG, board(), history)]
    assert bids == list(range(LG.silent_auction["bid_floor"],
                              max(b.bid for b in history) + 1))


def test_a_level_whose_only_ties_went_live_reports_no_bumps_but_names_the_years():
    """$39 tied in 2023 and settled live; empty bumps alone would mislead."""
    o = [x for x in plan_bids(LG, board(), load_bid_history(REAL))
         if x.bid == 39][0]
    assert o.tie_rate == pytest.approx(0.2)
    assert o.winning_bumps == []
    assert o.escalated_years == [2023]


def test_the_likely_pick_is_the_board_row_at_the_median_rank():
    rows = board()
    out = plan_bids(LG, rows, load_bid_history(REAL))
    o = [x for x in out if x.bid == 41][0]      # median rank 2.0
    ranked = sorted(rows, key=lambda r: -r.my_dollars)
    assert o.median_rank == 2.0
    assert o.likely_player == ranked[1].name
    assert o.likely_my_dollars == ranked[1].my_dollars
    assert o.likely_est_price == ranked[1].est_price


def test_a_half_step_median_illustrates_the_later_of_the_two_picks():
    """Median 8.5 means 8th or 9th; showing the 9th never overstates it."""
    rows = board()
    o = [x for x in plan_bids(LG, rows, load_bid_history(REAL))
         if x.bid == 31][0]
    ranked = sorted(rows, key=lambda r: -r.my_dollars)
    assert o.median_rank == 8.5
    assert o.likely_player == ranked[8].name


def test_a_caller_may_ask_about_specific_bids():
    out = plan_bids(LG, board(), load_bid_history(REAL), candidates=[30, 40])
    assert [o.bid for o in out] == [30, 40]


def test_candidates_come_back_in_bid_order_however_they_were_supplied():
    out = plan_bids(LG, board(), load_bid_history(REAL),
                    candidates=[40, 30, 40])
    assert [o.bid for o in out] == [30, 40]


def test_a_sub_floor_candidate_is_refused_rather_than_priced():
    with pytest.raises(ValueError):
        plan_bids(LG, board(), load_bid_history(REAL), candidates=[25])


def test_an_empty_history_is_named_rather_than_failing_inside_max():
    with pytest.raises(ValueError, match="no bid history"):
        plan_bids(LG, board(), [])


def test_a_league_with_no_silent_auction_configured_is_refused():
    lg = LeagueProfile(dict(LG.raw, silent_auction={}))
    with pytest.raises(ValueError, match="bid_floor"):
        plan_bids(lg, board(), load_bid_history(REAL))


def test_the_per_spot_figure_divides_what_is_left_by_the_spots_left():
    o = [x for x in plan_bids(LG, board(), load_bid_history(REAL))
         if x.bid == 44][0]
    assert o.budget_left == 66
    assert o.discretionary == 54
    assert o.per_remaining_spot == pytest.approx(66.0 / 12)


def test_outcomes_are_bid_outcomes():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    assert all(isinstance(o, BidOutcome) for o in out)
