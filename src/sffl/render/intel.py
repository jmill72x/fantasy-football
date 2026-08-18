"""The facts behind the printed board, gathered from the run that produced it.

The workbook's second worksheet is a legend and a briefing: what the two dollar
columns mean, what this room has actually done with its money, where the model
is weak, and how round one works. It is written for somebody who knows this
league - it explains the numbers, it does not tell anyone how to draft.

WHY THE NUMBERS ARE GATHERED RATHER THAN TYPED. Every figure on that page is a
claim about the board printed beside it. A hardcoded $8.98 or a hardcoded "top
EST$ is $32" is correct exactly once - the day it was measured - and silently
wrong for every re-render after the next extract lands, which is the week
before the auction. So `gather` derives what it can from the objects the render
already has in hand (the league profile, the board rows, the valued pool, the
observed prices, the fitted curve, the tracked bid history), and a fact it
cannot derive comes back None and its sentence says so instead of quoting a
stale number. Three things resist that and are named constants below, each with
its reason.

WHAT DEGRADES. `gather(lg, rows)` alone still produces a usable page: the
column meanings, the flat-price policy, the capital and the bid floor all come
off the league profile and the rows. The market figures need `prices`/`pool`
(i.e. a run with --prices), and the history figures need the tracked bid file.
Where those are missing the page says the run did not measure them - never a
zero, never last month's number.
"""

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sffl.identity import normalize_name
from sffl.silent import (DEFAULT_BIDS, bids_for_rank, load_bid_history,
                         years_on_record)
from sffl.value import _pool_of

# HARDCODED, AND WHY. `calibration/2025.yaml` records its own provenance in a
# generated comment - "# Data: N distinct players, M player-weeks" - and
# yaml.safe_load throws comments away, so no consumer of that file can read it
# back. Parsing a comment out of a data file to put a number on a printed page
# is worse than stating it here: the failure mode of a changed comment format
# would be a wrong number, not a missing one. `test_the_calibration_provenance
# _matches_the_curve_file` reads that header and fails if these drift from it,
# so the file and the page cannot disagree unnoticed.
CALIBRATION_PLAYERS = 48
CALIBRATION_PLAYER_WEEKS = 811

# HARDCODED, AND WHY. The direction of Team QB's residuals is not something any
# shipped function computes: it came out of a one-off analysis of the 2025
# price residuals recorded in NEXT.md ("rushing-QB franchises are under-priced
# (BAL -$28, WAS -$27, PHI -$18); pocket-passer franchises over-priced (DAL
# +$21, CIN +$17, MIN +$16)"). Re-deriving it here would mean re-fitting per
# franchise at render time on the same single year of prices and presenting the
# result as if it were new evidence. The magnitude of the mis-fit IS derived
# (mae, below); this is only its shape, and it is stated as the finding it is.
TQB_UNDERPRICED = ("BAL", "WAS", "PHI")
TQB_OVERPRICED = ("DAL", "CIN", "MIN")

# Which ranks the silent-auction section quotes. Every rank on record would be
# twelve lines on a page that has room for one; these four sample the range
# top to bottom. Any that the history does not hold are dropped rather than
# invented.
SAMPLE_RANKS = (1, 3, 6, 9)


@dataclass
class IntelFacts(object):
    """Everything the intel sheet may state, with None for "not measured".

    None is never 0 and never a default: a missing figure changes the sentence
    that would have carried it (see `sections`), because a page that quotes a
    number the run did not produce is the failure this whole module exists to
    avoid.
    """

    # From the league profile - always available.
    total_capital: int
    league_name: str = ""
    season: Optional[int] = None
    flat_price: Optional[float] = None
    flat_pools: Tuple[str, ...] = ()
    bid_floor: Optional[int] = None

    # From the board rows.
    top_est_price: Optional[float] = None

    # From the market fit (a run with --prices).
    curve: Optional[Tuple[float, float]] = None
    n_prices_loaded: Optional[int] = None
    n_prices_joined: Optional[int] = None
    n_curve_obs: Optional[int] = None
    record_price: Optional[float] = None
    # pool name -> (n joined, mean absolute error of MY$ against price paid)
    mae_by_pool: Dict[str, Tuple[int, float]] = field(default_factory=dict)
    # Flat-priced pools measured against what was really paid for them:
    # {"n", "max_price", "n_at_flat", "kickers", "kickers_at_flat"}
    flat_obs: Optional[Dict[str, float]] = None

    # From the tracked silent-auction bid history.
    years: Optional[int] = None
    round_one_low: Optional[int] = None
    round_one_high: Optional[int] = None
    record_bid: Optional[int] = None
    # (rank, lowest bid that bought it, highest bid that bought it)
    rank_bids: List[Tuple[int, int, int]] = field(default_factory=list)
    floor_ranks: Tuple[int, ...] = ()


