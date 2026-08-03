from sffl.ingest.profiles import load_profile, read_extract

PROFILE = "sources/footballguys.yaml"
FIXTURE = "tests/fixtures/footballguys_sample.csv"


def rows():
    return read_extract(load_profile(PROFILE), FIXTURE, 2026)


def test_profile_is_name_based():
    p = load_profile(PROFILE)
    assert p.by_index is False
    assert p.columns["pass_cmp"] == "pass-cmp"
    assert p.capabilities["multi_set"] is True


def test_reads_every_set_row():
    r = rows()
    assert len(r) == 5
    assert {x.set_name for x in r} == {"Consensus", "Dan Hindery"}


def test_same_player_appears_once_per_set():
    allen = [x for x in rows() if x.name == "Josh Allen"]
    assert len(allen) == 2
    by_set = {x.set_name: x.stats["rush_yds"] for x in allen}
    assert by_set["Consensus"] == 610.0
    assert by_set["Dan Hindery"] == 690.0


def test_lowercase_positions_are_canonicalized():
    r = rows()
    assert {x.pos for x in r} == {"QB", "WR", "DST"}


def test_two_point_conversions_are_captured():
    allen = [x for x in rows() if x.name == "Josh Allen"
             and x.set_name == "Consensus"][0]
    assert allen.stats["pass_2pt"] == 1.2
    assert allen.stats["rush_2pt"] == 0.4


def test_defense_safety_is_captured():
    d = [x for x in rows() if x.pos == "DST"][0]
    assert d.stats["def_safety"] == 1.0
    assert d.stats["def_ya"] == 5010.0
