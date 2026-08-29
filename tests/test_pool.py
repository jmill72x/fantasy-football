import pytest

from sffl import pool as pool_module
from sffl.calibrate import STAT_POSITIONS, load_curves
from sffl.league import load_league
from sffl.pool import build_pool, score_season, score_season_calibrated, score_week
from sffl.schema import PlayerProjection
from sffl.scoring import score_game

LG = load_league("leagues/sffl/2026.yaml")
DS_PROFILE = "sources/draftsharks.yaml"
DS_FIXTURE = "tests/fixtures/draftsharks_sample.csv"
FBG_PROFILE = "sources/footballguys.yaml"
FBG_FIXTURE = "tests/fixtures/footballguys_sample.csv"


def test_score_season_averages_to_per_game_then_bands():
    # 1700 receiving yards over 17 games = 100/game -> band 100-124 = 3 pts
    # 102 catches over 17 = 6/game -> band 5-6 = 2 pts
    p = PlayerProjection(name="X", team="CIN", pos="WR", source="t", source_year=2026,
                         games=17, stats=dict(rec_yds=1700, rec_ct=102), raw_name="X")
    assert score_season(LG, p) == (3 + 2) * 17


def wr(rec_ct, rec_yds=1200, games=17):
    return PlayerProjection(name="WR", team="CIN", pos="WR", source="t",
                            source_year=2026, games=games,
                            stats=dict(rec_yds=rec_yds, rec_ct=rec_ct),
                            raw_name="WR")


def test_more_catches_never_score_fewer_points():
    """Regression: season totals divide to FRACTIONAL per-game rates.

    With integer-edged bands treated as closed intervals, a WR averaging
    6.18 catches per game (105 over 17) fell between rec_ct's [5,6] and
    [7,8] bands and scored ZERO reception points for the season - 34 fewer
    points than the same WR with three catches less. The old test used
    102 catches over 17 games, which divides to exactly 6.0 and hid it.
    """
    prev = None
    for catches in range(0, 260):
        pts = score_season(LG, wr(catches))
        if prev is not None:
            assert pts >= prev, "%d catches scored %s, %d scored %s" % (
                catches, pts, catches - 1, prev)
        prev = pts

    # The specific measured regression.
    assert score_season(LG, wr(105)) >= score_season(LG, wr(102))
    # 1200 yds / 17 = 70.6 per game -> rec_yds band [50,74] = 1
    # 105 rec / 17  = 6.18 per game -> rec_ct band [7,8]   = 3   (was 0)
    assert score_season(LG, wr(105)) == (1 + 3) * 17


def test_known_limitation_season_path_zeroes_all_dst_sacks():
    """DOCUMENTS A KNOWN LIMITATION - this is not the behaviour we want.

    Sacks score nothing below 3 in a game, and averaging a season total down
    to a per-game line puts every real defense under that threshold: the
    fixture projects 35 sacks over 17 games, or 2.06 a game, so
    `sack_points` returns 0 and the unit collects NONE of its
    largest projected category. Under a weekly distribution the true
    expectation is a real share of the unit's 81.

    Do NOT "fix" this by special-casing sacks - the averaging approximation
    is deliberate and documented in `score_season`. This test exists so the
    weekly distribution model that replaces it has to change this assertion
    deliberately and visibly, rather than moving DST valuations by accident.
    """
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    dst = next(p for p in pool if p.pos == "DST")
    assert dst.stats["def_sack"] == 35 and dst.games == 17   # 2.06 a game

    without_sacks = PlayerProjection(
        name=dst.name, team=dst.team, pos=dst.pos, source=dst.source,
        source_year=dst.source_year, games=dst.games, raw_name=dst.raw_name,
        stats=dict(dst.stats, def_sack=0))

    # 35 sacks and 0 sacks are worth precisely the same season score.
    assert score_season(LG, dst) == score_season(LG, without_sacks)

    # Not because the whole unit scores 0 - it scores 81 points of pass-
    # allowed, yards-allowed, turnover and touchdown production. The sacks
    # alone vanish.
    assert score_season(LG, dst) == pytest.approx(81)


