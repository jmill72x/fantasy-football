"""Command line entry point.

    python -m sffl.cli ingest --source sources/draftsharks.yaml \
        --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
"""

import argparse
import csv
import sys

from sffl.calibrate import load_curves
from sffl.fit import DEFAULT_TQB_STARTERS, choose_policy, load_prices
from sffl.identity import normalize_name
from sffl.league import load_league
from sffl.market import assign_expected_prices, fit_price_curve
from sffl.pool import build_pool, score_season_calibrated
from sffl.value import assign_dollars, assign_vorp, replacement_levels

DEFAULT_LEAGUE = "leagues/sffl/2026.yaml"


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
        prices = load_prices(args.prices, tqb_starters_path=args.tqb_starters)

    policy = args.policy
    if policy == "fit":
        if not args.prices:
            print("error: --policy fit requires --prices with observed auction prices")
            return 1
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
    # property of this run's data, not a crash, so it is reported and _dollars
    # /_est_price stay exactly as they were - never a fabricated estimate.
    curve = None
    if prices is not None:
        priced = [(p.stats["_dollars"], prices[normalize_name(p.name)])
                  for p in pool if normalize_name(p.name) in prices]
        try:
            curve = fit_price_curve(priced)
        except ValueError as e:
            print("  market curve: not fitted (%s)\n" % e)
        else:
            assign_expected_prices(lg, pool, curve)
            print("  market curve: price = %.3f * value^%.3f  "
                  "(fitted on %d observed 2025 prices)\n"
                  % (curve[0], curve[1], len(priced)))

    print("replacement level (%s policy):" % policy)
    for name in sorted(levels):
        print("  %-5s %8.1f pts" % (name, levels[name]))
    print("  $%.4f per VORP point\n" % rate)

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
    print("top 25 by value:  MY$ = worth against replacement, EST$ = what the room will pay")
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
        print("\nbias against observed prices, by model dollar band:")
        print("  %-10s %4s %9s %9s %9s" % ("band", "n", "MY$ bias", "EST$ bias", "actual"))
        bands = [(30, 1e9, "$30+"), (20, 30, "$20-30"), (10, 20, "$10-20"),
                 (5, 10, "$5-10"), (2, 5, "$2-5"), (0, 2, "$1-2")]
        for lo, hi, label in bands:
            rows = [p for p in pool
                    if normalize_name(p.name) in prices
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
