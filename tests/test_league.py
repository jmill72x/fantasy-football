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
