import warnings

import pytest

from sffl.weekly import DuplicateEntityWarning, load_weekly

FIXTURE = "tests/fixtures/weekly_sample.csv"
FIXTURE_BLANKS = "tests/fixtures/weekly_blanks.csv"
FIXTURE_DUPLICATE_ENTITY = "tests/fixtures/weekly_duplicate_entity.csv"
FIXTURE_SAME_NAME = "tests/fixtures/weekly_same_name_different_history.csv"


def test_reads_every_row():
    rows = load_weekly(FIXTURE)
    assert len(rows) == 5


def test_parses_identity_and_week():
    rows = load_weekly(FIXTURE)
    r = rows[0]
    assert r.player_id == "2185957"
    assert r.name == "Saquon Barkley"
    assert r.team == "PHI"
    assert r.pos == "RB"
    assert r.week == 3
    assert r.cbs_fpts == 0.0


def test_stats_are_floats_keyed_by_scoring_vocabulary():
    rows = load_weekly(FIXTURE)
    barkley_wk8 = [r for r in rows if r.player_id == "2185957" and r.week == 8][0]
    assert barkley_wk8.stats["rush_yds"] == 150.0
    assert barkley_wk8.stats["rec_ct"] == 4.0
    assert barkley_wk8.stats["rec_td"] == 1.0
    assert barkley_wk8.cbs_fpts == 19.0
    assert all(isinstance(v, float) for v in barkley_wk8.stats.values())


def test_cbs_fpts_is_not_inside_stats():
    # cbs_fpts is ground truth for comparison, never an input to scoring
    rows = load_weekly(FIXTURE)
    assert "cbs_fpts" not in rows[0].stats


def test_blank_stat_cells_become_zero():
    """Blank stat cells (empty or whitespace) should parse as 0.0."""
    rows = load_weekly(FIXTURE_BLANKS)
    assert len(rows) == 1
    r = rows[0]
    # Fixture has blank pass_cmp, pass_td, pass_int, rush_yds, rec_yds, and many others
    assert r.stats["pass_cmp"] == 0.0
    assert r.stats["pass_td"] == 0.0
    assert r.stats["pass_int"] == 0.0
    assert r.stats["rush_yds"] == 0.0
    assert r.stats["rec_yds"] == 0.0


def test_non_numeric_stat_cell_raises():
    """Non-numeric stat cells (garbage data) should raise ValueError with context."""
    # Create a simple CSV with a non-numeric stat value
    import tempfile
    import os

    csv_content = """player_id,name,team,pos,week,cbs_fpts,pass_cmp,pass_yds,pass_td,pass_int,rush_yds,rush_td,rec_ct,rec_yds,rec_td,xp_made,fg_u30,fg_30_39,fg_40_49,fg_50_59,fg_60,fg_missed,def_pa,def_ya,def_sack,def_int,def_fum_rec,def_td,def_safety
9999999,Test Player,NYG,QB,5,10,15,GARBAGE,2,0,5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"""

    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        os.write(fd, csv_content.encode())
        os.close(fd)
        with pytest.raises(ValueError) as exc_info:
            load_weekly(path)
        # Error message should contain column name, player_id, and week
        error_msg = str(exc_info.value)
        assert "pass_yds" in error_msg or "column=" in error_msg
        assert "9999999" in error_msg or "player_id=" in error_msg
        assert "week" in error_msg
        assert "GARBAGE" in error_msg
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_blank_week_raises():
    """Blank week should raise ValueError, not become week 0."""
    import tempfile
    import os

    csv_content = """player_id,name,team,pos,week,cbs_fpts,pass_cmp,pass_yds,pass_td,pass_int,rush_yds,rush_td,rec_ct,rec_yds,rec_td,xp_made,fg_u30,fg_30_39,fg_40_49,fg_50_59,fg_60,fg_missed,def_pa,def_ya,def_sack,def_int,def_fum_rec,def_td,def_safety
8888888,Test Player,NYG,QB,,10,15,200,2,0,5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"""

    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        os.write(fd, csv_content.encode())
        os.close(fd)
        with pytest.raises(ValueError) as exc_info:
            load_weekly(path)
        # Error message should indicate week is blank
        error_msg = str(exc_info.value)
        assert "week" in error_msg
        assert "blank" in error_msg
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_duplicate_entity_with_identical_stat_history_is_collapsed():
    """Two player_ids whose complete week-by-week stat history is
    byte-identical are the SAME ENTITY (this is exactly the real bug found
    in RB.csv/TQB.full.csv/WR.full.csv/DST.full.csv - see sffl.weekly's
    module docstring). load_weekly must collapse them to one id so a
    fit/holdout split (calibrate_eval.player_folds) can never separate a
    player's own weeks into two different folds.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rows = load_weekly(FIXTURE_DUPLICATE_ENTITY)

    ids = {r.player_id for r in rows}
    # 1001 and 2002 collapse to one; 3003 (a genuinely different, unrelated
    # player) survives untouched.
    assert ids == {"1001", "3003"}
    assert len([r for r in rows if r.player_id == "1001"]) == 3
    assert len([r for r in rows if r.player_id == "3003"]) == 1


def test_duplicate_entity_collapse_is_loud():
    """Collapsing must never be silent: a DuplicateEntityWarning fires,
    naming the file, the ids involved, and the player - a bare count is
    not enough (a human must be able to see WHO was collapsed).
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_weekly(FIXTURE_DUPLICATE_ENTITY)

    dup_warnings = [w for w in caught if issubclass(w.category, DuplicateEntityWarning)]
    assert len(dup_warnings) == 1
    msg = str(dup_warnings[0].message)
    assert FIXTURE_DUPLICATE_ENTITY in msg
    assert "Test Duplicate" in msg
    assert "1001" in msg
    assert "2002" in msg


def test_same_name_different_history_is_not_collapsed():
    """Two DIFFERENT real players who merely share a name and position must
    survive as two players. The test is identical STAT HISTORY, never
    identical name - real case: two players named Mike Williams, both WRs,
    on different teams, with different weekly lines.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rows = load_weekly(FIXTURE_SAME_NAME)

    ids = {r.player_id for r in rows}
    assert ids == {"4001", "5002"}
    assert len([r for r in rows if r.player_id == "4001"]) == 2
    assert len([r for r in rows if r.player_id == "5002"]) == 2

    dup_warnings = [w for w in caught if issubclass(w.category, DuplicateEntityWarning)]
    assert dup_warnings == []


def test_malformed_week_raises():
    """Malformed week (non-integer) should raise ValueError, not become week 0."""
    import tempfile
    import os

    csv_content = """player_id,name,team,pos,week,cbs_fpts,pass_cmp,pass_yds,pass_td,pass_int,rush_yds,rush_td,rec_ct,rec_yds,rec_td,xp_made,fg_u30,fg_30_39,fg_40_49,fg_50_59,fg_60,fg_missed,def_pa,def_ya,def_sack,def_int,def_fum_rec,def_td,def_safety
7777777,Test Player,NYG,QB,WEEK_FIVE,10,15,200,2,0,5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"""

    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        os.write(fd, csv_content.encode())
        os.close(fd)
        with pytest.raises(ValueError) as exc_info:
            load_weekly(path)
        # Error message should indicate week is malformed
        error_msg = str(exc_info.value)
        assert "week" in error_msg
        assert "WEEK_FIVE" in error_msg or "not a valid integer" in error_msg
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