def test_zero_games_does_not_divide_by_zero():
    p = PlayerProjection(name="Y", team="CIN", pos="WR", source="t", source_year=2026,
                         games=0, stats=dict(rec_yds=0), raw_name="Y")
    assert score_season(LG, p) == 0.0


def test_build_pool_scores_every_player_and_adds_tqb():
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    assert all("_season_points" in p.stats for p in pool)
    assert any(p.pos == "TQB" for p in pool)
    tqb = [p for p in pool if p.pos == "TQB"]
    assert [t.name for t in tqb] == ["BUF"]


def test_individual_quarterbacks_are_removed_from_the_pool():
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    assert not any(p.pos == "QB" for p in pool), \
        "individual QBs are not draftable in this league"


def test_build_pool_multi_set_source_without_set_raises_clear_error():
    # Footballguys stacks multiple analysts' projections in one file. Calling
    # without --set would silently multiply Team QB stats by the number of
    # analyst sets covering each franchise, so build_pool must refuse instead.
    with pytest.raises(ValueError) as exc_info:
        build_pool(LG, FBG_PROFILE, FBG_FIXTURE, 2026)
    msg = str(exc_info.value)
    assert "--set" in msg
    # The available set names must be named so the user knows what to pass.
    assert "Consensus" in msg
    assert "Dan Hindery" in msg


def test_typo_set_name_on_multi_set_source_raises_naming_available_sets():
    """A mistyped --set must not silently filter every row to zero.

    Before the fix, filtering by a set name that matches nothing produced an
    empty pool with no error at all - the CLI would report a "successful"
    ingest of 0 players.
    """
    with pytest.raises(ValueError) as exc_info:
        build_pool(LG, FBG_PROFILE, FBG_FIXTURE, 2026, set_name="Typo Name")
    msg = str(exc_info.value)
    assert "Typo Name" in msg
    assert "Consensus" in msg
    assert "Dan Hindery" in msg


def test_set_name_on_single_set_source_raises_source_has_no_sets():
    """--set passed to a single-set source (every row set_name=None) must
    raise, naming that the source has no sets - not silently yield 0 rows.
    """
    with pytest.raises(ValueError) as exc_info:
        build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026, set_name="Consensus")
    msg = str(exc_info.value)
    assert "no analyst sets" in msg or "no sets" in msg


def test_unrelated_value_error_from_build_tqb_is_not_masked(monkeypatch):
    """Only the genuine multi-set condition gets rewritten.

    Any other ValueError build_tqb raises must propagate with its own
    message intact, not get overwritten with the multi-set/--set message.
    """
    def boom(lg, rows, set_name=None):
        raise ValueError("unrelated failure: bad franchise code XYZ")

    monkeypatch.setattr(pool_module, "build_tqb", boom)

    with pytest.raises(ValueError) as exc_info:
        build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    msg = str(exc_info.value)
    assert "unrelated failure: bad franchise code XYZ" in msg
    assert "--set" not in msg


def test_calibrated_scoring_recovers_value_the_naive_path_zeroes():
    # A quarterback averaging 35 rushing yards per game scores ZERO rushing under
    # the naive path, because band(35) == 0. A curve built from a player who
    # alternated 0 and 70 yards says the true expectation is 1.0 per game.
    lg = LG
    curves = {"rush_yds": [(35.0, 1.0)]}
    p = PlayerProjection(name="QB", team="BUF", pos="TQB", source="t",
                         source_year=2026, games=17,
                         stats=dict(rush_yds=595.0), raw_name="QB")
    naive = score_season(lg, p)
    cal = score_season_calibrated(lg, p, curves)
    assert naive == 0.0
    assert cal == pytest.approx(17.0)


