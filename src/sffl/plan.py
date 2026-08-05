"""The silent-auction tradeoff table: what a bid likely buys, and what it costs.

Joins five years of sealed bids (`sffl.silent`) to today's priced board. For
each candidate bid it answers three questions and stops:

    Where would I pick?      best/worst/median rank, by counterfactual
                             insertion against all five years.
    Who is likely there?     an ILLUSTRATION - the board rows at the best,
                             median and worst rank, assuming the room drafts
                             in our board's order, which it will not exactly.
                             Read it as the RANGE it is: at $39 that is ranks
                             1 through 5, and quoting the median row alone
                             would hide four of them.
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

TWO TIE NUMBERS, NOT ONE, and they answer different questions. `join_tie_rate`
is the share of years somebody was ALREADY at that exact bid - join it and you
are in a tie. `field_tie_rate` is the share of years two or more franchises
tied each OTHER there. The second is the narrower fact about the record; the
first is the bidder's own exposure, and it is much the larger number at the
levels this board's top actually sits on ($30: 100% against 40%). Jeff ruled on
2026-08-05 that both go on the page, because which one he wants depends on how
he is thinking at the table. Neither may be labelled simply "tie".

`join_tie_rate`, `field_tie_rate`, `winning_bumps` and `escalated_years` are
Optional and are None - never 0.0, never [] - at a bid nobody has ever
submitted. $28, $29 and $36 sit inside the plausible range and have never been
bid; reporting "0% tie risk" there would be a fabrication read as fact.
`observations` says which case you are in, and a renderer must print "no data"
rather than a number when it is 0.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sffl.league import LeagueProfile
from sffl.render.rows import BoardRow, overall_board
from sffl.silent import (SilentBid, _require_history, escalated_at,
                         field_tie_rate_at, join_tie_rate_at, observations_at,
                         ranks_for_bid, winning_bumps_at, years_on_record)


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

    # The SAME illustration read at the two ends of the rank span, because the
    # median row alone is a lie by omission wherever the span is wide. $39 has
    # finished anywhere from 1st to 5th in five years; naming only the rank-4
    # player throws four ranks away and reads as precision the evidence does
    # not have. Equal to each other, and to `likely_player`, when the span is a
    # single rank ($45 -> 1-1). None on a board shallower than the rank, on the
    # same rule as `likely_player` - and independently, so a board deep enough
    # for rank 1 but not rank 5 names the best end and blanks the worst.
    best_player: Optional[str]
    worst_player: Optional[str]

    # BEFORE ANY BUMP, and every surface must say so. A bump is chosen by the
    # bidder and charged only on a winning tie, so it cannot be subtracted here
    # without guessing - read these alongside `winning_bumps` and
    # `escalated_years`, which quantify that exposure. $39 shows $71 left, but
    # 2023's winner at $39 paid $42 and had $68.
    budget_left: int           # lg.budget - bid
    discretionary: int         # budget_left beyond $1 for every other spot

    # None means "never submitted, so nothing is known"; 0.0 / [] mean
    # "submitted, and it never happened". THE TWO ARE NOT INTERCHANGEABLE and
    # no shortcut may collapse them - `x or None` would silently reclassify
    # every observed-but-never-tied level ($27, $44, $45) as unknown.
    observations: int                        # times this bid was ever made

    # The denominator behind both tie rates, carried so a renderer can name it
    # in the legend instead of typing "5" and being wrong next August.
    years: int

    # Two different questions - see the module docstring, and never print
    # either under a bare "TIE" heading. All four fields below go None
    # together, exactly when observations == 0.
    join_tie_rate: Optional[float]           # years SOMEONE was already there
    field_tie_rate: Optional[float]          # years 2+ franchises tied there
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
    years = years_on_record(history)

    out = []  # type: List[BidOutcome]
    for bid in sorted(set(candidates)):
        best, worst, median = ranks_for_bid(history, bid)
        pick = _row_at(ranked, median)
        best_pick = _row_at(ranked, best)
        worst_pick = _row_at(ranked, worst)
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
            best_player=(best_pick.name if best_pick else None),
            worst_player=(worst_pick.name if worst_pick else None),
            budget_left=budget_left,
            discretionary=budget_left - spots_left,
            observations=seen,
            years=years,
            join_tie_rate=(join_tie_rate_at(history, bid) if seen else None),
            field_tie_rate=(field_tie_rate_at(history, bid) if seen else None),
            winning_bumps=(winning_bumps_at(history, bid) if seen else None),
            escalated_years=(escalated_at(history, bid) if seen else None),
        ))
    return out


def tie_cells(o):
    """(join, field, bump, live) as any surface must print them.

    Lives here rather than in a renderer for the same reason
    `sffl.render.rows.overall_board` does: the PDF and the terminal must not
    be able to disagree about what the evidence says.

    FOUR CELLS, AND THE FIRST TWO ARE DIFFERENT QUESTIONS. `join` is the share
    of years someone was already sitting at this exact bid - join it and you
    are in a tie. `field` is the share of years two or more franchises tied
    each other there. `join` is never smaller, and at $30 it is 100% against
    40%. A surface that prints one of them under a bare "TIE" heading has
    thrown the distinction away; both need a heading that names which is which,
    and a legend that spells both out.

    There are THREE states of evidence and no two of them may be collapsed:

      never submitted   `observations == 0`, so both rates, winning_bumps and
                        escalated_years are all None. BOTH RATE CELLS read
                        "no data" - one number beside a blank would read as a
                        measured zero for the blank one - and the bump and live
                        cells stay EMPTY, since an em dash there would claim
                        "none happened", which is evidence nobody has. $28, $29
                        and $36 are in this state.
      submitted, never tied
                        a real measurement over five years. $27 reads 40% join
                        and 0% field: someone was there in two of five years,
                        and never twice in the same year. Em dashes beside.
      tied, settled by a bump
                        the bumps actually charged, e.g. 1,2,2,2 at the floor.
      tied, escalated to a LIVE auction
                        an EMPTY bump list with years beside it ($35 in 2021,
                        $39 in 2023, $33 in 2025). Real money was paid above
                        the bid in those years; it simply was not paid as a
                        bump anyone could pre-commit. Printing the empty bump
                        list without the years reads as a free tie.
    """
    # type: (BidOutcome) -> Tuple[str, str, str, str]
    if not o.observations:
        return ("no data", "no data", "", "")
    return (
        "%.0f%%" % (o.join_tie_rate * 100.0),
        "%.0f%%" % (o.field_tie_rate * 100.0),
        ",".join(str(b) for b in o.winning_bumps) if o.winning_bumps else "—",
        " ".join("'%02d" % (y % 100) for y in o.escalated_years)
        if o.escalated_years else "—",
    )


def pick_range(o):
    """The illustration's two ends as one string, or "" when nothing is known.

    NEVER THE MEDIAN ROW ON ITS OWN. At $39 the span is ranks 1 to 5, and
    naming only the rank-4 player would present a four-rank spread as a single
    pick - precisely where the illustration is least trustworthy. It collapses
    to one name only where the evidence really is that tight: $45 has never
    been anything but rank 1.
    """
    # type: (BidOutcome) -> str
    if o.best_player is None:
        return ""
    if o.worst_player is None:
        # Board deeper than the best rank but not the worst. Say so rather
        # than stretching the one name we do have across the whole span.
        return "%s - (off board)" % o.best_player
    if o.best_player == o.worst_player:
        return o.best_player
    return "%s - %s" % (o.best_player, o.worst_player)


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
