"""Command line entry point.

    python -m sffl.cli ingest --source sources/draftsharks.yaml \
        --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import textwrap
import warnings

from sffl.calibrate import load_curves
from sffl.fit import (DEFAULT_TQB_STARTERS, SeasonMismatchError,
                      UnverifiedPricesSeasonWarning, choose_policy,
                      load_prices)
from sffl.identity import NFL_TEAMS, normalize_name
from sffl.league import load_league
from sffl.market import assign_expected_prices, fit_price_curve
from sffl.plan import pick_range, plan_bids, tie_cells
from sffl.pool import build_pool, score_season_calibrated
from sffl.render.intel import gather as gather_intel
from sffl.render.pdf import render_pdf
from sffl.render.rows import DEFAULT_BYES, build_rows, load_byes
from sffl.render.xlsx import render_xlsx
from sffl.silent import DEFAULT_BIDS, load_bid_history
from sffl.value import _pool_of, assign_dollars, assign_vorp, replacement_levels

DEFAULT_LEAGUE = "leagues/sffl/2026.yaml"

# `sffl alert`'s CBS URLs.
#
# ROSTER: bare /teams, with NO team number. CBS resolves it to whoever is
# logged in - identity-derived, so it can never drift onto another manager's
# team the way a hardcoded /teams/<N> could.
#
# PROJECTIONS: week-parameterised AND scope-parameterised. Built from
# --week and a group's CBS "scope" token rather than accepting a hardcoded
# URL, so a new week never requires editing a URL by hand (and can never
# silently run against last week's page because someone forgot to) and
# scoring an eighth lineup slot never requires a second hand-written URL
# literal that could drift out of sync with this one.
CBS_LEAGUE_BASE = "https://stripesfantasyfootballleague.football.cbssports.com"
DEFAULT_TEAM_URL = CBS_LEAGUE_BASE + "/teams"
# `print_rows` IS LOAD-BEARING, not a tuning knob. Without it CBS returns
# exactly 100 player rows - its default page size - and every rostered
# player outside CBS's top 100 silently has NO projection at all. That is
# not hypothetical: the 2026-08-30 dry run had THREE of Jeff's thirteen
# (TreVeyon Henderson, Rhamondre Stevenson, Courtland Sutton) missing for
# exactly this reason, reported as "no projection row - data problem" when
# the real cause was a page-size cap nobody had looked for. It stayed
# invisible until the BENCH board started naming all thirteen, because the
# three were reserves and the digest only ever named the eight it started.
#
# 9999, NOT the 999 that CBS's own "All" pagination link uses: 999 was
# measured to still return 100 rows, while 9999 returns the full 1710-row
# RB/WR/TE universe (verified live 2026-08-30, and all 1710 parse). Applied
# to EVERY group, not just RB-WR-TE - K is currently 98 rows, two under the
# cap, and would begin truncating silently the moment CBS listed two more
# kickers.
PROJECTIONS_PAGE_ROWS = 9999
PROJECTIONS_URL_TEMPLATE = (
    CBS_LEAGUE_BASE + "/stats/stats-main/all:%s/%d:p/standard/projections"
    "?print_rows=%d")

# The four position-group pages `sffl alert` captures and merges into one
# pool, in the order they are captured - and the CBS URL "scope" token each
# one lives at, which is NOT always the same string as the group's own name
# (RB-WR-TE's scope is "RB:WR:TE", colon-joined; the others are their own
# name). `sources/cbs-weekly.yaml` owns what each group's PAGE COLUMNS mean;
# this dict is the only place that owns what each group's URL looks like -
# one mapping, so a fifth group later needs one new entry here, not a
# hand-written URL literal added at each call site.
ALERT_GROUPS = ("RB-WR-TE", "TQB", "K", "DST")
GROUP_SCOPES = {
    "RB-WR-TE": "RB:WR:TE",
    "TQB": "TQB",
    "K": "K",
    "DST": "DST",
}

# Which `PlayerProjection.pos` (and `cbs_roster` slot) values each group
# covers, when it succeeds. `_cmd_alert` uses this to tell a TRANSIENT
# failure (this run's page for K failed, so a K starter was not scored
# TODAY) apart from a PERMANENT scope limit (no group covers this position
# at all) - conflating the two, fixed 2026-08-30 after a reviewer caught it,
# made a K page that 404s for one run read as "this tool has never captured
# kickers," which is false and hides the actual, one-run, fixable failure.
GROUP_POSITIONS = {
    "RB-WR-TE": frozenset(("RB", "WR", "TE")),
    "TQB": frozenset(("TQB",)),
    "K": frozenset(("K",)),
    "DST": frozenset(("DST",)),
}


# Rest-of-season pages, for the Friday digest's trade block. Same scopes and
# the same row-count parameter as the weekly URL; only the period token
# differs. `restofseason` is CBS's own - verified live 2026-09-01, and
# pre-season it returns the same figures as `season`, which is what
# rest-of-season MEANS on day zero.
ROS_URL_TEMPLATE = (
    CBS_LEAGUE_BASE + "/stats/stats-main/all:%s/restofseason:p/standard/"
    "projections?print_rows=%d")

# The `-ROS` profile group for each weekly one. The rest-of-season pages
# carry an extra FPTS/G column, so reusing a weekly map reads every field one
# place out - see sources/cbs-weekly.yaml's REST OF SEASON block.
ROS_GROUPS = dict((g, g + "-ROS") for g in ALERT_GROUPS)


def _ros_url(group):
    """The CBS rest-of-season URL for one position group's page."""
    return ROS_URL_TEMPLATE % (GROUP_SCOPES[group], PROJECTIONS_PAGE_ROWS)


def _projections_url(group, week):
    """The CBS weekly-projections URL for one position group's page.

    The ONLY function that turns a (group, week) pair into a URL - see
    PROJECTIONS_URL_TEMPLATE and GROUP_SCOPES above.
    """
    return PROJECTIONS_URL_TEMPLATE % (GROUP_SCOPES[group], week,
                                       PROJECTIONS_PAGE_ROWS)


def _banner(title, body):
    """Print an unmissable block. Used where a run must SAY what it could not check.

    Wrapped and indented rather than one long line because the messages that
    matter here are paragraphs, and a paragraph printed as a single 600-column
    line is, in a terminal, a way of not saying it.
    """
    print("")
    print("  ** %s **" % title)
    for line in textwrap.wrap(body, 74):
        print("     " + line)
    print("")