def test_calibrated_leaves_linear_categories_untouched():
    lg = LG
    curves = {}
    p = PlayerProjection(name="K", team="DAL", pos="K", source="t",
                         source_year=2026, games=17,
                         stats=dict(xp_made=34.0, fg_40_49=17.0), raw_name="K")
    # 34 XP at 1 + 17 FG at 4 = 102, and no banded stat is involved
    assert score_season_calibrated(lg, p, curves) == pytest.approx(102.0)


def test_calibrated_equals_naive_when_curve_matches_the_band():
    lg = LG
    curves = {"rec_yds": [(100.0, 3.0)]}
    p = PlayerProjection(name="WR", team="CIN", pos="WR", source="t",
                         source_year=2026, games=17,
                         stats=dict(rec_yds=1700.0), raw_name="WR")
    assert score_season_calibrated(lg, p, curves) == pytest.approx(score_season(lg, p))


def test_calibrated_non_dst_player_gets_zero_defense_points_from_populated_curve():
    """Regression for the brief's reference-implementation defect.

    A non-DST player's per-game stats never include def_pa/def_ya, so their
    mean defaults to 0.0. Both def_pa and def_ya band 0 at their MAXIMUM
    points ([[0,2,6],...] and [[0,150,6],...]), so any implementation that
    loops over every stat in lg.bands regardless of position - rather than
    gating on player.pos == "DST" the way score_game does - pays a receiver
    phantom defense points for a shutout they never played.

    This is a real regression test: it FAILS against the brief's Step 3
    reference implementation, which loops `for stat in lg.bands` unconditionally.
    """
    lg = LG
    curves = {"def_pa": [(0.0, 6.0)], "def_ya": [(0.0, 6.0)]}
    p = PlayerProjection(name="WR", team="CIN", pos="WR", source="t",
                         source_year=2026, games=17,
                         stats=dict(rec_yds=850.0), raw_name="WR")
    # 850 / 17 = 50/game -> rec_yds band [50,74] = 1 point/game * 17 = 17
    assert score_season_calibrated(lg, p, curves) == pytest.approx(17.0)


def test_calibrated_kicker_gets_zero_phantom_pass_points_from_qb_curve():
    """Regression for CRITICAL 1: expected_points CLAMPS below its lowest
    anchor, band_points FLOORS to 0. A kicker's per-game mean for pass_yds
    and pass_cmp is always 0.0 (the stat is absent from a kicker's line).
    Feeding that 0.0 into a pass_yds/pass_cmp curve built only from TQB
    weeks - whose lowest observed anchor sits well above zero - must NOT
    clamp to that anchor and pay the kicker phantom season points.

    Measured before the fix: a pure kicker worth 102 real points scored
    174.00 (+72.00) through score_season_calibrated with curves whose
    lowest pass_yds/pass_cmp anchors were (205.765, 2.0) and (18.706, 2.235).
    """
    lg = LG
    curves = {
        "pass_yds": [(205.765, 2.0), (400.0, 4.0)],
        "pass_cmp": [(18.706, 2.235), (30.0, 3.0)],
    }
    p = PlayerProjection(name="K", team="DAL", pos="K", source="t",
                         source_year=2026, games=17,
                         stats=dict(xp_made=34.0, fg_40_49=17.0), raw_name="K")
    # 34 XP at 1 + 17 FG at 4 = 102, unaffected by a curve for a stat a
    # kicker never records.
    assert score_season_calibrated(lg, p, curves) == pytest.approx(102.0)


def test_calibrated_kicker_scores_correctly_against_a_fully_populated_curve_set():
    """Coverage gap: every other calibrated test exercises the curve path
    with only the single stat under test populated. Here every banded stat
    sffl.league declares has a non-trivial (non-zero-anchored) curve, and
    the player (a kicker) produces none of the banded stats at all - only
    linear categories (XP, FG). Nothing but the linear total should survive.
    """
    lg = LG
    curves = {stat: [(50.0, 5.0), (100.0, 8.0)] for stat in lg.bands}
    p = PlayerProjection(name="K", team="DAL", pos="K", source="t",
                         source_year=2026, games=17,
                         stats=dict(xp_made=34.0, fg_40_49=17.0), raw_name="K")
    assert score_season_calibrated(lg, p, curves) == pytest.approx(102.0)


