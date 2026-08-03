"""Compare Draft Sharks' synced scoring config against actual CBS/SFFL scoring.

Draft Sharks models scoring as per-unit rates plus a FIXED set of named bonus
thresholds. SFFL uses arbitrary bands with hard floors. The two are structurally
different, so the sync produces an approximation. This quantifies the error on
representative stat lines.

DS config read from the synced league on draftsharks.com, 2026-08-02.
"""


def band(table, v):
    for lo, hi, pts in table:
        if lo <= v <= hi:
            return pts
    return 0


# ---------- CBS / SFFL (verified: DST confirmed against real CBS output) ----------
PA_YD = [(150, 250, 2), (251, 350, 4), (351, 450, 5), (451, 9999, 7)]
PA_CMP = [(15, 19, 2), (20, 24, 3), (25, 29, 4), (30, 34, 5), (35, 39, 6), (40, 99, 7)]
RU_YD = [(50, 74, 2), (75, 99, 3), (100, 124, 4), (125, 149, 5), (150, 174, 6),
         (175, 199, 7), (200, 224, 8), (225, 249, 9), (250, 9999, 10)]
RE_YD = [(50, 74, 1), (75, 99, 2), (100, 124, 3), (125, 149, 4), (150, 174, 5),
         (175, 199, 6), (200, 9999, 7)]
RE_CT = [(5, 6, 2), (7, 8, 3), (9, 10, 4), (11, 12, 6), (13, 99, 7)]
DPA = [(0, 2, 6), (3, 5, 5), (6, 6, 4), (7, 9, 3), (10, 13, 2), (14, 14, 1), (15, 99, 0)]
DYD = [(0, 150, 6), (151, 250, 4), (251, 299, 3), (300, 350, 2), (351, 399, 0),
       (400, 499, -1), (500, 9999, -2)]


def cbs(s):
    p = 0
    p += band(PA_YD, s.get("pa_yd", 0)) + band(PA_CMP, s.get("pa_cmp", 0))
    p += s.get("pa_td", 0) * 5 - s.get("pa_int", 0)
    p += band(RU_YD, s.get("ru_yd", 0)) + s.get("ru_td", 0) * 3
    p += s.get("ru_td_short", 0) * 2 + s.get("ru_td_long", 0) * 5
    p += band(RE_YD, s.get("re_yd", 0)) + band(RE_CT, s.get("re_ct", 0))
    p += s.get("re_td", 0) * 5
    if "d_pa" in s:
        p += band(DPA, s["d_pa"]) + band(DYD, s["d_yd"])
        p += s.get("d_int", 0) + s.get("d_fum", 0) + s.get("d_td", 0) * 6
        n = s.get("d_sack", 0)
        p += 0 if n < 3 else 3 + (n - 3)
    return p


# ---------- Draft Sharks, as synced ----------
DS_PA_BONUS = [(250, 4), (300, 0), (350, 5), (400, 7)]   # named thresholds
DS_RU_BONUS = [(100, 4), (125, 5), (150, 7), (200, 10)]


def ds(s, stack=False):
    """stack=True assumes every crossed threshold fires; False = highest only."""
    p = 0
    hits = [pts for thr, pts in DS_PA_BONUS if s.get("pa_yd", 0) >= thr]
    p += sum(hits) if stack else (hits[-1] if hits else 0)
    p += s.get("pa_cmp", 0) * 2                      # 2 pts PER completion
    p += s.get("pa_td", 0) * 5 - s.get("pa_int", 0)
    hits = [pts for thr, pts in DS_RU_BONUS if s.get("ru_yd", 0) >= thr]
    p += sum(hits) if stack else (hits[-1] if hits else 0)
    p += s.get("ru_td", 0) * 3                       # no distance bonus
    p += s.get("re_ct", 0) * 2                       # 2 pts PER reception
    p += s.get("re_td", 0) * 5                       # rec yards score nothing
    if "d_pa" in s:
        p += 0                                       # every Pts Allowed band = 0
        p += s.get("d_int", 0) + s.get("d_fum", 0)
        p += s.get("d_td", 0) * 6                    # sacks 0, no yards allowed
    return p


CASES = [
    ("WR  6 rec, 85 yds",            dict(re_ct=6, re_yd=85)),
    ("WR 10 rec, 150 yds, 1 TD",     dict(re_ct=10, re_yd=150, re_td=1)),
    ("WR  3 rec, 40 yds (below floor)", dict(re_ct=3, re_yd=40)),
    ("RB 80 rush, 1 short TD, 3 rec/20", dict(ru_yd=80, ru_td=1, ru_td_short=1,
                                             re_ct=3, re_yd=20)),
    ("RB 130 rush, 2 short TD",      dict(ru_yd=130, ru_td=2, ru_td_short=2)),
    ("TQB 25/35, 280 yds, 2 TD 1 INT", dict(pa_cmp=25, pa_yd=280, pa_td=2, pa_int=1)),
    ("TQB 32/48, 410 yds, 3 TD",     dict(pa_cmp=32, pa_yd=410, pa_td=3)),
    ("DST Eagles wk15 (verified 17)", dict(d_pa=0, d_yd=75, d_int=1, d_sack=4)),
    ("DST Eagles wk14 (verified 13)", dict(d_pa=22, d_yd=275, d_int=1, d_fum=2,
                                           d_sack=7)),
]

if __name__ == "__main__":
    print(f"{'stat line':34s} {'CBS':>5} {'DS':>5} {'DSstk':>6}   error")
    print("-" * 72)
    for name, s in CASES:
        c, d, dk = cbs(s), ds(s), ds(s, stack=True)
        err = "exact" if c == d else (
            f"{d/c:.1f}x over" if c and d > c else
            f"{c/d:.1f}x under" if d else "ZERO vs " + str(c))
        print(f"{name:34s} {c:>5} {d:>5} {dk:>6}   {err}")
    print("""
Kicking is the one category DS reproduces exactly:
  CBS 1 + distance bonus -> 20-29:2  30-39:3  40-49:4  50-59:5  60+:8
  DS  FG<30:2  FG30-39:3  FG40-49:4  FG50-59:5  FG60+:8            MATCH""")
