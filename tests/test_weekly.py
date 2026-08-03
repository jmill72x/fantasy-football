from sffl.weekly import load_weekly

FIXTURE = "tests/fixtures/weekly_sample.csv"


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
