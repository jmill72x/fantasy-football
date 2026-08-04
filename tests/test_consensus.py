import pytest

from sffl.consensus import merge
from sffl.schema import PlayerProjection


def proj(name, source, set_name, **stats):
    return PlayerProjection(name=name, team="BUF", pos="TQB", source=source,
                            source_year=2026, games=17, stats=dict(stats),
                            raw_name=name, set_name=set_name)


def test_averages_across_sources():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0),
                 proj("Josh Allen", "fbg", "Hindery", rush_yds=690.0)])
    assert len(out) == 1
    assert out[0].stats["rush_yds"] == pytest.approx(650.0)
    assert out[0].stats["_n_sources"] == 2


def test_records_the_spread():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0),
                 proj("Josh Allen", "fbg", "Hindery", rush_yds=690.0)])
    assert out[0].stats["_spread_rush_yds"] == pytest.approx(40.0)


def test_single_source_has_zero_spread():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0)])
    assert out[0].stats["_spread_rush_yds"] == pytest.approx(0.0)
    assert out[0].stats["_n_sources"] == 1


def test_missing_stat_in_one_source_counts_as_absent_not_zero():
    # Only one source reports rec_yds; averaging must not halve it.
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0, rec_yds=40.0),
                 proj("Josh Allen", "fbg", "B", rush_yds=600.0)])
    assert out[0].stats["rec_yds"] == pytest.approx(40.0)


def test_different_players_are_kept_apart():
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0),
                 proj("Lamar Jackson", "fbg", "A", rush_yds=800.0)])
    assert len(out) == 2


def test_games_is_averaged_too():
    a = proj("Josh Allen", "fbg", "A", rush_yds=600.0)
    b = proj("Josh Allen", "fbg", "B", rush_yds=600.0)
    b.games = 15
    out = merge([a, b])
    assert out[0].games == pytest.approx(16.0)
