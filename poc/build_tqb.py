"""Build TQB projections from Draft Sharks per-stat QB projections.

Proves the pipeline end to end on the hardest position: take raw stat lines,
apply SFFL banded scoring ourselves, aggregate quarterbacks by franchise into
Team QB units. No vendor needs to support the TQB slot for this to work.

Input: rankingsQB.csv exported from draftsharks.com (Projections view).
"""

import csv
import sys
from collections import defaultdict

# positional indices - the export reuses header names across stat groups
I_TEAM, I_PLAYER, I_GAMES = 1, 2, 4
I_PA_ATT, I_PA_CMP, I_PA_YD, I_PA_TD, I_PA_INT = 7, 8, 9, 10, 11
I_RU_YD, I_RU_TD = 13, 14

PA_YD = [(150, 250, 2), (251, 350, 4), (351, 450, 5), (451, 9999, 7)]
PA_CMP = [(15, 19, 2), (20, 24, 3), (25, 29, 4), (30, 34, 5), (35, 39, 6), (40, 99, 7)]
RU_YD = [(50, 74, 2), (75, 99, 3), (100, 124, 4), (125, 149, 5), (150, 174, 6),
         (175, 199, 7), (200, 224, 8), (225, 249, 9), (250, 9999, 10)]


def band(t, v):
    for lo, hi, p in t:
        if lo <= v <= hi:
            return p
    return 0


def f(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return 0.0


def per_game_points(r):
    """SFFL points per game from a season stat line.

    Bands apply to each week's line, so we average to a per-game line and band
    that. This is the documented approximation: averaging collapses the variance
    the bands reward, and it bites hardest at the hard floors.
    """
    g = f(r[I_GAMES]) or 1
    pa_yd, pa_cmp = f(r[I_PA_YD]) / g, f(r[I_PA_CMP]) / g
    pa_td, pa_int = f(r[I_PA_TD]) / g, f(r[I_PA_INT]) / g
    ru_yd, ru_td = f(r[I_RU_YD]) / g, f(r[I_RU_TD]) / g
    pts = band(PA_YD, pa_yd) + band(PA_CMP, pa_cmp)
    pts += pa_td * 5 - pa_int
    pts += band(RU_YD, ru_yd)
    pts += ru_td * (3 + 2)          # most rushing TDs land in the 3-35 yd bonus
    return pts, g


def main(path):
    rows = list(csv.reader(open(path)))[1:]
    rows = [r for r in rows if len(r) > I_RU_TD and r[I_PLAYER].strip()]

    franchises = defaultdict(list)
    for r in rows:
        ppg, g = per_game_points(r)
        franchises[r[I_TEAM].strip()].append((r[I_PLAYER].strip(), ppg, g, ppg * g))

    tqb = []
    for team, qbs in franchises.items():
        tqb.append((team, sum(s for *_, s in qbs), qbs))
    tqb.sort(key=lambda t: -t[1])

    print(f"{len(rows)} QBs -> {len(tqb)} franchise TQB units\n")
    print(f"{'rk':>3} {'tm':>4} {'TQB pts':>8}   quarterbacks")
    print("-" * 78)
    for i, (team, total, qbs) in enumerate(tqb, 1):
        who = ", ".join(f"{n.split()[-1]} {s:.0f}" for n, _, _, s in
                        sorted(qbs, key=lambda q: -q[3]))
        print(f"{i:>3} {team:>4} {total:>8.1f}   {who[:56]}")

    if len(tqb) > 12:
        repl = tqb[12][1]
        print(f"\nreplacement TQB (13th of {len(tqb)}): {tqb[12][0]} {repl:.1f}")
        print(f"VORP of TQB1 ({tqb[0][0]}): {tqb[0][1] - repl:.1f}")

    print("\nNOTE on the approximation, visible in this data:")
    for r in rows[:1]:
        g = f(r[I_GAMES])
        print(f"  {r[I_PLAYER]}: {f(r[I_RU_YD]):.0f} rush yds over {g:.0f} games "
              f"= {f(r[I_RU_YD])/g:.1f}/game")
        print(f"  That is below the 50-yard floor, so averaging scores it ZERO -")
        print(f"  yet he would clear 50 in several individual weeks. Averaging")
        print(f"  understates exactly the players the bands are meant to reward.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/extracts/rankingsQB.csv")
