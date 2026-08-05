"""Five years of sealed silent-auction bids, and what they say about a price.

Round one of this league's auction is a silent auction: every franchise submits
one sealed bid with a floor of $26, the bids are ranked high to low, each team
pays its OWN bid, and picks are made in bid order - an order that then governs
nomination for the rest of the draft. A bid below the floor is discarded and
that team forfeits its silent pick entirely.

Ties are broken by a sealed bump, and the bump is charged ONLY if it wins the
tie (`silent_auction.bump_charged_only_on_winning_tie` in the league profile).

READ `cap_cost`, NOT `bump`. The `bump` column records what a franchise
submitted; it says nothing about what it paid. `cap_cost` differs from `bid`
exactly when extra money was actually charged, so `cap_cost - bid` is the
premium that won. 2024 rank 4 submitted `bump 2` and paid `cap_cost 39` on a
`bid 39` - no tie, so nothing was charged. Inferring a charged bump from the
`bump` column would have that team paying $41 it never spent.
"""

import csv
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# The silent-auction bid floor, and the fallback for history analysis, which
# has no league object in scope. Where a LeagueProfile IS available, read
# `lg.silent_auction["bid_floor"]` instead - this constant exists so the
# functions below can validate a bid without one, and
# `test_the_module_floor_matches_the_league_profile` pins it to the profile so
# the two cannot drift.
BID_FLOOR = 26

_COLUMNS = ("year", "rank", "franchise", "bid", "bump", "cap_cost", "player",
            "note")

# src/sffl/silent.py -> src/sffl -> src -> repo root
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# League-owned history, not vendor data, so it is tracked in the repo.
DEFAULT_BIDS = os.path.join(_ROOT, "data", "league", "silent-auction-bids.csv")


@dataclass
class SilentBid(object):
    """One franchise's sealed bid in one year's silent auction."""

    year: int
    rank: int          # 1 is the highest bid; 12 the lowest that still bought
    franchise: str
    bid: int           # what was sealed and submitted
    bump: int          # the tiebreak submitted - NOT necessarily charged
    cap_cost: int      # what was actually charged against the $110 cap
    player: str = ""   # blank in the years the source did not record it
    note: str = ""

    @property
    def charged_bump(self):
        """What this bid actually paid above itself - the bump that won.

        Zero for a row that had no tie, or lost one. This is the only correct
        reading of a charged bump; see the module docstring.
        """
        return self.cap_cost - self.bid


def load_bid_history(path=DEFAULT_BIDS):
    """Read the tracked bid history into `SilentBid` rows, in file order.

    Raises ValueError on a missing column, an unparseable number, or a
    `cap_cost` below its own `bid` - nobody can pay less than they bid, and a
    row like that would silently corrupt every charged-bump figure below.
    """
    # type: (str) -> List[SilentBid]
    with open(path) as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in _COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "%s is missing the bid-history column(s) %s; expected %s"
                % (path, ", ".join(missing), ", ".join(_COLUMNS)))
        history = []  # type: List[SilentBid]
        for lineno, row in enumerate(reader, start=2):
            numbers = {}
            for field in ("year", "rank", "bid", "bump", "cap_cost"):
                raw = (row.get(field) or "").strip()
                try:
                    numbers[field] = int(raw)
                except ValueError:
                    raise ValueError(
                        "%s line %d: %s is %r, which is not a whole number"
                        % (path, lineno, field, raw))
            if numbers["cap_cost"] < numbers["bid"]:
                raise ValueError(
                    "%s line %d: cap_cost %d is below bid %d, but a franchise "
                    "always pays at least its own bid"
                    % (path, lineno, numbers["cap_cost"], numbers["bid"]))
            history.append(SilentBid(
                year=numbers["year"],
                rank=numbers["rank"],
                franchise=(row.get("franchise") or "").strip(),
                bid=numbers["bid"],
                bump=numbers["bump"],
                cap_cost=numbers["cap_cost"],
                player=(row.get("player") or "").strip(),
                note=(row.get("note") or "").strip(),
            ))
    if not history:
        raise ValueError("%s holds no bids" % path)
    return history


def _check_floor(bid):
    # type: (int) -> None
    if bid < BID_FLOOR:
        raise ValueError(
            "a silent bid of $%d is below the $%d floor; a sub-floor bid is "
            "discarded and the team forfeits its silent pick"
            % (bid, BID_FLOOR))


