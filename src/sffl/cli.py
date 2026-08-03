"""Command line entry point.

    python -m sffl.cli ingest --source sources/draftsharks.yaml \
        --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
"""

import argparse
import csv
import sys

from sffl.league import load_league
from sffl.pool import build_pool

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
