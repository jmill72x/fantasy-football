import pytest

from sffl.league import load_league
from sffl.pool import build_pool, score_season
from sffl.schema import PlayerProjection

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
