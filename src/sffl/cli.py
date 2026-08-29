"""Command line entry point.

    python -m sffl.cli ingest --source sources/draftsharks.yaml \
        --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
"""

import argparse
import csv
import os
import sys

from sffl.calibrate import load_curves
from sffl.fit import (DEFAULT_TQB_STARTERS, choose_policy, load_prices,
                      tqb_starters_season)
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
# PROJECTIONS: week-parameterised. Built from --week rather than accepting a
# hardcoded URL, so a new week never requires editing a URL by hand (and can
# never silently run against last week's page because someone forgot to).
CBS_LEAGUE_BASE = "https://stripesfantasyfootballleague.football.cbssports.com"
DEFAULT_TEAM_URL = CBS_LEAGUE_BASE + "/teams"
PROJECTIONS_URL_TEMPLATE = (
    CBS_LEAGUE_BASE + "/stats/stats-main/all:RB:WR:TE/%d:p/standard/projections")


def _value_pool(lg, args):
    """Build a pool and run it through the full valuation path: vendor
    extract -> calibration curves -> replacement policy -> VORP/dollars ->
    (if prices are supplied) the market price curve.

    Shared by cmd_value and cmd_render so the two commands can never price
    the same player differently - duplicating this path would let a fix or a
    calibration change land in one command's copy and not the other's.

    Returns (pool, curve, prices) on success. Returns None after printing why
    on the one recoverable failure (`--policy fit` without `--prices`) - the
    caller should print nothing further and return 1.
    """
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    if args.curves:
        curves = load_curves(args.curves)
        for p in pool:
            p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
        pool.sort(key=lambda p: -p.stats["_season_points"])

    # Loaded whenever --prices is supplied, under any policy: --policy fit
    # needs it to choose a replacement level, and every policy needs it to
    # fit the market curve (_est_price) below. Without it there is nothing
    # to fit against, so `prices` stays None and _est_price is never written.
    prices = None
    if args.prices:
        # THE GUARD THAT THE 2026 REFIT PAID FOR. Fitting one season's prices
        # against another season's projections is what manufactured a phantom
        # $13.2 top-end bias, an EST$ curve tuned to remove it, and a deferred
        # code change waiting on evidence that never existed. It is invisible
        # in the output - every number looks reasonable. So it is refused here.
        _map_season = tqb_starters_season(args.tqb_starters)
        if _map_season is not None and _map_season != args.year:
            raise SystemExit(
                "refusing to value %d projections against the %d Team QB "
                "starter map (%s).\n"
                "Quarterbacks change franchises between seasons, so the wrong "
                "map silently mis-joins or drops every Team QB price - and "
                "pairing one season's prices with another's projections is "
                "what produced this project's largest measurement error.\n"
                "Pass --tqb-starters for %d, and a --prices file from %d."
                % (args.year, _map_season, args.tqb_starters,
                   args.year, args.year))
        prices = load_prices(args.prices, tqb_starters_path=args.tqb_starters)

    policy = args.policy
    if policy == "fit":
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
    if prices is not None:
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

    return pool, curve, prices


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
    pool, curve, prices = result

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

    if curve is not None:
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

    return 0


def cmd_render(args):
    if not args.pdf and not args.xlsx:
        print("error: render needs at least one of --pdf or --xlsx to write")
        return 1

    lg = load_league(args.league)
    result = _value_pool(lg, args)
    if result is None:
        return 1
    pool, curve, prices = result

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
        facts = gather_intel(lg, rows, pool=pool, prices=prices, curve=curve)
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
    pool, _curve, _prices = result

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


