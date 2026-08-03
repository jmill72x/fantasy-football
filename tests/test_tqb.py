import pytest

from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.tqb import build_tqb

LG = load_league("leagues/sffl/2026.yaml")


def qb(name, team, games, pass_yds, pass_cmp, pass_td, rush_yds, set_name=None):
    return PlayerProjection(
        name=name, team=team, pos="QB", source="test", source_year=2026,
        games=games,
        stats=dict(pass_yds=pass_yds, pass_cmp=pass_cmp, pass_td=pass_td,
                   pass_int=0.0, rush_yds=rush_yds, rush_td=0.0),
        raw_name=name, set_name=set_name,
    )


def test_single_qb_franchise():
    out = build_tqb(LG, [qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145)])
    assert len(out) == 1
    t = out[0]
    assert t.pos == "TQB"
    assert t.name == "CIN"
    assert t.team == "CIN"
    assert t.stats["pass_yds"] == 4690


def test_multi_qb_franchise_sums_stats():
    out = build_tqb(LG, [
        qb("Deshaun Watson", "CLE", 9, 1920, 177, 11, 161),
        qb("Shedeur Sanders", "CLE", 6, 1280, 113, 7, 67),
        qb("Dillon Gabriel", "CLE", 1, 205, 19, 1, 10),
    ])
    assert len(out) == 1
    t = out[0]
    assert t.stats["pass_yds"] == 3405
    assert t.stats["pass_cmp"] == 309
    assert t.games == 16      # summed franchise starts, capped at 17


def test_games_capped_at_seventeen():
    out = build_tqb(LG, [
        qb("A", "NYJ", 12, 3000, 250, 20, 100),
        qb("B", "NYJ", 9, 2000, 170, 12, 50),
    ])
    assert out[0].games == 17


def test_only_the_requested_set_is_used():
    players = [
        qb("Josh Allen", "BUF", 17, 4010, 349, 29, 610, set_name="Consensus"),
        qb("Josh Allen", "BUF", 17, 4180, 360, 31, 690, set_name="Dan Hindery"),
    ]
    out = build_tqb(LG, players, set_name="Dan Hindery")
    assert len(out) == 1
    assert out[0].stats["rush_yds"] == 690


def test_non_quarterbacks_are_ignored():
    players = [
        qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145),
        PlayerProjection(name="Ja'Marr Chase", team="CIN", pos="WR", source="test",
                         source_year=2026, games=17, stats=dict(rec_yds=1587),
                         raw_name="Ja'Marr Chase"),
    ]
    out = build_tqb(LG, players)
    assert len(out) == 1
    assert "rec_yds" not in out[0].stats


def test_qb_extraneous_fields_are_dropped():
    """QB record with non-passing/rushing stat key has that key dropped."""
    players = [
        PlayerProjection(
            name="Joe Burrow", team="CIN", pos="QB", source="test",
            source_year=2026, games=17,
            stats=dict(pass_yds=4690, pass_cmp=428, pass_td=37, pass_int=0.0,
                       rush_yds=145, rush_td=0.0, rec_yds=50),  # rec_yds is extraneous
            raw_name="Joe Burrow", set_name=None,
        ),
    ]
    out = build_tqb(LG, players)
    assert len(out) == 1
    assert out[0].stats["pass_yds"] == 4690
    assert "rec_yds" not in out[0].stats


def test_multi_set_data_raises_without_set_name():
    """Calling build_tqb with set_name=None on multi-set data raises ValueError."""
    players = [
        qb("Josh Allen", "BUF", 17, 4010, 349, 29, 610, set_name="Consensus"),
        qb("Josh Allen", "BUF", 17, 4180, 360, 31, 690, set_name="Dan Hindery"),
    ]
    with pytest.raises(ValueError) as exc_info:
        build_tqb(LG, players, set_name=None)
    assert "Consensus" in str(exc_info.value)
    assert "Dan Hindery" in str(exc_info.value)


def test_non_franchise_team_code_is_excluded():
    """A vendor's "FA" (free agent) QB must not become a phantom 33rd TQB.

    A downstream component ranks TQB units 1-32 to find replacement level; a
    phantom franchise shifts every real team's ordinal rank wherever it
    outscores them.
    """
    out = build_tqb(LG, [
        qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145),
        qb("Some Journeyman", "FA", 8, 1500, 130, 8, 40),
    ])
    assert len(out) == 1
    assert [t.team for t in out] == ["CIN"]


def test_single_set_data_works_with_set_name_none():
    """Single-set source (all set_name=None) works with set_name=None."""
    players = [
        qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145, set_name=None),
        qb("Jake Browning", "CIN", 0, 0, 0, 0, 0, set_name=None),
    ]
    out = build_tqb(LG, players, set_name=None)
    assert len(out) == 1
    assert out[0].stats["pass_yds"] == 4690
