"""Validate rushing and receiving bands against real CBS weekly output.

Source: Saquon Barkley 2025 game log from the live SFFL league site.
Columns include longest-gain (LG), which bounds how large a TD distance bonus
could have been: a rushing TD cannot be longer than the longest rush.

Bonus tiers under league rules:
  rushing TD    3 base, +2 at 3-35 yds, +5 at 36+
  receiving TD  5 base, +1 at 36-74 yds, +3 at 75+
So a rushing TD is worth 3, 5, or 8; a receiving TD 5, 6, or 8.
"""

import os
import sys
from itertools import product

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.league import load_league          # noqa: E402
from sffl.scoring import band_points         # noqa: E402

LG_PROFILE = load_league(os.path.join(os.path.dirname(__file__), "..",
                                      "leagues", "sffl", "2026.yaml"))
B = LG_PROFILE.bands

# wk, ratt, ryds, rlg, rtd, rec, recyds, reclg, rectd, fumlost, cbs
GAMES = [
    (1,  18,  60, 16, 1, 4,  24,  8, 0, 0,  7),
    (2,  22,  88, 13, 1, 2,   6,  6, 0, 0,  8),
    (3,  18,  46, 12, 0, 4,   9,  5, 0, 0,  0),
    (4,  19,  43, 10, 1, 4,  31, 15, 0, 0,  5),
    (5,   6,  30, 17, 0, 3,  58, 47, 1, 0,  7),
    (6,  12,  58, 18, 0, 2,   9, 10, 0, 0,  2),
    (7,  18,  44,  9, 0, 1,  -2, -2, 0, 0,  0),
    (8,  14, 150, 65, 1, 4,  24, 12, 1, 0, 19),
    (10, 22,  60, 15, 0, 3,  41, 41, 0, 0,  2),
    (11, 26,  83, 14, 0, 1,   7,  7, 0, 0,  3),
    (12, 10,  22,  7, 0, 7,  52, 16, 0, 1,  4),
    (13, 13,  56, 15, 0, 0,   0,  0, 0, 0,  2),
    (14, 20, 122, 52, 1, 0,   0,  0, 0, 0, 12),
    (15, 22,  78, 17, 1, 2,  14,  8, 0, 0,  6),
    (16, 21, 132, 48, 1, 0,   0,  0, 0, 0, 12),
    (17, 19,  68, 16, 0, 0,   0,  0, 0, 0,  2),
    (19, 26, 106, 29, 0, 3,  25, 20, 0, 0,  4),
]

RUSH_TD_VALUES = {"short(1-2)": 3, "mid(3-35)": 5, "long(36+)": 8}
REC_TD_VALUES = {"short(<36)": 5, "mid(36-74)": 6, "long(75+)": 8}


def base(g):
    """Yardage and reception points only - no touchdowns at all."""
    _, _, ryds, _, _, rec, recyds, _, _, _, _ = g
    return (band_points(B["rush_yds"], ryds)
            + band_points(B["rec_yds"], recyds)
            + band_points(B["rec_ct"], rec))


def explain(g):
    """Find every TD-distance combination consistent with CBS's total."""
    wk, _, ryds, rlg, rtd, rec, recyds, reclg, rectd, _, cbs = g
    need = cbs - base(g)
    rush_opts = [(k, v) for k, v in RUSH_TD_VALUES.items()
                 if not (k == "long(36+)" and rlg < 36)]
    rec_opts = [(k, v) for k, v in REC_TD_VALUES.items()
                if not (k == "mid(36-74)" and reclg < 36)
                and not (k == "long(75+)" and reclg < 75)]
    fits = []
    for rc in product(rush_opts, repeat=rtd):
        for cc in product(rec_opts, repeat=rectd):
            total = sum(v for _, v in rc) + sum(v for _, v in cc)
            if total == need:
                fits.append([k for k, _ in rc] + [k for k, _ in cc])
    return need, fits


def main():
    print(f"{'wk':>3} {'ryd':>4} {'rlg':>4} {'rTD':>3} {'rec':>3} {'reyd':>5} "
          f"{'relg':>5} {'reTD':>4} | {'CBS':>4} {'base':>5} {'TDpts':>6}  verdict")
    print("-" * 92)
    bad = []
    for g in GAMES:
        wk, _, ryds, rlg, rtd, rec, recyds, reclg, rectd, _, cbs = g
        need, fits = explain(g)
        if rtd == 0 and rectd == 0:
            verdict = "EXACT (no TDs)" if need == 0 else "*** MISMATCH ***"
            if need != 0:
                bad.append((wk, need))
        elif fits:
            verdict = "consistent: " + " + ".join(fits[0])
        else:
            verdict = "*** NO TD COMBINATION FITS ***"
            bad.append((wk, need))
        print(f"{wk:>3} {ryds:>4} {rlg:>4} {rtd:>3} {rec:>3} {recyds:>5} "
              f"{reclg:>5} {rectd:>4} | {cbs:>4} {base(g):>5} {need:>6}  {verdict}")

    no_td = [g for g in GAMES if g[4] == 0 and g[8] == 0]
    ok = sum(1 for g in no_td if explain(g)[0] == 0)
    print(f"\n  weeks with NO touchdowns (unambiguous): {ok}/{len(no_td)} exact")
    print(f"  weeks needing a TD-bonus explanation that has one: "
          f"{len(GAMES) - len(no_td) - len([b for b in bad if b[0] not in [g[0] for g in no_td]])}"
          f"/{len(GAMES) - len(no_td)}")
    if bad:
        print(f"\n  *** UNEXPLAINED WEEKS: {bad} ***")
    else:
        print("\n  NO UNEXPLAINED WEEKS.")

    hit = sorted({band_points(B["rush_yds"], g[2]) for g in GAMES if g[2] >= 50})
    print(f"\n  rush_yds band values exercised: {hit}")
    hitr = sorted({band_points(B["rec_yds"], g[6]) for g in GAMES if g[6] >= 50})
    hitc = sorted({band_points(B["rec_ct"], g[5]) for g in GAMES if g[5] >= 5})
    print(f"  rec_yds band values exercised : {hitr}")
    print(f"  rec_ct  band values exercised : {hitc}")


if __name__ == "__main__":
    main()
