import pytest

from sffl.ingest.profiles import load_profile, read_extract
from sffl.league import load_league
from sffl.scoring import band_points, sack_points, score_game

PROFILE = "leagues/sffl/2026.yaml"
DS_PROFILE = "sources/draftsharks.yaml"
DS_FIXTURE = "tests/fixtures/draftsharks_sample.csv"


@pytest.fixture(scope="module")
def lg():
    return load_league(PROFILE)


def test_band_boundaries_inclusive(lg):
    t = lg.bands["rec_yds"]
    assert band_points(t, 49) == 0     # below the floor
    assert band_points(t, 50) == 1     # first band, lower edge
    assert band_points(t, 74) == 1     # first band, upper edge
    assert band_points(t, 75) == 2     # next band
    assert band_points(t, 200) == 7
    assert band_points(t, 999) == 7


def test_reception_floor(lg):
    t = lg.bands["rec_ct"]
    assert band_points(t, 4) == 0
    assert band_points(t, 5) == 2
    assert band_points(t, 13) == 7


def test_fractional_values_between_integer_band_edges(lg):
    """Per-game rates are fractional; the integer band edges must not gap.

    rec_ct bands are [5,6], [7,8], [9,10], [11,12], [13,99]. A rate of 6.18
    catches per game sits between the first two bands. It must score the
    first band whose high clears it, not fall through to the floor.
    """
    t = lg.bands["rec_ct"]
    assert band_points(t, 4.9) == 0     # still below the hard floor
    assert band_points(t, 5.0) == 2
    assert band_points(t, 6.18) == 3    # was 0: fell between [5,6] and [7,8]
    assert band_points(t, 8.5) == 4
    assert band_points(t, 10.9) == 6
    assert band_points(t, 12.1) == 7
    assert band_points(t, 150) == 7     # above every high


def test_band_points_has_no_gaps_above_the_floor(lg):
    """No value at or above a table's floor may fall through to 0.

    Every band table is swept at tenth-of-a-unit resolution - the resolution
    per-game rates actually arrive at. Above the floor the result must always
    be a value the table declares, and must move monotonically in whatever
    direction that table's points run (offensive tables reward more; def_pa
    and def_ya penalize more).
    """
    for key, table in lg.bands.items():
        declared = [pts for _, _, pts in table]
        ascending = declared[-1] >= declared[0]
        low, top = table[0][0], table[-1][1]
        prev = None
        v = low
        while v <= min(top, low + 600):
            pts = band_points(table, v)
            assert pts in declared, "%s: %s fell outside every band" % (key, v)
            if prev is not None:
                if ascending:
                    assert pts >= prev, "%s went backwards at %s" % (key, v)
                else:
                    assert pts <= prev, "%s went forwards at %s" % (key, v)
            prev = pts
            v = round(v + 0.1, 1)
        assert band_points(table, top + 1000) == declared[-1]


def test_sack_rule(lg):
    r = lg.sack_rule
    assert sack_points(r, 0) == 0
    assert sack_points(r, 2) == 0
    assert sack_points(r, 3) == 3
    assert sack_points(r, 4) == 4
    assert sack_points(r, 7) == 7


# Golden file: Eagles DST 2025 weeks 13-17, stat lines and the points CBS awarded.
DST_GOLDEN = [
    (dict(def_pa=24, def_ya=425, def_int=1, def_sack=2), 0),
    (dict(def_pa=22, def_ya=275, def_int=1, def_fum_rec=2, def_sack=7), 13),
    (dict(def_pa=0, def_ya=75, def_int=1, def_sack=4), 17),
    (dict(def_pa=18, def_ya=220, def_int=1, def_sack=2), 5),
    (dict(def_pa=12, def_ya=331, def_fum_rec=1, def_sack=5), 10),
]


@pytest.mark.parametrize("pos", [None, "DST"])
@pytest.mark.parametrize("stats,expected", DST_GOLDEN)
def test_dst_matches_real_cbs_output(lg, stats, expected, pos):
    assert score_game(lg, stats, pos=pos) == expected


def test_receiving_game(lg):
    # 6 catches (band 5-6 = 2), 85 yards (band 75-99 = 2)
    assert score_game(lg, dict(rec_ct=6, rec_yds=85)) == 4


def test_below_all_floors_scores_zero(lg):
    assert score_game(lg, dict(rec_ct=3, rec_yds=40, rush_yds=30)) == 0


def test_kicking(lg):
    # 2 XP + one 45-yarder (4) + one 55-yarder (5) + one miss (-1)
    assert score_game(lg, dict(xp_made=2, fg_40_49=1, fg_50_59=1, fg_missed=1)) == 10


def test_dense_wr_row_from_real_ingest_scores_no_phantom_defense_points(lg):
    """Regression for a real bug: every ingest profile maps def_pa/def_ya onto
    EVERY row regardless of position, defaulting to 0.0 for non-defenses. 0
    sits in the top band for both def_pa ([0,2,6]) and def_ya ([0,150,6]), so
    checking key presence alone ("def_pa" in stats) awarded every skill
    player +12 phantom points per game. Hand-built sparse stat dicts (as used
    elsewhere in this file) cannot catch this, since they simply omit the
    def_ keys - real ingest output is dense and always includes them at 0.
    This test builds from actual read_extract output to exercise that.
    """
    profile = load_profile(DS_PROFILE)
    rows = read_extract(profile, DS_FIXTURE, 2026)
    wr = next(r for r in rows if r.pos == "WR")

    # Sanity: ingest really does map def_pa/def_ya onto this WR row at 0.0 -
    # this is the dense-stat-dict condition the bug depended on.
    assert wr.stats.get("def_pa") == 0.0
    assert wr.stats.get("def_ya") == 0.0

    per_game = {f: v / wr.games for f, v in wr.stats.items()}
    scored_with_pos = score_game(lg, per_game, pos="WR")
    # The same dense dict with the def_ keys stripped out entirely is the
    # ground truth for "no defense points included."
    skill_only = {f: v for f, v in per_game.items() if not f.startswith("def_")}
    expected = score_game(lg, skill_only, pos="WR")

    assert scored_with_pos == expected

    # The legacy key-presence fallback (pos=None) is exactly the bug this
    # guards against: with the same dense dict it awards 12 phantom points
    # (def_pa=0 -> top band 6, def_ya=0 -> top band 6) that pos="WR" must not.
    scored_legacy_fallback = score_game(lg, per_game)
    assert scored_legacy_fallback - scored_with_pos == 12
