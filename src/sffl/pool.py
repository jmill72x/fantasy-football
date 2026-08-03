"""Turn a vendor extract into a scored, league-correct player pool."""

from sffl.ingest.profiles import load_profile, read_extract
from sffl.scoring import score_game
from sffl.tqb import MultipleAnalystSetsError, build_tqb


def score_season(lg, player):
    """Season points from a season stat line.

    APPROXIMATION, and a biased one. Bands apply to each week's line, so we
    average to a per-game line, band that, and multiply back up. Averaging
    collapses the variance the bands reward and erases production that sits
    below a floor in the mean but clears it in individual weeks - Josh Allen's
    ~35 rushing yards per game scores zero here despite weeks well over 50.

    TEAM DEFENSES ARE THE WORST CASE, and it is not a rounding error: sacks
    score nothing below 3 IN A GAME (see `sack_points`), while a good NFL
    defense averages 2.1-2.6. Every defense therefore lands under the
    threshold in the mean and collects NONE of its projected sacks all
    season. The Draft Sharks fixture projects the Eagles at 42 sacks; through
    this function they contribute exactly 0 of the unit's ~92 points, where a
    weekly distribution would pay roughly 30. A DST's single largest scoring
    category is structurally zeroed here, so DSTs are systematically
    undervalued relative to skill players, whose floors merely clip a tail.

    See `test_known_limitation_season_path_zeroes_all_dst_sacks` - it pins the
    current behaviour so the weekly model changes it visibly, on purpose.

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
        filtered = [r for r in rows if r.set_name == set_name]
        if not filtered:
            available = sorted({r.set_name for r in rows if r.set_name is not None})
            if available:
                raise ValueError(
                    "%s has no rows for --set %r. Pass --set with one of: %s"
                    % (profile.name, set_name, ", ".join(available))
                )
            raise ValueError(
                "%s has no analyst sets (every record has set_name=None); "
                "--set does not apply to this source, omit it." % profile.name
            )
        rows = filtered

    # Only the genuine multi-set condition gets rewritten into a friendlier
    # message; any other ValueError build_tqb might raise propagates as-is,
    # with its own message and traceback, rather than being masked here.
    try:
        tqb = build_tqb(lg, rows, set_name=set_name)
    except MultipleAnalystSetsError:
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