def _load_prices_announcing(path, tqb_starters_path, season):
    """`fit.load_prices`, with its unverifiable-season warning PRINTED.

    `load_prices` raises the warning so no caller can bypass it (Decision 3),
    but a `warnings.warn` is easy to miss in a terminal full of a valuation's
    own output - and this particular silence is the exact thing the branch
    exists to end. So the CLI catches it and prints it as a banner, in the
    same stream as the numbers it qualifies.

    Only this module's own warning is intercepted. Anything else raised
    inside is re-emitted untouched: swallowing an unrelated DeprecationWarning
    to make room for this one would be the same mistake in miniature.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prices = load_prices(path, tqb_starters_path=tqb_starters_path,
                             season=season)
    for w in caught:
        if issubclass(w.category, UnverifiedPricesSeasonWarning):
            _banner("UNVERIFIED PRICES SEASON", str(w.message))
        else:
            warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)
    return prices


def _value_pool(lg, args):
    """Build a pool and run it through the full valuation path: vendor
    extract -> calibration curves -> replacement policy -> VORP/dollars ->
    (if prices are supplied) the market price curve.

    Shared by cmd_value and cmd_render so the two commands can never price
    the same player differently - duplicating this path would let a fix or a
    calibration change land in one command's copy and not the other's.

    Returns (pool, curve, prices, market) on success. `market` is the loaded
    `MarketModel` (see `sffl.market_model.load`) when this run applied one via
    `--market`, else None - callers that need to name which model priced the
    board (see `sffl.render.intel.gather`'s `market=` argument) must carry
    this fourth element out; the 3-tuple this used to return had no way to.
    Returns None after printing why on the one recoverable failure
    (`--policy fit` without `--prices`) - the caller should print nothing
    further and return 1.

    `--market <path>` APPLIES a model persisted earlier by `fit-market`
    instead of fitting one from `--prices` in this run. The two are mutually
    exclusive: one fits, one applies, and asking for both in a single run is
    the exact confusion this split exists to end. With a model supplied, its
    persisted policy is used (`choose_policy` never runs, so `--policy fit`
    needs no prices at all) and its persisted curve is applied directly -
    `prices` stays None, matching the "no --prices supplied" shape everywhere
    downstream.
    """
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    if args.curves:
        curves = load_curves(args.curves)
        for p in pool:
            p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
        pool.sort(key=lambda p: -p.stats["_season_points"])

    market = None
    if getattr(args, "market", None):
        if args.prices:
            raise SystemExit(
                "--market and --prices are mutually exclusive: --market "
                "APPLIES a model fitted earlier, --prices FITS one now. "
                "Passing both is asking to fit and apply in the same run, "
                "which is the confusion this split exists to end. Use "
                "--prices with `sffl fit-market` to produce a model, then "
                "--market to price a board with it.")
        from sffl.market_model import describe
        from sffl.market_model import load as load_market
        market = load_market(args.market)
        # ANNOUNCED EVERY RUN, and loudly when the seasons differ. A curve
        # silently older than the board it prices is the failure this split
        # was built to design out - permitting the cross-season apply is only
        # safe because it is impossible to do accidentally.
        print("  " + describe(market))
        if market.season != args.year:
            print("  NOTE: this is a CROSS-SEASON apply - a %d model pricing "
                  "%d projections. That is intended (last year's model of how "
                  "this room behaves), but it is not a year-matched fit."
                  % (market.season, args.year))

    # Loaded whenever --prices is supplied, under any policy: --policy fit
    # needs it to choose a replacement level, and every policy needs it to
    # fit the market curve (_est_price) below. Without it there is nothing
    # to fit against, so `prices` stays None and _est_price is never written.
    prices = None
    if args.prices:
        # The guard now lives in fit.load_prices, so it cannot be bypassed by
        # a caller that reaches for the function directly. Converted to
        # SystemExit here so the CLI keeps its clean single-line failure -
        # but only for the guard's OWN failure (SeasonMismatchError). Any
        # other ValueError (a bad alias chain, an unrecognised franchise
        # code, a malformed price cell) is a genuine data problem and must
        # keep its traceback so the offending row can be located, not be
        # flattened to this guard's single-line message.
        try:
            prices = _load_prices_announcing(args.prices,
                                             args.tqb_starters, args.year)
        except SeasonMismatchError as exc:
            raise SystemExit(str(exc))

    policy = args.policy
    if market is not None:
        # The persisted policy was chosen from year-matched prices when the
        # model was fitted, so a pre-auction run needs no price file to know
        # it - this is the deadlock closing.
        policy = market.policy
    elif policy == "fit":
        if not args.prices:
            print("error: --policy fit requires --prices with observed auction prices")
            return None
        policy, reports = choose_policy(lg, pool, prices)
        total_prices = prices.total_rows
        for r in reports:
            unmatched = total_prices - r["n"]
            print("  %-10s n=%d of %d prices (%d unmatched)  mae=$%.2f rmse=$%.2f top10_mae=$%.2f"
                  % (r["policy"], r["n"], total_prices, unmatched,
                     r["mae"], r["rmse"], r["top10_mae"]))
        print("  chosen: %s\n" % policy)

        chosen_report = [r for r in reports if r["policy"] == policy][0]
        print("  fit by pool (chosen policy):")
        for name in sorted(chosen_report["by_pool"]):
            stats = chosen_report["by_pool"][name]
            if stats["n"]:
                flat = (" (flat $%g)" % lg.flat_priced_pools[name]
                        if name in lg.flat_priced_pools else "")
                print("    %-5s n=%-3d mae=$%.2f%s" % (name, stats["n"], stats["mae"], flat))

    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    rate = assign_dollars(lg, pool)

    # _est_price is only meaningful once _dollars exists on every record, so
    # this runs after assign_dollars. `prices` is loaded whenever --prices is
    # supplied, under any policy - fit the curve against whichever players
    # join. A small run can legitimately have too few joined observations to
    # fit a trustworthy curve (fit_price_curve enforces a minimum); that is a
    # property of this run's data, not a crash, so it is reported (loudly, not
    # silently) and _dollars/_est_price stay exactly as they were - never a
    # fabricated estimate.
    #
    # Flat-priced pools (K, DST) are excluded from the fit input on purpose:
    # their _dollars is pinned to the league's flat price by policy, not
    # derived from the model, so every one of them contributes a point at
    # x = log(1) = 0 that would anchor the curve's cheap end with data that
    # isn't evidence about how the market responds to value. Their displayed
    # _est_price is unaffected either way - assign_expected_prices applies
    # the same flat override to them regardless of what curve was fit.
    curve = None
    if market is not None:
        curve = market.curve
        assign_expected_prices(lg, pool, curve)
    elif prices is not None:
        priced = [(p.stats["_dollars"], prices[normalize_name(p.name)])
                  for p in pool if normalize_name(p.name) in prices
                  and _pool_of(p.pos) not in lg.flat_priced_pools]
        try:
            curve = fit_price_curve(priced)
        except ValueError as e:
            print("  WARNING: market curve not fitted (%s)\n" % e)
        else:
            assign_expected_prices(lg, pool, curve)
            print("  market curve: price = %.3f * value^%.3f  "
                  "(fitted on %d observed prices from %s, excluding "
                  "flat-priced K/DST)\n"
                  % (curve[0], curve[1], len(priced),
                     os.path.basename(args.prices)))

    print("replacement level (%s policy):" % policy)
    for name in sorted(levels):
        print("  %-5s %8.1f pts" % (name, levels[name]))
    print("  $%.4f per VORP point\n" % rate)

    return pool, curve, prices, market


def _board_rows(lg, pool, args):
    """A valued pool turned into render-ready rows, minus the unrostered.

    Shared by cmd_render and cmd_plan so the board the PDF draws and the board
    the tradeoff table illustrates from are the same board, ranked the same
    way. Two copies of this filter would let one command's "rank 3" mean a
    different player from the other's.

    23 of 543 real Draft Sharks rows carry a placeholder team code (UNS x22
    unsigned free agents, RK x1) - not real NFL franchises, so they have no
    bye week. build_rows correctly raises on an unknown team code rather than
    rendering a blank bye, so filter them out here, at the render layer, using
    sffl.identity.NFL_TEAMS as the authority on what counts as a real
    franchise. All of them sit below replacement, so dropping them changes no
    dollar value on the board - but dropping them silently would be exactly
    the kind of quiet data loss this project's raise-don't-guess rule exists
    to prevent, so the count is always printed. A team code that IS a real
    franchise but is still missing from the bye file is left alone here and
    reaches build_rows, which still raises - that is a genuine data gap, not a
    free agent, and must not be swallowed the same way.
    """
    rosterable = [p for p in pool if p.team in NFL_TEAMS]
    dropped = [p for p in pool if p.team not in NFL_TEAMS]
    if dropped:
        codes = sorted(set(p.team for p in dropped))
        print("dropped %d unrostered player(s) with a non-NFL team code (%s) "
              "- not real franchises, so no bye week and not draftable"
              % (len(dropped), ", ".join(codes)))
    return build_rows(lg, rosterable, load_byes(args.byes))


# The header, row format and legend of the silent-auction tradeoff table, in
# the terminal. Deliberately the same columns, the same order and the same
# three tie states as the PDF's management page - `sffl.plan.tie_cells` and
# `pick_range` are the single source for the wording of both. That includes
# BOTH tie columns: TIE1+ (someone was already there) and TIE2+ (the field tied
# itself). The terminal has width the page does not, so it spells the headers
# out where the PDF has to abbreviate; the meanings are identical.
# LIVE is %-12s, not %-6s: a level that escalated in three separate
# years prints "'21 '22 '23" and any narrower field shunts PICK RANGE
# right on that row alone, breaking the column the eye is following.
_PLAN_ROW = "  %-5s %-7s %-8s %-8s %-10s %-12s %-7s %-7s %s"


def _print_plan(outcomes, bid_floor):
    # The tie rates' denominator comes off the outcome, which took it from the
    # file. Typing "5" here goes wrong the August 2026's twelve rows land.
    years = outcomes[0].years
    print("silent auction (rd 1): what each bid has historically bought, and "
          "what it leaves")
    print("  a bid under $%d is DISCARDED and forfeits the silent pick "
          "entirely" % bid_floor)
    print("  PICK is an ILLUSTRATION - our own board read at each end of the "
          "rank span,")
    print("  assuming the room drafts in that order, which it will not. RANK "
          "is a fact and")
    print("  is priced at nothing here; whether finishing first is worth "
          "anything is unmeasured.")
    print(_PLAN_ROW % ("BID", "RANK", "TIE1+", "TIE2+", "BUMP", "LIVE",
                       "LEFT*", "DISCR*", "PICK RANGE (ILLUSTRATION)"))
    for o in outcomes:
        join, field, bump, live = tie_cells(o)
        span = ("%d" % o.best_rank if o.best_rank == o.worst_rank
                else "%d-%d" % (o.best_rank, o.worst_rank))
        print(_PLAN_ROW % ("$%d" % o.bid, span, join, field, bump, live,
                           "$%d" % o.budget_left, "$%d" % o.discretionary,
                           pick_range(o)))
    print("  TIE1+ = share of the %d years with a team ALREADY at this exact "
          "bid: join it and" % years)
    print("  you are in a tie. TIE2+ = share with 2+ teams tied EACH OTHER "
          "there, so TIE1+ is")
    print("  never the smaller. \"no data\" in both = never bid, so nothing is "
          "known: it is NOT")
    print("  a measured 0%. BUMP = bumps actually charged to win a tie. LIVE = "
          "a year the tie")
    print("  went to a live auction, where money was paid over the bid: an "
          "empty BUMP beside")
    print("  a LIVE year is not a free tie. *LEFT and DISCR are PRE-BUMP - win "
          "a tie and the")
    print("  bump comes out of them too.")


def cmd_ingest(args):
    lg = load_league(args.league)
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    by_pos = {}
    for p in pool:
        by_pos[p.pos] = by_pos.get(p.pos, 0) + 1
    print("%d players from %s" % (len(pool), args.source))
    print("  " + "  ".join("%s=%d" % kv for kv in sorted(by_pos.items())))
    print("\ntop 15 by SFFL season points:")
    for i, p in enumerate(pool[:15], 1):
        print("  %2d. %7.1f  %-4s %s" % (i, p.stats["_season_points"], p.pos, p.name))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "team", "pos", "games", "season_points", "source", "set"])
            for p in pool:
                w.writerow([p.name, p.team, p.pos, p.games,
                            round(p.stats["_season_points"], 2),
                            p.source, p.set_name or ""])
        print("\nwrote %s" % args.out)
    return 0


def cmd_value(args):
    lg = load_league(args.league)
    result = _value_pool(lg, args)
    if result is None:
        return 1
    pool, curve, prices, _market = result

    # _spread_rec_yds / _spread_rush_yds / _n_sources are only populated when
    # the pool came through sffl.consensus.merge (multi-source agreement
    # spread). Nothing currently wires build_pool's output through merge, so
    # detect it empirically instead of assuming: if not one single record in
    # the pool carries any "_spread_" key, consensus was never run, and the
    # spread column has not been measured - it is not "measured as zero."
    # Printing 0.0/1 in that case reads as "the analysts agree" when the
    # truth is "nobody asked a second analyst," so we say so explicitly and
    # print an empty field instead of a fabricated zero.
    consensus_ran = any(any(k.startswith("_spread_") for k in p.stats) for p in pool)

    pool.sort(key=lambda p: -p.stats["_dollars"])
    if curve is not None:
        print("top 25 by value:  $ = MY$, worth against replacement; "
              "est $ = EST$, what the room will pay")
        print("  (EST$ compresses hardest at the top of the board - for a "
              "single specific top target, treat it as a floor on his "
              "price, not a point estimate)")
    else:
        print("top 25 by value:")
    if not consensus_ran:
        print("  (consensus not wired for this run - spread unavailable, single source only)")
    for i, p in enumerate(pool[:25], 1):
        est = ("  est $%5.1f" % p.stats["_est_price"]) if curve is not None else ""
        if consensus_ran:
            spread = p.stats.get("_spread_rec_yds", 0.0) + p.stats.get("_spread_rush_yds", 0.0)
            print("  %2d. $%5.1f  %-4s %-24s vorp %6.1f  spread %5.1f%s"
                  % (i, p.stats["_dollars"], p.pos, p.name[:24], p.stats["_vorp"], spread, est))
        else:
            print("  %2d. $%5.1f  %-4s %-24s vorp %6.1f%s"
                  % (i, p.stats["_dollars"], p.pos, p.name[:24], p.stats["_vorp"], est))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "team", "pos", "games", "season_points",
                        "vorp", "dollars", "est_price", "spread", "n_sources"])
            for p in pool:
                if consensus_ran:
                    spread = round(p.stats.get("_spread_rec_yds", 0.0)
                                   + p.stats.get("_spread_rush_yds", 0.0), 2)
                    n_sources = int(p.stats.get("_n_sources", 1))
                else:
                    # Empty, not 0.0/1: this run never measured a spread, so
                    # writing zeros would claim "measured as zero agreement"
                    # instead of "not measured."
                    spread = ""
                    n_sources = ""
                # Empty, not 0.0 and not a copy of dollars: without a fitted
                # curve there is nothing to estimate from, and either
                # fabricated value would read as a real measurement.
                est_price = round(p.stats["_est_price"], 2) if curve is not None else ""
                w.writerow([p.name, p.team, p.pos, p.games,
                            round(p.stats.get("_season_points", 0.0), 2),
                            round(p.stats.get("_vorp", 0.0), 2),
                            round(p.stats.get("_dollars", 0.0), 2),
                            est_price,
                            spread,
                            n_sources])
        print("\nwrote %s" % args.out)

    if curve is not None and prices is not None:
        # Restricted to the same non-flat population the curve was fit on
        # (see `priced` above): flat-priced K/DST all land in the $1-2 band
        # at exactly $1 MY$/EST$ regardless of what the curve does, so
        # mixing them into this table would measure a different, easier
        # population than the one the fit's bias is evidence about and
        # flatter the $1-2 band's reported bias.
        print("\nbias against observed prices, by model dollar band "
              "(excludes flat-priced K/DST, matching the fitted population):")
        print("  %-10s %4s %9s %9s %9s" % ("band", "n", "MY$ bias", "EST$ bias", "actual"))
        bands = [(30, 1e9, "$30+"), (20, 30, "$20-30"), (10, 20, "$10-20"),
                 (5, 10, "$5-10"), (2, 5, "$2-5"), (0, 2, "$1-2")]
        for lo, hi, label in bands:
            rows = [p for p in pool
                    if normalize_name(p.name) in prices
                    and _pool_of(p.pos) not in lg.flat_priced_pools
                    and lo <= p.stats["_dollars"] < hi]
            if not rows:
                continue
            actual = [prices[normalize_name(p.name)] for p in rows]
            mybias = sum(p.stats["_dollars"] for p in rows) / len(rows) \
                - sum(actual) / len(actual)
            estbias = sum(p.stats["_est_price"] for p in rows) / len(rows) \
                - sum(actual) / len(actual)
            print("  %-10s %4d %+9.1f %+9.1f %9.1f"
                  % (label, len(rows), mybias, estbias, sum(actual) / len(actual)))
    elif curve is not None:
        # curve came from --market, not a fit against this run's own
        # --prices, so there is nothing observed to measure bias against.
        # Correct to omit the table, but every other omission in this
        # function says why it is absent - a table that vanishes with no
        # explanation reads as a bug to the operator, not a property of the
        # run.
        print("\n(bias against observed prices not shown - this run applied "
              "a persisted --market model rather than fitting against "
              "--prices, so there are no observed prices to compare against)")

    return 0


def cmd_render(args):
    if not args.pdf and not args.xlsx:
        print("error: render needs at least one of --pdf or --xlsx to write")
        return 1

    lg = load_league(args.league)
    result = _value_pool(lg, args)
    if result is None:
        return 1
    pool, curve, prices, market = result

    rows = _board_rows(lg, pool, args)

    # The board is the artifact that MUST exist on auction day, so a missing
    # or malformed bid history degrades one block of one page rather than
    # failing the render - loudly, never silently, and never into the
    # hardcoded sub-floor grid this replaced.
    if args.pdf:
        outcomes = None
        try:
            outcomes = plan_bids(lg, rows, load_bid_history(args.bids))
        except (OSError, ValueError) as e:
            print("  WARNING: silent-auction table not built (%s); the "
                  "management page falls back to budget arithmetic only" % e)
        pages = render_pdf(lg, rows, args.pdf, outcomes=outcomes)
        print("wrote %s (%d pages)" % (args.pdf, pages))
    if args.xlsx:
        # The workbook's second sheet states what the board's numbers mean and
        # how far they can be trusted, for whoever is drafting from it. Every
        # figure on it is measured from THIS run - the pool, the observed
        # prices, the fitted curve and the tracked bid history - so it cannot
        # quote a number the board beside it does not support. A fact this run
        # did not produce is reported as not measured, never as a stale
        # constant. See sffl.render.intel.
        # year=args.year, NOT the league profile's season: this page's
        # cross-season verdict must be the same verdict stdout printed a few
        # lines above, and stdout compares against --year. A 2027 board built
        # from the 2026 profile used to be announced CROSS-SEASON in the
        # terminal and "year-matched to this board" in the workbook - and the
        # workbook is what goes to the draft table.
        facts = gather_intel(lg, rows, pool=pool, prices=prices, curve=curve,
                             market=market, year=args.year)
        stats = render_xlsx(lg, rows, args.xlsx, intel=facts)
        print("wrote %s" % args.xlsx)
        # render_xlsx truncates to a hard two-page row budget (derived from
        # page geometry, not a hardcoded player count - see
        # sffl.render.xlsx.ROW_BUDGET) because a full board cannot fit in
        # two printed pages. Report it per section, not as one combined
        # number - a single global count once hid an entire position
        # (Receivers) getting cut to zero while the total still looked
        # reasonable.
        ov = stats["overall"]
        if ov["cut"]:
            print("  Overall Board: %d of %d shown (%d cut)"
                  % (ov["shown"], ov["shown"] + ov["cut"], ov["cut"]))
        else:
            print("  Overall Board: all %d shown, nothing cut" % ov["shown"])
        for title, sec in sorted(stats["sections"].items()):
            total = sec["shown"] + sec["cut"]
            if sec["cut"]:
                print("  %s: %d of %d shown (%d cut)" % (title, sec["shown"], total, sec["cut"]))
            else:
                print("  %s: all %d shown, nothing cut" % (title, sec["shown"]))
        # The legend sheet cannot overflow silently - render_xlsx raises if it
        # would need a second page - so this is a headroom report, not a
        # warning: how much room is left for another paragraph.
        it = stats["intel"]
        print("  Key & Intel: one page, %d of %d rows used"
              % (it["rows"], it["budget"]))

    return 0


def cmd_plan(args):
    """The management page's silent-auction table, in the terminal.

    Same numbers, same wording, no PDF. Unlike cmd_render this does NOT
    degrade when the bid history cannot be read: the table IS the output here,
    so an unreadable history is a hard failure rather than a blank page.
    """
    lg = load_league(args.league)
    result = _value_pool(lg, args)
    if result is None:
        return 1
    pool, _curve, _prices, _market = result

    try:
        history = load_bid_history(args.bids)
    except (OSError, ValueError) as e:
        # BOTH, and ValueError is the likelier of the two. OSError is a missing
        # or unreadable file; ValueError is what `load_bid_history` raises for
        # a MALFORMED one - a missing column, an unparseable number, a
        # cap_cost under its own bid, a duplicated or transposed rank - and it
        # raises with a message naming the file, the line and the problem.
        # Catching only OSError threw that message away behind a traceback.
        print("error: cannot read the bid history: %s" % e, file=sys.stderr)
        return 1

    rows = _board_rows(lg, pool, args)
    _print_plan(plan_bids(lg, rows, history), lg.silent_auction["bid_floor"])
    return 0


_PATH_SEASON = re.compile(r"^(?:19|20)\d\d$")


def projections_season_from_path(path):
    """The season an extract's PATH names, or None when it names none clearly.

    The extracts are stored one directory per season - `data/extracts/Draft
    Sharks/2026/rankings-2026-08-23.csv` - so the path is a second, independent
    statement of which season a file is FOR, alongside `--year`. Independent is
    the whole value: `--year` is what the operator typed, and typing the wrong
    one is the failure being guarded against, so it cannot be checked against
    itself.

    Only a whole path COMPONENT that is exactly four digits counts. The date
    inside `rankings-2026-08-23.csv` is deliberately not read: it is when the
    file was pulled, not the season it projects, and a January pull for the
    previous season would make those two disagree. Returns None when no
    component qualifies OR when two different ones do - an ambiguous path is
    not evidence, and the caller must say so rather than pick one.
    """
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    years = set(int(p) for p in parts if _PATH_SEASON.match(p))
    return years.pop() if len(years) == 1 else None


def _sha256_file(path):
    """Content hash of a file, for evidence that names data too large or too
    licensed to commit (a gitignored vendor extract that gets overwritten in
    place). A path alone proves nothing a year later - the file at that path
    may since have been refreshed - but a hash pins exactly which bytes were
    fitted against, without copying a single row into a tracked file.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_fit_market(args):
    """Fit this room's price curve and policy from year-matched evidence, and persist them.

    THE ONLY COMMAND THAT FITS. Everything else applies a model this wrote.
    That separation is the point: fitting is season-bound and can only happen
    after an auction, while applying needs nothing but a curve and this year's
    projections. Fusing them is what made a pre-auction run choose between
    refusing outright and silently fitting across seasons.
    """
    import datetime

    from sffl.market_model import MarketModel, save

    # THE PROJECTIONS' OWN SEASON, checked BEFORE any work: the `evidence`
    # block exists so a bad fit cannot be invisible, and an evidence block
    # that can assert a self-contradicting falsehood is worse than none,
    # because it will be believed. `projections_year: 2025` beside
    # `projections_file: .../2026/rankings-2026-08-23.csv` was reproducible
    # here - nothing compared the extract to --year, and projections_year was
    # written from --year rather than read from anything.
    path_season = projections_season_from_path(args.file)
    if path_season is not None and path_season != args.year:
        raise SystemExit(
            "refusing to fit: --year %d, but the projections file is %s, "
            "whose path names season %d. One of the two is wrong, and a fit "
            "pairs prices with projections - getting that pairing wrong is "
            "what this command exists to make impossible. Correct --year or "
            "point --file at the %d extract."
            % (args.year, args.file, path_season, args.year))
    if path_season is None:
        _banner(
            "PROJECTIONS SEASON NOT VERIFIED",
            "%s names no unambiguous season in its path, so --year %d could "
            "not be cross-checked against the projections themselves and is "
            "being taken on trust. The artifact records that: its "
            "evidence.projections_year_source will say '--year (unverified)' "
            "rather than claiming the file confirmed it. Storing extracts one "
            "directory per season (data/extracts/<vendor>/<year>/) makes this "
            "checkable." % (args.file, args.year))

    lg = load_league(args.league)
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    if args.curves:
        curves = load_curves(args.curves)
        for p in pool:
            p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
        pool.sort(key=lambda p: -p.stats["_season_points"])

    # season=args.year is what makes this refuse every cross-season
    # combination it can detect - the TQB map's season and the prices file's
    # own season column must both agree with the projections' year. Only the
    # guard's own SeasonMismatchError becomes SystemExit here; any other
    # ValueError (bad alias chain, unrecognised franchise code, malformed
    # price cell) is a genuine data problem and keeps its traceback.
    #
    # require_file_season is what separates a FIT from an apply: a prices
    # file that cannot state its own season is REFUSED here (and merely
    # warned about on value/render), because a fit is persisted and later
    # seasons trust it without ever re-deriving it.
    try:
        prices = load_prices(args.prices, tqb_starters_path=args.tqb_starters,
                             season=args.year, require_file_season=True)
    except SeasonMismatchError as exc:
        raise SystemExit(str(exc))

    policy, reports = choose_policy(lg, pool, prices)
    chosen = [r for r in reports if r["policy"] == policy][0]

    # choose_policy leaves the pool carrying the LAST policy's numbers, not
    # the winner's - see its docstring. Re-run the valuation with the chosen
    # policy before fitting, or the curve is fit against the wrong dollars.
    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    assign_dollars(lg, pool)

    pairs = []
    for p in pool:
        if lg.flat_priced_pools.get(_pool_of(p.pos)) is not None:
            continue
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((p.stats["_dollars"], prices[key]))

    curve = fit_price_curve(pairs)

    model = MarketModel(
        season=args.year,
        fitted_on=datetime.date.today().isoformat(),
        curve=curve,
        policy=policy,
        evidence={
            "prices_file": args.prices,
            "prices_rows": prices.total_rows,
            "observations": len(pairs),
            "projections_source": args.source,
            # READ from the extract's path when it says one, not copied from
            # --year. The two are cross-checked above, so they cannot
            # disagree here - and when the path says nothing, the artifact
            # says WHERE the year came from instead of presenting an
            # unverified assertion in the same shape as a verified one.
            "projections_year": (path_season if path_season is not None
                                 else args.year),
            "projections_year_source": (
                "projections file path"
                if path_season is not None
                else "--year (unverified: the path names no season)"),
            "tqb_starters": args.tqb_starters,
            # Added so the artifact can be reproduced, not just described:
            # `projections_source` above names the PROFILE (e.g.
            # sources/draftsharks.yaml), which says how to parse a file but
            # not which one - two extracts of the same vendor on the same day
            # can disagree. `projections_file` names the actual path used and
            # `projections_file_sha256` pins its bytes, since the extract
            # itself is gitignored licensed data that gets overwritten in
            # place (a path alone would go stale silently). `curves_file`,
            # `league_profile` and `set` complete the command line that
            # produced this fit - everything `sffl fit-market` was given,
            # bar the output path and prices, is recoverable from `evidence`.
            "projections_file": args.file,
            "projections_file_sha256": _sha256_file(args.file),
            "curves_file": args.curves,
            "league_profile": args.league,
            "set": args.set,
        },
        diagnostics={
            "mae": round(chosen["mae"], 4),
            "top10_mae": round(chosen["top10_mae"], 4),
            "top10_bias": round(chosen["top10_bias"], 4),
        },
    )
    try:
        save(args.out, model, overwrite=args.force)
    except OSError as exc:
        raise SystemExit(str(exc))
    print("wrote %s" % args.out)
    print("  policy chosen from these prices: %s" % policy)
    print("  curve: a=%.4f b=%.4f from %d observations"
          % (curve[0], curve[1], len(pairs)))
    return 0


def _avail_classifier(path, owner_codes):
    """Pick cbs_weekly's tab-path or space-path `classify_avail*` for `path`.

    `PlayerProjection` carries no per-row flag for which of cbs_weekly's two
    row shapes produced it. `cbs_weekly._parse_row` dispatches PER LINE on a
    literal tab while parsing, but that distinction does not survive onto
    the `PlayerProjection` it returns - by the time this CLI sees the rows,
    it is gone. (I looked at adding a field for this on `PlayerProjection`
    and did not: other agents' tests construct that record directly, and
    schema.py was out of this task's file scope - see the task-7 report.)

    So this is necessarily a FILE-level signal, not `_parse_row`'s per-line
    one: a Playwright `capture()` page has tab characters throughout its
    ENTIRE rendered text - nav, headers, every row, not just player rows -
    while the older browser-tool space-delimited save has none anywhere.
    Checking for a literal tab ANYWHERE in the file is therefore a safe,
    cheap stand-in for "which capture path produced this," for every file
    this pipeline has ever actually produced. cbs_weekly's own docstring
    notes a file COULD mix both row shapes; this cannot tell such a file's
    rows apart (it would pick one classifier for the whole file) - no such
    file has ever been observed, and refusing to guess PER ROW here would
    require exactly the schema field this task declined to add.

    `classify_avail_tab` needs no `owner_codes` (its own docstring explains
    why: the tab path's owner cell cannot be confused with a name no matter
    what it contains). `classify_avail` does, so it comes back pre-bound to
    them - both branches return a one-argument `avail -> status` callable.
    """
    from sffl.cbs_weekly import classify_avail, classify_avail_tab

    with open(path) as fh:
        is_tab_delimited = any("\t" in line for line in fh)
    if is_tab_delimited:
        return classify_avail_tab
    return lambda avail: classify_avail(avail, owner_codes)


def _merge_projection_groups(group_rows):
    """Merge parsed rows from several position-group pages into one pool.

    `group_rows` is an ORDERED list of (group_name, [PlayerProjection, ...])
    - one entry per page already parsed with `cbs_weekly.parse(group=...)`.
    Returns `(merged, owner, duplicates)`: `merged` is the combined row
    list; `owner` maps each row's KEY (see below) to whichever group's row
    is IN `merged` for that key, so a caller that needs to know which page
    a given row came from (`_cmd_week`'s avail classifier - see below) does
    not have to re-derive it; `duplicates` is a list of `(name, pos, team,
    kept_group, dropped_group)` for every TRUE cross-group duplicate found
    - EMPTY in the ordinary case. This is printed as a WARNING either way
    (below), but a caller such as `_cmd_alert` that must not let a
    duplicate reach the reader as a silent, clean run also needs it as
    DATA, not just as terminal noise - a warning that only ever reaches
    stdout is invisible to the pushed digest and to the exit code, unlike
    every other degradation `_cmd_alert` reports.

    THE KEY IS `p.key()` - `identity.player_key`'s (name, team, pos), NOT
    (name, pos) and NOT name alone. Two hazards, both real, found while
    wiring this up:

    (1) CBS's TQB and DST pages both use the NFL TEAM'S NICKNAME as the
    row's "player name" - e.g. "Chargers" is a genuine row on BOTH pages,
    one an aggregate of the team's quarterback production, the other of
    its defense. Every one of the 32 NFL teams collides this way EVERY
    WEEK - not a rare edge case. `pos` alone (TQB vs DST) already tells
    these two apart.

    (2) `pos` alone is NOT enough, though: the NFL has had two
    simultaneously active players sharing a name at the same position on
    DIFFERENT teams (two players both named Mike Williams, both WRs, in
    the same season is real, not hypothetical). A (name, pos) key would
    read that as one cross-group-style duplicate even within a single
    RB-WR-TE page and silently drop one of two real players, handing his
    projection to the other. `team` (already on every `PlayerProjection`,
    normalized identically to every other vendor source via `identity.
    normalize_team`) is the field that tells THEM apart.

    A player is still expected to appear on exactly one group's page - RB,
    WR, TE and K rows are real individuals, and TQB/DST rows are one team
    aggregate each - but this does NOT assume it. The FIRST group (in the
    order given) to claim a given key wins; every LATER group's claim on
    the SAME key is reported with a WARNING naming both groups and dropped,
    rather than silently kept or silently overwritten - a TRUE duplicate
    (same name, same position, same TEAM, two different pages) is exactly
    the kind of merge surprise that must be visible, since it would
    otherwise either double-count him or silently pick one page's numbers
    over the other's with no signal either way.

    EVEN THIS THREE-FIELD KEY IS A HEURISTIC, NOT A PROVEN-UNIQUE IDENTITY
    - see `cbs_roster`'s module docstring for the full reasoning and what
    the durable fix (CBS's own stable player IDs) would cost. Nothing
    stops two same-named players at the same position on the SAME team
    from existing in the data (a churn artifact, a data error); that
    residual case is not silently assumed away - it still lands here as a
    "duplicate" (same key, different row) and is reported exactly like a
    cross-group collision, because there is no fourth field left to
    disambiguate it with.

    Deliberately narrower than that: a key repeated WITHIN one group's own
    row list (e.g. a normalize_name suffix collision, "Braelon Allen" vs
    "Braelon Allen Jr.", both RB on the SAME team) is NOT touched here and
    both rows pass through unchanged - that is a different, already-handled
    concern (`_cmd_week`'s own by_key construction warns and keeps the last
    one; `_cmd_alert`'s own by_key construction, built with the SAME
    residual-duplicate reporting as this function, catches it too), not a
    cross-group duplicate, and treating it the same way here would silently
    drop one of two genuinely different players before those existing
    checks ever saw the second row.
    """
    merged = []
    owner = {}
    duplicates = []
    for group_name, rows in group_rows:
        for p in rows:
            key = p.key()
            if key in owner and owner[key] != group_name:
                print("  WARNING: %r (%s, %s) appears in both the %s and "
                      "%s projection groups - a player at that position, "
                      "on that team, should be on exactly one group's "
                      "page. Keeping the %s row, dropping this %s one so "
                      "the pool is not double-counted."
                      % (p.name, p.pos, p.team, owner[key], group_name,
                         owner[key], group_name))
                duplicates.append((p.name, p.pos, p.team, owner[key],
                                  group_name))
                continue
            owner.setdefault(key, group_name)
            merged.append(p)
    return merged, owner, duplicates


def _cmd_week(args):
    from sffl.cbs_weekly import DEFAULT_PROFILE, _load_owner_codes
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import normalize_name
    from sffl.lineup import Candidate, best_add_drop, best_lineup, delta
    from sffl.pool import score_week

    owner_codes = _load_owner_codes(DEFAULT_PROFILE)

    lg = load_league(args.league)
    curves = load_curves(args.curves) if args.curves else None

    # --projections/--group is the ORIGINAL single-page interface and stays
    # exactly as it was: give none of the three flags below and this
    # function is byte-for-byte the same as before this task, which is why
    # every pre-existing test above still passes only this pair.
    # --projections-tqb/-k/-dst are new and OPTIONAL - give any of them and
    # that saved page is parsed under its own FIXED group name (never
    # --group, which only ever names the first pair's group) and merged
    # into the same pool, so a waiver run or a start/sit check can see all
    # eight lineup slots instead of five.
    group_files = [(args.group, args.projections)]
    for group_name, path in (("TQB", args.projections_tqb),
                             ("K", args.projections_k),
                             ("DST", args.projections_dst)):
        if path:
            group_files.append((group_name, path))

    group_rows = [(group_name, parse_weekly(path, group=group_name,
                                            week=args.week, season=lg.season))
                 for group_name, path in group_files]
    projections, owner_group, _dupes = _merge_projection_groups(group_rows)

    if len(group_files) > 1:
        print("  merged %d position group page(s): %s"
              % (len(group_files), ", ".join(g for g, _p in group_files)))

    # F5. The spec's failure table requires a raise for an empty roster
    # (below) on the reasoning that an empty roster optimises to an empty
    # lineup and would recommend claiming everyone; a zero-row PROJECTIONS
    # parse is the same class of mistake. A saved page that parses no rows
    # at all is almost certainly a login page or a truncated save, not a
    # real empty week, and printing "0 rows parsed ... best legal lineup:
    # 0.00" while returning success hides exactly the failure this repo's
    # raise-rather-than-guess convention exists to surface.
    if not projections:
        raise SystemExit(
            "0 rows parsed from %s; a page that parses no rows is almost "
            "certainly the wrong page or a failed save, not a real empty "
            "result" % ", ".join(path for _g, path in group_files))

    owned_raw = [l.strip() for l in open(args.roster) if l.strip()]
    if not owned_raw:
        raise SystemExit("roster is empty (%s); an empty roster optimises to "
                         "an empty lineup and would recommend claiming "
                         "everyone" % args.roster)
    owned = set(normalize_name(n) for n in owned_raw)

    # last-write-wins: normalize_name strips generational suffixes, so e.g.
    # "Braelon Allen" and "Braelon Allen Jr." collide on the same key and
    # one silently vanishes. Not raised - a real page can legitimately carry
    # two similarly-named players - but it must not be silent, so name both
    # raw spellings when it happens.
    #
    # This by_key is keyed by name ALONE, unlike `_merge_projection_groups`'
    # `p.key()` (name, team, pos) key - `--roster`/`--current` are plain
    # one-name-per-line text files with no position OR team column, so a
    # lookup against them can only ever have a bare name to go on, and
    # keying by_key any other way would make every roster/current lookup
    # below unable to find its own entries. The COMPARISON below still
    # checks pos AND team (not just name) so a same-name collision is
    # caught regardless of which field actually differs: CBS's TQB and DST
    # pages both use the NFL TEAM NICKNAME as the row name ("Chargers" is a
    # real row on both, same team, different pos), and separately two
    # different real players can share a name at the same position on
    # different teams. Either way `--roster`'s plain-text format has no
    # position or team column to disambiguate with, so the warning below
    # still WARNS and still keeps only the last one (silently answering for
    # more than one real roster slot with a single row) rather than
    # raising, because there is no more information here to resolve it
    # correctly; a manager who hits this should read the warning as a real
    # limitation of this command's input format, not a bug report.
    #
    # THE WARNING IS RESTRICTED TO `key in owned`. A real capture lists all
    # 32 NFL teams on both the TQB and DST pages, so this collision fires
    # for every team merging both groups produces - most of which nobody
    # on THIS roster has anything to do with. Printing all ~32 every run
    # buries the one warning that might actually matter under noise at
    # exit 0 regardless (this function has no exit-code concept); only a
    # name Jeff actually ROSTERS can produce a wrong start/sit or waiver
    # read, so only that case is worth interrupting the output for. An
    # UNOWNED collision is still resolved the same way (last one wins,
    # silently) - it can only ever cost free-agent-board accuracy for two
    # names nobody here owns, a pre-existing, lower-severity limitation.
    by_key = {}
    for p in projections:
        key = normalize_name(p.name)
        if key in by_key and (by_key[key].name != p.name
                              or by_key[key].pos != p.pos
                              or by_key[key].team != p.team):
            if key in owned:
                print("  WARNING: %r (%s, %s) and %r (%s, %s) both "
                      "normalize to the same key - only %r (%s, %s) is "
                      "kept (last one wins); the other's projection is "
                      "silently dropped from the pool"
                      % (by_key[key].name, by_key[key].pos,
                         by_key[key].team, p.name, p.pos, p.team, p.name,
                         p.pos, p.team))
        by_key[key] = p

    missing = [n for n in owned_raw if normalize_name(n) not in by_key]
    for name in missing:
        print("  no projection for %s - excluded from the lineup, NOT scored "
              "as zero" % name)

    # I2. The guard above only catches an empty roster FILE. A roster whose
    # every name fails to resolve is the same failure by a different route:
    # `roster` below ends up empty either way, `best_lineup` optimises an
    # empty lineup to 0.00, and every free agent then ranks as a claim, at
    # exit 0 - the exact "would recommend claiming everyone" outcome the
    # empty-file guard exists to prevent. Realistic cause: get_page_text can
    # emit a non-breaking space where CBS renders a normal one, and
    # normalize_name's `[^a-z0-9 ]` strip DELETES \xa0 rather than treating
    # it as a word separator, so "Woody\xa0Marks" collapses to "woodymarks",
    # which matches nothing. Raise here, naming the count and the likely
    # cause, instead of silently proceeding.
    resolved = len(owned_raw) - len(missing)
    if resolved == 0:
        raise SystemExit(
            "0 of %d roster name(s) in %s resolved to a projection; every "
            "one would be excluded, the lineup would optimise to empty, and "
            "every free agent would rank as a claim - the same failure an "
            "empty roster file raises for. A likely cause is a non-breaking "
            "space or other invisible character from the saved page "
            "(normalize_name strips it rather than splitting on it); check "
            "%s against the names in %s." % (
                len(owned_raw), args.roster, args.roster,
                ", ".join(path for _g, path in group_files)))

    def cand(p):
        return Candidate(name=p.name, pos=p.pos,
                         points=score_week(lg, p, curves))

    # A player designated Out will not take the field and scores zero, so the
    # optimiser would otherwise start him and report a lineup total that
    # cannot happen. Excluded here - and NAMED, never dropped silently, the
    # same treatment `missing` and `not_evaluated` already get, because a
    # player who quietly vanishes from the board reads as "no longer on your
    # roster" rather than as "ruled out."
    from sffl.cbs_weekly import is_out
    sidelined = sorted((by_key[k].name, by_key[k].status)
                       for k in owned if k in by_key and is_out(by_key[k].status))
    for name, status in sidelined:
        print("  %s is %s - excluded from the lineup, he will not play"
              % (name, status))

    roster = [cand(by_key[k]) for k in owned
              if k in by_key and not is_out(by_key[k].status)]

    # Flagged, NOT excluded - see cbs_weekly.OUT_STATUSES.
    questionable = sorted((by_key[k].name, by_key[k].status)
                          for k in owned
                          if k in by_key and by_key[k].status in ("Q", "D"))
    for name, status in questionable:
        print("  %s is %s - STARTED anyway; check his status before kickoff"
              % (name, status))

    # F3: `avail` on CBS's ALL PLAYERS view names a genuine free agent
    # ("FA"), a waiver-claimable player ("W (9/16)"), or another manager's
    # team - a player who is not on Jeff's --roster file but is not
    # unclaimed either. Treating every non-roster row as claimable, as this
    # used to, is how the ALL PLAYERS view - which the spec itself
    # advertises as the source to save - turns into a board recommending a
    # claim on another team's starter. Classify every non-roster row before
    # it is even scored: only a row confidently identified as available is
    # ranked; a row confidently identified as owned is excluded and counted;
    # a row whose avail shape has never been seen before is refused rather
    # than guessed at, exactly like every other "raise rather than guess"
    # gate in this project.
    #
    # `classify_by_group` picks cbs_weekly's tab-path or space-path
    # classifier PER FILE - see `_avail_classifier`. This used to be a
    # single classifier bound to `args.projections`, which was correct
    # when there was only one file; merging in --projections-tqb/-k/-dst
    # means a free row can come from any of up to four files, and each one
    # independently is tab- or space-delimited (a real Playwright capture
    # is tab-delimited; the historical browser-tool save is not) - `owner_group`
    # (from `_merge_projection_groups`) says which file a given row survived
    # the merge from, so each row is classified against ITS OWN file's
    # shape, never against whichever file happened to be `--projections`.
    # Wiring the space-path `classify_avail` unconditionally here (this
    # command's only option before `classify_avail_tab` existed) is exactly
    # the bug a real Playwright-captured file hits: a tab-path owner cell
    # like "Sgt Hu..." matches no configured `owner_codes` and is not
    # "FA"/"W", so it comes back unclassified for every single owned row on
    # that page - a noisy warning naming a dozen team names, and a waiver
    # board that has silently stopped telling owned players from free
    # agents on the format this pipeline now actually captures.
    classify_by_group = dict((group_name, _avail_classifier(path, owner_codes))
                             for group_name, path in group_files)
    free_rows = [(k, p) for k, p in by_key.items() if k not in owned]
    available_rows = []
    excluded_owned = 0
    excluded_out_free = []
    unclassified_avail = set()
    for k, p in free_rows:
        # `owner_group` is keyed by `p.key()` - see `_merge_projection_
        # groups` - not by the plain `by_key`/`owned` name key `k`, so it
        # is re-derived from the row itself rather than from `k`.
        status = classify_by_group[owner_group[p.key()]](p.avail)
        if status == "available":
            if is_out(p.status):
                excluded_out_free.append(p)
            else:
                available_rows.append(p)
        elif status == "owned":
            excluded_owned += 1
        else:
            unclassified_avail.add(p.avail)

    # Free agents designated Out will not take the field and score zero. Exclude
    # them from waiver ranking - and NAMED, never dropped silently, the same
    # treatment owned and unclassified rows get.
    for p in excluded_out_free:
        print("  %s is %s - excluded from waivers, he will not play"
              % (p.name, p.status))

    if unclassified_avail:
        print("  WARNING: %d distinct avail value(s) not recognized as "
              "free-agent, waiver, or owned - ranking nothing from them "
              "since availability cannot be verified: %s"
              % (len(unclassified_avail), ", ".join(sorted(unclassified_avail))))

    free = [cand(p) for p in available_rows]

    # Denominators, not just results - this repo's convention (see
    # fit.PriceMap.total_rows, _board_rows' dropped-count print) is to say
    # "n matched of N loaded" rather than a bare count with nothing to
    # compare it against. `resolved` was already computed above, where the
    # I2 guard needs it first.
    print("  %d rows parsed from %s"
          % (len(projections), ", ".join(path for _g, path in group_files)))
    print("  %d of %d roster names resolved to a projection"
          % (resolved, len(owned_raw)))
    print("  %d free agents ranked (%d excluded - rostered by another team)"
          % (len(free), excluded_owned))

    base = best_lineup(lg, roster)
    print("\n  best legal lineup: %.2f pts" % base.total)
    for slot, pick in base.slots:
        print("    %-6s %s" % (slot, pick.name if pick else "(unfilled)"))

    if args.waivers or not (args.waivers or args.start_sit):
        # F8. Points, not just name, is the tiebreak. `delta` ties at 0.00
        # often - every free agent too weak to crack the lineup ties there,
        # not just two who happen to be close - and among players who add
        # nothing THIS week, the better player is the better stash for next
        # week. Sorting those ties by name alone put a 1.10-point bench
        # option (Tyrone Tracy Jr.) above a 1.60-point one (Woody Marks) for
        # no reason but the alphabet. `-c.points` breaks the delta tie by
        # who is the better player; name remains the final tiebreak for a
        # genuine points tie too (see
        # test_waiver_ranking_ties_break_by_name_not_page_order), and
        # `sorted` being stable is still what makes that deterministic.
        ranked = sorted(free, key=lambda c: (-delta(lg, roster, c), -c.points, c.name))
        shown = ranked[:args.top]
        print("\n  WAIVER TARGETS (top %d of %d)   %-8s %-6s %-26s %s"
              % (len(shown), len(ranked), "+PTS", "SLOT", "PLAYER", "DROP"))
        for c in shown:
            d = delta(lg, roster, c)
            # F8. A slot label is a claim that the addition CRACKS the
            # lineup. `best_lineup` breaks a pure points tie by name, so a
            # free agent who ties the worst starter exactly - delta 0.00,
            # by definition no better - can still be the one chosen into a
            # named slot (e.g. FLEX3) purely on alphabetical luck. Printing
            # that slot would read as "this claim improves your lineup" when
            # it provably does not, so any zero-gain row shows as bench
            # regardless of which slot the tie happened to resolve into.
            where = "bench"
            if d > 0:
                after = best_lineup(lg, roster + [c])
                slot = next((s for s, p in after.slots if p and p.name == c.name),
                            None)
                where = slot if slot else "bench"
            # THE DROP. A claim in this league is a swap - the roster is
            # capped at `roster_size` - so an addition with no named
            # release is advice that cannot be submitted. `net` is not
            # reprinted beside `d`: they are provably equal at this
            # league's geometry (see lineup.best_add_drop), and showing
            # two identical columns would imply a distinction that does
            # not exist here.
            drop, _net = best_add_drop(lg, roster, c)
            drop_label = drop.name if drop else "(open spot)"
            print("    %-8.2f %-6s %-26s %s"
                  % (d, where, "%s (%s)" % (c.name, c.pos), drop_label))

        if shown:
            print("\n    DROP = the cheapest release THIS WEEK. Every release")
            print("    that leaves the same optimal lineup ties at zero cost,")
            print("    and this breaks those ties by lowest projection - it")
            print("    cannot see bye weeks or next week, so check the pick")
            print("    before submitting.")

    if args.start_sit:
        optimal_by_key = dict((normalize_name(p.name), p.name)
                              for _s, p in base.slots if p)
        if not args.current:
            print("\n  no current lineup supplied - printing the optimum only")
        else:
            current_by_key = {}
            for line in open(args.current):
                name = line.strip()
                if name:
                    current_by_key[normalize_name(name)] = name

            # --current is documented as the whole eight-player lineup set
            # on CBS. A name with no projection was never in by_key at all,
            # so it is excluded from SIT here, same as `missing` excludes it
            # from the roster above - and NAMED, so the exclusion is visible
            # rather than reading as "bench your kicker."
            #
            # CORRECTED 2026-08-30: this comment used to justify the
            # exclusion with "sources/cbs-weekly.yaml only defines the
            # RB-WR-TE group - a TQB, K or DST name has no projection." That
            # reason is dead. Four groups are defined now (RB-WR-TE, TQB,
            # DST, K) and `week` takes --projections-tqb/-k/-dst, so a
            # TQB/K/DST name DOES resolve whenever its page was supplied.
            # The exclusion itself still stands, for the general reason
            # above: it now fires when a page was not passed, or a player
            # genuinely has no row - which is a signal worth seeing, not the
            # weekly norm it used to be. `sffl alert` distinguishes those
            # cases explicitly (see alert.POSITION_NOT_CAPTURED and
            # friends); `week` states the fact without classifying it.
            not_evaluated = sorted(current_by_key[k] for k in current_by_key
                                   if k not in by_key)
            for name in not_evaluated:
                print("  no projection for %s - not evaluated for "
                      "start/sit, NOT a recommendation to sit him" % name)
            current_by_key = dict((k, v) for k, v in current_by_key.items()
                                  if k in by_key)

            start = sorted(optimal_by_key[k] for k in optimal_by_key
                           if k not in current_by_key)
            sit = sorted(current_by_key[k] for k in current_by_key
                         if k not in optimal_by_key)
            if not start and not sit:
                print("\n  lineup is already optimal - no changes")
            else:
                print("\n  START           SIT")
                for i in range(max(len(start), len(sit))):
                    a = start[i] if i < len(start) else ""
                    b = sit[i] if i < len(sit) else ""
                    print("    %-15s %s" % (a, b))
    return 0


class _AllProjectionsFailed(Exception):
    """Every one of the four position-group pages failed this run.

    A DELIBERATELY DISTINCT exception type from `CaptureError`, not a
    string this module inspects after the fact. `_cmd_alert` needs to tell
    "the roster capture itself failed" (still `CaptureError`/`ValueError`,
    unchanged - the roster is a precondition for everything else) apart
    from "the roster was read fine but every projection page failed" -
    `compose()` renders the two completely differently (see its
    docstring), and reusing `CaptureError` for both, caught by the same
    `except`, was exactly the bug a reviewer caught: the roster-failure
    prose ("Fix: cbs_login.py") was shown for a projections-only failure,
    pointing at the wrong fix.
    """


def _cmd_alert(args):
    """Capture, score, and push one digest. The launchd entry point.

    ORDER MATTERS. Capture first and let a failure short-circuit everything:
    a stale or unverified page must never reach the composer, because an
    expired CBS session parses to an empty roster that looks exactly like a
    real one with nobody on it.
    """
    import datetime
    import os

    from sffl.alert import (POSITION_NOT_CAPTURED, PROJECTION_MISSING,
                            PROJECTION_PAGE_FAILED, STALE_INJURIES_MINUTES,
                            BoardRow, STALE_PROJECTIONS_HOURS, compose)
    from sffl.calibrate import load_curves
    from sffl.capture import CaptureError, capture
    from sffl.pool import score_season, score_season_calibrated
    from sffl.trade import games_remaining, rank_targets
    from sffl.cbs_weekly import (WEEK_MISMATCH_RATIO, read_report_stamp,
                                 shared_team_count, week_conflicts)
    from sffl.cbs_roster import parse_lineup_rows
    from sffl.cbs_weekly import DEFAULT_PROFILE, _load_owner_codes
    from sffl.cbs_weekly import is_out
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import IdentityIndex, normalize_team
    from sffl.injuries import for_roster, load as load_injuries
    from sffl.league import load_league
    from sffl.lineup import Candidate, best_lineup
    from sffl.notify import send, topic_from_keychain
    from sffl.pool import score_week

    lg = load_league(args.league)

    capture_error = None
    # Distinct from `capture_error` - see `_AllProjectionsFailed`'s
    # docstring and `compose`'s. Set ONLY when the roster was read fine but
    # every one of the four projection pages failed.
    projections_capture_error = None
    roster_names = []
    # None means "capture never got far enough to know" - distinct from a
    # successful parse that legitimately found nobody starting. `compose`
    # renders those two states differently (see its docstring), so this
    # must not default to `[]`.
    current_starters = None
    # Week/freshness validation outcomes. None means "the check did not
    # fire", never "the check passed" - compose distinguishes the two.
    week_mismatch = None
    stale_projections = None
    # None means "not attempted" (Sunday, or --no-trade); [] would claim the
    # search ran and found nothing.
    trade_targets = None
    trade_error = None
    projections_age_hours = None
    # None, not [] - see compose's docstring. [] would render "BENCH ... (0)"
    # and assert an empty bench on a run where the roster was never read at
    # all, which is a claim this code cannot make.
    roster_board = None
    # Current starters that were never scored. `None` for the same reason
    # `current_starters` is: until the projections parse, nobody knows.
    unevaluated_starters = None
    reports = []
    sidelined = []
    result = None
    age_days = 0
    # (group, reason) for each of the four position-group pages that could
    # NOT be captured or parsed on THIS run. Distinct from
    # POSITION_NOT_CAPTURED below: that means the pipeline never covers this
    # position at all (a permanent scope limit); this means it normally
    # does and THIS run's fetch of it failed (a transient, one-run
    # problem) - conflating the two would make a DST page that starts
    # 404ing in week 6 read as "we've never captured defenses," which is
    # false and hides the actual, fixable failure.
    group_failures = []
    # (name, pos, kept_group, dropped_group) for every TRUE cross-group
    # projection duplicate `_merge_projection_groups` found - EMPTY in the
    # ordinary case. Tracked here (not just printed inside the merge) so
    # it can also reach the pushed body and the exit code, like every
    # other degradation this command reports.
    cross_group_duplicates = []
    # (name, pos, team) for every projection row that STILL collides after
    # keying on all three fields - see the by_key construction below and
    # `cbs_roster`'s module docstring's "THE COMPOSITE KEY IS A HEURISTIC"
    # note. EMPTY in the ordinary case; the key is a strong disambiguator
    # but not a PROVEN-unique one, so this is the safety net for whatever
    # it still cannot tell apart (e.g. two same-named players at the same
    # position on the same team).
    residual_projection_duplicates = []
    # (group, row_count) for every position-group page whose parsed rows
    # ALL came back with `player_id == ""` this run, despite having rows at
    # all - Task 3b review round 1 Important 3: without this, `sffl.
    # capture.capture` silently losing its id extraction on one page (a
    # CBS markup change, say) degrades every join on that page's rows back
    # to the (name, team, pos) composite FOREVER, with zero indication
    # anywhere - exactly the rot Task 3b's own brief asked this feature to
    # guard against. A single row lacking an id (real churn - a player
    # dropped from a live page between one capture and the next) is NOT
    # reported here; only TOTAL loss across an entire page's rows is,
    # since that is the signal a real extraction regression produces (a
    # live capture 2026-08-30 measured 100%, 98/98, 32/32, and 32/32
    # coverage across the four groups - occasional single misses are
    # normal, wholesale loss is not).
    id_coverage_losses = []

    try:
        # ROSTER FIRST, its own capture() call, and any failure here still
        # suppresses the whole digest exactly as before this task - an
        # unverified roster parses to an empty one, and nothing downstream
        # can be trusted once that has happened.
        roster_written = capture({"roster": args.team_url}, args.out_dir,
                                 args.profile_dir)
        roster_path = roster_written[args.team_url]
        # parse_lineup_rows, not parse_lineup/parse_roster: the page also
        # carries Jeff's CURRENT starting lineup, which is the actual
        # start/sit value - compose() renders it against the optimum
        # below. Each `RosterRow(name, slot, team)` keeps its own slot AND
        # team rather than collapsing by name alone (see cbs_roster's
        # module docstring) - the fix for a real, reproduced bug: a
        # roster carrying the SAME NFL team for both TQB and DST used to
        # silently lose the second row's slot entirely, rendering that
        # slot `-- UNFILLED` at exit 0 with no mention anywhere.
        starter_rows, reserve_rows = parse_lineup_rows(roster_path)
        roster_rows = starter_rows + [r for r in reserve_rows
                                      if r not in starter_rows]
        # `current_starters` is (name, pos, team) triples, not bare names -
        # see `alert.compose`'s docstring for why name alone cannot tell
        # two same-named starters apart (the same Chargers TQB/DST shape).
        # `r.team` is normalized here (minor review fix): `RosterRow.team`
        # is RAW off the page (see cbs_roster's module docstring - a
        # page-parsing module has no opinion on identity normalization),
        # but `alert._start_sit_diff` compares this tuple's team against
        # `Candidate.team`, which IS normalized (`PlayerProjection.team` is
        # normalized at parse time by `cbs_weekly.parse`). Left raw, a
        # JAX/WSH/LVR-coded starter would build a key that never matches
        # its own optimal-lineup entry and land in BOTH the START and SIT
        # columns - latent today only because every fixture's team codes
        # already happen to be canonical.
        current_starters = [(r.name, r.slot, normalize_team(r.team))
                            for r in starter_rows]
        roster_names = [r.name for r in roster_rows]
        age_days = int(
            (datetime.datetime.now()
             - datetime.datetime.fromtimestamp(os.path.getmtime(roster_path)))
            .total_seconds() // 86400)

        curves = load_curves(args.curves) if args.curves else None

        # EACH of the four position-group pages gets its OWN capture() call,
        # in its OWN try/except - not one combined call for all four. A
        # single combined call shares one browser-navigation loop inside
        # `capture()` (see capture.py) that raises and stops on the FIRST
        # page that fails, so pages later in that one call would never even
        # be attempted - exactly the outcome Task 3 exists to prevent ("a
        # failure on one page should not prevent the other three from being
        # captured and scored"). Recovering already-written pages from a
        # single failed combined call was considered and rejected: it would
        # depend on capture.py's internal out_dir/name.txt file-naming
        # scheme, which is not part of its documented return-or-raise
        # contract and which this task's file scope does not include
        # changing. The cost is real (see the report's timing section) but
        # bounded and predictable, and correctness under partial failure
        # matters more here than shaving a few seconds off a background job.
        group_rows = []
        page_stamps = {}
        for group in ALERT_GROUPS:
            url = (args.projections_url
                   if group == "RB-WR-TE" and args.projections_url
                   else _projections_url(group, args.week))
            try:
                written = capture({group: url}, args.out_dir,
                                  args.profile_dir)
                rows = parse_weekly(written[url], group=group,
                                    week=args.week, season=lg.season)
            except (CaptureError, ValueError) as exc:
                group_failures.append((group, str(exc)))
                continue
            group_rows.append((group, rows))
            # The page stamps its own freshness. Read here, while the file
            # path is still in hand, because nothing downstream keeps it.
            page_stamps[group] = read_report_stamp(written[url])
            if rows and not any(p.player_id for p in rows):
                id_coverage_losses.append((group, len(rows)))

        if not group_rows:
            # Every single position-group page failed - the projections
            # half of this run learned NOTHING. Nothing downstream can be
            # SCORED, but the ROSTER above was read fine, which is a
            # meaningfully different failure from the roster capture
            # failing outright - `_AllProjectionsFailed` (not
            # `CaptureError`) keeps the two apart all the way to `compose`,
            # which renders a message that says so and does NOT tell the
            # reader to re-run cbs_login.py for a problem login had nothing
            # to do with.
            raise _AllProjectionsFailed(
                "all %d position-group projection pages failed to capture "
                "or parse: %s" % (
                    len(ALERT_GROUPS),
                    "; ".join("%s (%s)" % (g, m) for g, m in group_failures)))

        # WEEK VALIDATION. `--week` used to be accepted by parse() and
        # dropped on the floor: a saved week-3 page handed to a week-4 run
        # exited 0 and produced a confident lineup. Two independent signals
        # now guard it, and they catch different failures:
        #
        #   1. Cross-page opponent agreement. Every page in one run is the
        #      same NFL week and TQB/DST both list all 32 teams, so a mixed
        #      pair disagrees on essentially every shared team (measured:
        #      32/32). Judged by RATIO, because CBS's own TQB page ships a
        #      known 2-team OPP defect - see cbs_weekly.WEEK_MISMATCH_RATIO.
        #   2. Page freshness. The page's own "REPORT UPDATED AS OF" stamp,
        #      which the in-season spec named as the staleness signal and
        #      which nothing read until now.
        #
        # Neither can be a hard failure: this job runs unattended ninety
        # minutes before kickoff, and refusing to send anything because one
        # signal looks off is strictly worse than sending a lineup that says
        # so. Both degrade the run and are rendered in the message.
        pages_by_group = dict(group_rows)
        n_shared = shared_team_count(pages_by_group)
        conflicts = week_conflicts(pages_by_group)
        if n_shared and (float(len(conflicts)) / n_shared) > WEEK_MISMATCH_RATIO:
            week_mismatch = (len(conflicts), n_shared, conflicts[:3])

        known = [t for t in page_stamps.values() if t is not None]
        if known:
            newest = max(known)
            age_h = (datetime.datetime.now() - newest).total_seconds() / 3600.0
            projections_age_hours = age_h
            if age_h > STALE_PROJECTIONS_HOURS:
                stale_projections = (age_h, newest)

        projections, _owner_group, cross_group_duplicates = (
            _merge_projection_groups(group_rows))

        # Keyed on `p.key()` - `identity.resolve_key`'s SINGLE per-row key:
        # a real CBS `player_id` (lifted from a `playerpage/<id>` link by
        # `sffl.capture.capture`) when the row has one, `identity.
        # player_key`'s (name, team, pos) composite as the documented
        # fallback when it does not. This IS the right tool HERE - deduping
        # `projections` against ITSELF is a SYMMETRIC, single-source check
        # (see `resolve_key`'s own docstring, corrected in Task 3b review
        # round 1: it is the WRONG tool for the asymmetric roster ↔
        # projections join further below, which uses `IdentityIndex`
        # instead). NOT (name, pos): the NFL has had two simultaneously
        # active players sharing a name at the same position on DIFFERENT
        # teams (real, not hypothetical - see `_merge_projection_groups`'s
        # docstring), and a (name, pos) key would silently merge them,
        # handing one player's projection to the other. THE COMPOSITE
        # FALLBACK IS STILL A HEURISTIC, NOT A PROVEN-UNIQUE IDENTITY - see
        # `cbs_roster`'s module docstring for why - so a residual collision
        # (two rows that still share this key) is DETECTED and REPORTED
        # here, exactly like `_merge_projection_groups`'s cross-group one,
        # never silently resolved by keeping the first and dropping the
        # second. This also naturally catches a within-group duplicate
        # `_merge_projection_groups` deliberately leaves untouched (see its
        # docstring) whenever that duplicate is a TRUE one rather than a
        # normalize_name suffix collision between two different real
        # players (those have different keys here too, since name differs)
        # - UNLESS both rows carry ids, in which case a suffix collision
        # like that can no longer happen here at all: their ids differ, so
        # their resolve_key values differ too. This branch is therefore
        # only ever reached via the composite fallback - a genuine id
        # collision (two DIFFERENT rows both claiming the SAME id) is the
        # one case an id cannot resolve either, and lands here just as
        # loud, correctly described below as a JOIN KEY collision, not
        # asserted to be caused by a missing id (Task 3b review round 1
        # minor: the pushed-body banner used to claim EVERY residual here
        # was "because at least one of them carried no CBS id," which is
        # false for the shared-id case - the per-row WARNING below already
        # named that case correctly; only the pushed-body banner text was
        # wrong, and is now worded to cover both without asserting which).
        by_key = {}
        for p in projections:
            key = p.key()
            if key in by_key and by_key[key] is not p:
                print("  WARNING: %r (%s, %s) shares its join key with %r "
                      "(%s, %s) even after the id-first, composite-fallback "
                      "join (see identity.resolve_key) - this is either a "
                      "true duplicate row, an id CBS assigned to two rows, "
                      "or two DIFFERENT real players whose (name, team, "
                      "position) composite happened to collide (e.g. a "
                      "generational suffix normalize_name strips) because "
                      "at least one of them carried no CBS id. Keeping the "
                      "first row seen, dropping this one so the pool is not "
                      "double-counted."
                      % (p.name, p.pos, p.team, by_key[key].name,
                         by_key[key].pos, by_key[key].team))
                residual_projection_duplicates.append((p.name, p.pos, p.team))
                continue
            by_key[key] = p

        # THE ACTUAL ROSTER <-> PROJECTIONS JOIN - deliberately NOT built by
        # calling `resolve_key` per roster row and looking that single key
        # up in `by_key`. Task 3b review round 1 reproduced, live, exactly
        # why that is wrong: `resolve_key` never computes a composite key
        # for a row that HAS an id, so if the roster's capture carried real
        # ids while a projections page's capture (this run) carried none at
        # all - the two sides of this join CAN legitimately disagree, since
        # each page's id extraction succeeds or degrades independently -
        # every roster row's `"id:<n>"` key missed `by_key` entirely (every
        # projection in it was keyed by ITS OWN composite instead) and
        # NOTHING fell back to anything. Result: BEST LINEUP 0.00 pts,
        # every slot UNFILLED, exit 0, no DEGRADED banner - worse than the
        # heuristic this task replaced, and completely silent.
        #
        # `IdentityIndex` (see identity.py) is the fix: every surviving
        # projection is indexed under BOTH its id (if it has one) AND its
        # composite key, and a lookup tries the id first, falling back to
        # composite - so either side losing its ids independently still
        # resolves via whichever key the OTHER side can supply. Built from
        # `by_key.values()`, not `projections` directly, so it inherits the
        # dedup already done above (a true duplicate never reaches it).
        lookup_index = IdentityIndex()
        for p in by_key.values():
            lookup_index.add(p.player_id, p.name, p.team, p.pos, p)

        # Each `RosterRow` already knows its OWN slot and team - no more
        # "which position does this bare name mean" ambiguity to detect:
        # `parse_lineup_rows` never collapsed the Chargers TQB/DST case (or
        # any other same-name-different-row case) in the first place, so
        # each row is looked up independently and CORRECTLY, not merely
        # flagged as unresolvable. `resolved` maps each `RosterRow` (the
        # namedtuple itself, hashable) to its matching `PlayerProjection`,
        # or omits it entirely when `lookup_index` finds nothing - the
        # single source every downstream computation below reads from,
        # rather than each recomputing its own key/lookup independently.
        resolved = {}
        for r in roster_rows:
            match = lookup_index.get(r.player_id, r.name, r.team, r.slot)
            if match is not None:
                resolved[r] = match

        # Which positions had NO usable data this run because their OWN
        # page failed to capture or parse - as opposed to a position no
        # group covers at all (a permanent scope limit). Checked BEFORE
        # `covered_positions` below in the loop, because a failed group's
        # position is also, incidentally, absent from `covered_positions`
        # (no rows came back from it) - without this check that transient,
        # one-run failure would misreport as "this pipeline has never
        # captured this position," which is false and was flagged by a
        # reviewer against a stubbed K-page failure.
        failed_positions = set()
        for failed_group, _reason in group_failures:
            failed_positions |= GROUP_POSITIONS.get(failed_group, frozenset())

        # C1. Which of CBS's eight starters could not be scored at all, and
        # WHY. Before this task only RB-WR-TE was ever captured, so the TQB,
        # the kicker and the defense had no projection and were not in
        # `resolved`; the START/SIT diff in `compose` is a set difference,
        # so before that fix they landed in the SIT column every single
        # week, dressed as merit-based bench advice.
        #
        # The covered positions are read off the MERGED pages themselves
        # rather than off a group name, because what actually decides
        # whether a missing projection is expected is what the pages
        # contained - and after this task that is ordinarily all four
        # groups, not one. A starter whose position IS covered and who
        # still has no row is a different animal - a data problem, not a
        # scope limit - and the two must not be reported as one thing.
        covered_positions = set(p.pos for p in projections)

        def _why_unscored(row):
            """Why this roster row has no projection. See _UNEVALUATED_REASONS.

            Factored out because the BENCH board needs the SAME answer for a
            RESERVE, and the two must never drift: a bench player and a
            starter with identical missing data have identical causes, and
            two copies of this ladder would eventually disagree about which.
            """
            if row.slot in failed_positions:
                return PROJECTION_PAGE_FAILED
            if row.slot and row.slot in covered_positions:
                return PROJECTION_MISSING
            return POSITION_NOT_CAPTURED

        unevaluated_starters = []
        for row in starter_rows:
            if row in resolved:
                continue
            unevaluated_starters.append(
                (row.name, row.slot, _why_unscored(row)))

        sidelined = sorted((resolved[r].name, resolved[r].status)
                           for r in roster_rows
                           if r in resolved and is_out(resolved[r].status))
        result = best_lineup(lg, [
            Candidate(name=resolved[r].name, pos=resolved[r].pos,
                      points=score_week(lg, resolved[r], curves),
                      team=resolved[r].team)
            for r in roster_rows
            if r in resolved and not is_out(resolved[r].status)])

        # EVERY rostered player, not just the eight that got slotted. All
        # thirteen were already CONSIDERED above (`roster_rows` is starters
        # plus reserves); until this existed the digest simply never showed
        # the twelve-odd numbers behind the eight names it printed, so a
        # reserve out-projecting a startable starter was invisible on the
        # phone. Out players are scored and listed here WITH their status
        # rather than dropped: `best_lineup` must not pick them (it does not
        # - they are filtered out of the pool above), but the reader still
        # needs to see who they are and what they would have been worth.
        # TRADE TARGETS - FRIDAY ONLY, and never at the cost of the digest.
        # Friday is the planning message with two days of runway; Sunday is
        # ninety minutes from kickoff and has no use for a trade idea. The
        # whole block is wrapped because it is a nice-to-have bolted onto a
        # job whose real purpose is telling Jeff who is hurt: four extra page
        # captures must not be able to take that down, so ANY failure here
        # degrades to a one-line note and the alert goes out regardless.
        # getattr, not args.no_trade: this function is called directly with a
        # hand-built Namespace by a good deal of the test suite, and a new
        # required attribute would break every one of those callers for a
        # flag they have no opinion about.
        if args.kind == "friday" and not getattr(args, "no_trade", False):
            try:
                ros_rows = []
                # Keyed "<group>-ROS", NOT "<group>": `capture` names the
                # file it writes after the key, so reusing the weekly name
                # OVERWRITES data/captures/<group>.txt with rest-of-season
                # content. Harmless inside a single run (the weekly parse is
                # already done by here) but it leaves the on-disk weekly
                # capture silently holding the wrong season's numbers, which
                # is exactly the kind of thing someone debugs for an hour.
                for group in ALERT_GROUPS:
                    written = capture({ROS_GROUPS[group]: _ros_url(group)},
                                      args.out_dir, args.profile_dir)
                    ros_rows.extend(parse_weekly(
                        written[_ros_url(group)], group=ROS_GROUPS[group],
                        week=args.week, season=lg.season))
                # Loaded here rather than assumed in scope: `_cmd_alert`
                # never needed owner codes before this block, and referring
                # to a name that only exists in `_cmd_week`/`_cmd_trade` is
                # what made the first live Friday run report
                # "NameError: name 'owner_codes' is not defined".
                ros_classifier = _avail_classifier(
                    written[_ros_url(ALERT_GROUPS[-1])],
                    _load_owner_codes(DEFAULT_PROFILE))
                mine_names = set(normalize_name(r.name) for r in roster_rows)
                owned_by, my_token, hits = _split_pool_by_owner(
                    ros_rows, ros_classifier, mine_names, normalize_name)
                if my_token is None:
                    trade_error = ("could not tell which owner column is "
                                   "yours on the rest-of-season pages")
                elif hits < len(mine_names) / 2:
                    # A weak match means the token is probably wrong, and a
                    # wrong token would rank YOUR OWN players as targets.
                    trade_error = (
                        "only %d of %d rostered players matched the owner "
                        "column, too few to trust which team is yours"
                        % (hits, len(mine_names)))
                else:
                    def _ros_pts(p):
                        p.games = float(
                            games_remaining(args.week, p.bye)) or 1.0
                        return (score_season_calibrated(lg, p, curves)
                                if curves else score_season(lg, p))
                    mine_ros = [Candidate(p.name, p.pos, _ros_pts(p), p.team)
                                for p in owned_by[my_token]]
                    market = [(Candidate(p.name, p.pos, _ros_pts(p), p.team),
                               token)
                              for token, players in sorted(owned_by.items())
                              if token != my_token for p in players]
                    trade_targets = rank_targets(lg, mine_ros, market, top=3)
            except Exception as exc:
                # DELIBERATELY BROAD, and only around this block. The narrow
                # `except (CaptureError, ValueError)` around the projections
                # capture above must STAY narrow - broadening it would mask a
                # real capture defect as a data problem. Here the calculus is
                # reversed: this block is a convenience bolted onto a job
                # whose actual purpose is telling Jeff who is hurt, and no
                # failure in it - a KeyError from a changed page, an
                # arithmetic error in scoring, anything - may be allowed to
                # stop that message going out ninety minutes before he needs
                # it. The failure is REPORTED in the digest, never swallowed.
                # KeyboardInterrupt and SystemExit derive from BaseException
                # and are still not caught.
                trade_error = "%s: %s" % (type(exc).__name__, str(exc)[:160])

        roster_board = []
        for r in roster_rows:
            if r in resolved:
                p = resolved[r]
                roster_board.append(BoardRow(
                    name=p.name, pos=p.pos, team=p.team,
                    points=score_week(lg, p, curves),
                    status=p.status or "", why=None))
            else:
                roster_board.append(BoardRow(
                    name=r.name, pos=r.slot, team=normalize_team(r.team),
                    points=None, status="", why=_why_unscored(r)))
    except _AllProjectionsFailed as exc:
        # Checked as its OWN except, ahead of (never merged into)
        # CaptureError/ValueError below - see the class's own docstring for
        # why conflating the two misdirects the reader to the wrong fix.
        projections_capture_error = str(exc)
    except (CaptureError, ValueError) as exc:
        capture_error = str(exc)

    # C2. A failed injury fetch is NOT a quiet week. This used to be a bare
    # `if args.injuries and os.path.exists(...)`: with StatsDeck down or
    # `claude -p` failing there is no file, `reports` stayed [], and the
    # digest printed "no designations on your roster." and "nothing new." -
    # byte-identical to a genuinely quiet week - and exited 0. The only
    # warning went to stderr, which never reaches the phone. Every branch
    # below now produces either real rows or a reason the reader can see.
    injury_error = None
    injuries_age_minutes = None
    injury_fetch_failed = False
    if not args.injuries:
        # Not a failure - nobody asked for injury data on this invocation -
        # but the message must still not claim a clean roster it never
        # looked at. Rendered, not counted against the exit code.
        injury_error = ("no --injuries file was given to this run, so no "
                        "injury feed was read at all")
    elif not os.path.exists(args.injuries):
        injury_error = (
            "%s does not exist - the StatsDeck fetch step (see "
            "ops/fetch_injuries.sh) did not produce a file" % args.injuries)
        injury_fetch_failed = True
    else:
        try:
            reports = for_roster(load_injuries(args.injuries), roster_names)
            injuries_age_minutes = int(
                (datetime.datetime.now()
                 - datetime.datetime.fromtimestamp(
                     os.path.getmtime(args.injuries)))
                .total_seconds() // 60)
        except Exception as exc:
            # DELIBERATELY BROAD, and only around the injury payload - see
            # the narrow `except (CaptureError, ValueError)` above, which
            # must stay narrow because that path suppresses the lineup and
            # broadening it would mask a real capture defect as a news
            # problem.
            #
            # A file that exists but cannot be read or parsed is the same
            # class of failure as no file at all, and must not take the
            # whole alert down as a traceback: the lineup half of this
            # digest is still worth pushing, and an unattended job that
            # produces NOTHING ninety minutes before kickoff is the exact
            # outcome this branch exists to prevent. ValueError covers
            # json's decode error and injuries.load's own raise on a row
            # with no player name; OSError a read failure - but a payload
            # that is well-formed JSON of the WRONG SHAPE ({"report":
            # ["some prose"]}, or a dict where a list belongs) reaches
            # `row.get` and raises AttributeError/TypeError, which escaped
            # every handler in this process. fetch_injuries.sh's shape check
            # blocks the top-level case; it cannot vet each row. So every
            # non-exiting exception from parsing this file degrades the run
            # instead of ending it. KeyboardInterrupt and SystemExit derive
            # from BaseException and are still not caught here.
            reports = []
            injuries_age_minutes = None
            injury_error = (
                "%s could not be parsed (%s: %s). The file EXISTS, so the "
                "fetch step ran - this is a payload problem, not a failed "
                "fetch, and the fix is at the source: check its shape "
                "against ops/fetch_injuries.sh."
                % (args.injuries, type(exc).__name__, exc))
            injury_fetch_failed = True

    # Data that is real but not from this run is its own kind of wrong: it
    # renders last week's designations as today's. The alert says so, and
    # the run counts as degraded.
    if (injuries_age_minutes is not None
            and injuries_age_minutes > STALE_INJURIES_MINUTES):
        injury_fetch_failed = True

    # `current_starters` carries `parse_lineup`'s starters straight through
    # so `compose` can render the START/SIT diff against the optimum
    # itself - this used to be a second, stdout-only implementation of that
    # same diff living here, which the alert.py owner flagged as certain to
    # drift from compose's own rendering. One implementation now: compose's.
    body = compose(args.kind, age_days, reports, result, sidelined,
                   capture_error=capture_error,
                   current_starters=current_starters,
                   unevaluated_starters=unevaluated_starters,
                   injury_error=injury_error,
                   injuries_age_minutes=injuries_age_minutes,
                   projections_capture_error=projections_capture_error,
                   roster_board=roster_board,
                   week_mismatch=week_mismatch,
                   stale_projections=stale_projections,
                   projections_age_hours=projections_age_hours,
                   trade_targets=trade_targets, trade_error=trade_error)

    # A PARTIAL capture failure - one to three of the four position-group
    # pages, with the roster and at least one other page still good - must
    # be LOUD IN THE PUSHED MESSAGE ITSELF, not merely on stdout: this is
    # appended to `body` (the exact string handed to `send()` below), never
    # only printed separately, because a note that never reaches the phone
    # is exactly as invisible as the silent UNFILLED slot this task exists
    # to replace. Unlike `capture_error`, this never suppresses the digest -
    # `compose` above already rendered a real (if partial) lineup from
    # whatever DID come back, per the per-page isolation in the try block -
    # so this banner supplements that lineup instead of replacing it.
    # Skipped when `capture_error` OR `projections_capture_error` fired:
    # both of those already say nothing (or nothing scoreable) could be
    # verified at all, and a per-group breakdown under either would bury
    # the one fact that matters.
    if group_failures and not capture_error and not projections_capture_error:
        banner = ["!! PROJECTIONS DEGRADED: %d of %d position-group page(s) "
                  "could not be captured or parsed this run:"
                  % (len(group_failures), len(ALERT_GROUPS))]
        for group, reason in group_failures:
            banner.append("  - %s: %s" % (group, reason))
        banner.append(
            "  Any lineup slot normally filled from these group(s) may be "
            "missing or based on stale data this run - this is NOT the "
            "same as a position this pipeline never covers (see NOT "
            "EVALUATED above, if present).")
        body = body + "\n\n" + "\n".join(banner)

    # A TRUE cross-group projection duplicate (the same name, position, AND
    # team claimed by two different pages - see `_merge_projection_groups`)
    # is printed as a WARNING there, but that print reaches stdout ONLY -
    # unlike every other degradation this command reports, it never
    # reached the pushed body or the exit code before a reviewer flagged
    # it. It does now, on the same terms as the group-failure banner above.
    if (cross_group_duplicates and not capture_error
            and not projections_capture_error):
        dup_banner = ["!! %d cross-group projection duplicate(s) found - a "
                      "player was claimed by more than one of the four "
                      "pages, even after matching on name, position, AND "
                      "team:" % len(cross_group_duplicates)]
        for name, pos, team, kept_group, dropped_group in cross_group_duplicates:
            dup_banner.append(
                "  - %s (%s, %s): kept the %s row, dropped the %s one"
                % (name, pos, team, kept_group, dropped_group))
        body = body + "\n\n" + "\n".join(dup_banner)

    # Task 3b review round 1, Important 3: NO SIGNAL ANYWHERE previously
    # existed for id coverage silently dropping to zero on a page that
    # normally carries ids - the exact rot Task 3b's brief asked this
    # feature to guard against. Surfaced the same way every other
    # degradation here is: a named banner in the pushed body, and it counts
    # toward the exit code below. A single missed row is NOT this - only a
    # page whose EVERY row came back id-less is (see `id_coverage_losses`'s
    # own comment above for why that threshold).
    if (id_coverage_losses and not capture_error
            and not projections_capture_error):
        id_banner = [
            "!! ID COVERAGE LOST on %d of %d position-group page(s): every "
            "row parsed with no CBS player id at all, though rows were "
            "present. A live capture normally pairs virtually every row "
            "with one (100%%, measured 2026-08-30) - this usually means "
            "CBS changed the page's markup or the id-extraction broke, and "
            "every row on the named page(s) has silently fallen back to "
            "the (name, team, pos) composite key for this run:"
            % (len(id_coverage_losses), len(ALERT_GROUPS))]
        for group, count in id_coverage_losses:
            id_banner.append("  - %s: 0 of %d row(s) carried an id"
                             % (group, count))
        body = body + "\n\n" + "\n".join(id_banner)

    # A RESIDUAL projection duplicate - two rows that still share the same
    # join key even after `identity.resolve_key`'s id-first, composite-
    # fallback key was applied. TWO DISTINCT CAUSES land here, and the
    # banner below must not claim it is always one of them (Task 3b review
    # round 1 minor: this banner used to assert unconditionally "because
    # at least one of them carried no CBS id," which is FALSE for the
    # shared-id case - the per-row WARNING above already names that case
    # correctly; only this pushed-body summary was wrong):
    #   (1) two DIFFERENT real players share a (name, team, position)
    #       composite key because at least one of them carried no CBS id
    #       (e.g. `normalize_name` stripping a generational suffix -
    #       "Braelon Allen" vs "Braelon Allen Jr.", same team and
    #       position) - a player id on BOTH rows would have told them
    #       apart automatically;
    #   (2) two rows both claim the SAME CBS id - a genuine data anomaly
    #       an id cannot resolve either, since an id assumed unique turned
    #       out not to be.
    # Either way the key is a HEURISTIC for rows without an id, or an
    # assumption that turned out false for rows that share one (see
    # cbs_roster's module docstring) - this is the loud safety net for
    # whatever it still could not tell apart, rather than silently keeping
    # the first row and dropping the second.
    if (residual_projection_duplicates and not capture_error
            and not projections_capture_error):
        residual_banner = [
            "!! %d residual projection duplicate(s) found - a row's join "
            "key collided with an earlier one's even after the id-first, "
            "composite-fallback key. This does NOT necessarily mean the "
            "same player was captured twice: it can also mean two "
            "DIFFERENT real players share a (name, team, position) "
            "composite key because at least one of them carried no CBS id "
            "(e.g. a generational suffix normalize_name strips) - a "
            "player id on BOTH rows would have told them apart "
            "automatically - OR that two rows both claim the SAME CBS id, "
            "a data anomaly an id cannot resolve either. Only the first "
            "row seen is kept; check these names by hand:"
            % len(residual_projection_duplicates)]
        for name, pos, team in residual_projection_duplicates:
            residual_banner.append("  - %s (%s, %s)" % (name, pos, team))
        body = body + "\n\n" + "\n".join(residual_banner)

    print(body)

    # ORDERING: the topic is fetched HERE, after the digest above is already
    # composed and printed, not before capture/scoring even starts. This
    # runs unattended under launchd, so a run that produced a correct alert
    # but could not PUSH it is a different, more valuable failure to see in
    # the log than one that produced nothing at all - the printed body above
    # has standalone worth (it can be read straight out of the log) even
    # when delivery fails, and fetching the topic first would throw that
    # away for the sake of failing a few seconds earlier.
    delivery_error = None
    try:
        topic = topic_from_keychain()
        sent = send(topic, "SFFL %s" % args.kind.title(), body,
                    dry_run=args.dry_run)
        print("\n[%s]" % ("sent" if sent else "dry run - nothing sent"))
    except (RuntimeError, ValueError, OSError) as exc:
        # Caught here rather than left to propagate as a traceback: this
        # runs unattended at 4:45pm on a Friday, and a raw Python traceback
        # in a log file is not an actionable failure, it is a puzzle.
        # RuntimeError is the no-Keychain-entry case (its message already
        # names the exact `security add-generic-password` fix - surfaced
        # verbatim); ValueError is an empty topic/body reaching `send`;
        # OSError is the base of `urllib.error.URLError`, a real network
        # failure talking to ntfy.sh. All three mean the same thing to
        # launchd's log: the alert was built correctly but not delivered.
        print("\n[DELIVERY FAILED] %s" % exc)
        delivery_error = exc

    # A capture failure, an all-projections failure, a DEGRADED run (the
    # injury fetch produced nothing, or produced something that is not
    # from this run, or one to three of the four position-group pages
    # failed - `group_failures` - or a cross-group projection duplicate was
    # found, or a page's id coverage silently dropped to zero across every
    # row - `id_coverage_losses`, Task 3b review round 1 - or a residual
    # (name, pos, team) collision survived even the full composite key -
    # see `residual_projection_duplicates`), or the projections failing a
    # week/freshness check - `week_mismatch`, `stale_projections`: a lineup
    # built on the wrong week's or days-old numbers is wrong in a way no
    # other signal in this run reveals - or a delivery failure is each
    # visible in a way launchd's log must be able to see, so each makes
    # the exit code non-zero - but they are DIFFERENT failures (nothing
    # produced, vs. an alert missing half its content, vs. a correct alert
    # that could not be pushed), and the printed body above, not the exit
    # code, is what tells them apart. A missing --injuries argument is NOT
    # counted here: that is a deliberate invocation, not a failed step, and
    # it is still stated in the body.
    return 1 if (capture_error or projections_capture_error
                or injury_fetch_failed or delivery_error or group_failures
                or cross_group_duplicates or id_coverage_losses
                or residual_projection_duplicates
                or week_mismatch or stale_projections) else 0


def _split_pool_by_owner(rows, classifier, roster_names, normalize_name):
    """({owner_token: [rows]}, my_token, hits) from one pool of projections.

    Ownership is read off the page's OWN owner column, never by joining a
    name list against it - a name-only join matches "Chargers" to BOTH the
    TQB and the DST row, which reported a 13-man roster as 16 entries the
    first time this was written.

    Which token is Jeff's is decided by overlap with `roster_names` and the
    hit count is returned so the caller can PRINT it: CBS truncates the
    column ("Sgt Hu..."), so the token is neither the team name nor stable
    enough to hard-code, and a wrong guess must be visible rather than
    silent.

    Shared by `sffl trade` and the Friday alert's trade block so the two
    cannot drift apart on who owns whom.
    """
    owned_by = {}
    for p in rows:
        if classifier(p.avail or "") != "owned":
            continue
        owned_by.setdefault((p.avail or "").strip(), []).append(p)
    my_token, hits = None, 0
    for token, players in owned_by.items():
        n = sum(1 for p in players if normalize_name(p.name) in roster_names)
        if n > hits:
            my_token, hits = token, n
    return owned_by, my_token, hits


def _cmd_trade(args):
    """Rest-of-season trade valuation. READ-ONLY - never contacts a manager.

    Deliberately has no path to CBS's trade form. A proposal is a message to
    a real person in Jeff's league; this command drafts one and stops. See
    `trade.draft_proposal`.
    """
    from sffl.calibrate import load_curves
    from sffl.cbs_weekly import DEFAULT_PROFILE, _load_owner_codes
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import normalize_name
    from sffl.league import load_league
    from sffl.lineup import Candidate
    from sffl.pool import score_season, score_season_calibrated
    from sffl.trade import (acquisition_value, draft_proposal, evaluate_trade,
                            games_remaining, lineup_value, rank_targets,
                            release_cost)

    lg = load_league(args.league)
    curves = load_curves(args.curves) if args.curves else None
    owner_codes = _load_owner_codes(DEFAULT_PROFILE)

    # The -ROS groups, not the weekly ones. CBS's restofseason pages carry an
    # extra FPTS/G column and `parse` slices the stat block off the RIGHT, so
    # a weekly map reads every field one place out - see sources/
    # cbs-weekly.yaml's REST OF SEASON block.
    group_files = [(args.group, args.projections)]
    for group, path in (("TQB-ROS", args.projections_tqb),
                        ("K-ROS", args.projections_k),
                        ("DST-ROS", args.projections_dst)):
        if path:
            group_files.append((group, path))

    rows = []
    for group, path in group_files:
        rows.extend(parse_weekly(path, group=group, week=args.week,
                                 season=lg.season))

    # ROS points, not weekly. `score_season_calibrated` divides by games,
    # bands the per-game line through the curves, and multiplies back up -
    # exactly what a rest-of-season TOTAL needs, and the reason `games` has
    # to be right per player rather than a league-wide constant.
    def ros(p):
        p.games = float(games_remaining(args.week, p.bye)) or 1.0
        # `score_season_calibrated` REQUIRES curves and raises on None. With
        # no --curves the honest fallback is `score_season`, which bands the
        # per-game mean directly - a documented approximation (see its own
        # docstring) rather than a crash, and the same one the auction path
        # used before curves existed.
        if curves is None:
            return score_season(lg, p)
        return score_season_calibrated(lg, p, curves)

    # WHOSE PLAYERS ARE WHOSE, taken off the page's own owner column rather
    # than by joining a name list against it. Two reasons, and the first is a
    # correctness bug this codebase has hit repeatedly: a name-only join
    # matches "Chargers" to BOTH the TQB row and the DST row, so a 13-man
    # roster came back as 16 entries with the same team counted twice. Every
    # projection row already carries its own (name, pos, team) and its
    # owner, so reading ownership off the row cannot collide at all.
    classifier = _avail_classifier(args.projections, owner_codes)
    roster_names = set(normalize_name(l.strip())
                       for l in open(args.roster) if l.strip())

    owned_by, my_token, my_hits = _split_pool_by_owner(
        rows, classifier, roster_names, normalize_name)
    if my_token is None:
        print("could not identify which owner column is yours - no owned row "
              "matched any name in %s" % args.roster)
        return 1

    mine = [Candidate(name=p.name, pos=p.pos, points=ros(p), team=p.team)
            for p in owned_by[my_token]]
    market = [(Candidate(name=p.name, pos=p.pos, points=ros(p), team=p.team),
               token)
              for token, players in sorted(owned_by.items()) if token != my_token
              for p in players]

    if not mine:
        print("no rostered player resolved to a projection - nothing to value")
        return 1
    print("  you are %r on this page (%d of your %d roster names matched)"
          % (my_token, my_hits, len(roster_names)))

    print("REST-OF-SEASON, from week %d (%d weeks left)"
          % (args.week, games_remaining(args.week, 0)))
    print("  your starting lineup, ROS: %.1f pts" % lineup_value(lg, mine))
    print("\n  WHAT EACH ROSTERED PLAYER IS WORTH TO YOUR LINEUP")
    print("  %-24s %-5s %9s %9s" % ("PLAYER", "POS", "ROS PTS", "IF TRADED"))
    for cand in sorted(mine, key=lambda x: -release_cost(lg, mine, x)):
        print("  %-24s %-5s %9.1f %9.1f"
              % (cand.name[:24], cand.pos, cand.points,
                 -release_cost(lg, mine, cand)))

    if args.get or args.give:
        by_name = dict((normalize_name(c.name), c) for c in mine)
        market_by_name = dict((normalize_name(c.name), (c, o))
                              for c, o in market)
        give, get, unknown = [], [], []
        for n in (args.give or "").split(",") if args.give else []:
            k = normalize_name(n.strip())
            (give.append(by_name[k]) if k in by_name else unknown.append(n.strip()))
        for n in (args.get or "").split(",") if args.get else []:
            k = normalize_name(n.strip())
            (get.append(market_by_name[k][0]) if k in market_by_name
             else unknown.append(n.strip()))
        if unknown:
            print("\n  NOT FOUND (refusing to price a trade around a player "
                  "this pool does not contain): %s" % ", ".join(unknown))
            return 1
        my_net = evaluate_trade(lg, mine, give, get)
        # The counterparty's side, computed the same way from THEIR roster -
        # a proposal quoting only the proposer's gain is one the recipient
        # checks in thirty seconds and resents for the rest of the season.
        owner = market_by_name[normalize_name(args.get.split(",")[0].strip())][1] \
            if args.get else "another team"
        theirs = [c for c, o in market if o == owner]
        their_net = (evaluate_trade(lg, theirs, get, give)
                     if all(any((t.name, t.pos, t.team) == (g.name, g.pos, g.team)
                                for t in theirs) for g in get) else float("nan"))
        print("\n  TRADE EVALUATION")
        print("    you give: %s" % (", ".join(c.name for c in give) or "nobody"))
        print("    you get:  %s" % (", ".join(c.name for c in get) or "nobody"))
        print("    your ROS lineup change:  %+.2f" % my_net)
        print("    their ROS lineup change: %+.2f" % their_net)
        print("\n  DRAFT PROPOSAL (review and send yourself - this tool "
              "never contacts another manager)\n")
        for line in draft_proposal("your team", owner, give, get,
                                   my_net, their_net).split("\n"):
            print("    %s" % line)
        return 0

    print("\n  TOP ACQUISITION TARGETS (held by other teams)")
    print("  %-24s %-5s %9s %9s  %s"
          % ("PLAYER", "POS", "ROS PTS", "+YOUR LU", "OWNER"))
    for cand, owner, gain in rank_targets(lg, mine, market, top=args.top):
        print("  %-24s %-5s %9.1f %9.2f  %s"
              % (cand.name[:24], cand.pos, cand.points, gain, owner))
    print("\n  +YOUR LU is what he would add to YOUR optimal lineup, not his")
    print("  projection. A fourth receiver's points are mostly unreachable in")
    print("  a lineup that starts one WR/TE and three FLEX.")
    return 0


def _cmd_lineup(args):
    """Set the CBS starting lineup to this week's optimum.

    DRY RUN BY DEFAULT. `--confirm` is the only thing that makes this touch
    the live team, and it is refused when stdin is not a TTY so a scheduled
    job can never submit: CBS applies each move as it happens with no save
    step and no undo, and an unattended run that half-completes leaves a real
    mixed lineup ninety minutes before kickoff.
    """
    import sys as _sys

    from sffl.calibrate import load_curves
    from sffl.cbs_lineup import LineupWriteError, apply_swaps, open_edit_mode
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.league import load_league
    from sffl.lineup import Candidate, best_lineup
    from sffl.lineup_write import describe_plan, plan_swaps
    from sffl.pool import score_week

    lg = load_league(args.league)
    curves = load_curves(args.curves) if args.curves else None

    group_files = [(args.group, args.projections)]
    for group, path in (("TQB", args.projections_tqb), ("K", args.projections_k),
                        ("DST", args.projections_dst)):
        if path:
            group_files.append((group, path))
    rows = []
    for group, path in group_files:
        rows.extend(parse_weekly(path, group=group, week=args.week,
                                 season=lg.season))
    # Joined on CBS's own player id, never on name. The lineup page and the
    # projections pages come from the same site and carry the same ids, and
    # name matching is what put "Chargers" in two places at once elsewhere in
    # this codebase.
    points_by_id = dict((p.player_id, p) for p in rows if p.player_id)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            args.profile_dir, headless=not args.show, timeout=45000)
        try:
            page = ctx.new_page()
            current = open_edit_mode(page)
            cands, unpriced = [], []
            for slot in current:
                proj = points_by_id.get(slot.player_id)
                if proj is None:
                    unpriced.append(slot)
                    continue
                cands.append((slot, Candidate(
                    name=slot.name, pos=slot.pos,
                    points=score_week(lg, proj, curves), team=proj.team)))
            if unpriced:
                # Refuse rather than optimise around a hole: a player with no
                # projection scores 0 and would be benched by arithmetic
                # rather than by judgement.
                print("REFUSING: %d rostered player(s) have no projection in "
                      "the pages given, and a missing projection scores zero "
                      "- which would bench a healthy player as if he were "
                      "worthless:" % len(unpriced))
                for slot in unpriced:
                    print("    %-22s (%s, id %s)" % (slot.name, slot.pos,
                                                     slot.player_id))
                return 1

            id_by_cand = dict((id(c), slot.player_id) for slot, c in cands)
            best = best_lineup(lg, [c for _s, c in cands])
            target_ids = set(id_by_cand[id(p)] for _slot, p in best.slots if p)
            swaps = plan_swaps(current, target_ids)

            print("CURRENT starters: %s"
                  % ", ".join(s.name for s in current if s.starting))
            print("OPTIMAL (%.2f pts): %s"
                  % (best.total, ", ".join(p.name for _s, p in best.slots if p)))
            print("\nPLAN")
            print(describe_plan(swaps))

            if not swaps:
                return 0
            if not args.confirm:
                print("\n  DRY RUN - nothing was changed. Re-run with "
                      "--confirm to apply.")
                return 0
            if not _sys.stdin.isatty():
                print("\n  REFUSING to apply: --confirm was given but this is "
                      "not an interactive terminal. CBS applies each move as "
                      "it happens with no undo, so an unattended run that "
                      "half-completes leaves a real mixed lineup. Run it by "
                      "hand.")
                return 1

            print("\n  APPLYING - each swap is verified before the next.")
            def step(i, swap):
                print("    step %d: bench %s, start %s"
                      % (i, swap.bench_name, swap.promote_name))
            applied = apply_swaps(page, swaps, target_ids, on_step=step)
            print("  DONE - %d of %d swaps applied and verified."
                  % (applied, len(swaps)))
            return 0
        except LineupWriteError as exc:
            print("LINEUP WRITE FAILED: %s" % exc)
            return 1
        finally:
            ctx.close()


def _cmd_claim(args):
    """File one waiver claim: add a free agent, drop a rostered player.

    DRY RUN BY DEFAULT, and even with --confirm the claim JOINS THE WAIVER
    QUEUE rather than executing immediately, unless --now is also given. A
    queued offer sits in PENDING ADD/DROPS for days and can be cancelled on
    CBS; an immediate execution drops a real player the moment it is sent,
    and a drop is the one action in this project that can actually cost
    something.
    """
    import sys as _sys

    from sffl.cbs_claim import (ClaimError, droppable_ids, pending_claims,
                                select_drop, stage_add, submit_claim)

    if not args.add or not args.drop:
        print("both --add and --drop are required: a claim on a full roster "
              "is an add AND a drop, and CBS will not take one without the "
              "other")
        return 1

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            args.profile_dir, headless=not args.show, timeout=45000)
        try:
            page = ctx.new_page()
            stage_add(page, args.pos, args.add)
            offered = droppable_ids(page)
            if args.drop not in offered:
                print("REFUSING: CBS does not list player id %s as droppable "
                      "on this claim. Nothing was submitted." % args.drop)
                print("  it offered: %s" % (", ".join(offered) or "none"))
                return 1
            select_drop(page, args.drop)

            print("CLAIM")
            print("  ADD   %s (%s, id %s)" % (args.add_name or "?", args.pos,
                                              args.add))
            print("  DROP  %s (id %s)" % (args.drop_name or "?", args.drop))
            print("  mode  %s" % ("EXECUTE IMMEDIATELY" if args.now
                                  else "pending waiver offer (cancellable)"))
            for line in page.inner_text("body").split("\n"):
                t = line.strip()
                if ("waiver offers remaining" in t
                        or "will be processed on" in t):
                    print("  CBS says: %s" % t[:96])

            if not args.confirm:
                print("\n  DRY RUN - staged in the browser only, nothing was "
                      "sent. Re-run with --confirm to file it.")
                return 0
            if not _sys.stdin.isatty():
                print("\n  REFUSING to file: --confirm was given but this is "
                      "not an interactive terminal. A claim drops a real "
                      "player; it is not something a scheduled job should do "
                      "unattended.")
                return 1

            submit_claim(page, queue_as_waiver=not args.now,
                         move_to_top=args.move_to_top)
            # Verify against CBS's own pending list rather than reporting
            # success for having clicked a button.
            after = pending_claims(page)
            filed = args.add in after or (args.add_name or "\0") in after
            print("\n  SUBMITTED. CBS's transactions page %s this claim."
                  % ("now lists" if filed else "does NOT yet list"))
            if not filed:
                print("  Check CBS directly before assuming it was filed.")
                return 1
            return 0
        except ClaimError as exc:
            print("CLAIM FAILED: %s" % exc)
            return 1
        finally:
            ctx.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sffl")
    sub = ap.add_subparsers(dest="cmd")

    ing = sub.add_parser("ingest", help="read a vendor extract into a scored pool")
    ing.add_argument("--source", required=True)
    ing.add_argument("--file", required=True)
    ing.add_argument("--year", type=int, required=True)
    ing.add_argument("--set", default=None, help="analyst set, for multi-set sources")
    ing.add_argument("--league", default=DEFAULT_LEAGUE)
    ing.add_argument("--out", default=None)
    ing.set_defaults(func=cmd_ingest)

    val = sub.add_parser("value", help="assign auction dollar values")
    val.add_argument("--source", required=True)
    val.add_argument("--file", required=True)
    val.add_argument("--year", type=int, required=True)
    val.add_argument("--set", default=None)
    val.add_argument("--league", default=DEFAULT_LEAGUE)
    val.add_argument("--curves", default=None,
                      help="calibration curves YAML from `sffl.calibrate`")
    val.add_argument("--policy", default="starter",
                      choices=["starter", "draftable", "fit"])
    val.add_argument("--prices", default=None,
                      help="observed auction prices CSV; required with --policy fit")
    val.add_argument("--market", default=None,
                      help="apply a persisted market model (see fit-market); "
                           "mutually exclusive with --prices")
    val.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                      help="year-bound map of starting QB name -> franchise code, "
                           "used to join --prices' Team QB rows to the pool "
                           "(default: the 2025 map; a new season needs its own file)")
    val.add_argument("--out", default=None)
    val.set_defaults(func=cmd_value)

    ren = sub.add_parser("render", help="value the pool and write the PDF/Excel cheatsheets")
    ren.add_argument("--source", required=True)
    ren.add_argument("--file", required=True)
    ren.add_argument("--year", type=int, required=True)
    ren.add_argument("--set", default=None)
    ren.add_argument("--league", default=DEFAULT_LEAGUE)
    ren.add_argument("--curves", default=None,
                      help="calibration curves YAML from `sffl.calibrate`")
    ren.add_argument("--policy", default="starter",
                      choices=["starter", "draftable", "fit"])
    ren.add_argument("--prices", default=None,
                      help="observed auction prices CSV; required with --policy fit")
    ren.add_argument("--market", default=None,
                      help="apply a persisted market model (see fit-market); "
                           "mutually exclusive with --prices")
    ren.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                      help="year-bound map of starting QB name -> franchise code, "
                           "used to join --prices' Team QB rows to the pool "
                           "(default: the 2025 map; a new season needs its own file)")
    ren.add_argument("--byes", default=DEFAULT_BYES,
                      help="team code -> bye week YAML (default: %s)" % DEFAULT_BYES)
    ren.add_argument("--bids", default=DEFAULT_BIDS,
                      help="silent-auction bid history CSV driving the "
                           "management page's tradeoff table (default: %s)"
                           % DEFAULT_BIDS)
    ren.add_argument("--pdf", default=None, help="path to write the iPad board PDF")
    ren.add_argument("--xlsx", default=None, help="path to write the printed workbook")
    ren.set_defaults(func=cmd_render)

    pln = sub.add_parser("plan", help="print the silent-auction tradeoff table")
    pln.add_argument("--source", required=True)
    pln.add_argument("--file", required=True)
    pln.add_argument("--year", type=int, required=True)
    pln.add_argument("--set", default=None)
    pln.add_argument("--league", default=DEFAULT_LEAGUE)
    pln.add_argument("--curves", default=None,
                      help="calibration curves YAML from `sffl.calibrate`")
    pln.add_argument("--policy", default="starter",
                      choices=["starter", "draftable", "fit"])
    pln.add_argument("--prices", default=None,
                      help="observed auction prices CSV; required with --policy fit")
    # `plan` is a PRE-AUCTION command, and pre-auction is exactly when a
    # persisted model is the only option there is: --prices for the season
    # being planned does not exist until the auction it was meant to inform
    # has happened. _value_pool already handles it identically for all three
    # commands; only the flag was missing.
    pln.add_argument("--market", default=None,
                      help="apply a persisted market model (see fit-market); "
                           "mutually exclusive with --prices")
    pln.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                      help="year-bound map of starting QB name -> franchise code, "
                           "used to join --prices' Team QB rows to the pool "
                           "(default: the 2025 map; a new season needs its own file)")
    pln.add_argument("--byes", default=DEFAULT_BYES,
                      help="team code -> bye week YAML (default: %s)" % DEFAULT_BYES)
    pln.add_argument("--bids", default=DEFAULT_BIDS,
                      help="silent-auction bid history CSV (default: %s)" % DEFAULT_BIDS)
    pln.set_defaults(func=cmd_plan)

    fm = sub.add_parser("fit-market",
                        help="fit this room's price curve from year-matched "
                             "prices and persist it for future seasons")
    fm.add_argument("--source", required=True)
    fm.add_argument("--file", required=True)
    fm.add_argument("--year", type=int, required=True)
    fm.add_argument("--set", default=None)
    fm.add_argument("--league", default=DEFAULT_LEAGUE)
    fm.add_argument("--curves", default=None)
    fm.add_argument("--prices", required=True,
                    help="observed auction prices FROM THE SAME SEASON as --year")
    fm.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                    help="Team QB starter map for --year")
    fm.add_argument("--out", required=True,
                    help="where to write the model, e.g. market/2026.yaml")
    fm.add_argument("--force", action="store_true",
                    help="overwrite an existing model")
    fm.set_defaults(func=cmd_fit_market)

    wk = sub.add_parser("week", help="weekly waiver and start/sit decisions")
    wk.add_argument("--projections", required=True,
                    help="saved CBS weekly projections page text")
    wk.add_argument("--group", default="RB-WR-TE",
                    help="the group --projections was saved from (default: "
                         "RB-WR-TE, this command's original single-page "
                         "interface). Unrelated to --projections-tqb/-k/"
                         "-dst below, which are each always parsed under "
                         "their own fixed group name")
    wk.add_argument("--projections-tqb", default=None,
                    help="OPTIONAL: a saved CBS weekly TQB page, merged "
                         "with --projections into one pool. Omit it (and "
                         "-k/-dst) and this command behaves exactly as "
                         "before this flag existed - RB-WR-TE (or "
                         "whatever --group names) only")
    wk.add_argument("--projections-k", default=None,
                    help="OPTIONAL: a saved CBS weekly K page - see "
                         "--projections-tqb")
    wk.add_argument("--projections-dst", default=None,
                    help="OPTIONAL: a saved CBS weekly DST page - see "
                         "--projections-tqb. KNOWN LIMITATION: CBS's TQB "
                         "and DST pages both list every NFL team's "
                         "nickname as a row's own name (e.g. 'Chargers' "
                         "is a real row on both), and this command's "
                         "plain one-name-per-line --roster file has no "
                         "position column to disambiguate which one an "
                         "owned team name refers to when BOTH -tqb and "
                         "-dst are given. This is reported (a WARNING "
                         "names both positions), never silent, but is not "
                         "fully resolved - sffl alert does not have this "
                         "limitation, since it reads position off the "
                         "captured roster page instead")
    wk.add_argument("--week", type=int, required=True)
    wk.add_argument("--roster", required=True,
                    help="one owned player name per line")
    wk.add_argument("--league", default=DEFAULT_LEAGUE)
    wk.add_argument("--curves", default=None,
                    help="calibration curves YAML; without it the naive band "
                         "is used and the main edge over CBS is lost")
    wk.add_argument("--waivers", action="store_true")
    wk.add_argument("--start-sit", action="store_true")
    wk.add_argument("--current", default=None,
                    help="the lineup currently set on CBS, one name per line; "
                         "without it the optimum is printed with no diff")
    wk.add_argument("--top", type=int, default=10)
    wk.set_defaults(func=_cmd_week)

    tr = sub.add_parser("trade", help="rest-of-season trade valuation "
                                      "(read-only; never contacts a manager)")
    tr.add_argument("--projections", required=True,
                    help="saved CBS REST-OF-SEASON projections page "
                         "(restofseason:p), not a weekly one")
    tr.add_argument("--group", default="RB-WR-TE-ROS",
                    help="profile group for --projections. Defaults to the "
                         "REST-OF-SEASON variant; the weekly map would "
                         "misread these pages by one column")
    tr.add_argument("--projections-tqb", default=None)
    tr.add_argument("--projections-k", default=None)
    tr.add_argument("--projections-dst", default=None)
    tr.add_argument("--roster", required=True,
                    help="one owned player name per line")
    tr.add_argument("--week", type=int, required=True,
                    help="the week the rest of the season starts FROM - "
                         "decides how many games each player has left")
    tr.add_argument("--give", default=None,
                    help="comma-separated players YOU would send")
    tr.add_argument("--get", default=None,
                    help="comma-separated players you would RECEIVE")
    tr.add_argument("--league", default=DEFAULT_LEAGUE)
    tr.add_argument("--curves", default=None)
    tr.add_argument("--top", type=int, default=10)
    tr.set_defaults(func=_cmd_trade)

    ln = sub.add_parser("lineup", help="set the CBS starting lineup to the "
                                       "weekly optimum (DRY RUN unless "
                                       "--confirm)")
    ln.add_argument("--projections", required=True)
    ln.add_argument("--group", default="RB-WR-TE")
    ln.add_argument("--projections-tqb", default=None)
    ln.add_argument("--projections-k", default=None)
    ln.add_argument("--projections-dst", default=None)
    ln.add_argument("--week", type=int, required=True)
    ln.add_argument("--league", default=DEFAULT_LEAGUE)
    ln.add_argument("--curves", default=None)
    ln.add_argument("--profile-dir", default="data/browser-profile")
    ln.add_argument("--show", action="store_true",
                    help="run the browser visibly")
    ln.add_argument("--confirm", action="store_true",
                    help="actually apply the swaps. Without this nothing is "
                         "changed. Refused when stdin is not a TTY, so a "
                         "scheduled job can never submit")
    ln.set_defaults(func=_cmd_lineup)

    cl = sub.add_parser("claim", help="file a waiver claim: add one free "
                                      "agent, drop one rostered player "
                                      "(DRY RUN unless --confirm)")
    cl.add_argument("--add", required=True, help="CBS player id to ADD")
    cl.add_argument("--pos", required=True,
                    help="that player's position, as CBS spells it in the "
                         "add link (TQB/RB/WR/TE/K/DST)")
    cl.add_argument("--drop", required=True, help="CBS player id to DROP")
    cl.add_argument("--add-name", default=None, help="label, for the printout")
    cl.add_argument("--drop-name", default=None, help="label, for the printout")
    cl.add_argument("--profile-dir", default="data/browser-profile")
    cl.add_argument("--show", action="store_true")
    cl.add_argument("--move-to-top", action="store_true",
                    help="put this ahead of your other pending offers")
    cl.add_argument("--now", action="store_true",
                    help="EXECUTE IMMEDIATELY instead of queueing as a "
                         "cancellable waiver offer. This drops the player at "
                         "once and cannot be undone")
    cl.add_argument("--confirm", action="store_true",
                    help="actually file it. Without this nothing is sent. "
                         "Refused when stdin is not a TTY")
    cl.set_defaults(func=_cmd_claim)

    alr = sub.add_parser("alert", help="capture, score, and push the weekly digest")
    alr.add_argument("--kind", choices=["friday", "sunday"], required=True)
    alr.add_argument("--league", default=DEFAULT_LEAGUE)
    alr.add_argument("--week", type=int, required=True)
    alr.add_argument("--curves")
    alr.add_argument("--injuries", help="JSON written by ops/fetch_injuries.sh")
    alr.add_argument("--team-url", default=DEFAULT_TEAM_URL,
                     help="CBS roster page (default: bare /teams, which CBS "
                          "resolves to whoever is logged in - do not point "
                          "this at a numbered /teams/<N>, that is a "
                          "DIFFERENT manager's team)")
    alr.add_argument("--projections-url",
                     help="override the RB-WR-TE weekly projections URL "
                          "only; the TQB/K/DST pages have no override and "
                          "are always built from --week. By default all "
                          "four are built from --week against CBS's "
                          "stats-main page, so a new week never needs a "
                          "hand-edited URL")
    alr.add_argument("--out-dir", default="data/captures")
    alr.add_argument("--profile-dir", default="data/browser-profile")
    alr.add_argument("--dry-run", action="store_true")
    alr.add_argument("--no-trade", action="store_true",
                     help="skip the Friday digest's trade block, and the "
                          "four rest-of-season page captures it needs")
    alr.set_defaults(func=_cmd_alert)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1

    try:
        return args.func(args)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
