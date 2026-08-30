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

WHICH MODEL PRICED EST$, AND FROM WHEN. A curve fit fresh from this run's own
--prices and a curve applied from a persisted `MarketModel` (--market) are the
same (a, b) tuple - nothing about the shape says which one it is, or what
season an applied one came from. `gather`'s `market` argument (the loaded
`MarketModel` itself, only ever available on an applied run) is the one way to
learn an applied model's season, fit date and observation count; failing that,
whether `prices` is `None` still tells `gather` an in-process fit apart from
an applied one, because `sffl.cli._value_pool` leaves `prices` `None` on every
--market run. See `_market_provenance` and the "Model" item in
`_dollar_columns` - a reader looking at EST$ has no other way to tell a
year-matched curve from one carried over from a season this board is not.
"""

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sffl.identity import normalize_name
from sffl.render.rows import overall_board
from sffl.silent import (DEFAULT_BIDS, bids_for_rank, load_bid_history,
                         years_on_record)
from sffl.value import _pool_of

# How many of the top OVERALL names the "if the news moves" item reasons over.
# Four is the shallowest depth that can show a drop-off if there is one: it
# spans the whole top-3 zone a high sealed bid buys, plus the first name past
# it. See `_top_cluster`.
TOP_CLUSTER_DEPTH = 4

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

# REMOVED 2026-08-27: TQB_UNDERPRICED / TQB_OVERPRICED.
#
# They named six franchises and told the reader that RUSHING-QB franchises come
# out under-priced and POCKET-PASSER ones over-priced. Measured year-matched
# against the 2026 prices all six do land in the claimed direction - and the
# explanation is still wrong. corr(MY$, residual) over all 21 Team QB units is
# 0.773 (r^2 0.598), and the six named franchises are simply the extremes of
# the MY$ distribution: all three "rushing" ones price at the $1 replacement
# floor, all three "pocket" ones above $14. Nine of the nine units at the floor
# are under-priced, not merely the three named.
#
# So the pattern is real and the cause was invented. What the model actually
# does is OVER-DISPERSE Team QB dollars - it drives some franchises to $1 and
# others past $40 while the room pays a much narrower band. That is derivable
# from the run, so `_tqb_dispersion` derives it and nothing here is frozen.
#
# The general lesson, learned twice in one week (see also market.py): a
# coherent causal story fitted to a pattern a duller explanation covers better.

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
    # The top few OVERALL names as (name, MY$), best first. Feeds the one item
    # on the page about a board that has gone stale between printing and
    # auction day - see `_the_silent_pick`.
    top_cluster: Tuple[Tuple[str, float], ...] = ()

    # From the market fit (a run with --prices).
    curve: Optional[Tuple[float, float]] = None
    n_prices_loaded: Optional[int] = None
    n_prices_joined: Optional[int] = None
    n_curve_obs: Optional[int] = None
    record_price: Optional[float] = None
    # Which model produced `curve`, and from when - see `_market_provenance`.
    # True: `curve` was APPLIED from a persisted `MarketModel` (--market).
    # False: `curve` was FIT in this run, from this run's own --prices.
    # None: no curve at all - the two market fields below stay None too.
    market_applied = None  # type: Optional[bool]
    # The model's own season. Always known when `curve` was fit in-process
    # (it is this run's own `season`, by construction). Known for an applied
    # model only when `gather` was handed the `MarketModel` itself - the
    # curve tuple alone carries no season, which is the exact fact this field
    # exists to report honestly as unmeasured rather than assume "current".
    market_season: Optional[int] = None
    # The date string a persisted model records it was fitted on. Only ever
    # known for an applied model whose `MarketModel` was passed in.
    market_fitted_on: Optional[str] = None
    # How many real prices the curve in use was fitted against - THIS run's
    # `n_curve_obs` for an in-process fit, or the persisted model's own
    # recorded `evidence["observations"]` for an applied one.
    market_n_obs: Optional[int] = None
    # market_season != this board's season. None (not False) until
    # market_season is itself known - "not cross-season" is a claim that
    # needs a season to compare against, not a default.
    market_cross_season: Optional[bool] = None
    # pool name -> (n joined, mean absolute error of MY$ against price paid)
    mae_by_pool: Dict[str, Tuple[int, float]] = field(default_factory=dict)
    # {"median","n_low","n_low_under","n_high","n_high_over"} - see
    # `_tqb_dispersion`. None when too few Team QB units carry a price.
    tqb_dispersion = None  # type: Optional[Dict[str, float]]
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


def _top_cluster(rows):
    """The top few OVERALL names as (name, MY$), best first.

    Ranked through `overall_board` rather than by re-sorting `rows` here, so
    this cannot disagree with the block the page tells the drafter to read.
    """
    return tuple((r.name, float(r.my_dollars))
                 for r in overall_board(rows)[:TOP_CLUSTER_DEPTH])


def _tqb_dispersion(pool, prices):
    """How the Team QB pool's errors line up with its own MY$ scale.

    Splits the priced TQB units at their MEDIAN MY$ - a split the data picks
    rather than a threshold anyone typed - and counts how many on each side
    miss in the expected direction. Returns None below four units, where a
    median split says nothing.
    """
    pairs = []
    for p in pool:
        if _pool_of(p.pos) != "TQB" or "_dollars" not in p.stats:
            continue
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((float(p.stats["_dollars"]), float(prices[key])))
    if len(pairs) < 4:
        return None
    mid = statistics.median([m for m, _ in pairs])
    low = [(m, a) for m, a in pairs if m < mid]
    high = [(m, a) for m, a in pairs if m > mid]
    if not low or not high:
        return None
    return {
        "median": mid,
        "n_low": len(low),
        "n_low_under": sum(1 for m, a in low if m < a),
        "n_high": len(high),
        "n_high_over": sum(1 for m, a in high if m > a),
    }


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


def _market_provenance(lg, prices, market, n_curve_obs):
    """Which model produced this run's curve, and from when.

    `curve` (a, b) is silent about its own origin - both an in-process fit
    and an applied persisted model produce the exact same tuple shape. Two
    signals distinguish them, and only two:

      - `market`, when the caller passes the loaded `MarketModel` itself
        (`sffl.market_model.load`'s return value, or anything duck-typed the
        same way: `.season`, `.fitted_on`, `.evidence`). This is the only way
        to learn an APPLIED model's season, fit date or observation count -
        none of that survives into the bare curve tuple `_value_pool` returns
        today, so without it those facts are correctly None, not guessed.
      - `prices`, which `sffl.cli._value_pool` leaves `None` on a `--market`
        run and populated on a `--prices` run (see its own docstring) - so
        "prices is not None" is itself evidence this run fit the curve fresh,
        year-matched by construction (`load_prices`'s season guard already
        enforces that upstream, before `gather` ever sees the result).

    Returns `(applied, season, fitted_on, n_obs, cross_season)`, every one of
    them `None` except `applied` when the run gave `gather` no way to know
    the season a persisted model came from.
    """
    if market is not None:
        season = getattr(market, "season", None)
        fitted_on = getattr(market, "fitted_on", None)
        evidence = getattr(market, "evidence", None) or {}
        n_obs = evidence.get("observations")
        cross = (season != lg.season) if season is not None else None
        return True, season, fitted_on, n_obs, cross
    if prices is not None:
        # Fit in this run, from this run's own prices - by construction the
        # model's season IS this board's season, and it is not a cross-season
        # apply. Nothing here is assumed: load_prices refuses any prices file
        # whose own season or TQB-starter map disagrees with `--year`.
        return False, lg.season, None, n_curve_obs, False
    # A curve exists (the caller only reaches `gather`'s market block when it
    # does) but neither signal above fired - a --market apply whose loaded
    # MarketModel was not threaded through to `gather`. Still knowable as
    # "applied" (it is the one remaining way `_value_pool` sets a curve with
    # `prices` left None); everything about WHICH model is honestly None.
    return True, None, None, None, None


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


def gather(lg, rows, pool=None, prices=None, curve=None, market=None,
           history=None, bids_path=DEFAULT_BIDS):
    """Everything the intel sheet may state about THIS render.

    `pool` and `prices` come from the valuation run (`sffl.cli._value_pool`);
    without them the market figures are simply absent. `history` defaults to
    loading the tracked bid file, and a missing or malformed one degrades that
    section rather than failing the render - the board is the artifact that
    must exist on auction day, and this page is a legend for it.

    `market` is the loaded `MarketModel` (`sffl.market_model.load`'s return
    value) when this run applied a persisted one (`--market`); leave it None
    for an in-process fit or when no curve was fitted at all. It is the only
    way this page can name an applied model's own season, fit date and
    observation count - see `_market_provenance`.
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

    facts.top_cluster = _top_cluster(rows)

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
        facts.tqb_dispersion = _tqb_dispersion(pool, prices)

    if facts.curve is not None:
        (facts.market_applied, facts.market_season, facts.market_fitted_on,
         facts.market_n_obs, facts.market_cross_season) = _market_provenance(
            lg, prices, market, facts.n_curve_obs)

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