def test_score_week_with_no_curves_is_exactly_score_game():
    """Without curves there is nothing to calibrate, so the weekly scorer must
    not drift from the validated engine by even a rounding step."""
    p = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=1.0,
                         stats={"rec_ct": 4.4, "rec_yds": 59.7, "rec_td": 0.5})
    assert score_week(LG, p, None) == score_game(LG, p.stats, "WR")


def test_score_week_pays_a_projection_sitting_just_under_a_band_edge():
    """The whole point. 4.4 receptions is under the 5-reception band, so the
    naive band pays 0 - but a player projected at 4.4 clears 5 in plenty of
    weeks and has a real expectation."""
    curves = load_curves("calibration/2025.yaml")
    p = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=1.0, stats={"rec_ct": 4.4})
    naive = score_game(LG, p.stats, "WR")
    assert naive == 0.0
    assert score_week(LG, p, curves) > 0.5


def test_score_week_does_not_leak_a_passing_curve_into_a_receiver():
    """Gate (b) protects against curve leakage: expected_points clamps below
    its lowest anchor where band_points floors to 0. pass_yds curves are built
    from QB weeks only, so their lowest anchor sits well above zero; this test
    verifies a receiver never queries a passing curve. (Does NOT test gate (a),
    the DST position filter for def_pa/def_ya - see the separate DST tests.)"""
    curves = load_curves("calibration/2025.yaml")
    receiver = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                                source_year=2026, games=1.0,
                                stats={"rec_ct": 4.4, "def_pa": 0.0, "def_ya": 0.0})
    assert score_week(LG, receiver, curves) < 5.0


def test_score_week_does_not_pay_a_kicker_from_a_passing_curve():
    """expected_points CLAMPS below the lowest anchor where band_points FLOORS.
    pass_yds curves are built from QB weeks only, so their lowest anchor is far
    above zero; asking one about a kicker's 0.0 pays phantom points."""
    curves = load_curves("calibration/2025.yaml")
    k = PlayerProjection(name="Test K", team="GB", pos="K", source="t",
                         source_year=2026, games=1.0,
                         stats={"xp_made": 2.0, "pass_yds": 0.0})
    naive = score_game(LG, k.stats, "K")
    assert score_week(LG, k, curves) == naive


def test_score_week_calibrates_a_defense_s_banded_points():
    """The other side of gate (a): for a DST, def_pa and def_ya DO go through
    the curves, so the calibrated result must differ from the naive band."""
    curves = load_curves("calibration/2025.yaml")
    d = PlayerProjection(name="Test DST", team="GB", pos="DST", source="t",
                         source_year=2026, games=1.0,
                         stats={"def_pa": 17.0, "def_ya": 305.0})
    assert score_week(LG, d, curves) != score_game(LG, d.stats, "DST")


def test_score_week_refuses_a_season_line():
    """score_week takes ONE week's projected line; score_season_calibrated
    takes a season total - same PlayerProjection type, opposite shape, no
    guard. A 95-catch, 1300-yard SEASON line silently returned a
    plausible-looking 51.25 with nothing to say it was never a week. This
    repo refuses this class of mistake elsewhere (tqb_starters_season, the
    flat_priced_pools price guard, build_pool's multi-set refusal) rather
    than documenting it and hoping - this is the same discipline applied
    here."""
    p = PlayerProjection(name="Season WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=17,
                         stats={"rec_ct": 95.0, "rec_yds": 1300.0})
    with pytest.raises(ValueError, match="games"):
        score_week(LG, p, None)


def test_gate_a_is_redundant_only_while_the_defense_stats_are_dst_only():
    """score_week's `applicable` gate and STAT_POSITIONS currently encode the
    same condition, which is why deleting the gate changes nothing today. If
    STAT_POSITIONS ever widens, that gate becomes load-bearing - and it has no
    direct test. Fail here so the widening is a decision, not a discovery."""
    assert STAT_POSITIONS["def_pa"] == {"DST"}
    assert STAT_POSITIONS["def_ya"] == {"DST"}


