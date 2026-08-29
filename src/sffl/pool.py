"""Turn a vendor extract into a scored, league-correct player pool."""

from sffl.calibrate import STAT_POSITIONS, expected_points
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
    #
    # A second, distinct reason the calibrated loop below ALSO needs a
    # per-stat position gate (via STAT_POSITIONS), separate from this
    # `applicable` list: `band_points` and `expected_points` disagree on what
    # to return below the lowest observed value. `band_points` FLOORS to 0
    # below the first band's low edge, but `expected_points` CLAMPS to the
    # curve's lowest anchor. pass_yds/pass_cmp curves are built only from
    # QB/TQB weeks, so their lowest anchor sits well above 0 (e.g. ~2 points
    # at a 205 pass_yds mean). A kicker, defense, receiver or back has a
    # per-game mean of 0.0 for pass_yds/pass_cmp - band_points(0.0) correctly
    # returns 0, but expected_points(curve, 0.0) clamps to that non-zero
    # anchor and pays every non-passer phantom season points. Gating the
    # curve lookup on `player.pos in STAT_POSITIONS[stat]` keeps the
    # calibrated path from ever asking a curve about a stat that position
    # cannot produce, so producer (`build_curves`) and consumer agree on the
    # one table instead of two independently-maintained gates drifting apart.
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
        if curve and player.pos in STAT_POSITIONS[stat]:
            calibrated_banded += expected_points(curve, mean)
        else:
            calibrated_banded += band_points(lg.bands[stat], mean)

    return (linear_total + calibrated_banded) * player.games


def _band_direction(table):
    """Whether `band_points` pays MORE (+1) or LESS (-1) as the raw stat
    value climbs, read off the table itself rather than a hardcoded list of
    stat names.

    Five of the seven banded stats reward more of the raw number: more
    rushing yards, more catches, more completions all score more, and
    `band_points`'s own docstring calls this "monotonic in the value: more
    production can never score less." def_pa/def_ya invert it - fewer
    points or yards allowed is the better defensive outcome, so those two
    tables (leagues/sffl/2026.yaml) pay the MOST at the low end and taper to
    zero (def_pa) or negative (def_ya) as the raw value climbs; NEXT.md's "a
    zero is not a no-op for def_pa and def_ya" note is the same fact from
    the scoring side. `_monotone_envelope` below has to run whichever
    direction `band_points` already runs for THIS table, or "fixing"
    monotonicity for the five ascending stats would silently re-break it for
    the two descending ones (see `_calibrated_band_value`, case (c)).
    """
    sign = 0
    for i in range(1, len(table)):
        delta = table[i][2] - table[i - 1][2]
        if delta > 0:
            step = 1
        elif delta < 0:
            step = -1
        else:
            continue
        if sign == 0:
            sign = step
        elif sign != step:
            raise ValueError(
                "band table is not monotonic in either direction, so there "
                "is no single envelope direction to build: %r" % (table,))
    return sign or 1


def _monotone_envelope(curve, direction):
    """`curve`'s `(mean, expected)` anchors, coerced to move only one way as
    `mean` rises.

    `curve` is built by `calibrate.build_curves` from single-player SEASON
    aggregates - 48 players, no smoothing (see TODO B in NEXT.md) - so two
    anchors close together in `mean` can land far apart in `expected` purely
    from which player happened to produce that mean. Measured on the real
    rush_yds curve: a 21.0 yd/game anchor pays 0.525, a 25.7 yd/game anchor
    four yards HEAVIER pays only 0.119. Raw linear interpolation between
    anchors like that is not merely noisy, it is NOT MONOTONE - and
    `score_week` feeds it straight into a ranking (`sffl week --waivers`),
    so a non-monotone curve does not just look odd, it makes the tool
    recommend the strictly worse of two free agents (the 21.0-yard back
    over the 25.7-yard one - see test_cli_week's end-to-end regression for
    this exact pair).

    The fix is a running extremum over the anchors in ascending `mean`
    order: a running MAXIMUM when `band_points` pays more as the value rises
    (`direction=+1` - rush_yds, rec_yds, rec_ct, pass_yds, pass_cmp), a
    running MINIMUM when it pays less (`direction=-1` - def_pa, def_ya).
    Either way the result never moves the wrong way as `mean` rises, and
    linear interpolation between two points that only move one way is
    itself monotone the same way - it cannot reintroduce the noise this
    removes.

    Every point this returns is >= (direction=+1) or <= (direction=-1) the
    raw curve's value at that same mean - a running extremum can only move
    toward its own bound, never away from it. That is what keeps existing
    calibration values from ever being LOWERED by this (e.g. the 4.4-catch
    case only ever goes up or holds), and why the docstring above can
    promise "raise or hold, never lower."
    """
    if not curve:
        return curve
    ordered = sorted(curve)
    out = []
    running = None
    for mean, exp in ordered:
        if running is None:
            running = exp
        elif direction > 0:
            if exp > running:
                running = exp
        else:
            if exp < running:
                running = exp
        out.append((mean, running))
    return out


