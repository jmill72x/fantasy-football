import pytest
from sffl.cbs_weekly import (build_line_re, classify_avail, classify_avail_tab,
                              parse)

FIXTURE = "tests/fixtures/cbs_weekly_rbwrte.txt"
TAB_FIXTURE = "tests/fixtures/cbs_weekly_tab_rbwrte.txt"


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


def test_a_line_without_a_leading_status_token_raises_naming_the_count(tmp_path):
    """F4, the real observed bug: 'DJ Moore WR • CHI ...' has no leading
    avail token. Before the fix this silently mis-parsed as name='Moore',
    avail='DJ' - the two-initial first name swallowed as if it were a
    status - attributing Moore's real stats to a fabricated 'Moore' while
    the true 'DJ Moore' printed as 'no projection'. After tightening the
    avail group so a bare two-letter token can no longer match, this line
    fails `_LINE` entirely - and since it still looks like a player row
    (contains ' • '), parse() must refuse the whole page rather than drop
    it silently."""
    bad = tmp_path / "no_token.txt"
    bad.write_text(
        "DJ Moore WR • CHI @LAR 22 11 86 63 8 "
        "0.4 0.8 2.0 0.1 7.7 5.2 46.5 8.9 0.5 0.1 4.81\n")
    with pytest.raises(ValueError, match="1 line"):
        parse(str(bad), group="RB-WR-TE", week=1)


def test_dj_moore_parses_correctly_with_a_leading_status_token(tmp_path):
    """The other side of F4's fix: a two-initial name is not itself the
    problem - DJ Moore parses under his real, full name once a genuine
    status token precedes it, and that token is captured as `avail`."""
    ok = tmp_path / "with_token.txt"
    ok.write_text(
        "FA DJ Moore WR • CHI @LAR 22 11 86 63 8 "
        "0.4 0.8 2.0 0.1 7.7 5.2 46.5 8.9 0.5 0.1 4.81\n")
    rows = parse(str(ok), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].name == "DJ Moore"
    assert rows[0].avail == "FA"


def test_classify_avail_recognizes_free_agent_and_waiver_as_available():
    assert classify_avail("FA", []) == "available"
    assert classify_avail("W", []) == "available"
    assert classify_avail("W (9/16)", []) == "available"


def test_classify_avail_no_longer_infers_owned_from_bare_letter_shape():
    """Superseded by the enumerated-owner-codes design below. `classify_avail`
    used to treat any bare, letters-only token of 3+ characters as "owned" by
    SHAPE alone; that is exactly the looseness F4 exists to forbid, so a bare
    token not present in `owner_codes` must now come back None rather than
    "owned", even though "DAL" looks exactly like a team abbreviation."""
    assert classify_avail("DAL", []) is None
    assert classify_avail("DAL", ["DAL"]) == "owned"


def test_classify_avail_refuses_to_guess_an_unfamiliar_shape():
    """A parenthetical status other than 'W (...)' - e.g. an injury flag -
    is a shape this page has not been observed to produce. Guessing which
    bucket it belongs in is the mistake F3 exists to prevent."""
    assert classify_avail("IR (Q)", []) is None


CODES = ["JM", "Bp3", "SMITH"]