def test_score_week_uses_the_naive_band_above_the_curves_span():
    """THE FIX FOR F1. calibrate.expected_points CLAMPS to the curve's last
    anchor for any mean above it, and the curves are built from 2025 SEASON
    per-game means (48 players) - rush_yds tops out at a 93.8 yd/game mean,
    paying 3.18. A weekly PROJECTION routinely exceeds that: a back projected
    for 150 rushing yards in a single week is not the same claim as a 150
    yd/game season average, but expected_points cannot tell the difference
    and would clamp to the same 3.18 paid to a back projected at 96 or 110.
    Outside the curve's observed span there is no evidence behind the
    calibrated number, so score_week must fall back to the naive band -
    exactly what it already does when there is no curve at all."""
    curves = load_curves("calibration/2025.yaml")
    p = PlayerProjection(name="Big Game RB", team="GB", pos="RB", source="t",
                         source_year=2026, games=1.0, stats={"rush_yds": 150.0})
    assert score_week(LG, p, curves) == score_game(LG, p.stats, "RB")


def test_score_week_still_calibrates_a_value_inside_the_span():
    """The other side of the same fix: a value INSIDE the curve's observed
    span must still be calibrated, not fall back to the naive band just
    because the out-of-span guard now exists. Same fixture as
    test_score_week_pays_a_projection_sitting_just_under_a_band_edge, given
    its own name in this block so the in-span path is pinned alongside the
    out-of-span one it is now adjacent to in the implementation."""
    curves = load_curves("calibration/2025.yaml")
    p = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=1.0, stats={"rec_ct": 4.4})
    naive = score_game(LG, p.stats, "WR")
    assert naive == 0.0
    assert score_week(LG, p, curves) > naive


def test_score_week_does_not_collapse_two_backs_above_the_span_to_one_number():
    """Measured before the fix: 96 and 110 rushing yards both clamped to the
    curve's last anchor (3.18 pts) and scored identically despite being
    visibly different projections - as would 150. The naive band tells them
    apart (3.00 vs 4.00 vs 6.00), so score_week must too."""
    curves = load_curves("calibration/2025.yaml")

    def rb(rush_yds):
        return PlayerProjection(name="RB %d" % rush_yds, team="GB", pos="RB",
                                source="t", source_year=2026, games=1.0,
                                stats={"rush_yds": rush_yds})

    assert score_week(LG, rb(96), curves) != score_week(LG, rb(110), curves)


def test_score_week_seam_at_the_top_anchor_does_not_decrease():
    """C1(b), the seam a previous fix introduced. The rush_yds curve's top
    anchor sits at 93.824 yds and pays 3.176 - the highest expected value
    anywhere on the curve. Before the monotone envelope, a value one tenth
    of a yard past it (94.0) fell back to band_points and paid only 3.000: a
    DROP as production rose, immediately above the point score_week's own
    fallback logic is supposed to protect. `max(band_points(value),
    envelope_at_top_anchor)` must keep 94.0 at or above 93.824's value."""
    curves = load_curves("calibration/2025.yaml")

    def rb(rush_yds):
        return PlayerProjection(name="RB", team="GB", pos="RB", source="t",
                                source_year=2026, games=1.0,
                                stats={"rush_yds": rush_yds})

    at_top_anchor = score_week(LG, rb(93.824), curves)
    just_past_it = score_week(LG, rb(94.0), curves)
    assert just_past_it >= at_top_anchor, (
        "the seam at the top anchor decreased: 93.824 yds scored %.4f but "
        "94.0 yds scored %.4f" % (at_top_anchor, just_past_it))