def _market_model_text(f):
    """Which market model priced EST$, and from which season.

    The one place this page states the curve's full provenance in one spot -
    season, coefficients, observation count, and (when known) whether this is
    a cross-season apply - so a reader does not have to piece it together
    from the EST$ sentence. Every clause degrades to naming what this run did
    NOT record rather than omitting the fact silently or guessing "current
    season" for an applied model whose own season is unknown here - see
    `_market_provenance`.
    """
    if f.curve is None:
        return "No curve was fitted this run, so no model priced this board."

    coeffs = "a=%.2f, b=%.2f" % f.curve

    if not f.market_applied:
        # Fit in-process, this run: the season and "not cross-season" are
        # known by construction (see `_market_provenance`), never guessed.
        obs = ("%d" % f.market_n_obs) if f.market_n_obs is not None else "an unrecorded number of"
        return ("%s, fit fresh this run from %s of this %s board's own "
                "prices - year-matched by construction."
                % (coeffs, obs, f.season if f.season is not None else "this"))

    # Applied from a persisted model (--market).
    if f.market_season is None:
        return ("%s, applied from a persisted market model - this run did "
                "not record its season, fit date or observation count." % coeffs)

    obs = ("%s" % f.market_n_obs) if f.market_n_obs is not None else "an unrecorded number of"
    fitted = (", fitted %s" % f.market_fitted_on) if f.market_fitted_on else ""
    if f.market_cross_season:
        return ("%s, the persisted %d model (n=%s%s) - a CROSS-SEASON apply "
                "onto this %s board, not a year-matched fit."
                % (coeffs, f.market_season, obs, fitted,
                   f.season if f.season is not None else "this"))
    return ("%s, the persisted %d model (n=%s%s), year-matched to this board."
            % (coeffs, f.market_season, obs, fitted))