def test_a_two_letter_manager_code_parses():
    m = build_line_re(CODES).match("JM Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("avail") == "JM"
    assert m.group("name") == "Nick Chubb"


def test_a_mixed_case_code_with_a_digit_parses():
    m = build_line_re(CODES).match("Bp3 Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("avail") == "Bp3"


def test_a_row_missing_its_status_token_still_does_not_match():
    # F4. "DJ" is a first name here, not a manager code. It is not in
    # CODES, so the line must fail rather than parse as avail="DJ",
    # name="Moore" - which files a real player's stats under a fake one.
    assert build_line_re(CODES).match("DJ Moore WR • CHI @GB 1 2 3") is None


def test_an_injury_tag_after_the_position_is_captured_not_swallowed():
    m = build_line_re(CODES).match("FA Nick Chubb RB Q • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("name") == "Nick Chubb"
    assert (m.group("status1") or m.group("status2")) == "Q"


def test_an_injury_tag_after_the_name_is_captured_not_swallowed():
    m = build_line_re(CODES).match("FA Nick Chubb Q RB • CLE @PIT 1 2 3")
    assert m is not None
    # The bug: the greedy name group used to absorb this, renaming the
    # player to "Nick Chubb Q" - who matches nothing downstream.
    assert m.group("name") == "Nick Chubb"
    assert (m.group("status1") or m.group("status2")) == "Q"


@pytest.mark.parametrize("tag", ["Q", "D", "O", "IR", "PUP", "SUSP", "NA"])
def test_every_standard_designation_is_recognized(tag):
    m = build_line_re(CODES).match(
        "FA Nick Chubb %s RB • CLE @PIT 1 2 3" % tag)
    assert m is not None
    assert (m.group("status1") or m.group("status2")) == tag


def test_an_undesignated_row_still_parses_with_no_status():
    m = build_line_re(CODES).match("FA Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert (m.group("status1") or m.group("status2")) is None


def test_waiver_and_free_agent_are_available():
    assert classify_avail("FA", CODES) == "available"
    assert classify_avail("W", CODES) == "available"
    assert classify_avail("W (9/16)", CODES) == "available"


def test_a_configured_manager_code_is_owned():
    assert classify_avail("JM", CODES) == "owned"
    assert classify_avail("Bp3", CODES) == "owned"


def test_an_unconfigured_code_is_refused_not_guessed():
    # Must not fall back to "owned". An unknown token means the config is
    # stale, and guessing either way silently mis-ranks the waiver board.
    assert classify_avail("ZZZ", CODES) is None


def test_status_reaches_the_projection_record(tmp_path):
    from sffl.cbs_weekly import parse
    page = tmp_path / "p.txt"
    # 17 tokens after the team code, matching sources/cbs-weekly.yaml.
    stats = " ".join(["1"] * 17)
    page.write_text(
        "FA Nick Chubb O RB • CLE %s\n"
        "FA Bijan Robinson RB • ATL %s\n" % (stats, stats))
    rows = dict((p.name, p) for p in parse(str(page), group="RB-WR-TE", week=1))
    assert rows["Nick Chubb"].status == "O"
    assert rows["Bijan Robinson"].status == ""


# Round 2 (in-season pipeline against the real captured page): the
# Playwright `capture()` path used by the scheduled job emits TAB-delimited
# rows, not the space-delimited text the browser-tool capture used for
# FIXTURE above. TAB_FIXTURE is real data - the 100 player rows from a real
# captured page, sanitized only in the fantasy TEAM NAME column (this repo
# is public); every NFL player name and stat is untouched.


def test_the_real_tab_delimited_capture_all_parses_as_one_group():
    rows = parse(TAB_FIXTURE, group="RB-WR-TE", week=1)
    assert len(rows) == 100


def test_a_tab_row_stats_land_in_the_right_slots():
    """Puka Nacua's real row: '\\tTeam J...\\tPuka Nacua WR • LAR \\tSF\\t18\\t
    11\\t98\\t97\\t2\\t0.9\\t6.2\\t6.9\\t0.1\\t11.1\\t8.1\\t100.0\\t12.3\\t0.6\\t0.0\\t9.31'.
    Tab-splitting the trailing fields (instead of whitespace-splitting) is
    what lets 'N/R' (a non-numeric EXPERT rank, its own tab field) sit
    safely in the ignored preamble on this path too - see
    test_a_non_numeric_expert_rank... above for the space-path version of
    the same guarantee."""
    r = by_name(parse(TAB_FIXTURE, group="RB-WR-TE", week=1))["Puka Nacua"]
    assert r.pos == "WR" and r.team == "LAR"
    assert r.stats["rush_att"] == 0.9
    assert r.stats["rec_yds"] == 100.0
    assert r.stats["fum_lost"] == 0.0


def test_a_tab_row_owned_by_another_manager_is_classified_owned():
    """The owner cell is its own tab field: 'Team J...' is a sanitized
    stand-in for a real (truncated) fantasy TEAM name, not FA/W, so
    classify_avail_tab must call it owned - no owner_codes list involved,
    since F4 cannot happen on this path by construction."""
    r = by_name(parse(TAB_FIXTURE, group="RB-WR-TE", week=1))["Puka Nacua"]
    assert r.avail == "Team J..."
    assert classify_avail_tab(r.avail) == "owned"


def test_a_tab_free_agent_row_is_available(tmp_path):
    page = tmp_path / "tab_fa.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text("\tFA\tNick Chubb RB • CLE\t@PIT\t%s\n" % stats)
    rows = parse(str(page), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].avail == "FA"
    assert classify_avail_tab(rows[0].avail) == "available"


def test_a_tab_waiver_row_is_available(tmp_path):
    page = tmp_path / "tab_waiver.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text(
        "\tW (9/16)\tHarold Fannin Jr. TE • CLE\t@JAC\t%s\n" % stats)
    rows = parse(str(page), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].avail == "W (9/16)"
    assert classify_avail_tab(rows[0].avail) == "available"


def test_an_empty_tab_owner_cell_does_not_silently_become_available(tmp_path):
    """An empty owner cell means the column came back blank, not that the
    player is confirmed unowned - those are different facts, and treating
    the first as the second would rank an indeterminate row as claimable.
    classify_avail_tab must refuse it (None), the same as any other
    unrecognized shape - never fall through to 'available'."""
    page = tmp_path / "tab_empty_owner.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text("\t\tNick Chubb RB • CLE\t@PIT\t%s\n" % stats)
    rows = parse(str(page), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].avail == ""
    assert classify_avail_tab(rows[0].avail) is None
    assert classify_avail_tab(rows[0].avail) != "available"


def test_a_tab_injury_tag_after_the_position_is_captured():
    """Same optional-status mechanism as the space path (see
    test_an_injury_tag_after_the_position_is_captured_not_swallowed above),
    exercised on the tab path's name cell, which the real capture did not
    happen to contain any examples of this week."""
    from sffl.cbs_weekly import _TAB_NAME
    m = _TAB_NAME.match("Nick Chubb Q RB • CLE")
    assert m is not None
    assert m.group("name") == "Nick Chubb"
    assert (m.group("status1") or m.group("status2")) == "Q"


def test_the_space_delimited_fixture_is_unaffected_by_the_tab_path():
    """Per-line dispatch (tab vs space) must not change a single result for
    the OLDER, space-delimited capture path - FIXTURE contains no tabs at
    all, so every row here must take exactly the path it always did."""
    rows = parse(FIXTURE, group="RB-WR-TE", week=1)
    assert len(rows) == 8
    r = by_name(rows)["Braelon Allen"]
    assert r.pos == "RB" and r.team == "NYJ"
    assert r.stats["rush_yds"] == 36.8