# C1: the property test. Sweeps a 0.1 grid across a generous range for
# EVERY banded stat calibration/2025.yaml defines and asserts score_week's
# contribution only ever moves the direction band_points already moves for
# that stat - never the other way. This single test is the one that would
# have caught all three defects in the report at once:
#   (a) intra-span anchor noise - measured pre-fix: a projected RB averaging
#       21.0 rush_yds/game scored 0.525 while one averaging 25.7 (MORE
#       production) scored only 0.119; the 0.1-yard sweep below over
#       rush_yds alone found 201 inverted steps before the fix.
#   (b) the top-of-span seam (see the dedicated test above).
#   (c) the mirrored bottom-of-span seam on a DESCENDING stat: a defense
#       projected to allow 16.0 points (worse than allowing none) scored
#       0.0, but one projected to allow 18.2 (WORSE still) scored 1.118 -
#       a worse defense paying more.
#
# Ranges are generous on both sides of each curve's observed span - see
# calibration/2025.yaml for the actual anchors - so the sweep exercises the
# bottom seam, the interior, and the top seam together. rush_yds's 0-120 is
# the exact range the defect report measured its 201 inversions across.
_GRID_RANGES = {
    "pass_yds": (0.0, 500.0),
    "pass_cmp": (0.0, 45.0),
    "rush_yds": (0.0, 120.0),
    "rec_yds": (0.0, 220.0),
    "rec_ct": (0.0, 20.0),
    "def_pa": (0.0, 60.0),
    "def_ya": (0.0, 600.0),
}

# Any one position valid for the stat exercises the same curve - curves are
# keyed by stat only, never by position; STAT_POSITIONS only gates WHETHER
# score_week consults a curve at all, not which one.
_GRID_POS = {
    "pass_yds": "TQB",
    "pass_cmp": "TQB",
    "rush_yds": "RB",
    "rec_yds": "WR",
    "rec_ct": "WR",
    "def_pa": "DST",
    "def_ya": "DST",
}


def _table_direction(table):
    """Ground truth direction read straight off the band table's first and
    last (low, high, pts) rows - deliberately NOT importing
    pool._band_direction, so a bug in that helper cannot also blind the
    test meant to catch it. Every table this league defines is monotonic
    pts-wise end to end (see test_league.py / leagues/sffl/2026.yaml), so
    comparing only the endpoints is sufficient here."""
    first_pts, last_pts = table[0][2], table[-1][2]
    if last_pts > first_pts:
        return 1
    if last_pts < first_pts:
        return -1
    raise AssertionError(
        "table's first and last band pay the same, no direction to check: %r"
        % (table,))


@pytest.mark.parametrize("stat", sorted(LG.bands))
def test_score_week_is_monotone_across_a_grid_for_every_banded_stat(stat):
    assert stat in _GRID_RANGES and stat in _GRID_POS, (
        "%s has no grid range/position configured for this property test - "
        "a new banded stat must be added here, not skipped" % stat)
    curves = load_curves("calibration/2025.yaml")
    lo, hi = _GRID_RANGES[stat]
    pos = _GRID_POS[stat]
    direction = _table_direction(LG.bands[stat])

    def score_at(value):
        p = PlayerProjection(name="Probe", team="GB", pos=pos, source="t",
                             source_year=2026, games=1.0,
                             stats={stat: value})
        return score_week(LG, p, curves)

    steps = int(round((hi - lo) / 0.1))
    prev_x, prev_y = lo, score_at(lo)
    for i in range(1, steps + 1):
        x = round(lo + i * 0.1, 6)
        y = score_at(x)
        if direction > 0:
            assert y >= prev_y - 1e-9, (
                "%s must pay AT LEAST as much as production rises, but "
                "%r scored %.6f while the lower input %r scored %.6f"
                % (stat, x, y, prev_x, prev_y))
        else:
            assert y <= prev_y + 1e-9, (
                "%s must pay AT MOST as much as the raw value rises (fewer "
                "points/yards allowed is the better outcome), but %r scored "
                "%.6f while the lower input %r scored %.6f"
                % (stat, x, y, prev_x, prev_y))
        prev_x, prev_y = x, y
