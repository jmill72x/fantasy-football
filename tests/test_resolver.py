from sffl.identity import Resolver, player_key

ALIASES = "identity/aliases.yaml"


def make():
    r = Resolver(ALIASES)
    r.register([
        player_key("Cameron Ward", "TEN", "QB"),
        player_key("Ja'Marr Chase", "CIN", "WR"),
        player_key("Jahmyr Gibbs", "DET", "RB"),
        player_key("Brandon Aiyuk", "SF", "WR"),
    ])
    return r


def test_exact_match_after_normalization():
    r = make()
    assert r.resolve("Ja'Marr Chase", "CIN", "WR") == player_key("Ja'Marr Chase", "CIN", "WR")


def test_alias_file_resolves_cam_ward():
    r = make()
    assert r.resolve("Cam Ward", "TEN", "qb") == player_key("Cameron Ward", "TEN", "QB")


def test_alias_handles_missing_space():
    r = make()
    assert r.resolve("BRANDONAIYUK", "SF", "WR") == player_key("Brandon Aiyuk", "SF", "WR")


def test_fuzzy_match_catches_a_typo():
    r = make()
    got = r.resolve("Jahmyr Gibs", "DET", "RB")
    assert got == player_key("Jahmyr Gibbs", "DET", "RB")


def test_unknown_player_is_reported_not_dropped():
    r = make()
    got = r.resolve("Completely Unknown Person", "XXX", "WR")
    assert got is None
    assert len(r.unresolved) == 1
    name, team, pos, candidates = r.unresolved[0]
    assert name == "Completely Unknown Person"
    assert isinstance(candidates, list)