def _mae_by_pool(pool, prices):
    """{pool: (n, mae)} - MY$ against what was really paid, per pool.

    Computed off the pool as it stands AFTER the chosen policy has priced it,
    not off `fit.choose_policy`'s report: the report exists only under
    `--policy fit`, and `score_fit` re-prices the pool as a side effect. This
    measures the board actually being printed, which is the only board the
    page's reader can act on.
    """
    errs = {}  # type: Dict[str, List[float]]
    for p in pool:
        if "_dollars" not in p.stats:
            continue
        key = normalize_name(p.name)
        if key not in prices:
            continue
        errs.setdefault(_pool_of(p.pos), []).append(
            abs(float(p.stats["_dollars"]) - float(prices[key])))
    return dict((name, (len(v), sum(v) / len(v)))
                for name, v in errs.items() if v)


def _flat_pool_observations(lg, pool, prices):
    """What the room really paid for the pools this board prices flat.

    The flat $1 on kickers and defenses is a policy decision, and the evidence
    for it is prices, not projections - so the page cites the prices. Returns
    None when nothing joined, never a dict of zeros.
    """
    paid = []  # type: List[Tuple[str, float]]
    for p in pool:
        if _pool_of(p.pos) not in lg.flat_priced_pools:
            continue
        key = normalize_name(p.name)
        if key in prices:
            paid.append((p.pos, float(prices[key])))
    if not paid:
        return None
    flat = float(min(lg.flat_priced_pools.values()))
    kickers = [price for pos, price in paid if pos == "K"]
    return {
        "n": len(paid),
        "max_price": max(price for _pos, price in paid),
        "n_at_flat": sum(1 for _pos, price in paid if price == flat),
        "kickers": len(kickers),
        "kickers_at_flat": sum(1 for price in kickers if price == flat),
    }


def _history_facts(facts, history):
    """Fill the silent-auction figures from the tracked bid file."""
    facts.years = years_on_record(history)

    per_year = {}  # type: Dict[int, int]
    for b in history:
        per_year[b.year] = per_year.get(b.year, 0) + b.cap_cost
    facts.round_one_low = min(per_year.values())
    facts.round_one_high = max(per_year.values())
    # The record is what was CHARGED (cap_cost), not what was bid: a tie won
    # by a bump costs more than the bid that entered it.
    facts.record_bid = max(b.cap_cost for b in history)

    ranks = sorted(set(b.rank for b in history))
    for rank in SAMPLE_RANKS:
        if rank not in ranks:
            continue
        low, high, _median = bids_for_rank(history, rank)
        facts.rank_bids.append((rank, low, high))

    if facts.bid_floor is not None:
        facts.floor_ranks = tuple(
            r for r in ranks
            if all(b.bid == facts.bid_floor for b in history if b.rank == r))


def gather(lg, rows, pool=None, prices=None, curve=None, history=None,
           bids_path=DEFAULT_BIDS):
    """Everything the intel sheet may state about THIS render.

    `pool` and `prices` come from the valuation run (`sffl.cli._value_pool`);
    without them the market figures are simply absent. `history` defaults to
    loading the tracked bid file, and a missing or malformed one degrades that
    section rather than failing the render - the board is the artifact that
    must exist on auction day, and this page is a legend for it.
    """
    facts = IntelFacts(total_capital=lg.total_capital(),
                       league_name=lg.name, season=lg.season)

    if lg.flat_priced_pools:
        facts.flat_pools = tuple(sorted(lg.flat_priced_pools))
        facts.flat_price = float(min(lg.flat_priced_pools.values()))
    floor = (lg.silent_auction or {}).get("bid_floor")
    facts.bid_floor = int(floor) if floor is not None else None

    ests = [r.est_price for r in rows if r.est_price is not None]
    if ests:
        facts.top_est_price = max(ests)

    if curve is not None:
        facts.curve = (float(curve[0]), float(curve[1]))

    if prices is not None and pool:
        facts.n_prices_loaded = getattr(prices, "total_rows", None) or len(prices)
        joined = [p for p in pool if normalize_name(p.name) in prices]
        facts.n_prices_joined = len(joined)
        # The curve is fit on the non-flat joins only (see sffl.market): a
        # flat-priced player's _dollars is the policy restated, not market
        # evidence, so quoting the whole join count as the fit's base would
        # overstate it by ~24 observations.
        facts.n_curve_obs = sum(
            1 for p in joined if _pool_of(p.pos) not in lg.flat_priced_pools)
        if prices:
            facts.record_price = max(prices.values())
        facts.mae_by_pool = _mae_by_pool(pool, prices)
        facts.flat_obs = _flat_pool_observations(lg, pool, prices)

    if history is None:
        try:
            history = load_bid_history(bids_path)
        except (OSError, ValueError):
            history = None
    if history:
        _history_facts(facts, history)

    return facts


