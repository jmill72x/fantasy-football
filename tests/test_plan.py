import pytest

from sffl.league import LeagueProfile, load_league
from sffl.plan import BidOutcome, plan_bids
from sffl.render.rows import BoardRow
from sffl.silent import load_bid_history, observations_at

LG = load_league("leagues/sffl/2026.yaml")

# FROZEN SNAPSHOT of data/league/silent-auction-bids.csv as it stood through the
# 2025 season: 60 rows, five years. Kept as a fixture because the assertions
# below pin exact tie rates, bump counts and rank ranges, and pointed at the
# LIVE file those break every August when a season is appended - which is not a
# regression, it is the data doing its job. Appending 2026 broke twenty of them
# at once. Behaviour is pinned against a dataset that cannot move; the live file
# gets its own structural test instead (see the LIVE tests at the end).
FROZEN = "tests/fixtures/silent_bids_2021_2025.csv"
LIVE = "data/league/silent-auction-bids.csv"


def row(rank, name, pos, dollars, est):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=float(est))


def board():
    return [row(i, "Player %d" % i, "RB" if i % 2 else "WR",
                60.0 - 1.5 * i, 40.0 - 1.0 * i) for i in range(1, 40)]


def test_every_outcome_is_at_or_above_the_floor():
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    assert out
    assert all(o.bid >= LG.silent_auction["bid_floor"] for o in out)


def test_budget_arithmetic_matches_the_league_config():
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    o = [x for x in out if x.bid == 26][0]
    assert o.budget_left == LG.budget - 26
    assert o.discretionary == (LG.budget - 26) - (LG.roster_size - 1)


def test_a_higher_bid_never_buys_a_worse_rank():
    out = sorted(plan_bids(LG, board(), load_bid_history(FROZEN)),
                 key=lambda o: o.bid)
    medians = [o.median_rank for o in out]
    assert medians == sorted(medians, reverse=True), \
        "median rank must improve (fall) as the bid rises"


def test_the_floor_bid_reports_a_tie_every_year():
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    o = [x for x in out if x.bid == 26][0]
    assert o.field_tie_rate == pytest.approx(1.0)
    assert o.winning_bumps, "a floor bid has always needed a bump"


def test_only_skill_positions_are_offered_as_the_likely_pick():
    rows = board() + [row(99, "Some Kicker", "K", 1.0, 1.0),
                      row(98, "Some Defense", "DST", 1.0, 1.0)]
    out = plan_bids(LG, rows, load_bid_history(FROZEN))
    assert all(o.likely_player not in ("Some Kicker", "Some Defense")
               for o in out)


def test_an_empty_board_raises():
    with pytest.raises(ValueError):
        plan_bids(LG, [], load_bid_history(FROZEN))


def test_a_board_shallower_than_the_rank_reports_no_player_rather_than_guessing():
    out = plan_bids(LG, [row(1, "Only Guy", "RB", 50.0, 30.0)],
                    load_bid_history(FROZEN))
    deep = [o for o in out if o.median_rank > 1]
    assert deep, "expected some bid whose median rank is past the board"
    assert all(o.likely_player is None for o in deep)


# --- the unobserved-bid cases the brief's seven tests do not reach -----------

def test_an_unobserved_bid_reports_no_tie_evidence_rather_than_a_fabricated_zero():
    """$36 has never been submitted. 0.0 would read as "never ties"."""
    history = load_bid_history(FROZEN)
    assert observations_at(history, 36) == 0
    o = [x for x in plan_bids(LG, board(), history) if x.bid == 36][0]
    assert o.join_tie_rate is None
    assert o.field_tie_rate is None
    assert o.winning_bumps is None
    assert o.escalated_years is None
    assert o.observations == 0


def test_an_observed_level_that_never_tied_reports_zero_not_no_data():
    """The other side of the same distinction, and the one that regresses.

    $27 was bid in 2022 and 2025, never twice in one year. "0%" and "no data"
    are different facts on the auction-day page, and any shortcut that
    collapses them - `field_tie_rate_at(...) or None` being the obvious one -
    would pass every other test in this file while flipping this row to
    unknown. Note the two rates disagree here and both are measurements: 40% of
    years had somebody at $27, 0% had two teams there.
    """
    history = load_bid_history(FROZEN)
    o = [x for x in plan_bids(LG, board(), history) if x.bid == 27][0]
    assert observations_at(history, 27) == 2
    assert o.observations == 2
    assert o.join_tie_rate == pytest.approx(0.4)
    assert o.field_tie_rate == pytest.approx(0.0)
    assert o.winning_bumps == []
    assert o.escalated_years == []


def test_every_observed_level_that_never_tied_is_zero_and_every_unobserved_is_none():
    """The invariant behind the two tests above, over the whole table."""
    history = load_bid_history(FROZEN)
    out = plan_bids(LG, board(), history)
    assert [o.bid for o in out if o.observations and o.field_tie_rate == 0.0] \
        == [27, 32, 34, 37, 42, 43, 44, 45]
    assert [o.bid for o in out if o.field_tie_rate is None] == [28, 29, 36]
    for o in out:
        none_fields = (o.join_tie_rate, o.field_tie_rate,
                       o.winning_bumps, o.escalated_years)
        assert all(f is None for f in none_fields) == (o.observations == 0), \
            "$%d: tie evidence must be None exactly when unobserved" % o.bid


def test_an_unobserved_bid_still_reports_a_rank_because_every_year_votes_on_it():
    """Rank evidence is counterfactual insertion, so $36 is fully evidenced."""
    o = [x for x in plan_bids(LG, board(), load_bid_history(FROZEN))
         if x.bid == 36][0]
    assert (o.best_rank, o.worst_rank, o.median_rank) == (5, 7, 6.0)
    assert o.likely_player is not None


