"""The silent-auction tradeoff table: what a bid likely buys, and what it costs.

Joins five years of sealed bids (`sffl.silent`) to today's priced board. For
each candidate bid it answers three questions and stops:

    Where would I pick?      best/worst/median rank, by counterfactual
                             insertion against all five years.
    Who is likely there?     an ILLUSTRATION - the board row at the median
                             rank, assuming the room drafts in our board's
                             order, which it will not exactly.
    What is left over?       budget after the bid, and how much of that is
                             discretionary once every other roster spot is
                             covered at the $1 minimum.

THIS TABLE DOES NOT RECOMMEND. There is no "best bid" field, no score, no
ordering by attractiveness - outcomes come back in bid order and nothing else.
The tradeoff is the deliverable; the bidder weighs it live. In particular,
NOTHING HERE PRICES FINISHING FIRST. Bid order also governs nomination for the
rest of the draft, but whether that is worth anything is unmeasured, so rank is
stated as a fact and never converted into value.

THE LIKELY PICK IS AN ILLUSTRATION, NOT A PREDICTION, and every surface that
renders it must say so. It assumes eleven other franchises value players in
exactly our order.

`tie_rate`, `winning_bumps` and `escalated_years` are Optional and are None -
never 0.0, never [] - at a bid nobody has ever submitted. $28, $29 and $36 sit
inside the plausible range and have never been bid; reporting "0% tie risk"
there would be a fabrication read as fact. `observations` says which case you
are in, and a renderer must print "no data" rather than a number when it is 0.
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from sffl.league import LeagueProfile
from sffl.render.rows import BoardRow, overall_board
from sffl.silent import (SilentBid, _require_history, escalated_at,
                         observations_at, ranks_for_bid, tie_rate_at,
                         winning_bumps_at)


@dataclass
class BidOutcome(object):
    """One candidate bid, and everything known about what it would buy."""

    bid: int
    best_rank: int
    worst_rank: int
    median_rank: float

    # The illustration at the median rank. All three go None together when the
    # board is shallower than that rank - an honest blank beats a fabricated
    # pick. TEST `likely_player`, NOT THE OTHER TWO: `BoardRow.est_price` is
    # itself Optional, so `likely_est_price is None` also means "this player
    # has no market estimate" on a pick that exists. Only `likely_player` is a
    # sound shallow-board sentinel.
    likely_player: Optional[str]
    likely_my_dollars: Optional[float]
    likely_est_price: Optional[float]

    # BEFORE ANY BUMP. A bump is chosen by the bidder and charged only on a
    # winning tie, so it cannot be subtracted here without guessing - read
    # these alongside `winning_bumps` and `escalated_years`, which quantify
    # that exposure. At the $26 floor it has really been $1 and $2.
    budget_left: int           # lg.budget - bid
    per_remaining_spot: float  # budget_left / the other roster spots
    discretionary: int         # budget_left beyond $1 for every other spot

    # None means "never submitted, so nothing is known"; 0.0 / [] mean
    # "submitted, and it never happened". THE TWO ARE NOT INTERCHANGEABLE and
    # no shortcut may collapse them - `x or None` would silently reclassify
    # every observed-but-never-tied level ($27, $44, $45) as unknown.
    observations: int                        # times this bid was ever made
    tie_rate: Optional[float]                # None iff observations == 0
    winning_bumps: Optional[List[int]]       # None iff observations == 0
    escalated_years: Optional[List[int]]     # None iff observations == 0


def default_candidates(lg, history):
    """Every whole dollar from the league floor to the highest bid on record.

    Capped at the observed maximum because offering a bid nobody has ever made
    is speculation about the room, not evidence about it. `ranks_for_bid` would
    answer a $50 bid perfectly well - it reports rank 1, correctly - but "rank
    1" is the only thing $50 could ever be told, and a table of bids that all
    say the same thing invites spending $5 to buy nothing.

    Raises ValueError on an empty history or a league profile with no silent
    auction configured.
    """
    # type: (LeagueProfile, List[SilentBid]) -> List[int]
    _require_history(history)
    if "bid_floor" not in (lg.silent_auction or {}):
        raise ValueError(
            "%s configures no silent_auction.bid_floor, so there is no floor "
            "to build candidate bids from" % lg.name)
    floor = int(lg.silent_auction["bid_floor"])
    return list(range(floor, max(b.bid for b in history) + 1))


def plan_bids(lg, rows, history, candidates=None):
    """A `BidOutcome` per candidate bid, in ascending bid order.

    Caller-supplied `candidates` are sorted and de-duplicated, so the result is
    always one row per distinct bid in bid order however they arrived.

    Raises ValueError on an empty board, on a board with no skill-position
    rows, on an empty history, on a league profile with no silent auction
    configured, or (via `sffl.silent`) on a candidate below the bid floor.
    """
    # type: (LeagueProfile, List[BoardRow], List[SilentBid], Optional[List[int]]) -> List[BidOutcome]
    _require_history(history)
    ranked = overall_board(rows)
    if not ranked:
        raise ValueError(
            "the board holds no TQB/RB/WR/TE rows, so there is no pick to "
            "illustrate; nobody spends a silent pick on a kicker or a defense")

    if candidates is None:
        candidates = default_candidates(lg, history)

    spots_left = lg.roster_size - 1

    out = []  # type: List[BidOutcome]
    for bid in sorted(set(candidates)):
        best, worst, median = ranks_for_bid(history, bid)
        pick = _row_at(ranked, median)
        budget_left = lg.budget - bid
        seen = observations_at(history, bid)
        out.append(BidOutcome(
            bid=bid,
            best_rank=best,
            worst_rank=worst,
            median_rank=median,
            likely_player=(pick.name if pick else None),
            likely_my_dollars=(pick.my_dollars if pick else None),
            likely_est_price=(pick.est_price if pick else None),
            budget_left=budget_left,
            per_remaining_spot=float(budget_left) / spots_left,
            discretionary=budget_left - spots_left,
            observations=seen,
            tie_rate=(tie_rate_at(history, bid) if seen else None),
            winning_bumps=(winning_bumps_at(history, bid) if seen else None),
            escalated_years=(escalated_at(history, bid) if seen else None),
        ))
    return out


def _row_at(ranked, median_rank):
    """The board row illustrating a pick at `median_rank`, or None.

    A median of 8.5 means the bid landed 8th in some years and 9th in others.
    This takes the LATER pick - the 9th row - so the illustration can never
    flatter the bid. None once the rank runs past the end of the board.
    """
    # type: (List[BoardRow], float) -> Optional[BoardRow]
    index = int(math.ceil(median_rank)) - 1
    if index >= len(ranked):
        return None
    return ranked[index]