def _require_history(history):
    # type: (List[SilentBid]) -> None
    if not history:
        raise ValueError("no bid history to read")


def ranks_for_bid(history, bid):
    """(best_rank, worst_rank, median_rank) this bid has historically bought.

    For a bid that WAS observed, these are simply the best (lowest), worst
    (highest) and median rank it took across every year in the history.

    For a bid that was NEVER observed, the answer is a bracket, not a point:
    the nearest observed bid above sets the best rank (a strictly larger bid
    has never done worse than that), and the nearest observed bid below sets
    the worst rank. The median is interpolated between the two neighbours'
    medians by where the bid sits between them.

    NEVER EXTRAPOLATES PAST THE OBSERVED RANGE. A bid above everything ever
    observed is CLAMPED to the highest observed bid, and a bid below
    everything observed to the lowest. Nobody has ever bid $60, so this
    reports what $45 - the most anyone has bid - actually bought, rather than
    inventing a rank for a bid with no evidence behind it.

    Raises ValueError for a bid below the floor, or on an empty history.
    """
    # type: (List[SilentBid], int) -> Tuple[int, int, float]
    _require_history(history)
    _check_floor(bid)

    by_bid = {}  # type: Dict[int, List[int]]
    for b in history:
        by_bid.setdefault(b.bid, []).append(b.rank)

    exact = by_bid.get(bid)
    if exact is not None:
        return (min(exact), max(exact), float(statistics.median(exact)))

    observed = sorted(by_bid)
    below = None  # type: Optional[int]
    above = None  # type: Optional[int]
    for value in observed:
        if value < bid:
            below = value
        elif above is None:
            above = value

    # Clamp rather than extrapolate: off either end, report the nearest bid
    # that was actually observed.
    if below is None:
        return ranks_for_bid(history, observed[0])
    if above is None:
        return ranks_for_bid(history, observed[-1])

    lo_best, lo_worst, lo_median = ranks_for_bid(history, below)
    hi_best, hi_worst, hi_median = ranks_for_bid(history, above)
    frac = float(bid - below) / float(above - below)
    median = lo_median + frac * (hi_median - lo_median)
    return (hi_best, lo_worst, median)


def bids_for_rank(history, rank):
    """(min, max, median) bid that historically bought this rank.

    Raises ValueError for a rank nobody has ever finished in, or on an empty
    history.
    """
    # type: (List[SilentBid], int) -> Tuple[int, int, float]
    _require_history(history)
    bids = [b.bid for b in history if b.rank == rank]
    if not bids:
        raise ValueError(
            "rank %r never appears in the bid history; observed ranks are "
            "%d-%d" % (rank, min(b.rank for b in history),
                       max(b.rank for b in history)))
    return (min(bids), max(bids), float(statistics.median(bids)))


def tie_rate_at(history, bid):
    """Fraction of YEARS in which two or more franchises submitted this bid.

    The denominator is years, not rows: five years of history means five
    chances to tie, so a bid tied in all five scores 1.0. Ranks 11-12 have
    tied at the $26 floor in every year on record.

    Raises ValueError for a bid below the floor, or on an empty history.
    """
    # type: (List[SilentBid], int) -> float
    _require_history(history)
    _check_floor(bid)
    per_year = {}  # type: Dict[int, int]
    for b in history:
        per_year.setdefault(b.year, 0)
        if b.bid == bid:
            per_year[b.year] += 1
    tied = sum(1 for count in per_year.values() if count >= 2)
    return float(tied) / float(len(per_year))


def winning_bumps_at(history, bid):
    """Every premium actually charged on top of this bid, ascending.

    Derived from `cap_cost - bid`, NOT from the `bump` column: a bump is
    charged only when it wins a tie, so a submitted bump that lost - or that
    was never tested - cost nothing and does not appear here. See the module
    docstring.

    An empty list means this bid level either never tied, or never won a tie.

    Raises ValueError for a bid below the floor, or on an empty history.
    """
    # type: (List[SilentBid], int) -> List[int]
    _require_history(history)
    _check_floor(bid)
    return sorted(b.charged_bump for b in history
                  if b.bid == bid and b.charged_bump > 0)