# --------------------------------------------------------------------------
# The prose. One place, so the wording and the numbers cannot drift apart.
# --------------------------------------------------------------------------

def _money(value):
    """$41 for a whole number, $41.50 otherwise - never $41.0.

    Thousands are grouped ($1,320): the only four-figure number on the page is
    the league's whole capital, and it is read there as a headline.
    """
    if value is None:
        return "?"
    if abs(value - round(value)) < 0.005:
        return "${:,}".format(int(round(value)))
    return "$%.2f" % value


def _dollar_columns(f):
    items = [
        ("MY$", "What a player is worth against replacement, in this "
                "league's %s of capital. A value, not a price."
                % _money(f.total_capital)),
    ]

    if f.curve is not None and f.n_curve_obs:
        joined = (" of the %d that join this board" % f.n_prices_joined
                  if f.n_prices_joined else "")
        est = ("What the room is likely to actually pay: that value bent onto "
               "this league's own price curve (price = %.2f x value^%.2f), "
               "fitted on %d real 2025 prices%s. Flat-priced kickers and "
               "defenses are left out of the fit."
               % (f.curve[0], f.curve[1], f.n_curve_obs, joined))
    else:
        est = ("What the room is likely to actually pay. This run fitted no "
               "price curve, so EST$ is blank on the board rather than "
               "guessed.")
    items.append(("EST$", est))

    items.append(
        ("Gap", "The gap between the two columns is the edge: MY$ well above "
                "EST$ is a player worth more than he should cost."))

    floor = ("EST$ is a FLOOR at the very top, not a point estimate. The fit "
             "is concave, so it compresses the top of the board")
    if f.top_est_price is not None and f.record_price is not None:
        floor += (": the highest EST$ here is %s against a %s record price in "
                  "this league. The most expensive player runs above his "
                  "estimate." % (_money(round(f.top_est_price)),
                                 _money(f.record_price)))
    elif f.top_est_price is not None:
        floor += (": the highest EST$ here is %s, and the top of this league's "
                  "market has run above the estimate every year it has been "
                  "checked." % _money(round(f.top_est_price)))
    else:
        floor += ", and the single most expensive player runs above his estimate."
    items.append(("Floor", floor))
    return ("THE TWO DOLLAR COLUMNS", items)


def _other_columns(f):
    return ("THE OTHER COLUMNS", [
        ("Tier", "Natural breaks in dollar value inside a position group, not "
                 "fixed bands. The gap to the next tier is what it costs to "
                 "miss this player."),
        ("Pos", "Position and rank within it (WR12). WR and TE are ONE pool "
                "for value everywhere else in this pipeline; this label is "
                "the only place they are counted apart."),
        ("Team/Bye", "NFL franchise and bye week."),
        ("AVG", "Projected points per game, this league's scoring."),
    ])


def _the_room(f):
    items = []

    if f.flat_obs and f.flat_price is not None:
        obs = f.flat_obs
        kicker_clause = ""
        if obs["kickers"]:
            kicker_clause = (" and %d of the %d kickers among them went at "
                             "exactly %s"
                             % (obs["kickers_at_flat"], obs["kickers"],
                                _money(f.flat_price)))
        items.append(("K & DST",
                      "Kickers and defenses go for %s. Of the %d observed "
                      "prices that join one, none is above %s%s. Both pools "
                      "are priced flat at %s on the board for that reason."
                      % (_money(f.flat_price), obs["n"],
                         _money(obs["max_price"]), kicker_clause,
                         _money(f.flat_price))))
    elif f.flat_price is not None:
        items.append(("K & DST",
                      "Kickers and defenses (%s) are priced flat at %s on the "
                      "board - this league treats both as fungible fillers. "
                      "This run joined no observed prices, so the supporting "
                      "counts are not shown."
                      % ("/".join(f.flat_pools), _money(f.flat_price))))

    top = "The top of the board is compressed."
    if f.record_price is not None:
        top += " The highest price in the observed price file is %s." % _money(
            f.record_price)
    if f.record_bid is not None and f.years:
        top += (" The most any franchise has been charged in %d years of "
                "sealed round-one bids is %s." % (f.years, _money(f.record_bid)))
    if f.record_price is None and f.record_bid is None:
        top += (" No observed prices were available to this run, so no record "
                "is quoted.")
    items.append(("Top end", top))

    if f.round_one_low is not None and f.years:
        items.append(("Round 1",
                      "Roughly a third of all league capital goes in the "
                      "silent auction's first round: %s-%s of %s in each of "
                      "the %d years on record."
                      % (_money(f.round_one_low), _money(f.round_one_high),
                         _money(f.total_capital), f.years)))
    else:
        items.append(("Round 1",
                      "The silent auction's first round takes a large share "
                      "of league capital. No bid history was readable on this "
                      "run, so the share is not quoted."))
    return ("WHAT THIS ROOM DOES - FROM ITS OWN PRICES", items)


