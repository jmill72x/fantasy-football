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


def test_a_repeated_stat_name_sums_its_columns(tmp_path):
    # fg_u30 is CBS's 1-19 plus its 20-29 column - rec_yds/rec_td here are
    # just two arbitrary real STAT_KEYS standing in for that mechanism
    # (post-IMPORTANT-3, a synthetic name like "a" would be refused at load).
    prof = tmp_path / "p.yaml"
    prof.write_text(
        "owner_codes: [ZZ]\n"
        "groups:\n"
        "  T:\n"
        "    stats: [rec_yds, rec_yds, rec_td]\n"
        "    expect_tokens: 4\n")
    page = tmp_path / "page.txt"
    # Tab-delimited row shape: leading tab, then owner cell, then namecell -
    # see _TAB_LINE's docstring and the real TAB_FIXTURE rows, which all
    # start with an (empty) leading cell the same way.
    page.write_text("\tFA\tNick Chubb RB • CLE\tOPP\t1.5\t2.5\t9.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert row.stats["rec_yds"] == 4.0      # 1.5 + 2.5
    assert row.stats["rec_td"] == 9.0


def test_a_single_occurrence_name_is_unaffected(tmp_path):
    prof = tmp_path / "p.yaml"
    prof.write_text("owner_codes: [ZZ]\ngroups:\n  T:\n    stats: [rec_yds, rec_td]\n    expect_tokens: 3\n")
    page = tmp_path / "page.txt"
    page.write_text("\tFA\tNick Chubb RB • CLE\tOPP\t1.5\t9.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert row.stats["rec_yds"] == 1.5 and row.stats["rec_td"] == 9.0


def test_repeated_underscore_columns_are_still_all_discarded(tmp_path):
    # `_` marks a column the engine does not use; repeating it must not
    # create a summed stat literally named "_".
    prof = tmp_path / "p.yaml"
    prof.write_text("owner_codes: [ZZ]\ngroups:\n  T:\n    stats: [_, _, rec_yds]\n    expect_tokens: 4\n")
    page = tmp_path / "page.txt"
    page.write_text("\tFA\tNick Chubb RB • CLE\tOPP\t1.0\t2.0\t3.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert "_" not in row.stats
    assert row.stats["rec_yds"] == 3.0


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


# --- Task 3b: an optional leading "id=<digits>\t" prefix -------------------

def test_a_leading_id_prefix_lands_on_player_id(tmp_path):
    page = tmp_path / "tab_id.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text("id=2966320\t\tTeam I...\tJa'Marr Chase WR • CIN\tTB\t%s\n"
                    % stats)
    rows = parse(str(page), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].name == "Ja'Marr Chase"
    assert rows[0].player_id == "2966320"


def test_a_row_with_no_id_prefix_falls_back_to_the_empty_string(tmp_path):
    """THE DOCUMENTED FALLBACK PATH. A row `capture()` could not pair with a
    `playerpage/<id>` link (page furniture, or any page saved before this
    existed - a real live TQB/DST team-aggregate row DOES carry its own id,
    see cbs_weekly's module docstring) carries no prefix at all -
    `player_id` must default to "", never None or a missing attribute, so
    `identity.resolve_key` can fall back to the (name, team, pos) composite
    unconditionally."""
    page = tmp_path / "tab_no_id.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text("\tTeam A...\tChargers TQB • LAC\tARI\t%s\n" % stats)
    rows = parse(str(page), group="TQB", week=1)
    assert len(rows) == 1
    assert rows[0].player_id == ""


def test_an_id_prefix_does_not_change_expect_tokens_pass_or_fail(tmp_path):
    """THE COLUMN-SHIFT GUARD MUST BE UNAFFECTED. `expect_tokens` counts
    tokens AFTER the team code - the id prefix sits entirely before that,
    stripped off before either delimiter path ever computes `tokens` (see
    `_strip_id_prefix`/`_parse_row`). Two identical rows, one with the
    prefix and one without, must both pass expect_tokens=17 (the real
    RB-WR-TE width) and produce byte-identical stats."""
    stats = "\t".join(str(n) for n in range(16))  # OPP + 16 = 17 tokens
    row_no_id = "\tTeam A...\tNick Chubb RB • CLE\t@PIT\t%s\n" % stats
    row_with_id = "id=12345\t" + row_no_id

    plain = tmp_path / "plain.txt"
    plain.write_text(row_no_id)
    prefixed = tmp_path / "prefixed.txt"
    prefixed.write_text(row_with_id)

    rows_plain = parse(str(plain), group="RB-WR-TE", week=1)
    rows_prefixed = parse(str(prefixed), group="RB-WR-TE", week=1)
    assert len(rows_plain) == 1 and len(rows_prefixed) == 1
    assert rows_plain[0].stats == rows_prefixed[0].stats
    assert rows_plain[0].player_id == ""
    assert rows_prefixed[0].player_id == "12345"


def test_an_id_prefix_does_not_hide_a_real_column_shift(tmp_path):
    """The inverse of the guarantee above: a TRUE width violation must still
    raise, prefix or no prefix - the prefix must not accidentally widen or
    narrow what expect_tokens sees."""
    stats = "\t".join(str(n) for n in range(15))  # one short: 16, not 17
    page = tmp_path / "short.txt"
    page.write_text("id=12345\t\tTeam A...\tNick Chubb RB • CLE\t@PIT\t%s\n"
                    % stats)
    with pytest.raises(ValueError) as exc:
        parse(str(page), group="RB-WR-TE", week=1)
    assert "expected 17" in str(exc.value)


def test_the_real_tab_fixture_carries_real_ids_on_nearly_every_row():
    """This fixture was regenerated from a real live capture (2026-08-30,
    Task 3b) - 99 of its 100 rows now carry a genuine CBS `player_id`. The
    one holdout (Michael Wilson, ARI - no longer on the live page as of
    this regeneration, most likely normal roster churn) exercises the
    documented FALLBACK path naturally, on real data, rather than only in a
    hand-constructed test - both paths matter and both must keep parsing."""
    rows = parse(TAB_FIXTURE, group="RB-WR-TE", week=1)
    assert len(rows) == 100
    by_name = dict((r.name, r) for r in rows)
    assert by_name["Ja'Marr Chase"].player_id == "2966320"
    assert by_name["Puka Nacua"].player_id == "3121687"
    assert by_name["Michael Wilson"].player_id == ""
    with_id = [r for r in rows if r.player_id]
    assert len(with_id) == 99


def test_a_whitespace_only_tab_owner_cell_is_refused_not_called_owned(tmp_path):
    """M1. The tab path used to hand `avail` through unstripped while the
    space path stripped it, so a cell holding only spaces was a non-empty
    string and classify_avail_tab's "any other non-empty value means owned"
    rule filed it as OWNED. That is the one classification made in silence -
    an owned row is excluded from the waiver board with no warning at all -
    so a blank column would quietly delete a genuine free agent from the
    board. Stripped, it is indistinguishable from the empty cell above and
    is refused loudly, which is what an indeterminate cell must do."""
    page = tmp_path / "tab_blank_owner.txt"
    stats = "\t".join(["1"] * 16)
    page.write_text("\t   \tNick Chubb RB • CLE\t@PIT\t%s\n" % stats)
    rows = parse(str(page), group="RB-WR-TE", week=1)
    assert len(rows) == 1
    assert rows[0].avail == ""
    assert classify_avail_tab(rows[0].avail) is None
    assert classify_avail_tab(rows[0].avail) != "owned"


def test_a_numeric_owner_code_does_not_crash_the_row_regex():
    """A human hand-edits `owner_codes` before week 1, and a code like `12`
    YAML-parses to an int. `sorted(key=len)` and `re.escape` both raise
    TypeError on an int, which took down the whole weekly command with a
    traceback naming neither the file nor the field. Coerced with str()."""
    line_re = build_line_re(["JM", 12, 50])
    m = line_re.match("12 Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("avail") == "12"
    assert m.group("name") == "Nick Chubb"


def test_numeric_owner_codes_from_yaml_also_classify_as_owned(tmp_path):
    """The regex coercion alone is not enough: `classify_avail` tests
    membership against the loaded list, and a page token is always a string,
    so an int code would match the row and then classify as unknown."""
    from sffl.cbs_weekly import _load_owner_codes
    profile = tmp_path / "profile.yaml"
    profile.write_text("owner_codes:\n  - JM\n  - 12\n")
    codes = _load_owner_codes(str(profile))
    assert codes == ["JM", "12"]
    assert classify_avail("12", codes) == "owned"


# ----------------------------------------------------- week validation
#
# The detection half of the `--week` fix. `parse` took a `week` argument and
# never used it, and nothing read the page's own "REPORT UPDATED AS OF"
# stamp, so a saved week-3 page run as week 4 exited 0 with a confident
# lineup and no signal anywhere.

def _proj(team, opp, pos="DST"):
    from sffl.schema import PlayerProjection
    return PlayerProjection(name=team, team=team, pos=pos, source="cbs-weekly",
                            source_year=2026, games=1.0, opp=opp)


def test_week_conflicts_finds_a_team_two_pages_disagree_about():
    from sffl.cbs_weekly import week_conflicts
    pages = {"TQB": [_proj("ARI", "@LAC"), _proj("SEA", "SF")],
             "DST": [_proj("ARI", "SEA"), _proj("SEA", "SF")]}
    got = week_conflicts(pages)
    assert [t for t, _ in got] == ["ARI"]
    assert got[0][1] == {"DST": "SEA", "TQB": "@LAC"}


def test_pages_that_agree_produce_no_conflicts():
    from sffl.cbs_weekly import week_conflicts
    pages = {"TQB": [_proj("ARI", "@LAC")], "DST": [_proj("ARI", "@LAC")]}
    assert week_conflicts(pages) == []


def test_a_team_on_only_one_page_cannot_conflict_with_itself():
    from sffl.cbs_weekly import week_conflicts
    pages = {"TQB": [_proj("ARI", "@LAC")], "K": [_proj("SEA", "SF")]}
    assert week_conflicts(pages) == []


def test_shared_team_count_is_the_denominator_and_excludes_lone_teams():
    from sffl.cbs_weekly import shared_team_count
    pages = {"TQB": [_proj("ARI", "@LAC"), _proj("GB", "MIN")],
             "DST": [_proj("ARI", "@LAC")]}
    assert shared_team_count(pages) == 1


def test_no_shared_teams_reports_zero_not_a_clean_bill_of_health():
    # 0 shared means the check COULD NOT RUN. A caller that divides by this
    # must notice; one that treats it as "no conflicts" is asserting
    # something it never tested.
    from sffl.cbs_weekly import shared_team_count, week_conflicts
    pages = {"TQB": [_proj("ARI", "@LAC")], "K": [_proj("SEA", "SF")]}
    assert shared_team_count(pages) == 0
    assert week_conflicts(pages) == []


def test_the_mismatch_ratio_sits_between_the_measured_noise_and_a_real_miss():
    # Measured 2026-08-31 on real captures: a genuine same-run TQB+DST pair
    # conflicts on 2/32 (6%) because CBS's TQB page ships a known OPP defect;
    # a week-1/week-2 pair conflicts on 32/32 (100%). The threshold must
    # exclude the first and catch the second, or it is useless in one
    # direction or the other.
    from sffl.cbs_weekly import WEEK_MISMATCH_RATIO
    assert 2.0 / 32 < WEEK_MISMATCH_RATIO < 32.0 / 32


def test_internally_inconsistent_opponents_catches_a_scrambled_page():
    from sffl.cbs_weekly import internally_inconsistent_opponents
    good = [_proj("ARI", "@SEA"), _proj("SEA", "ARI")]
    assert internally_inconsistent_opponents(good) == []
    bad = [_proj("ARI", "@SEA"), _proj("SEA", "SF"), _proj("SF", "SEA")]
    got = internally_inconsistent_opponents(bad)
    assert [t for t, _, _ in got] == ["ARI"]


def test_read_report_stamp_parses_the_real_page_format():
    import datetime, tempfile, os
    from sffl.cbs_weekly import read_report_stamp
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("junk\nREPORT UPDATED AS OF 8/31/26 10:26 PM EST\nmore\n")
        assert read_report_stamp(path) == datetime.datetime(2026, 8, 31, 22, 26)
    finally:
        os.unlink(path)


def test_a_page_with_no_stamp_returns_none_rather_than_a_guess():
    # None must mean "could not be read", never "is old" - an older capture
    # path or a layout change both produce it, and reporting either as stale
    # would cry wolf on every run.
    import tempfile, os
    from sffl.cbs_weekly import read_report_stamp
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("a page with no stamp at all\n")
        assert read_report_stamp(path) is None
    finally:
        os.unlink(path)
