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
    same discipline `expect_columns` enforces on the auction extracts.

    This line is short enough (8 tokens after the team code) that
    `expect_tokens` (the whole-segment check - see C1) now catches it before
    the trailing-block-width check below ever runs, with a more specific
    message naming the full expected width rather than just the stat
    block's."""
    bad = tmp_path / "bad.txt"
    bad.write_text("W (9/16) Someone Short RB • NYJ @TEN 17 13 25 1 55 9.5 36.8\n")
    with pytest.raises(ValueError, match="expected 17"):
        parse(str(bad), group="RB-WR-TE", week=1)


def test_an_unknown_group_names_the_groups_that_exist(tmp_path):
    with pytest.raises(ValueError, match="RB-WR-TE"):
        parse(FIXTURE, group="PUNTERS", week=1)


def test_a_short_preamble_now_raises_instead_of_being_silently_tolerated(tmp_path):
    """Before C1's `expect_tokens` fix, right-anchored slicing was the ONLY
    defence this parser had: `N/R` is one token exactly like a numeric rank,
    so a parser hardcoding `tokens[6:]` and one reading `tokens[-11:]` agreed
    on every captured row, and only a row with a genuinely narrower preamble
    (constructed by hand below, never captured) could tell them apart - that
    row used to parse successfully, on the reasoning that a shorter preamble
    was a shape right-anchoring should tolerate.

    C1 changed that reasoning: a preamble this short IS a shifted layout -
    exactly the "column removed" case C1 names - so it must now be refused
    up front by `expect_tokens`, not silently parsed by the trailing slice.
    Right-anchoring is still what finds the block on a line of the CORRECT
    width (see the N/R test above); it no longer has to also cover widths
    that are wrong."""
    short = tmp_path / "short_preamble.txt"
    # Same trailing 11-column stat block as Braelon Allen, but the preamble
    # carries four tokens instead of six - 15 total, not the required 17.
    short.write_text(
        "W (9/16) Braelon Allen RB • NYJ @TEN 17 13 25 "
        "9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70\n")
    with pytest.raises(ValueError, match="expected 17"):
        parse(str(short), group="RB-WR-TE", week=1)


def test_a_column_appended_after_the_stat_block_raises(tmp_path):
    """CRITICAL: block = tokens[-len(fields):] always returns exactly 11
    tokens whenever the line has at least 11 - so appending one column to a
    real, well-formed line does NOT trip the block-width check. It just
    reads a different, still-plausible 11 columns, shifted by one: this
    exact line, unpatched, reads rush_yds as 3.9 (was 36.8) and rec_ct as
    7.9 (was 0.9) - the precise silent misread C1 names. expect_tokens
    catches it by checking the WHOLE post-team segment, not just the
    trailing slice."""
    bad = tmp_path / "extra_column.txt"
    # Braelon Allen's real line (17 tokens after the team code) with one
    # extra trailing token - simulates CBS appending a new column.
    bad.write_text(
        "W (9/16) Braelon Allen RB • NYJ @TEN 17 13 25 1 55 "
        "9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70 99\n")
    with pytest.raises(ValueError, match="18"):
        parse(str(bad), group="RB-WR-TE", week=1)


def test_a_column_removed_from_the_stat_block_raises(tmp_path):
    """The other direction: dropping the trailing column still leaves 16
    tokens, well over the 11 the trailing slice needs, so the old
    block-width check could not see this shift either - it would silently
    read EXPERT (55) as rush_att and shift every other field by one."""
    bad = tmp_path / "missing_column.txt"
    # Braelon Allen's real line (17 tokens after the team code) with the
    # trailing column dropped.
    bad.write_text(
        "W (9/16) Braelon Allen RB • NYJ @TEN 17 13 25 1 55 "
        "9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2\n")
    with pytest.raises(ValueError, match="16"):
        parse(str(bad), group="RB-WR-TE", week=1)