def _calibrated_band_value(lg, stat, curve, value):
    """The monotone replacement for `expected_points(curve, value)`.

    Three fixes live here. None are tuned to the specific numbers below -
    those are just how the bug was found and how to check it stayed fixed.

    (a) INTRA-SPAN NOISE - `_monotone_envelope` above, which this calls
    before ever interpolating. See its docstring for the 21.0-vs-25.7
    rush_yds case.

    (b) THE TOP SEAM. Outside the envelope's span there is no curve
    evidence, so the fallback is `band_points` (unchanged from before this
    fix) - but `band_points` and the envelope are two independently built
    functions that happen to meet at the span's edge, and nothing guaranteed
    they meet at the SAME height. Measured: the rush_yds envelope's top
    anchor (93.824 yds) pays 3.176, while `band_points` at 94.0 yds - a
    tenth of a yard further in the direction that is supposed to pay MORE -
    pays only 3.000, a drop. `max(band_points(value), envelope_top)` fixes
    it: `band_points` is itself non-decreasing out there and the envelope's
    top is a constant, so their max is non-decreasing and can never dip
    below what the envelope already proved.

    (c) THE MIRROR SEAM. def_pa/def_ya run the other direction (see
    `_band_direction`), so their vulnerable seam is the BOTTOM: a defense
    projected for 16 points allowed (below the curve's lowest anchor, so the
    `band_points` fallback -> 0) scored LESS than one projected for 18.2
    (inside the span, envelope -> 1.118) - a worse defense paying more. Not
    reachable today - no DST group is wired into sources/cbs-weekly.yaml, so
    score_week never sees pos="DST" in production - but the code path exists
    and would fire the moment one is added. Same fix, mirrored by direction:
    below the bottom anchor, a direction=-1 stat needs
    `max(band_points(value), envelope_bottom)` (the fallback must not pay
    LESS than the envelope already proved a higher, worse value pays); a
    direction=+1 stat needs `min(...)` at that same bottom edge. That `min`
    is a no-op for all five ascending stats in this league today -
    `band_points` floors to exactly 0 below its first band, and every one of
    their curves is built from non-negative points, so there is nothing for
    it to clamp - but it is checked anyway, on the same principle
    score_week's old span check applied to both bounds: the curve has
    evidence on one side and none past it, in either direction.

    Never mutates `curve` - it is `curves[stat]`, the SAME list object
    `score_season_calibrated` reads for the auction path in this same
    process (see `cli._value_pool`). Building a fresh envelope here, rather
    than sorting or clamping `curve` in place, is what keeps that path
    bit-for-bit unchanged.
    """
    table = lg.bands[stat]
    if not curve:
        return band_points(table, value)

    direction = _band_direction(table)
    envelope = _monotone_envelope(curve, direction)
    lo_mean, lo_val = envelope[0]
    hi_mean, hi_val = envelope[-1]

    if lo_mean <= value <= hi_mean:
        return expected_points(envelope, value)

    raw = band_points(table, value)
    if value > hi_mean:
        return max(raw, hi_val) if direction > 0 else min(raw, hi_val)
    return min(raw, lo_val) if direction > 0 else max(raw, lo_val)


