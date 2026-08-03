"""Validate every kicking rule against real CBS weekly output.

Source: Evan McPherson 2025 game log from the live SFFL league site. CBS breaks
field goals out by distance band with made-attempted, which maps directly onto
the league's per-distance scoring, so this one log exercises the entire
kicking surface.

CBS reports 50+ as a single column while the league scores 50-59 and 60+
differently. The LONG column disambiguates: a week whose longest make is 60+
had exactly one 60+ kick.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.league import load_league          # noqa: E402
from sffl.scoring import score_game          # noqa: E402

LG = load_league(os.path.join(os.path.dirname(__file__), "..",
                              "leagues", "sffl", "2026.yaml"))

# wk, (made,att) per band 20-29 / 30-39 / 40-49 / 50+, long, (xp_made, xp_att), cbs
GAMES = [
    (1,  (0, 0), (1, 1), (0, 0), (0, 0), 35, (2, 2),  5),
    (2,  (0, 0), (1, 1), (0, 0), (0, 0), 31, (4, 4),  7),
    (3,  (0, 0), (0, 0), (1, 1), (0, 0), 45, (1, 1),  5),
    (4,  (1, 1), (0, 0), (0, 0), (0, 0), 26, (0, 0),  2),
    (5,  (0, 0), (0, 0), (0, 0), (1, 1), 50, (3, 3),  8),
    (6,  (0, 0), (0, 0), (1, 1), (0, 2), 45, (1, 1),  5),
    (7,  (1, 1), (1, 1), (2, 2), (0, 0), 49, (3, 3), 16),
    (8,  (1, 1), (0, 0), (0, 0), (0, 0), 26, (5, 5),  7),
    (9,  (0, 0), (1, 1), (1, 1), (0, 1), 41, (4, 4), 11),
    (11, (0, 0), (0, 0), (2, 2), (0, 0), 48, (0, 0),  8),
    (12, (0, 0), (0, 0), (0, 0), (2, 2), 63, (2, 2), 15),
    (13, (1, 1), (2, 2), (2, 2), (1, 1), 52, (2, 2), 23),
    (14, (0, 0), (0, 0), (0, 0), (0, 0),  0, (4, 4),  4),
    (15, (0, 0), (0, 0), (0, 0), (0, 0),  0, (0, 0),  0),
    (16, (0, 0), (0, 0), (1, 1), (0, 0), 45, (6, 6), 10),
    (17, (0, 0), (0, 0), (0, 0), (1, 1), 57, (4, 5),  9),
    (18, (0, 0), (0, 0), (0, 0), (0, 0),  0, (0, 2),  0),
]


def engine(g):
    wk, b20, b30, b40, b50, long_, xp, cbs = g
    made50, att50 = b50
    # split the 50+ column using LONG: a 60+ long means one of the makes was 60+
    sixty = 1 if (made50 and long_ >= 60) else 0
    fifty = made50 - sixty
    # misses below 50 carry a penalty; 50+ misses do not
    missed_under_50 = ((b20[1] - b20[0]) + (b30[1] - b30[0]) + (b40[1] - b40[0]))
    return score_game(LG, dict(
        fg_u30=b20[0], fg_30_39=b30[0], fg_40_49=b40[0],
        fg_50_59=fifty, fg_60=sixty,
        fg_missed=missed_under_50,
        xp_made=xp[0],
    ), "K")


def main():
    print(f"{'wk':>3} {'20s':>5} {'30s':>5} {'40s':>5} {'50+':>5} {'long':>5} "
          f"{'xp':>5} | {'CBS':>4} {'engine':>7}  verdict")
    print("-" * 74)
    bad = []
    for g in GAMES:
        wk, b20, b30, b40, b50, long_, xp, cbs = g
        got = engine(g)
        ok = got == cbs
        if not ok:
            bad.append((wk, cbs, got))
        print(f"{wk:>3} {b20[0]}-{b20[1]:<3} {b30[0]}-{b30[1]:<3} "
              f"{b40[0]}-{b40[1]:<3} {b50[0]}-{b50[1]:<3} {long_:>5} "
              f"{xp[0]}-{xp[1]:<3} | {cbs:>4} {got:>7.0f}  "
              f"{'EXACT' if ok else '*** MISMATCH ***'}")

    print(f"\n  {len(GAMES) - len(bad)}/{len(GAMES)} weeks exact")
    print("\n  rules proven by this one log:")
    print("    FG 20-29 = 2 | 30-39 = 3 | 40-49 = 4 | 50-59 = 5 | 60+ = 8")
    print("    XP made = 1")
    print("    50+ misses carry NO penalty  (wk 6: 0-2 from 50+, still exact)")
    print("    XP misses carry NO penalty   (wk 17: 4-5 XP; wk 18: 0-2 XP)")
    print("    a 63-yarder scored 8, confirming the 60+ tier  (wk 12)")
    print("\n  NOT proven: the -1 penalty for a missed FG under 50 yards -")
    print("    McPherson missed none inside 50 all season.")
    assert not bad, f"kicking mismatches: {bad}"


if __name__ == "__main__":
    main()
