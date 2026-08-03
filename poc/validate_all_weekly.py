"""Consolidated validation of the SFFL scoring engine against real CBS output.

Every row below is a real 2025 weekly stat line pulled from the live league site,
paired with the fantasy points CBS awarded. TD distance is not published, so a
week containing touchdowns is checked as "is there a legal TD-distance
combination that closes the gap"; a week without touchdowns is an exact test.

  rushing TD    3 base, +2 at 3-35, +5 at 36+   -> 3, 5, or 8
  receiving TD  5 base, +1 at 36-74, +3 at 75+  -> 5, 6, or 8
  passing TD    5 base, +1 at 36+               -> 5 or 6
"""

import os
import sys
from itertools import product

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.league import load_league          # noqa: E402
from sffl.scoring import band_points         # noqa: E402

LG = load_league(os.path.join(os.path.dirname(__file__), "..",
                              "leagues", "sffl", "2026.yaml"))
B = LG.bands

RUSH_TD = {"rush<3": 3, "rush3-35": 5, "rush36+": 8}
REC_TD = {"rec<36": 5, "rec36-74": 6, "rec75+": 8}
PASS_TD = {"pass<36": 5, "pass36+": 6}

# player, wk, ryds, rlg, rtd, rec, recyds, reclg, rectd, cmp, pyds, ptd, pint, cbs
ROWS = [
    # TreVeyon Henderson RB NE - settles the 125-149 rushing band
    ("Henderson", 10, 147, 69, 2,  1,   3,  3, 0, 0, 0, 0, 0, 21),
    ("Henderson", 15, 148, 65, 2,  2,  13,  7, 0, 0, 0, 0, 0, 21),
    ("Henderson",  8,  75, 27, 0,  0,   0,  0, 0, 0, 0, 0, 0,  3),
    ("Henderson", 17,  82, 17, 0,  0,   0,  0, 0, 0, 0, 0, 0,  3),
    ("Henderson", 12,  66,  9, 0,  3,  15,  7, 0, 0, 0, 0, 0,  2),
    ("Henderson", 13,  67, 26, 0,  3,  19, 12, 0, 0, 0, 0, 0,  2),
    ("Henderson",  9,  55,  8, 0,  4,  32, 19, 0, 0, 0, 0, 0,  2),
    ("Henderson",  1,  27, 14, 0,  6,  24, 13, 0, 0, 0, 0, 0,  2),
    ("Henderson",  2,  10,  6, 0,  2,  30, 15, 0, 0, 0, 0, 0,  0),
    ("Henderson",  4,  32, 11, 1,  2,  14,  9, 0, 0, 0, 0, 0,  5),
    ("Henderson", 11,  62,  9, 2,  5,  31, 10, 1, 0, 0, 0, 0, 19),
    ("Henderson", 18,  53, 13, 2,  0,   0,  0, 0, 0, 0, 0, 0, 10),
    # Jaxon Smith-Njigba WR SEA - the receiving bands
    ("JSN",  1, 0, 0, 0,  9, 124, 40, 0, 0, 0, 0, 0,  7),
    ("JSN",  2, 0, 0, 0,  8, 103, 43, 0, 0, 0, 0, 0,  6),
    ("JSN",  9, 11, 11, 0, 8, 129, 26, 0, 0, 0, 0, 0,  7),
    ("JSN", 11, 11, 11, 0, 9, 105, 28, 0, 0, 0, 0, 0,  7),
    ("JSN", 15, 0, 0, 0,  7, 113, 39, 0, 0, 0, 0, 0,  6),
    ("JSN", 17, 0, 0, 0,  9,  72, 18, 0, 0, 0, 0, 0,  5),
    ("JSN", 18, 0, 0, 0,  6,  84, 19, 0, 0, 0, 0, 0,  4),
    ("JSN",  4, 11, 10, 0, 4,  79, 36, 0, 0, 0, 0, 0,  2),
    ("JSN", 13, 0, 0, 0,  2,  23, 17, 0, 0, 0, 0, 0,  0),
    ("JSN", 22, 0, 0, 0,  4,  27, 16, 0, 0, 0, 0, 0,  0),
    ("JSN",  6, 0, 0, 0,  8, 162, 61, 1, 0, 0, 0, 0, 14),
    ("JSN", 12, 4,  4, 0, 8, 167, 63, 2, 0, 0, 0, 0, 19),
    ("JSN", 21, 0, 0, 0, 10, 153, 42, 1, 0, 0, 0, 0, 14),
    ("JSN",  5, 0, 0, 0,  8, 132, 53, 1, 0, 0, 0, 0, 12),
    ("JSN",  3, 0, 0, 0,  5,  96, 45, 1, 0, 0, 0, 0,  9),
    ("JSN",  7, 0, 0, 0,  8, 123, 26, 1, 0, 0, 0, 0, 11),
    ("JSN", 10, 0, 0, 0,  5,  93, 43, 1, 0, 0, 0, 0, 10),
    ("JSN", 14, -1, -1, 0, 7, 92, 30, 2, 0, 0, 0, 0, 15),
    ("JSN", 16, 0, 0, 0,  8,  96, 27, 1, 0, 0, 0, 0, 10),
    ("JSN", 20, 0, 0, 0,  3,  19, 11, 1, 0, 0, 0, 0,  5),
    # Puka Nacua WR LAR - closes the top two receiving-yardage bands
    ("Nacua", 15, 8, 6, 0,  9, 181, 39, 0, 0, 0, 0, 0, 10),
    ("Nacua", 16, 0, 0, 0, 12, 225, 58, 2, 0, 0, 0, 0, 24),
    ("Nacua",  1, 1, 1, 0, 10, 130, 25, 0, 0, 0, 0, 0,  8),
    ("Nacua",  3, 6, 6, 0, 11, 112, 20, 0, 0, 0, 0, 0,  9),
    ("Nacua",  6, 0, 0, 0,  2,  28, 23, 0, 0, 0, 0, 0,  0),
    ("Nacua", 12, 0, 0, 0,  7,  97, 31, 0, 0, 0, 0, 0,  5),
    ("Nacua", 13, 0, 0, 0,  6,  72, 31, 0, 0, 0, 0, 0,  3),
    ("Nacua", 11,18,18, 0,  7,  75, 19, 0, 0, 0, 0, 0,  5),
    ("Nacua", 20, 6, 4, 0,  5,  56, 16, 0, 0, 0, 0, 0,  3),
    ("Nacua", 14, 0, 0, 0,  7, 167, 32, 2, 0, 0, 0, 0, 18),
    ("Nacua",  4, 0, 0, 0, 13, 170, 31, 1, 0, 0, 0, 0, 17),
]


