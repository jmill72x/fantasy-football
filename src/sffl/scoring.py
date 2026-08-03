"""Apply SFFL banded scoring to a single game stat line.

Band tables are written with integer edges, [(low, high, points), ...] in
ascending order. The league's hard floor is the FIRST band's low: under 50
receiving yards is worth nothing. Above that floor a band's `high` is a
ceiling, not half of a closed interval - see `band_points`.
"""


def band_points(table, value):
    """Return the points for `value` in a [(low, high, points), ...] table.

    Semantics are "first band whose high >= value", with the first band's low
    as a hard floor. Below the floor is 0; above every high is the last band's
    points.

    The tables are integer-edged but the values are not: `score_season`
    divides season totals by games and hands us fractional per-game rates.
    Treating each band as a closed integer interval left gaps between them -
    a receiver averaging 6.18 catches per game fell through every rec_ct band
    ([5,6], [7,8], ...) to 0, so 105 catches scored 34 FEWER season points
    than 102 catches. Scoring is now monotonic in the value: more production
    can never score less.
    """
    if not table:
        return 0
    if value < table[0][0]:
        return 0
    for low, high, pts in table:
        if value <= high:
            return pts
    return table[-1][2]


def sack_points(rule, n):
    """Sacks score 0 below the threshold, then a flat award, then +1 each after.

    Verified against real CBS output: a 4-sack game scored 4, not 7, so the
    threshold award subsumes the first three sacks rather than adding to them.
    """
    if n < rule["threshold"]:
        return 0
    return rule["threshold_points"] + (n - rule["threshold"]) * rule["per_sack_after"]


def score_game(lg, stats, pos=None):
    """Total SFFL points for one game's stat line.

    `pos` gates the defense block. Real ingest output is dense: every profile
    maps def_pa/def_ya onto every row regardless of position, defaulting to
    0.0 for non-defenses. 0 sits inside the top band for both def_pa and
    def_ya, so testing key presence (`"def_pa" in stats`) alone would award
    every skill-position player phantom defense points on a dense stat dict.
    When `pos` is given, the defense block only runs for pos == "DST". When
    `pos` is None (the historical call signature, used by hand-built sparse
    stat dicts such as the golden DST tests below), we fall back to key
    presence so those callers are unaffected.
    """
    g = stats.get
    p = lg.points
    total = 0.0

    total += band_points(lg.bands["pass_yds"], g("pass_yds", 0))
    total += band_points(lg.bands["pass_cmp"], g("pass_cmp", 0))
    total += g("pass_td", 0) * p["pass_td"]
    total += g("pass_int", 0) * p["pass_int"]
    total += g("pass_2pt", 0) * p["pass_2pt"]

    total += band_points(lg.bands["rush_yds"], g("rush_yds", 0))
    total += g("rush_td", 0) * p["rush_td"]
    total += g("rush_2pt", 0) * p["rush_2pt"]

    total += band_points(lg.bands["rec_yds"], g("rec_yds", 0))
    total += band_points(lg.bands["rec_ct"], g("rec_ct", 0))
    total += g("rec_td", 0) * p["rec_td"]
    total += g("rec_2pt", 0) * p["rec_2pt"]

    total += g("xp_made", 0) * p["xp_made"]
    total += g("fg_u30", 0) * p["fg_under_30"]
    total += g("fg_30_39", 0) * p["fg_30_39"]
    total += g("fg_40_49", 0) * p["fg_40_49"]
    total += g("fg_50_59", 0) * p["fg_50_59"]
    total += g("fg_60", 0) * p["fg_60_plus"]
    total += g("fg_missed", 0) * p["fg_missed"]

    is_defense = pos == "DST" if pos is not None else ("def_pa" in stats or "def_ya" in stats)
    if is_defense:
        total += band_points(lg.bands["def_pa"], g("def_pa", 0))
        total += band_points(lg.bands["def_ya"], g("def_ya", 0))
        total += sack_points(lg.sack_rule, g("def_sack", 0))
        total += g("def_int", 0) * p["def_int"]
        total += g("def_fum_rec", 0) * p["def_fum_rec"]
        total += g("def_td", 0) * p["def_td"]
        total += g("def_safety", 0) * p["def_safety"]

    return total
