import pytest
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


def test_a_narrower_export_is_refused_rather_than_read_off_by_one(tmp_path):
    """A by_index profile reads stats by POSITION.

    Drop one column and every stat after it shifts: the run completes, names
    and teams look right, and the yardage belongs to a different category.
    There is no error to notice - only a plausible wrong board - so the width
    is checked up front.
    """
    import csv as _csv
    src = list(_csv.reader(open(FIXTURE, newline="")))
    narrowed = str(tmp_path / "narrow.csv")
    with open(narrowed, "w", newline="") as fh:
        _csv.writer(fh).writerows([row[:-1] for row in src])
    with pytest.raises(ValueError, match="maps stats by POSITION"):
        read_extract(load_profile(PROFILE), narrowed, 2026)


def test_a_renamed_header_still_loads_because_only_the_width_is_checked():
    """Draft Sharks renamed "3D Proj" to "DS Proj" mid-preseason 2026 with the
    layout unchanged. A header hash would have refused a perfectly good file,
    so the guard deliberately checks width alone."""
    import csv as _csv
    import tempfile, os
    src = list(_csv.reader(open(FIXTURE, newline="")))
    src[0] = ["DS " + c[3:] if c.startswith("3D ") else c for c in src[0]]
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="") as fh:
        _csv.writer(fh).writerows(src)
    try:
        rows = read_extract(load_profile(PROFILE), path, 2026)
        assert rows, "a renamed header must still load"
    finally:
        os.unlink(path)
