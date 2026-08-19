from sffl.ingest.profiles import load_profile, read_extract

PROFILE = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_sample.csv"


def test_profile_is_index_based():
    p = load_profile(PROFILE)
    assert p.name == "draftsharks"
    assert p.by_index is True
    assert p.columns["pass_cmp"] == 8


def test_reads_all_rows():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    assert len(rows) == 4
    assert {r.pos for r in rows} == {"QB", "RB", "WR", "DST"}


def test_quarterback_stats_land_in_the_right_slots():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    allen = [r for r in rows if r.name == "Josh Allen"][0]
    assert allen.team == "BUF"
    assert allen.games == 17
    assert allen.stats["pass_yds"] == 3500.0
    assert allen.stats["pass_cmp"] == 300.0
    assert allen.stats["rush_yds"] == 400.0
    assert allen.stats["rush_td"] == 5.0


def test_defense_position_is_canonicalized():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    d = [r for r in rows if r.pos == "DST"][0]
    assert d.stats["def_pa"] == 280
    assert d.stats["def_sack"] == 35


def test_blank_cells_become_zero_not_crash():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    for r in rows:
        for v in r.stats.values():
            assert isinstance(v, float)