def _dollar_columns(f):
    items = [
        ("MY$", "What a player is worth against replacement, in this "
                "league's %s of capital. A value, not a price."
                % _money(f.total_capital)),
    ]

    if f.curve is not None:
        curve_desc = "price = %.2f x value^%.2f" % (f.curve[0], f.curve[1])
        if f.market_applied:
            # An APPLIED model: `n_curve_obs` is not this run's to claim - see
            # `_market_provenance`. Was previously mis-tested here on
            # `f.n_curve_obs`, which is None on a --market run (prices stays
            # None), so this branch used to fall through to the "fitted no
            # price curve" sentence below and tell the reader EST$ was blank
            # when it was not.
            est = ("What the room is likely to actually pay: value bent onto "
                   "a market curve (%s). Flat-priced K/DST excluded. See "
                   "\"Model\" for which one and its season."
                   % curve_desc)
        else:
            joined = (" of %d joining" % f.n_prices_joined
                      if f.n_prices_joined else "")
            est = ("What the room is likely to actually pay: value bent onto "
                   "this league's own curve, fit fresh this run (%s) on %d "
                   "real prices%s. Flat-priced K/DST excluded."
                   % (curve_desc, f.n_curve_obs or 0, joined))
    else:
        est = ("What the room is likely to actually pay. This run fitted no "
               "price curve, so EST$ is blank on the board rather than "
               "guessed.")
    items.append(("EST$", est))

    items.append(("Model", _market_model_text(f)))

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
    d = f.tqb_dispersion
    if d:
        shape = (" The errors are structured, not noise: the model spreads "
                 "Team QB dollars WIDER than the room pays. Of the %d units it "
                 "prices below %s, %d went for more than it says; of the %d "
                 "above, %d went for less. Trust a Team QB number less the "
                 "further it sits from the middle."
                 % (d["n_low"], _money(round(d["median"], 2)),
                    d["n_low_under"], d["n_high"], d["n_high_over"]))
    else:
        shape = (" This run priced too few Team QB units to say which way its "
                 "errors run.")
    items.append(("Team QB", lead + shape))

    items.append(("Curves",
                  "The scoring calibration behind every projection is built "
                  "from %d players of 2025 weekly data (%d player-weeks). "
                  "Widening it further was tried and measured WORSE, so this "
                  "is the depth that fits best, not the depth we ran out of "
                  "time to improve."
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

    # A board is priced days before it is used, and this one cannot be
    # re-priced: Jeff travels before the auction. So the page has to say what
    # to do about news the board could not contain. Whether the top is tight
    # or a cliff changes that advice, so it is measured, not assumed.
    if len(f.top_cluster) >= 2:
        (first, top_v), (second, next_v) = f.top_cluster[0], f.top_cluster[1]
        gap = top_v - next_v
        span = top_v - f.top_cluster[-1][1]
        shape = ("%s (%s) and %s (%s) are %s apart, top %d span %s"
                 % (first, _money(round(top_v, 1)), second,
                    _money(round(next_v, 1)), _money(round(gap, 1)),
                    len(f.top_cluster), _money(round(span, 1))))
        if top_v > 0 and gap >= 0.15 * top_v:
            verdict = ("a real drop-off, so losing the top name costs more "
                       "than one rank of value")
        else:
            verdict = ("no gap worth defending - a name lost off the top "
                       "costs less than its rank suggests, the next is "
                       "near-equivalent, not a cliff")
        # Term stays <=10 characters - the workbook's term column is 10 units
        # wide and `xlsx` raises rather than letting a label bleed.
        items.append(("Snapshot",
                      "Priced before auction night, not after: news that "
                      "broke later is not in it, so a high rank here is not "
                      "evidence a player is active. %s - %s."
                      % (shape, verdict)))

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
