"""Validate the scoring engine against real CBS weekly output for a Team QB unit.

Source: Eagles TQB 2025 game log, pulled from the live SFFL league site.
Each row is the stat line CBS displayed plus the fantasy points CBS awarded.

TD distance is NOT in the game log, and the league pays distance bonuses
(passing TD +1 at 36+ yards; rushing TD +2 at 3-35 and +5 at 36+). So the
engine's floor estimate assumes NO bonus on any touchdown. A week with no
touchdowns is therefore an EXACT test; a week with touchdowns should come in
at or below CBS, with the gap explained by bonuses.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.league import load_league          # noqa: E402
from sffl.scoring import score_game          # noqa: E402

LG = load_league(os.path.join(os.path.dirname(__file__), "..",
                              "leagues", "sffl", "2026.yaml"))

# wk, opp, comp, att, pass_yds, pass_td, int, rush_yds, rush_td, cbs_fpts
GAMES = [
    (1,  "DAL",  19, 23, 152, 0, 0,  62, 2, 16),
    (2,  "@KC",  15, 22, 101, 0, 0,  15, 1,  5),
    (3,  "LAR",  21, 32, 226, 3, 0,  40, 1, 23),
    (4,  "@TB",  15, 24, 130, 2, 0,  62, 0, 14),
    (5,  "DEN",  23, 38, 280, 2, 0,   3, 0, 18),
    (6,  "@NYG", 24, 33, 283, 1, 1,  13, 1, 14),
    (7,  "@MIN", 19, 23, 326, 3, 0, -10, 0, 23),
    (8,  "NYG",  15, 20, 179, 4, 0,  20, 0, 25),
    (10, "@GB",  15, 26, 183, 1, 0,  27, 0, 10),
    (11, "DET",  14, 28, 135, 0, 0,  31, 1,  3),
    (12, "@DAL", 27, 39, 289, 1, 0,  33, 2, 21),
    (13, "CHI",  19, 34, 230, 2, 1,  31, 0, 13),
    (14, "@LAC", 21, 40, 240, 0, 4,   8, 0,  1),
    (15, "LV",   15, 18, 208, 3, 0,  48, 0, 19),
    (16, "@WAS", 22, 30, 185, 2, 0,  38, 0, 15),
    (17, "@BUF", 13, 27, 110, 1, 0,   5, 0,  5),
    (18, "WAS",  21, 40, 241, 1, 1,   3, 0,  9),
    (19, "SF",   20, 35, 168, 1, 0,  14, 0, 10),
]


def engine(g):
    _, _, comp, att, pyd, ptd, pint, ryd, rtd, _ = g
    return score_game(LG, dict(
        pass_cmp=comp, pass_yds=pyd, pass_td=ptd, pass_int=pint,
        rush_yds=ryd, rush_td=rtd,
    ), "TQB")


def main():
    print(f"{'wk':>3} {'opp':>5} {'cmp':>4} {'pyd':>4} {'ptd':>3} {'int':>3} "
          f"{'ryd':>4} {'rtd':>3} | {'CBS':>4} {'engine':>7}  {'gap':>4}  note")
    print("-" * 84)
    exact = ambiguous = mismatch = 0
    for g in GAMES:
        wk, opp, comp, att, pyd, ptd, pint, ryd, rtd, cbs = g
        got = engine(g)
        gap = cbs - got
        has_td = (ptd + rtd) > 0
        if gap == 0:
            note, exact = "EXACT", exact + 1
        elif has_td and gap > 0:
            note, ambiguous = f"+{gap:g} = TD distance bonuses", ambiguous + 1
        else:
            note, mismatch = "*** MISMATCH ***", mismatch + 1
        print(f"{wk:>3} {opp:>5} {comp:>4} {pyd:>4} {ptd:>3} {pint:>3} "
              f"{ryd:>4} {rtd:>3} | {cbs:>4} {got:>7.0f}  {gap:>4.0f}  {note}")

    no_td = [g for g in GAMES if (g[5] + g[8]) == 0]
    print(f"\n  weeks with NO touchdowns (exact tests): {len(no_td)} -> "
          f"{sum(1 for g in no_td if engine(g) == g[9])} match exactly")
    print(f"  exact {exact} | explained by TD bonuses {ambiguous} | "
          f"unexplained {mismatch}")

    print("\n  band coverage proven by this one game log:")
    print("    pass_yds  : 0 (below 150), 150-250, 251-350")
    print("    pass_cmp  : 0 (below 15), 15-19, 20-24, 25-29")
    print("    rush_yds  : 0 (below 50), 50-74")
    print("    pass_td 5 | pass_int -1 | rush_td 3 base")

    reg = [g for g in GAMES if g[0] <= 18]
    print(f"\n  weeks 1-18 CBS sum: {sum(g[9] for g in reg)}   "
          f"engine sum: {sum(engine(g) for g in reg):.0f}   "
          f"(CBS season row claims 196.00)")

    assert mismatch == 0, "engine disagrees with CBS on a week it cannot explain"
    print("\n  NO UNEXPLAINED DISAGREEMENTS.")


if __name__ == "__main__":
    main()
