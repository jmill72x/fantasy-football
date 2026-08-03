"""Validate the full DST scoring surface against real CBS weekly output.

Four 2025 defenses pulled from the live SFFL league site. Between them they
exercise every points-allowed and yards-allowed band, including the singletons
(exactly 6 points, exactly 14 points) and the 500+ yard collapse.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sffl.league import load_league          # noqa: E402
from sffl.scoring import score_game          # noqa: E402

LG = load_league(os.path.join(os.path.dirname(__file__), "..", "leagues", "sffl", "2026.yaml"))

# team, wk, pts, yds, int, fum, sack, td, cbs
GAMES = [
    # Vikings - mid bands, a shutout, and 351-399 yards
    ("MIN",  3, 10, 171, 2, 3, 4, 2, 27), ("MIN",  7, 22, 361, 0, 0, 3, 0,  3),
    ("MIN", 14,  0, 206, 2, 1, 2, 0, 13), ("MIN", 15, 26, 423, 0, 0, 2, 0, -1),
    ("MIN", 16,  7, 141, 1, 0, 5, 0, 15), ("MIN", 17, 10, 231, 2, 4, 5, 0, 17),
    ("MIN", 18,  3, 121, 0, 0, 4, 0, 15), ("MIN", 12, 23, 288, 0, 0, 1, 0,  3),
    # Packers - EXACTLY 6 points allowed (wk12 vs MIN)
    ("GB",  12,  6, 145, 2, 1, 5, 0, 18), ("GB",   1, 13, 246, 1, 0, 4, 0, 11),
    ("GB",   4, 38, 436, 0, 0, 1, 0, -1), ("GB",  10, 10, 294, 0, 1, 0, 0,  6),
    # Broncos - low-yardage games and defensive TDs
    ("DEN",  6,  9,  82, 0, 0, 9, 0, 18), ("DEN",  4,  3, 159, 0, 0, 3, 0, 12),
    ("DEN", 18,  3, 217, 1, 1, 4, 1, 21), ("DEN", 14, 17, 229, 0, 0, 4, 1, 14),
    ("DEN",  1, 12, 133, 0, 2, 6, 0, 16), ("DEN", 10,  7, 188, 1, 0, 6, 0, 14),
    ("DEN",  2, 29, 473, 0, 0, 1, 0, -1),
    # Bengals - EXACTLY 14 points (twice) and 500+ yards (three times)
    ("CIN",  9, 47, 576, 0, 0, 2, 1,  4), ("CIN", 13, 14, 346, 1, 3, 3, 0, 10),
    ("CIN", 17, 14, 233, 0, 0, 4, 0,  9), ("CIN",  8, 39, 502, 0, 0, 0, 0, -2),
    ("CIN",  4, 28, 512, 1, 0, 0, 0, -1), ("CIN", 18,  8, 200, 0, 1, 6, 0, 14),
    ("CIN", 12, 20, 392, 1, 0, 1, 1,  7),
]

def main():
    print(f"{'tm':>4} {'wk':>3} {'PA':>4} {'YA':>5} {'int':>4} {'fum':>4} {'sk':>3} {'td':>3} | {'CBS':>4} {'eng':>4}  verdict")
    print("-" * 70)
    bad = []
    for tm, wk, pa, ya, i, f, s, td, cbs in GAMES:
        got = score_game(LG, dict(def_pa=pa, def_ya=ya, def_int=i, def_fum_rec=f,
                                  def_sack=s, def_td=td), "DST")
        ok = got == cbs
        if not ok: bad.append((tm, wk))
        print(f"{tm:>4} {wk:>3} {pa:>4} {ya:>5} {i:>4} {f:>4} {s:>3} {td:>3} | {cbs:>4} {got:>4.0f}  "
              f"{'EXACT' if ok else '*** MISMATCH ***'}")
    print(f"\n  {len(GAMES)-len(bad)}/{len(GAMES)} weeks exact")
    print("\n  singleton bands closed:")
    print("    def_pa  6-6   = 4   GB wk12  (6 pts, 145 yds, 2 INT, 1 FUM, 5 sk) -> 18")
    print("    def_pa  14-14 = 1   CIN wk13 and wk17, two independent games")
    print("    def_ya  500+  = -2  CIN wk9 (576), wk8 (502), wk4 (512), three games")
    assert not bad, bad
    print("\n  def_pa and def_ya are now COMPLETE: 7/7 and 7/7")

if __name__ == "__main__":
    main()