def _cmd_week(args):
    from sffl.cbs_weekly import DEFAULT_PROFILE, _load_owner_codes
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import normalize_name
    from sffl.lineup import Candidate, best_lineup, delta
    from sffl.pool import score_week

    owner_codes = _load_owner_codes(DEFAULT_PROFILE)

    lg = load_league(args.league)
    curves = load_curves(args.curves) if args.curves else None
    projections = parse_weekly(args.projections, group=args.group,
                               week=args.week, season=lg.season)

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
            "result" % args.projections)

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
    by_key = {}
    for p in projections:
        key = normalize_name(p.name)
        if key in by_key and by_key[key].name != p.name:
            print("  WARNING: %r and %r both normalize to the same key - "
                  "only %r is kept (last one wins); the other's projection "
                  "is silently dropped from the pool"
                  % (by_key[key].name, p.name, p.name))
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
            "%s against the names in %s." % (len(owned_raw), args.roster,
                                              args.roster, args.projections))

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
    # `classify` picks cbs_weekly's tab-path or space-path classifier for
    # THIS file - see `_avail_classifier`. Wiring the space-path
    # `classify_avail` unconditionally here (this command's only option
    # before `classify_avail_tab` existed) is exactly the bug a real
    # Playwright-captured `--projections` file hits: a tab-path owner cell
    # like "Sgt Hu..." matches no configured `owner_codes` and is not
    # "FA"/"W", so it comes back unclassified for every single owned row on
    # that page - a noisy warning naming a dozen team names, and a waiver
    # board that has silently stopped telling owned players from free
    # agents on the format this pipeline now actually captures.
    classify = _avail_classifier(args.projections, owner_codes)
    free_rows = [p for k, p in by_key.items() if k not in owned]
    available_rows = []
    excluded_owned = 0
    excluded_out_free = []
    unclassified_avail = set()
    for p in free_rows:
        status = classify(p.avail)
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
    print("  %d rows parsed from %s" % (len(projections), args.projections))
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
        print("\n  WAIVER TARGETS (top %d of %d)   %-8s %-6s %s"
              % (len(shown), len(ranked), "+PTS", "SLOT", "PLAYER"))
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
            print("    %-8.2f %-6s %s (%s)" % (d, where, c.name, c.pos))

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
            # on CBS, but sources/cbs-weekly.yaml only defines the RB-WR-TE
            # group - a TQB, K or DST name has no projection and was never
            # in by_key at all. Excluded from SIT here, same as `missing`
            # excludes it from the roster above; named so the exclusion is
            # visible rather than reading as "bench your kicker."
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
                            STALE_INJURIES_MINUTES, compose)
    from sffl.calibrate import load_curves
    from sffl.capture import CaptureError, capture
    from sffl.cbs_roster import parse_lineup, parse_positions
    from sffl.cbs_weekly import is_out
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import normalize_name
    from sffl.injuries import for_roster, load as load_injuries
    from sffl.league import load_league
    from sffl.lineup import Candidate, best_lineup
    from sffl.notify import send, topic_from_keychain
    from sffl.pool import score_week

    lg = load_league(args.league)
    projections_url = args.projections_url or (PROJECTIONS_URL_TEMPLATE % args.week)
    urls = {
        "roster": args.team_url,
        "projections": projections_url,
    }

    capture_error = None
    roster_names = []
    starters = []
    # None means "capture never got far enough to know" - distinct from a
    # successful parse that legitimately found nobody starting. `compose`
    # renders those two states differently (see its docstring), so this
    # must not default to `[]`.
    current_starters = None
    # Current starters that were never scored. `None` for the same reason
    # `current_starters` is: until the projections parse, nobody knows.
    unevaluated_starters = None
    reports = []
    sidelined = []
    result = None
    age_days = 0

    try:
        written = capture(urls, args.out_dir, args.profile_dir)
        roster_path = written[urls["roster"]]
        proj_path = written[urls["projections"]]
        # parse_lineup, not parse_roster: the page also carries Jeff's
        # CURRENT starting lineup, which is the actual start/sit value -
        # compose() renders it against the optimum below. `starters` and
        # `reserves` together are the same player set `parse_roster` would
        # return.
        starters, reserves = parse_lineup(roster_path)
        current_starters = starters
        roster_names = starters + [n for n in reserves if n not in starters]
        age_days = int(
            (datetime.datetime.now()
             - datetime.datetime.fromtimestamp(os.path.getmtime(roster_path)))
            .total_seconds() // 86400)

        projections = parse_weekly(proj_path, group=args.group,
                                   week=args.week, season=lg.season)
        curves = load_curves(args.curves) if args.curves else None
        by_key = dict((normalize_name(p.name), p) for p in projections)
        owned = [normalize_name(n) for n in roster_names]

        # C1. Which of CBS's eight starters could not be scored at all, and
        # WHY. `--group` is RB-WR-TE, so the TQB, the kicker and the defense
        # have no projection and are not in `by_key`; the START/SIT diff in
        # `compose` is a set difference, so before this they landed in the
        # SIT column every single week, dressed as merit-based bench advice.
        #
        # The covered positions are read off the parsed page itself rather
        # than from the `--group` string: the group name is a label in
        # sources/cbs-weekly.yaml, while what the page actually contains is
        # the fact that decides whether a missing projection is expected.
        # A starter whose position IS on the page and who still has no row
        # is a different animal - a data problem, not a scope limit - and
        # the two must not be reported as one thing.
        covered_positions = set(p.pos for p in projections)
        starter_positions = parse_positions(roster_path)
        unevaluated_starters = []
        for name in starters:
            if normalize_name(name) in by_key:
                continue
            pos = starter_positions.get(name, "")
            why = (PROJECTION_MISSING if pos and pos in covered_positions
                   else POSITION_NOT_CAPTURED)
            unevaluated_starters.append((name, pos, why))

        sidelined = sorted((by_key[k].name, by_key[k].status)
                           for k in owned
                           if k in by_key and is_out(by_key[k].status))
        result = best_lineup(lg, [
            Candidate(name=by_key[k].name, pos=by_key[k].pos,
                      points=score_week(lg, by_key[k], curves))
            for k in owned if k in by_key and not is_out(by_key[k].status)])
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
        except (ValueError, OSError) as exc:
            # A file that exists but cannot be read or parsed is the same
            # class of failure as no file at all, and must not be allowed to
            # take the whole alert down as a traceback: the lineup half of
            # this digest is still worth pushing. ValueError covers both
            # json's decode error and injuries.load's own raise on a row
            # with no player name.
            reports = []
            injury_error = "%s could not be read: %s" % (args.injuries, exc)
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
                   injuries_age_minutes=injuries_age_minutes)
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

    # A capture failure, a DEGRADED run (the injury fetch produced nothing,
    # or produced something that is not from this run), or a delivery
    # failure is each visible in a way launchd's log must be able to see, so
    # each makes the exit code non-zero - but they are DIFFERENT failures
    # (nothing produced, vs. an alert missing half its content, vs. a
    # correct alert that could not be pushed), and the printed body above,
    # not the exit code, is what tells them apart. A missing --injuries
    # argument is NOT counted here: that is a deliberate invocation, not a
    # failed step, and it is still stated in the body.
    return 1 if (capture_error or injury_fetch_failed or delivery_error) else 0


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
    pln.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                      help="year-bound map of starting QB name -> franchise code, "
                           "used to join --prices' Team QB rows to the pool "
                           "(default: the 2025 map; a new season needs its own file)")
    pln.add_argument("--byes", default=DEFAULT_BYES,
                      help="team code -> bye week YAML (default: %s)" % DEFAULT_BYES)
    pln.add_argument("--bids", default=DEFAULT_BIDS,
                      help="silent-auction bid history CSV (default: %s)" % DEFAULT_BIDS)
    pln.set_defaults(func=cmd_plan)

    wk = sub.add_parser("week", help="weekly waiver and start/sit decisions")
    wk.add_argument("--projections", required=True,
                    help="saved CBS weekly projections page text")
    wk.add_argument("--group", default="RB-WR-TE")
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

    alr = sub.add_parser("alert", help="capture, score, and push the weekly digest")
    alr.add_argument("--kind", choices=["friday", "sunday"], required=True)
    alr.add_argument("--league", default=DEFAULT_LEAGUE)
    alr.add_argument("--week", type=int, required=True)
    alr.add_argument("--group", default="RB-WR-TE")
    alr.add_argument("--curves")
    alr.add_argument("--injuries", help="JSON written by ops/fetch_injuries.sh")
    alr.add_argument("--team-url", default=DEFAULT_TEAM_URL,
                     help="CBS roster page (default: bare /teams, which CBS "
                          "resolves to whoever is logged in - do not point "
                          "this at a numbered /teams/<N>, that is a "
                          "DIFFERENT manager's team)")
    alr.add_argument("--projections-url",
                     help="override the weekly projections URL; by default "
                          "built from --week against CBS's stats-main page, "
                          "so a new week never needs a hand-edited URL")
    alr.add_argument("--out-dir", default="data/captures")
    alr.add_argument("--profile-dir", default="data/browser-profile")
    alr.add_argument("--dry-run", action="store_true")
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