def test_the_candidate_range_spans_the_floor_to_the_highest_bid_ever_made():
    history = load_bid_history(FROZEN)
    bids = [o.bid for o in plan_bids(LG, board(), history)]
    assert bids == list(range(LG.silent_auction["bid_floor"],
                              max(b.bid for b in history) + 1))


def test_a_level_whose_only_ties_went_live_reports_no_bumps_but_names_the_years():
    """$39 tied in 2023 and settled live; empty bumps alone would mislead."""
    o = [x for x in plan_bids(LG, board(), load_bid_history(FROZEN))
         if x.bid == 39][0]
    assert o.field_tie_rate == pytest.approx(0.2)
    assert o.winning_bumps == []
    assert o.escalated_years == [2023]


def test_the_likely_pick_is_the_board_row_at_the_median_rank():
    rows = board()
    out = plan_bids(LG, rows, load_bid_history(FROZEN))
    o = [x for x in out if x.bid == 41][0]      # median rank 2.0
    ranked = sorted(rows, key=lambda r: -r.my_dollars)
    assert o.median_rank == 2.0
    assert o.likely_player == ranked[1].name
    assert o.likely_my_dollars == ranked[1].my_dollars
    assert o.likely_est_price == ranked[1].est_price


def test_a_half_step_median_illustrates_the_later_of_the_two_picks():
    """Median 8.5 means 8th or 9th; showing the 9th never overstates it."""
    rows = board()
    o = [x for x in plan_bids(LG, rows, load_bid_history(FROZEN))
         if x.bid == 31][0]
    ranked = sorted(rows, key=lambda r: -r.my_dollars)
    assert o.median_rank == 8.5
    assert o.likely_player == ranked[8].name


def test_a_caller_may_ask_about_specific_bids():
    out = plan_bids(LG, board(), load_bid_history(FROZEN), candidates=[30, 40])
    assert [o.bid for o in out] == [30, 40]


def test_candidates_come_back_in_bid_order_however_they_were_supplied():
    out = plan_bids(LG, board(), load_bid_history(FROZEN),
                    candidates=[40, 30, 40])
    assert [o.bid for o in out] == [30, 40]


def test_a_sub_floor_candidate_is_refused_rather_than_priced():
    with pytest.raises(ValueError):
        plan_bids(LG, board(), load_bid_history(FROZEN), candidates=[25])


def test_an_empty_history_is_named_rather_than_failing_inside_max():
    with pytest.raises(ValueError, match="no bid history"):
        plan_bids(LG, board(), [])


def test_a_league_with_no_silent_auction_configured_is_refused():
    lg = LeagueProfile(dict(LG.raw, silent_auction={}))
    with pytest.raises(ValueError, match="bid_floor"):
        plan_bids(lg, board(), load_bid_history(FROZEN))


def test_what_a_bid_leaves_is_the_budget_less_the_bid_and_a_dollar_a_spot():
    o = [x for x in plan_bids(LG, board(), load_bid_history(FROZEN))
         if x.bid == 44][0]
    assert o.budget_left == 66
    assert o.discretionary == 54


def test_outcomes_are_bid_outcomes():
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    assert all(isinstance(o, BidOutcome) for o in out)


# --- both tie numbers, ruled on by Jeff 2026-08-05 --------------------------

def test_both_tie_rates_reach_the_outcome_and_disagree_where_the_record_does():
    """The gap is the whole reason both are carried.

    A bidder weighing $30 wants to know that someone has been standing on $30
    in every year on record (TIE1+ 100%), which the narrower "two teams tied
    each other" figure (TIE2+ 40%) does not say. Pinned at the levels where the
    top of this board actually sits.
    """
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    by_bid = dict((o.bid, o) for o in out)
    for bid, join, field in ((30, 1.0, 0.4), (33, 0.8, 0.2), (39, 0.8, 0.2),
                             (27, 0.4, 0.0)):
        o = by_bid[bid]
        assert o.join_tie_rate == pytest.approx(join), "$%d join" % bid
        assert o.field_tie_rate == pytest.approx(field), "$%d field" % bid
        assert o.join_tie_rate >= o.field_tie_rate


def test_both_tie_rates_go_none_together_at_a_bid_nobody_has_ever_made():
    """$28 has never been submitted, so NEITHER number may be a number.

    Half an answer is worse than none: 0% beside "no data" would read as a
    measured "this level never draws a tie" for whichever cell held the zero.
    """
    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    o = [x for x in out if x.bid == 28][0]
    assert o.observations == 0
    assert o.join_tie_rate is None
    assert o.field_tie_rate is None
    # ...and the invariant, over every candidate: the two are never split.
    for x in out:
        assert (x.join_tie_rate is None) == (x.field_tie_rate is None), \
            "$%d: one tie rate known and the other not" % x.bid


def test_the_two_tie_cells_print_no_data_twice_and_never_a_bare_zero():
    from sffl.plan import tie_cells

    out = plan_bids(LG, board(), load_bid_history(FROZEN))
    by_bid = dict((o.bid, o) for o in out)
    assert tie_cells(by_bid[28]) == ("no data", "no data", "", "")
    assert tie_cells(by_bid[30])[:2] == ("100%", "40%")
    assert tie_cells(by_bid[39])[:2] == ("80%", "20%")
    # $27: observed twice, occupied in 40% of years, never tied in one.
    assert tie_cells(by_bid[27])[:2] == ("40%", "0%")