def score_week(lg, player, curves):
    """Expected points for ONE week from a projected stat line.

    `player.stats` holds a single week's projection, not a season total, so
    unlike `score_season_calibrated` there is no division by games and no
    multiplication back up.

    WHY THIS IS NOT JUST score_game. CBS already applies this league's bands to
    its weekly projections and agrees with `score_game` to within a cent. But it
    bands a POINT ESTIMATE, and `E[band(X)] != band(E[X])`: a player projected
    at 4.4 receptions is scored 0 for receptions, when he clears 5 in plenty of
    weeks. The curves map per-game mean -> expected points, and a weekly
    projection IS a per-game mean, so they apply directly here.

    The gating below is identical to `score_season_calibrated`'s and exists for
    the same two reasons - see its docstring. Do not simplify either gate away.

    Refuses a line that is not one week: `player` carries the same
    PlayerProjection type `score_season_calibrated` takes, and nothing about
    the type distinguishes a week from a season, so a season total passed
    here would silently return a plausible-looking number instead of the
    single week's expectation it claims to be. Same discipline as
    `tqb_starters_season`, the `flat_priced_pools` price guard and
    `build_pool`'s multi-set refusal: raise rather than document the trap.
    """
    if player.games != 1:
        raise ValueError(
            "score_week got games=%r for %r; score_week takes a single "
            "week's projected line (games=1), while score_season_calibrated "
            "takes a season total - pass the right function for the shape "
            "of this data" % (player.games, player.name))

    if curves is None:
        return score_game(lg, player.stats, pos=player.pos)

    line = dict((k, v) for k, v in player.stats.items()
                if not k.startswith("_"))

    applicable = _ALWAYS_BANDED
    if player.pos == "DST":
        applicable = _ALWAYS_BANDED + ("def_pa", "def_ya")

    full = score_game(lg, line, pos=player.pos)

    naive_banded = 0.0
    calibrated_banded = 0.0
    for stat in applicable:
        value = line.get(stat, 0.0)
        naive_banded += band_points(lg.bands[stat], value)
        curve = curves.get(stat)
        # STAT_POSITIONS[stat], not .get(stat, ()): score_season_calibrated
        # (above) uses the same direct indexing, and this docstring claims
        # the two gates are identical. A banded stat added to lg.bands
        # without a STAT_POSITIONS entry must raise here exactly as loudly
        # as it already does on the season path - a silent .get() fallback
        # would make that claim false and let the weekly path skip
        # calibration with no signal at all.
        if curve and player.pos in STAT_POSITIONS[stat]:
            # F1/C1. curve's observed span is [curve[0][0], curve[-1][0]] -
            # the range of PER-GAME MEANS actually measured when it was
            # built (calibrate.build_curves draws these from 2025 SEASON
            # per-game means across 48 players; rush_yds tops out at a 93.8
            # yd/game mean). A weekly PROJECTION is also a per-game mean, but
            # nothing stops it from landing above the highest one ever
            # observed - a back projected for 150 yards in a single week
            # exceeds that span by construction, not by error.
            #
            # Below F1 stopped here: outside the span, fall back to
            # band_points since the curve has no evidence there. That is
            # still true, but the curve's raw anchors are ALSO not
            # guaranteed monotone WITHIN the span, and the fallback is not
            # guaranteed to meet the curve at the same height AT the edge of
            # it - both are real, both invert a ranking, and neither is
            # calibrate.py's problem to fix: it is shared with the
            # already-merged auction pipeline via score_season_calibrated
            # above, so the fix lives here instead. See
            # `_calibrated_band_value`'s docstring for the three cases and
            # the concrete numbers that proved each one.
            calibrated_banded += _calibrated_band_value(lg, stat, curve, value)
        else:
            calibrated_banded += band_points(lg.bands[stat], value)

    return (full - naive_banded) + calibrated_banded


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
