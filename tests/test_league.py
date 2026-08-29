import copy

import pytest
import yaml

from sffl.league import LeagueProfile, load_league

PROFILE = "leagues/sffl/2026.yaml"


def _raw():
    with open(PROFILE) as fh:
        return yaml.safe_load(fh)


def test_loads_structure():
    lg = load_league(PROFILE)
    assert lg.teams == 12
    assert lg.budget == 110
    assert lg.roster_size == 13
    assert lg.flex_slots == 5


def test_total_capital_and_surplus():
    lg = load_league(PROFILE)
    assert lg.total_capital() == 1320
    assert lg.total_spots() == 156
    assert lg.surplus() == 1164


def test_bands_are_tuples_of_three_ints():
    lg = load_league(PROFILE)
    for name, table in lg.bands.items():
        for row in table:
            assert len(row) == 3, name
            assert all(isinstance(v, int) for v in row), name


def test_sack_rule_present():
    lg = load_league(PROFILE)
    assert lg.sack_rule["threshold"] == 3
    assert lg.sack_rule["threshold_points"] == 3
    assert lg.sack_rule["per_sack_after"] == 1


def test_flat_priced_pools_loads_configured_value():
    lg = load_league(PROFILE)
    assert lg.flat_priced_pools == {"K": 1.0, "DST": 1.0}


def test_flat_priced_pools_rejects_an_unknown_pool_name():
    # A typo like "KK" for "K" must not silently revert kickers to real
    # pricing with no error - it must be caught at load time.
    raw = copy.deepcopy(_raw())
    raw["flat_priced_pools"] = {"KK": 1}
    with pytest.raises(ValueError, match="KK"):
        LeagueProfile(raw)


def test_flat_priced_pools_rejects_a_non_dollar_price():
    # A flat price other than $1 would silently overspend the league budget,
    # because surplus() assumes every roster spot costs exactly $1.
    raw = copy.deepcopy(_raw())
    raw["flat_priced_pools"] = {"K": 3, "DST": 3}
    with pytest.raises(ValueError, match="only a flat price of exactly 1"):
        LeagueProfile(raw)


def test_the_lineup_slots_are_explicit_and_ordered():
    lg = load_league(PROFILE)
    assert lg.lineup == [
        ("TQB", ("TQB",)),
        ("RB", ("RB",)),
        ("WR/TE", ("WR", "TE")),
        ("FLEX1", ("RB", "WR", "TE")),
        ("FLEX2", ("RB", "WR", "TE")),
        ("FLEX3", ("RB", "WR", "TE")),
        ("K", ("K",)),
        ("DST", ("DST",)),
    ]


def test_the_slot_list_must_agree_with_the_starter_and_flex_counts():
    """starters and flex_slots existed first and are used by the auction path.
    Two sources of truth for the same fact drift; this makes them fail loudly."""
    lg = load_league(PROFILE)
    assert len(lg.lineup) == lg.starters
    flex = [s for s, elig in lg.lineup if set(elig) & {"RB", "WR", "TE"}]
    assert len(flex) == lg.flex_slots


def test_a_lineup_that_disagrees_with_the_starter_count_is_rejected():
    """The guard, not the fixture. The checked-in YAML is self-consistent, so a
    test that only reads it would pass with this validation deleted."""
    raw = yaml.safe_load(open(PROFILE))
    raw["lineup"] = raw["lineup"][:-1]          # 7 slots against starters: 8
    with pytest.raises(ValueError, match="starters is 8"):
        LeagueProfile(raw)


def test_a_lineup_that_disagrees_with_the_flex_count_is_rejected():
    raw = yaml.safe_load(open(PROFILE))
    for entry in raw["lineup"]:
        if entry["slot"] == "FLEX3":
            entry["eligible"] = ["TQB"]         # 4 flex-eligible against flex_slots: 5
    with pytest.raises(ValueError, match="flex_slots is 5"):
        LeagueProfile(raw)


def test_a_lineup_slot_naming_an_unknown_position_is_rejected():
    """Built from the parsed dict, not by string-replacing the YAML: the file
    is column-aligned, and a test that depends on its incidental whitespace
    breaks the next time someone reformats it."""
    raw = yaml.safe_load(open(PROFILE))
    raw["lineup"] = [{"slot": "K", "eligible": ["PUNTER"]}]
    with pytest.raises(ValueError, match="PUNTER"):
        LeagueProfile(raw)
