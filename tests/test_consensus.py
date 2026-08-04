import pytest

from sffl.consensus import merge
from sffl.schema import PlayerProjection
from sffl.identity import Resolver


def proj(name, source, set_name, **stats):
    return PlayerProjection(name=name, team="BUF", pos="TQB", source=source,
                            source_year=2026, games=17, stats=dict(stats),
                            raw_name=name, set_name=set_name)


def proj_with_team_pos(name, source, set_name, team, pos, **stats):
    return PlayerProjection(name=name, team=team, pos=pos, source=source,
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


def test_per_stat_source_count_with_missing_stat():
    # One source reports rec_yds, the other doesn't. _n_sources is 2,
    # but _n_rec_yds is 1. This disambiguates zero spread from disagreement.
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0, rec_yds=40.0),
                 proj("Josh Allen", "fbg", "B", rush_yds=600.0)])
    assert out[0].stats["_n_sources"] == 2.0
    assert out[0].stats["_n_rec_yds"] == 1.0
    assert out[0].stats["_spread_rec_yds"] == pytest.approx(0.0)
    assert out[0].stats["_n_rush_yds"] == 2.0


def test_per_stat_source_count_with_spread():
    # Both sources report rush_yds with different values.
    # _n_rush_yds is 2, spread is nonzero, indicating true disagreement.
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0),
                 proj("Josh Allen", "fbg", "B", rush_yds=700.0)])
    assert out[0].stats["_n_sources"] == 2.0
    assert out[0].stats["_n_rush_yds"] == 2.0
    assert out[0].stats["_spread_rush_yds"] == pytest.approx(50.0)


def test_resolver_merges_aliased_spellings():
    # Test that resolver parameter actually exercises the resolver branch,
    # not just p.key(). Use different spellings from aliases.yaml.
    # Without resolver: "Jamaar Chase" and "Ja'Marr Chase" have different keys.
    # With resolver: the alias resolves both to the same canonical key.

    a = proj_with_team_pos("Jamaar Chase", "src1", "A", team="KC", pos="WR",
                           rec_yds=100.0)
    b = proj_with_team_pos("Ja'Marr Chase", "src2", "B", team="KC", pos="WR",
                           rec_yds=110.0)

    # Without resolver: different spellings produce different keys, so 2 records.
    out_no_resolver = merge([a, b])
    assert len(out_no_resolver) == 2, (
        "Without resolver, different spellings must not merge"
    )

    # With resolver: aliases.yaml resolves "Jamaar Chase" -> "Ja'Marr Chase",
    # both map to the same canonical key, so they merge into 1 record.
    resolver = Resolver(alias_path="identity/aliases.yaml")
    resolver.register(["jamarr chase|KC|WR"])
    out_with_resolver = merge([a, b], resolver=resolver)
    assert len(out_with_resolver) == 1, (
        "With resolver, aliased spellings must merge"
    )
    assert out_with_resolver[0].stats["rec_yds"] == pytest.approx(105.0)
    assert out_with_resolver[0].stats["_n_sources"] == 2.0
