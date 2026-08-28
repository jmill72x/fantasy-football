import pytest
from sffl.cbs_weekly import parse

FIXTURE = "tests/fixtures/cbs_weekly_rbwrte.txt"


def by_name(rows):
    return dict((r.name, r) for r in rows)


def test_every_line_parses_and_nothing_is_silently_dropped():
    rows = parse(FIXTURE, group="RB-WR-TE", week=1)
    assert len(rows) == 8


def test_stats_land_in_the_right_slots():
    r = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))["Braelon Allen"]
    assert r.pos == "RB" and r.team == "NYJ"
    assert r.stats["rush_yds"] == 36.8
    assert r.stats["rush_td"] == 0.4
    assert r.stats["rec_ct"] == 0.9
    assert r.stats["rec_yds"] == 7.9
    assert r.stats["fum_lost"] == 0.2


def test_a_non_numeric_expert_rank_does_not_shift_the_stat_block():
    """EXPERT is 'N/R' for unranked players. Counting fields from the LEFT
    would shift every stat after it by one and produce a plausible wrong line."""
    r = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))["Elic Ayomanor"]
    assert r.stats["rec_ct"] == 2.6
    assert r.stats["rec_yds"] == 36.0
    assert r.stats["rush_yds"] == 0.0


def test_a_multi_word_suffixed_name_parses():
    rows = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))
    assert "Harold Fannin Jr." in rows
    assert "Tyrone Tracy Jr." in rows


def test_every_row_is_one_week_not_a_season():
    for r in parse(FIXTURE, group="RB-WR-TE", week=1):
        assert r.games == 1.0


def test_a_line_whose_stat_block_is_the_wrong_width_raises(tmp_path):
    """The layout is positional. A changed column count must fail loudly, the
    same discipline `expect_columns` enforces on the auction extracts."""
    bad = tmp_path / "bad.txt"
    bad.write_text("W (9/16) Someone Short RB • NYJ @TEN 17 13 25 1 55 9.5 36.8\n")
    with pytest.raises(ValueError, match="expected 11"):
        parse(str(bad), group="RB-WR-TE", week=1)


def test_an_unknown_group_names_the_groups_that_exist(tmp_path):
    with pytest.raises(ValueError, match="RB-WR-TE"):
        parse(FIXTURE, group="PUNTERS", week=1)


def test_the_stat_block_is_found_even_when_the_preamble_is_a_different_width(tmp_path):
    """The real discriminator between reading from the right and assuming a
    fixed offset from the left. In the captured fixture every preamble is the
    same width - `N/R` is one token exactly like a numeric rank - so a parser
    hardcoding `tokens[6:]` reads it identically and the N/R test cannot tell
    the two apart. A row with a SHORTER preamble can. Constructed by hand, not
    captured, which is why it lives here and not in the fixture file."""
    short = tmp_path / "short_preamble.txt"
    # Same trailing 11-column stat block as Braelon Allen, but the preamble
    # carries four tokens instead of six.
    short.write_text(
        "W (9/16) Braelon Allen RB • NYJ @TEN 17 13 25 "
        "9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70\n")
    rows = parse(str(short), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].stats["rush_yds"] == 36.8
    assert rows[0].stats["rec_ct"] == 0.9
    assert rows[0].stats["fum_lost"] == 0.2
