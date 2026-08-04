"""Turn a vendor extract into a scored, league-correct player pool."""

from sffl.calibrate import expected_points
from sffl.ingest.profiles import load_profile, read_extract
from sffl.scoring import band_points, score_game
from sffl.tqb import MultipleAnalystSetsError, build_tqb

# The banded stats score_game applies to EVERY position, regardless of pos.
# def_pa/def_ya are intentionally excluded here - see the pos == "DST" gate
# below and its explanation.
_ALWAYS_BANDED = ("pass_yds", "pass_cmp", "rush_yds", "rec_yds", "rec_ct")


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


def score_season_calibrated(lg, player, curves):
    """Season points using empirical expectation curves for banded stats.

    Replaces band(per-game mean) with E[band(weekly)] measured from real data.
    Linear categories - touchdowns, interceptions, extra points, field goals by
    distance - are unaffected by averaging and pass through unchanged.

    Only the banded portion of the score is swapped. Everything else -
    including the position gate on the defense block - runs through the
    validated `score_game` engine so nothing here can diverge from it.
    Concretely: run `score_game` once on the per-game line to get the full
    validated total, compute what it added for the banded stats that apply
    to this position (`naive_banded`), subtract that back out, and add the
    calibrated banded total in its place.

    KNOWN LIMITATION: sacks use a threshold rule rather than a band table, so
    they are not corrected here. A defense averaging 2.5 sacks per game still
    scores zero sack points across the season. See the spec.
    """
    if not player.games:
        return 0.0

    per_game = {}
    for field_name, total in player.stats.items():
        if field_name.startswith("_"):
            continue
        per_game[field_name] = total / player.games

    # def_pa/def_ya are banded stats, but score_game only ever applies them
    # for pos == "DST" - see its docstring. def_pa/def_ya band the value 0
    # at their MAXIMUM points ([[0,2,6],...], [[0,150,6],...]), and a non-DST
    # player's per-game mean for them is always 0.0 (the stat is absent from
    # their line). Dropping this gate would pay every skill player and
    # kicker phantom points for a shutout they never played - the exact bug
    # `score_game`'s docstring documents and fixed with this same gate. Keep
    # it in lockstep with `score_game`'s gate; do not delete as "redundant".
    applicable = _ALWAYS_BANDED
    if player.pos == "DST":
        applicable = _ALWAYS_BANDED + ("def_pa", "def_ya")

    full = score_game(lg, per_game, pos=player.pos)

    naive_banded = 0.0
    for stat in applicable:
        naive_banded += band_points(lg.bands[stat], per_game.get(stat, 0.0))

    linear_total = full - naive_banded

    calibrated_banded = 0.0
    for stat in applicable:
        mean = per_game.get(stat, 0.0)
        curve = curves.get(stat)
        if curve:
            calibrated_banded += expected_points(curve, mean)
        else:
            calibrated_banded += band_points(lg.bands[stat], mean)

    return (linear_total + calibrated_banded) * player.games


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