def base(r):
    _, _, ryds, _, _, rec, recyds, _, _, cmp_, pyds, _, pint, _ = r
    return (band_points(B["rush_yds"], ryds) + band_points(B["rec_yds"], recyds)
            + band_points(B["rec_ct"], rec) + band_points(B["pass_yds"], pyds)
            + band_points(B["pass_cmp"], cmp_) - pint)


def check(r):
    _, _, _, rlg, rtd, _, _, reclg, rectd, _, _, ptd, _, cbs = r
    need = cbs - base(r)
    ro = [(k, v) for k, v in RUSH_TD.items() if not (k == "rush36+" and rlg < 36)]
    co = [(k, v) for k, v in REC_TD.items()
          if not (k == "rec36-74" and reclg < 36) and not (k == "rec75+" and reclg < 75)]
    po = list(PASS_TD.items())
    for a in product(ro, repeat=rtd):
        for b in product(co, repeat=rectd):
            for c in product(po, repeat=ptd):
                if sum(v for _, v in a + b + c) == need:
                    return need, [k for k, _ in a + b + c]
    return need, None


def main():
    print(f"{'player':10} {'wk':>3} | {'CBS':>4} {'base':>5} {'TD':>4}  verdict")
    print("-" * 68)
    bad, exact = [], 0
    for r in ROWS:
        need, fit = check(r)
        has_td = (r[4] + r[8] + r[11]) > 0
        if not has_td:
            v = "EXACT (no TDs)" if need == 0 else "*** MISMATCH ***"
            exact += need == 0
            if need:
                bad.append((r[0], r[1]))
        elif fit is not None:
            v = "ok: " + " + ".join(fit)
        else:
            v = "*** NO TD COMBINATION FITS ***"
            bad.append((r[0], r[1]))
        print(f"{r[0]:10} {r[1]:>3} | {r[13]:>4} {base(r):>5} {need:>4}  {v}")

    n_no_td = sum(1 for r in ROWS if (r[4] + r[8] + r[11]) == 0)
    print(f"\n  {exact}/{n_no_td} touchdown-free weeks EXACT")
    print(f"  {len(ROWS) - len(bad)}/{len(ROWS)} rows consistent overall")
    print(f"  unexplained: {bad if bad else 'NONE'}")
    assert not bad, bad


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# Band-closing cases added after targeted hunting. Each is the ONLY observation
# in 2025 that reaches its band, so each is load-bearing.
#
#   Cardinals TQB wk11  57 att / 47 comp / 452 yds / 2 TD / 2 INT   CBS 22
#       pass_cmp [40-99] = 7 and pass_yds [451+] = 7
#       base 7 + 7 - 2 = 12, + two passing TDs at 5 = 22   EXACT FIT
#
#   Kyle Monangai wk9   26 att / 176 yds / 0 TD / 3 rec / 22 yds    CBS 7
#       rush_yds [175-199] = 7
#       zero touchdowns, so unambiguous                    EXACT
#
#   Derrick Henry wk17  36 att / 216 yds / 4 TD                     CBS 26
#       rush_yds [200-224] = 8
#   Jonathan Taylor wk10 32 att / 244 yds / 3 TD                    CBS 25
#       rush_yds [225-249] = 9
#   Ja'Marr Chase wk8   12 rec / 91 yds / 0 TD                      CBS 8
#       rec_ct [11-12] = 6                                 EXACT
#   Ja'Marr Chase wk2   14 rec / 165 yds / 1 TD                     CBS 17
#       rec_ct [13+] = 7
#   Vikings DST wk18    3 pts / 121 yds / 4 sacks                   CBS 15
#       def_pa [3-5] = 5                                   EXACT
#   Vikings DST wk16    7 pts / 141 yds / 1 INT / 5 sacks           CBS 15
#       def_pa [7-9] = 3                                   EXACT
#   Vikings DST wk7     22 pts / 361 yds / 3 sacks                  CBS 3
#       def_ya [351-399] = 0                               EXACT
