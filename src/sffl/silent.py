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

AND A CHARGED PREMIUM IS NOT ALWAYS A BUMP. When two franchises submit the
SAME bump at the same bid, the bump cannot break the tie either, and the tie
escalates to a live auction. The premium those rows paid is a live-auction
settlement, not a sealed bump a bidder could have pre-committed to. Four of
the fifteen ties on record escalated this way - 2021 at $35 (both bumped $4),
2022 at $26 (both bumped $0), 2023's four-way at $39, 2025 at $33 - and at
three of the nine bid levels that show a charged premium, EVERY premium came
from a live auction. `winning_bumps_at` therefore reports only ties a sealed
bump actually settled; `escalated_at` reports the rest.

Escalation is detected structurally - shared top bump inside a (year, bid) tie
group - and NOT by reading the `note` column, which is five years of
hand-written prose whose phrasing already varies ("bump tie -> live auction",
"4-way tie at 39 -> live auction", "bumps equal, resolved live"). The two
agree on all fifteen tie groups, and a test pins that.
"""

import csv
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Tuple

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
    _check_year_shape(history, path)
    return history


def _check_year_shape(history, path):
    """Each year must rank its bids uniquely, high bid to low.

    This file is hand-maintained. Two rows sharing a rank, or a rank order that
    disagrees with the bid order, means a transposed or mis-keyed row - and
    every function here would go on producing confident numbers from it.
    """
    # type: (List[SilentBid], str) -> None
    by_year = {}  # type: Dict[int, List[SilentBid]]
    for b in history:
        by_year.setdefault(b.year, []).append(b)
    for year in sorted(by_year):
        rows = sorted(by_year[year], key=lambda b: b.rank)
        for i, b in enumerate(rows):
            if i and b.rank == rows[i - 1].rank:
                raise ValueError(
                    "%s: %d has two bids at rank %d (%s and %s); ranks must be "
                    "unique within a year"
                    % (path, year, b.rank, rows[i - 1].franchise, b.franchise))
            if i and b.bid > rows[i - 1].bid:
                raise ValueError(
                    "%s: %d ranks %s ($%d) at %d above %s ($%d) at %d, but a "
                    "higher rank must never hold a lower bid"
                    % (path, year, rows[i - 1].franchise, rows[i - 1].bid,
                       rows[i - 1].rank, b.franchise, b.bid, b.rank))


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
    """(best_rank, worst_rank, median_rank) this bid would have taken.

    COUNTERFACTUAL INSERTION, not a lookup of observed ranks. For each year on
    record, this bid is placed against that year's twelve sealed bids:

        best  = 1 + (bids strictly above it)          - it wins every tie
        worst = best + max(bids equal to it, 1) - 1   - it loses every tie
                (worst == best when nothing ties it)

    then best/worst/median are taken across the years. A tie is a real spread,
    not a point: bidding the $26 floor has landed at rank 11 and at rank 12 in
    the same year depending on the bump, and both are reported.

    EVERY YEAR VOTES ON EVERY BID. Reading back only the ranks a bid was
    actually observed at answers a different and much weaker question - $32 was
    submitted exactly once in five years, so a lookup rests on n=1, while this
    places $32 against all sixty bids. It also removes the need to interpolate
    or clamp anything: there is no unobserved bid, only bids no one happened to
    submit, and those are placed on the same evidence as the rest.

    MONOTONE BY CONSTRUCTION. Both bounds are counts of bids beating (or
    matching) the candidate, so raising the bid can never worsen any of the
    three figures. The earlier nearest-neighbour bracket was not monotone: it
    claimed $36's best case was rank 6 while $35's was rank 5, which the data
    contradicts - $36 beats $35 in every year it could be compared.

    A bid above everything ever submitted correctly reports rank 1, which is
    an observation about the field and not an extrapolation past it. There is
    no rank 0 to invent.

    Raises ValueError for a bid below the floor, or on an empty history.
    """
    # type: (List[SilentBid], int) -> Tuple[int, int, float]
    _require_history(history)
    _check_floor(bid)

    by_year = {}  # type: Dict[int, List[int]]
    for b in history:
        by_year.setdefault(b.year, []).append(b.bid)

    bests = []  # type: List[int]
    worsts = []  # type: List[int]
    mids = []  # type: List[float]
    for year in sorted(by_year):
        bids = by_year[year]
        above = sum(1 for other in bids if other > bid)
        tied = sum(1 for other in bids if other == bid)
        best = above + 1
        worst = above + max(tied, 1)
        bests.append(best)
        worsts.append(worst)
        mids.append((best + worst) / 2.0)
    return (min(bests), max(worsts), float(statistics.median(mids)))


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


def observations_at(history, bid):
    """How many times this exact bid has ever been submitted.

    ZERO EVIDENCE AND STRONG EVIDENCE MUST NOT LOOK ALIKE. The tie rates and
    `winning_bumps_at` refuse to answer for a bid nobody has ever submitted,
    precisely so a never-looked-at bid cannot be reported as a confident
    "never tied". Call this first to find out which case you are in without
    handling an exception: $36 sits in the middle of the plausible range and
    has never been bid, while $39 has been bid seven times.

    Unlike the other functions here this one is a pure count of the record,
    so it neither raises on an unobserved bid nor checks the floor.
    """
    # type: (List[SilentBid], int) -> int
    return sum(1 for b in history if b.bid == bid)


def _require_observed(history, bid):
    """Refuse to summarise a bid level nobody has ever submitted."""
    # type: (List[SilentBid], int) -> None
    if observations_at(history, bid):
        return
    submitted = sorted(set(b.bid for b in history))
    below = [v for v in submitted if v < bid]
    above = [v for v in submitted if v > bid]
    raise ValueError(
        "$%d has never been submitted in %d years of bids, so there is no "
        "evidence to summarise - the nearest bids on record are %s and %s. "
        "Call observations_at() to test for this rather than reading a zero "
        "as 'never happened'"
        % (bid, len(set(b.year for b in history)),
           ("$%d" % below[-1]) if below else "nothing below",
           ("$%d" % above[0]) if above else "nothing above"))


def _tie_groups(history):
    """Every (year, bid) at which two or more franchises tied, keyed by both."""
    # type: (List[SilentBid]) -> Dict[Tuple[int, int], List[SilentBid]]
    groups = {}  # type: Dict[Tuple[int, int], List[SilentBid]]
    for b in history:
        groups.setdefault((b.year, b.bid), []).append(b)
    return dict((key, rows) for key, rows in groups.items() if len(rows) >= 2)


def _escalated(group):
    """True when a sealed bump could not settle this tie either.

    STRUCTURAL, from the league rule, not from the `note` prose. The bump only
    breaks a tie if one franchise submitted a strictly larger one; when the top
    bump inside a tie group is shared, the tie escalates to a live auction and
    whatever those rows paid is a live settlement, not a bump anyone could have
    committed to in advance. Agrees with the notes on all fifteen tie groups -
    see `test_the_structural_escalation_signal_agrees_with_every_note`.
    """
    # type: (List[SilentBid]) -> bool
    top = max(b.bump for b in group)
    return sum(1 for b in group if b.bump == top) >= 2


def _years_with_at_least(history, bid, minimum):
    """Fraction of YEARS holding at least `minimum` bids at exactly this level.

    The denominator is years, not rows: five years of history means five
    chances, so something seen in all five scores 1.0.
    """
    # type: (List[SilentBid], int, int) -> float
    per_year = {}  # type: Dict[int, int]
    for b in history:
        per_year.setdefault(b.year, 0)
        if b.bid == bid:
            per_year[b.year] += 1
    hits = sum(1 for count in per_year.values() if count >= minimum)
    return float(hits) / float(len(per_year))


def field_tie_rate_at(history, bid):
    """Fraction of YEARS in which two or more franchises submitted this bid.

    THE FIELD TYING AMONG ITSELF - a fact about the record, and the narrower of
    the two tie statistics here. It asks how often this exact number produced a
    tie between the twelve bids actually submitted. Ranks 11-12 have tied at
    the $26 floor in every year on record, so the floor scores 1.0.

    Read as a bidder's own tie risk it quietly assumes one of those two rows
    was YOURS. That assumption is right for the rank arithmetic in
    `ranks_for_bid` - `worst = above + max(tied, 1)` reproduces 2024's ranks 11
    and 12 at the floor exactly because it inserts you into the tie - but it is
    the wrong question when deciding whether to bid a level at all. Use
    `join_tie_rate_at` for that, and see its docstring for how far the two
    diverge ($30: 40% here, 100% there).

    Raises ValueError for a bid below the floor, for a bid nobody has ever
    submitted (see `observations_at` - 0.0 must mean "never tied", never "never
    looked"), or on an empty history.
    """
    # type: (List[SilentBid], int) -> float
    _require_history(history)
    _check_floor(bid)
    _require_observed(history, bid)
    return _years_with_at_least(history, bid, 2)


def join_tie_rate_at(history, bid):
    """Fraction of YEARS in which SOMEONE WAS ALREADY SITTING at this bid.

    YOUR exposure if you join it - one franchise already there is all it takes
    to put you in a tie, and a tie is settled by a bump or, when the bumps
    match, by a live auction. So the years that matter to a bidder choosing a
    number are the years anybody at all submitted it, not only the years two
    other franchises collided on it.

    ALWAYS >= `field_tie_rate_at`, and the gap is widest exactly where the
    stakes are: $30 has held a bid in all five years (1.0) while only two of
    those years saw two teams there (0.4); $33, $35, $38 and $39 all read 0.8
    against 0.2. Reporting only the narrower number understates the chance of
    needing a bump at four of the five levels the top of this board sits on.

    IT IS STILL THE HISTORICAL FIELD, NOT A PREDICTION of 2026's twelve bids.
    It says how often this number has been occupied, which is the best evidence
    available about whether it will be occupied again. It cannot know who else
    is deciding to move.

    Raises ValueError for a bid below the floor, for a bid nobody has ever
    submitted (0.0 must mean "nobody was ever there", never "never looked"), or
    on an empty history.
    """
    # type: (List[SilentBid], int) -> float
    _require_history(history)
    _check_floor(bid)
    _require_observed(history, bid)
    return _years_with_at_least(history, bid, 1)


def winning_bumps_at(history, bid):
    """Bumps that actually settled a tie at this bid level, ascending.

    Two filters, and both matter:

    1. The amount is `cap_cost - bid`, NOT the `bump` column. A bump is charged
       only when it wins, so a bump that lost - or was never tested - cost
       nothing and does not appear here.
    2. TIES THAT ESCALATED TO A LIVE AUCTION ARE EXCLUDED. When the top bump in
       a tie group is shared, no bump settled anything and the premium those
       rows paid was set live. Reporting those as bumps is how the $35 tie of
       2021 gets misread as "the largest charged bump in the file" when its own
       note says live auction. Use `escalated_at` for that exposure - it is
       real money, but it is not a bump a bidder can plan.

    An empty list means this bid level either never tied, or every tie it drew
    escalated rather than being settled by a bump. It never means "never
    submitted" - that raises.

    Raises ValueError for a bid below the floor, for a bid nobody has ever
    submitted, or on an empty history.
    """
    # type: (List[SilentBid], int) -> List[int]
    _require_history(history)
    _check_floor(bid)
    _require_observed(history, bid)
    bumps = []  # type: List[int]
    for (_, group_bid), rows in _tie_groups(history).items():
        if group_bid != bid or _escalated(rows):
            continue
        bumps.extend(b.charged_bump for b in rows if b.charged_bump > 0)
    return sorted(bumps)


def escalated_at(history, bid):
    """Years in which a tie at this bid escalated to a live auction, sorted.

    The complement of `winning_bumps_at`: these are the ties no sealed bump
    could settle, because the top bump was shared. One third of the bid levels
    showing a charged premium are entirely of this kind - three of nine ($39,
    $35, $33) - and the $26 floor has one such year too, 2022, where both
    franchises bumped $0.

    A bidder can pre-commit a bump; a bidder cannot pre-commit to winning a
    live auction. Report this as escalation risk, never as a bump.

    Raises ValueError for a bid below the floor, for a bid nobody has ever
    submitted, or on an empty history.
    """
    # type: (List[SilentBid], int) -> List[int]
    _require_history(history)
    _check_floor(bid)
    _require_observed(history, bid)
    return sorted(year for (year, group_bid), rows in _tie_groups(history).items()
                  if group_bid == bid and _escalated(rows))
