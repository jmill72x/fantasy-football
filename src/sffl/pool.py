"""Turn a vendor extract into a scored, league-correct player pool."""

from sffl.ingest.profiles import load_profile, read_extract
from sffl.scoring import score_game
from sffl.tqb import build_tqb


def score_season(lg, player):
    """Season points from a season stat line.

    APPROXIMATION, and a biased one. Bands apply to each week's line, so we
    average to a per-game line, band that, and multiply back up. Averaging
    collapses the variance the bands reward and erases production that sits
    below a floor in the mean but clears it in individual weeks - Josh Allen's
    ~35 rushing yards per game scores zero here despite weeks well over 50.
    Replace this with a weekly distribution model once weekly data exists.
    """
    if not player.games:
        return 0.0
    per_game = {}
    for field, total in player.stats.items():
        if field.startswith("_"):
            continue
        per_game[field] = total / player.games
    return score_game(lg, per_game, pos=player.pos) * player.games


def build_pool(lg, profile_path, csv_path, year, set_name=None):
    """Read one extract, drop individual QBs, add TQB units, score everything.

    Single-set sources (every record has set_name=None) work with set_name
    left as None. Multi-set sources - vendors that stack several analysts'
    projections in one file, like Footballguys - require the caller to pick
    one set explicitly. Calling a multi-set source without --set would let
    build_tqb silently sum the same franchise's quarterbacks across every
    analyst, inflating the Team QB by however many sets cover that team; we
    refuse instead, naming the available sets so the caller can choose.
    """
    profile = load_profile(profile_path)
    rows = read_extract(profile, csv_path, year)
    if set_name is not None:
        rows = [r for r in rows if r.set_name == set_name]

    try:
        tqb = build_tqb(lg, rows, set_name=set_name)
    except ValueError:
        available = sorted({r.set_name for r in rows if r.set_name is not None})
        raise ValueError(
            "%s provides multiple analyst sets and no --set was given. "
            "Pass --set with one of: %s" % (profile.name, ", ".join(available))
        ) from None

    pool = [r for r in rows if r.pos != "QB"] + tqb

    for p in pool:
        p.stats["_season_points"] = score_season(lg, p)
    pool.sort(key=lambda p: -p.stats["_season_points"])
    return pool