def _model_weakness(f):
    items = []

    tqb = f.mae_by_pool.get("TQB")
    flex = f.mae_by_pool.get("FLEX")
    if tqb and flex:
        lead = ("Team QB fits worst: MY$ misses the price paid by %s on "
                "average (n=%d) against %s for the skill pool (n=%d)."
                % (_money(round(tqb[1], 2)), tqb[0],
                   _money(round(flex[1], 2)), flex[0]))
    else:
        lead = ("Team QB is the worst-fitting pool on this board. This run "
                "joined no prices, so the size of the miss is not quoted.")
    items.append(("Team QB",
                  lead + " The errors are structured, not noise: rushing-QB "
                  "franchises (%s) come out UNDER-priced by the model, "
                  "pocket-passer franchises (%s) OVER-priced. Judgment beats "
                  "the number there."
                  % (", ".join(TQB_UNDERPRICED), ", ".join(TQB_OVERPRICED))))

    items.append(("Curves",
                  "The scoring calibration behind every projection is built "
                  "from %d players of 2025 weekly data (%d player-weeks). "
                  "Enough to prove the mechanism, thin enough to hold loosely."
                  % (CALIBRATION_PLAYERS, CALIBRATION_PLAYER_WEEKS)))

    items.append(("DST sacks",
                  "Defense sack scoring is structurally zeroed in the season "
                  "model - a documented limitation, not a surprise. It does "
                  "not reach DST dollars, which are flat %s by policy."
                  % _money(f.flat_price if f.flat_price is not None else 1)))
    return ("WHERE THE MODEL IS WEAK", items)


def _the_silent_pick(f):
    items = []

    floor = _money(f.bid_floor) if f.bid_floor is not None else "the floor"
    items.append(("Mechanic",
                  "Sealed bid, floor %s. Bids are ranked high to low; every "
                  "franchise pays its OWN bid and picks in that order, "
                  "highest first. A bid under the floor is discarded and the "
                  "team forfeits its round-one pick." % floor))

    items.append(("The split",
                  "Jeff submits the sealed bid himself before travelling. The "
                  "pick that bid buys is the surrogate's."))

    items.append(("The board",
                  "The Board sheet's OVERALL block is ranked by MY$ across "
                  "TQB/RB/WR/TE, so the best available by MY$ is the highest "
                  "name on it nobody has taken. Kickers and defenses are not "
                  "in that block by design."))

    rank_clause = ""
    if f.rank_bids:
        rank_clause = " ".join(
            "rank %d has cost %s-%s;" % (rank, _money(low), _money(high))
            for rank, low, high in f.rank_bids).rstrip(";") + "."
    floor_clause = ""
    if f.floor_ranks and f.bid_floor is not None:
        if len(f.floor_ranks) > 1:
            spread = "Ranks %d-%d" % (min(f.floor_ranks), max(f.floor_ranks))
        else:
            spread = "Rank %d" % f.floor_ranks[0]
        floor_clause = (" %s have sat at the %s floor in every year on record, "
                        "so the sealed bump decides them."
                        % (spread, _money(f.bid_floor)))
    if rank_clause and f.years:
        items.append(("The rank",
                      "What rank a bid buys is not knowable until the bids "
                      "are opened. Over %d years on record: %s%s"
                      % (f.years, rank_clause, floor_clause)))
    else:
        items.append(("The rank",
                      "What rank a bid buys is not knowable until the bids "
                      "are opened, and no bid history was readable on this "
                      "run to say what each rank has cost before."))
    return ("ROUND ONE - THE SILENT AUCTION PICK", items)


def title(f):
    """The sheet's headline. Names the season, so a page that outlives the
    auction it was printed for cannot be mistaken for this year's."""
    if f.season:
        return "KEY & INTEL - %d BOARD" % f.season
    return "KEY & INTEL"


def subtitle(f):
    """One line under the title, naming what this page is and is not."""
    return ("What the Board sheet's columns mean, what this room has done with "
            "its money, and where the model is weak. Every figure below is "
            "measured from the same run that printed the board beside it. "
            "Context, not instructions - the picks are the drafter's call.")


def left_sections(f):
    """The sections in the left-hand column, top to bottom."""
    return [_dollar_columns(f), _other_columns(f), _the_room(f)]


def right_sections(f):
    """The sections in the right-hand column, top to bottom."""
    return [_model_weakness(f), _the_silent_pick(f)]


def sections(f):
    """Every section, in reading order - left column first, then right."""
    return left_sections(f) + right_sections(f)
