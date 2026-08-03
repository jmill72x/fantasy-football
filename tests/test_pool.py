import pytest

from sffl import pool as pool_module
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
    Draft Sharks fixture projects the Eagles at 42 sacks over 17 games, or
    2.47 a game, so `sack_points` returns 0 and the unit collects NONE of its
    largest projected category. Under a weekly distribution the true
    expectation is roughly 30 points of the unit's ~92.

    Do NOT "fix" this by special-casing sacks - the averaging approximation
    is deliberate and documented in `score_season`. This test exists so the
    weekly distribution model that replaces it has to change this assertion
    deliberately and visibly, rather than moving DST valuations by accident.
    """
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    dst = next(p for p in pool if p.pos == "DST")
    assert dst.stats["def_sack"] == 42 and dst.games == 17   # 2.47 a game

    without_sacks = PlayerProjection(
        name=dst.name, team=dst.team, pos=dst.pos, source=dst.source,
        source_year=dst.source_year, games=dst.games, raw_name=dst.raw_name,
        stats=dict(dst.stats, def_sack=0))

    # 42 sacks and 0 sacks are worth precisely the same season score.
    assert score_season(LG, dst) == score_season(LG, without_sacks)

    # Not because the whole unit scores 0 - it scores ~92 points of pass-
    # allowed, yards-allowed, turnover and touchdown production. The sacks
    # alone vanish.
    assert score_season(LG, dst) == pytest.approx(92)


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
