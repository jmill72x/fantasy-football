"""Verify the SFFL DST scoring model against real CBS output.

Golden-file test using the Eagles DST 2025 game log (weeks 13-17) pulled from the
CBS league site. Resolves the sack-scoring ambiguity: CBS states
  0-2 SACKs = 0 points for every 1 SACK
  4-99 SACKs = 1 point for every 1 SACK
  Plus a 3 point bonus @ 3+ SACK
which admits two readings that diverge at 4+ sacks. Week 15 is a 4-sack game and
discriminates them directly.
"""

# points allowed -> points
DPA = [(0, 2, 6), (3, 5, 5), (6, 6, 4), (7, 9, 3), (10, 13, 2), (14, 14, 1), (15, 99, 0)]
# yards allowed -> points
YDS = [(0, 150, 6), (151, 250, 4), (251, 299, 3), (300, 350, 2),
       (351, 399, 0), (400, 499, -1), (500, 9999, -2)]


def band(table, v):
    for lo, hi, pts in table:
        if lo <= v <= hi:
            return pts
    raise ValueError(f"no band for {v}")


def sacks_A(n):
    """Bonus covers the first three sacks, then 1/sack beyond."""
    return 0 if n < 3 else 3 + (n - 3)


def sacks_B(n):
    """Literal text: 1/sack in the 4-99 band, plus an additive 3-point bonus at 3+."""
    per = n if n >= 4 else 0
    return per + (3 if n >= 3 else 0)


def score(g, sack_fn):
    return (band(DPA, g["pts"]) + band(YDS, g["yds"])
            + g["int"] * 1 + g["fum"] * 1
            + g["td"] * 6 + g["sty"] * 4
            + sack_fn(g["sack"]))


# Eagles DST 2025, weeks 13-17, as displayed by CBS
GAMES = [
    dict(wk=13, opp="CHI",  pts=24, yds=425, int=1, fum=0, sack=2, td=0, sty=0, cbs=0),
    dict(wk=14, opp="@LAC", pts=22, yds=275, int=1, fum=2, sack=7, td=0, sty=0, cbs=13),
    dict(wk=15, opp="LV",   pts=0,  yds=75,  int=1, fum=0, sack=4, td=0, sty=0, cbs=17),
    dict(wk=16, opp="@WAS", pts=18, yds=220, int=1, fum=0, sack=2, td=0, sty=0, cbs=5),
    dict(wk=17, opp="@BUF", pts=12, yds=331, int=0, fum=1, sack=5, td=0, sty=0, cbs=10),
]

if __name__ == "__main__":
    print(f"{'wk':>3} {'opp':>5} {'pts':>4} {'yds':>4} {'sk':>3} | "
          f"{'CBS':>4} {'(A)':>5} {'(B)':>5}   verdict")
    okA = okB = 0
    for g in GAMES:
        a, b = score(g, sacks_A), score(g, sacks_B)
        okA += a == g["cbs"]
        okB += b == g["cbs"]
        v = "A" if a == g["cbs"] and b != g["cbs"] else (
            "both" if a == g["cbs"] else ("B" if b == g["cbs"] else "NEITHER"))
        print(f"{g['wk']:>3} {g['opp']:>5} {g['pts']:>4} {g['yds']:>4} {g['sack']:>3} | "
              f"{g['cbs']:>4} {a:>5} {b:>5}   {v}")
    n = len(GAMES)
    print(f"\n  (A) bonus covers first 3 : {okA}/{n}")
    print(f"  (B) additive bonus       : {okB}/{n}")
    assert okA == n, "hypothesis A failed against CBS output"
    print("\n  CONFIRMED: sacks = 0 below 3, then 3 points at 3 and +1 per sack after.")
    print("  Also validated: DPA bands, yards-allowed bands (5 distinct bands hit),")
    print("  interceptions at 1, and fumble recoveries at 1.")
