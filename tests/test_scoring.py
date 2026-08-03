import pytest

from sffl.league import load_league
from sffl.scoring import band_points, sack_points, score_game

PROFILE = "leagues/sffl/2026.yaml"


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


@pytest.mark.parametrize("stats,expected", DST_GOLDEN)
def test_dst_matches_real_cbs_output(lg, stats, expected):
    assert score_game(lg, stats) == expected


def test_receiving_game(lg):
    # 6 catches (band 5-6 = 2), 85 yards (band 75-99 = 2)
    assert score_game(lg, dict(rec_ct=6, rec_yds=85)) == 4


def test_below_all_floors_scores_zero(lg):
    assert score_game(lg, dict(rec_ct=3, rec_yds=40, rush_yds=30)) == 0


def test_kicking(lg):
    # 2 XP + one 45-yarder (4) + one 55-yarder (5) + one miss (-1)
    assert score_game(lg, dict(xp_made=2, fg_40_49=1, fg_50_59=1, fg_missed=1)) == 10
