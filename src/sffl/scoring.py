"""Apply SFFL banded scoring to a single game stat line.

Bands are inclusive on both ends. A value outside every band scores 0, which is
how the league's hard floors work: under 50 receiving yards is worth nothing.
"""


def band_points(table, value):
    """Return the points for `value` in a [(low, high, points), ...] table."""
    for low, high, pts in table:
        if low <= value <= high:
            return pts
    return 0


def sack_points(rule, n):
    """Sacks score 0 below the threshold, then a flat award, then +1 each after.

    Verified against real CBS output: a 4-sack game scored 4, not 7, so the
    threshold award subsumes the first three sacks rather than adding to them.
    """
    if n < rule["threshold"]:
        return 0
    return rule["threshold_points"] + (n - rule["threshold"]) * rule["per_sack_after"]


def score_game(lg, stats):
    """Total SFFL points for one game's stat line."""
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

    if "def_pa" in stats or "def_ya" in stats:
        total += band_points(lg.bands["def_pa"], g("def_pa", 0))
        total += band_points(lg.bands["def_ya"], g("def_ya", 0))
        total += sack_points(lg.sack_rule, g("def_sack", 0))
        total += g("def_int", 0) * p["def_int"]
        total += g("def_fum_rec", 0) * p["def_fum_rec"]
        total += g("def_td", 0) * p["def_td"]
        total += g("def_safety", 0) * p["def_safety"]

    return total
