from sffl.league import load_league

PROFILE = "leagues/sffl/2026.yaml"


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
