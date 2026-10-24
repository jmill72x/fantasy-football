import re

import pytest

from sffl.cbs_roster import (_ROW, RosterRow, find_name_position_collisions,
                             parse_lineup, parse_lineup_rows,
                             parse_positions, parse_roster)

FIXTURE = "tests/fixtures/cbs_team_page.txt"

# Mirrors `cbs_roster._ID_PREFIX` - the fixture carries CBS-style ids
# (Task 3b; constructed since 2026-10-19), so a test that re-derives page order by matching `_ROW`
# directly against RAW file lines (bypassing `_iter_lines`, which strips
# this prefix before `_ROW` ever sees a line) must strip it too.
_STRIP_ID = re.compile(r"^id=\d+\t")


def _strip_id(line):
    return _STRIP_ID.sub("", line)


def test_the_real_captured_page_yields_a_full_roster():
    names = parse_roster(FIXTURE)
    # The league starts 8 and rosters more; anything under 8 means the
    # parser matched a fragment of the page rather than the roster table.
    assert len(names) >= 8


def test_names_are_unique_and_in_page_order():
    names = parse_roster(FIXTURE)
    assert len(names) == len(set(names))
    # ORDER, not just uniqueness. The name of this test claimed page order
    # and asserted nothing about it, so a parser that sorted, reversed, or
    # emitted starters after reserves passed unchallenged - and page order
    # is what makes `parse_lineup`'s starters/reserves split meaningful and
    # what `injuries.for_roster` walks to order its output.
    #
    # Pinned against the fixture's own line order, read independently of the
    # parser: the raw row lines in the order they appear on the page. If the
    # two ever disagree the parser reordered something.
    page_order = []
    with open(FIXTURE) as fh:
        for line in fh:
            m = _ROW.match(_strip_id(line.rstrip("\n")))
            if m:
                name = m.group("name").strip()
                if name not in page_order:
                    page_order.append(name)
    assert names == page_order
    # Belt and braces on the two ends, so a subtle mid-list swap is not the
    # only thing this can catch: the fixture's first row is the TQB and its
    # last is the final reserve.
    assert names[0] == "Chargers"
    assert names[-1] == "Courtland Sutton"


def test_the_fixture_has_exactly_thirteen_players():
    names = parse_roster(FIXTURE)
    assert len(names) == 13


def test_a_healthy_player_a_dst_and_a_tqb_all_parse():
    names = parse_roster(FIXTURE)
    assert "Brock Bowers" in names
    assert "Patriots" in names
    assert "Chargers" in names


def test_a_team_code_with_a_trailing_space_still_parses_cleanly():
    # "Ja'Marr Chase WR . CIN " - the trailing space is where an injury
    # glyph renders on the live page. It must not leak into the name.
    names = parse_roster(FIXTURE)
    assert "Ja'Marr Chase" in names


def test_header_and_furniture_never_produce_a_phantom_player():
    names = parse_roster(FIXTURE)
    for bogus in ("PLAYERS", "EDIT", "POS", "OPP", "RESERVES", "TRADES"):
        assert bogus not in names


def test_an_empty_page_raises_rather_than_returning_an_empty_roster(tmp_path):
    # An empty roster is indistinguishable downstream from "Jeff owns
    # nobody", which optimises to an empty lineup and ranks every free
    # agent as a claim - the same failure `_cmd_week`'s empty-roster guard
    # already raises for.
    p = tmp_path / "empty.txt"
    p.write_text("Nothing here at all\n")
    with pytest.raises(ValueError) as exc:
        parse_roster(str(p))
    assert "0 player" in str(exc.value)


def test_parse_lineup_splits_starters_from_reserves_on_the_real_page():
    starters, reserves = parse_lineup(FIXTURE)
    assert len(starters) == 8
    assert len(reserves) == 5
    assert "Chargers" in starters
    assert "Rico Dowdle" in reserves


def test_parse_lineup_and_parse_roster_never_silently_drift_apart():
    starters, reserves = parse_lineup(FIXTURE)
    assert sorted(parse_roster(FIXTURE)) == sorted(starters + reserves)


def test_parse_lineup_without_a_reserves_marker_raises(tmp_path):
    # Guessing where the bench starts would silently report bench players
    # as starters - refuse instead.
    p = tmp_path / "no_marker.txt"
    p.write_text("\tWR\tSome Guy WR • NYJ\tNE\t\n")
    with pytest.raises(ValueError) as exc:
        parse_lineup(str(p))
    assert "RESERVES" in str(exc.value)


def test_parse_lineup_on_an_empty_page_raises(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("Nothing here at all\n")
    with pytest.raises(ValueError) as exc:
        parse_lineup(str(p))
    assert "RESERVES" in str(exc.value)


def test_parse_positions_gives_every_player_his_page_position():
    """The alert needs the position to tell a known scope limit (the
    projections page covers RB/WR/TE, so a TQB/K/DST is never scored) apart
    from a data problem (a covered position with no projection anyway).
    Without it both render identically, and the first reads as bench
    advice."""
    positions = parse_positions(FIXTURE)
    assert positions["Chargers"] == "TQB"
    assert positions["Evan McPherson"] == "K"
    assert positions["Patriots"] == "DST"
    assert positions["Ja'Marr Chase"] == "WR"
    assert positions["Cam Skattebo"] == "RB"
    # Every name the roster parser returns has one - a starter with no
    # position would be classified by the fallback rather than by fact.
    for name in parse_roster(FIXTURE):
        assert positions[name]


def test_parse_positions_covers_reserves_as_well_as_starters():
    positions = parse_positions(FIXTURE)
    starters, reserves = parse_lineup(FIXTURE)
    for name in starters + reserves:
        assert name in positions


# --- find_name_position_collisions -----------------------------------------

def test_the_real_fixture_has_no_collisions():
    # The overwhelming common case, pinned explicitly: the shipped fixture
    # rosters "Chargers" (TQB) and "Patriots" (DST) - two different real
    # teams - so nothing should ever collide on it.
    assert find_name_position_collisions(FIXTURE) == {}


def test_the_same_team_rostered_for_both_tqb_and_dst_is_found(tmp_path):
    """THE REAL, REPRODUCED BUG this function exists to catch:
    `parse_lineup`/`parse_positions` silently collapse two DIFFERENT roster
    rows - a real NFL team's TQB aggregate AND its DST aggregate - into one
    the moment their display names collide, because nothing stops a
    manager from rostering the SAME team for both slots. This function is
    the only one that still sees both rows."""
    with open(FIXTURE) as fh:
        text = fh.read()
    # Same substitution used to reproduce the bug end-to-end for the task
    # report: rename the DST row's team from Patriots to Chargers so it
    # collides with the existing Chargers TQB row.
    collided = text.replace("Patriots DST • NE ", "Chargers DST • LAC ")
    assert "Chargers DST" in collided
    p = tmp_path / "collision.txt"
    p.write_text(collided)

    collisions = find_name_position_collisions(str(p))
    assert collisions == {"Chargers": ["DST", "TQB"]}
    # And "Patriots" - no longer present at all - is correctly absent, not
    # spuriously flagged.
    assert "Patriots" not in collisions


def test_a_collision_in_the_reserves_section_is_also_found(tmp_path):
    # A collision must be found regardless of which side of the RESERVES
    # marker either row falls on - the hazard is just as real for a bench
    # pick as for a starter.
    p = tmp_path / "collision.txt"
    p.write_text(
        "\tTQB\tChargers TQB • LAC\tARI\t\n"
        "RESERVES\n"
        "\tDST\tChargers DST • LAC\tARI\t\n"
    )
    assert find_name_position_collisions(str(p)) == {"Chargers": ["DST", "TQB"]}


def test_a_name_repeated_at_the_same_position_is_not_a_collision(tmp_path):
    # A genuine dedup case (e.g. the same row rendered twice by a page
    # quirk) must NOT be flagged - only a name whose rows DISAGREE on slot
    # is ambiguous.
    p = tmp_path / "same_slot.txt"
    p.write_text(
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
    )
    assert find_name_position_collisions(str(p)) == {}


# --- parse_lineup_rows: full-fidelity (name, slot, team) roster rows -------

def test_parse_lineup_rows_matches_parse_lineup_when_there_is_no_collision():
    starters, reserves = parse_lineup_rows(FIXTURE)
    name_starters, name_reserves = parse_lineup(FIXTURE)
    assert [r.name for r in starters] == name_starters
    assert [r.name for r in reserves] == name_reserves
    assert starters[0] == RosterRow("Chargers", "TQB", "LAC", "8987")
    assert reserves[-1] == RosterRow("Courtland Sutton", "WR", "DEN",
                                     "9443231")


def test_parse_lineup_rows_keeps_both_sides_of_a_real_collision(tmp_path):
    # THE REPRODUCED BUG: `parse_lineup` collapses this to ONE "Chargers"
    # entry and silently loses which slot the second row occupied.
    # `parse_lineup_rows` must keep BOTH, correctly labelled.
    with open(FIXTURE) as fh:
        text = fh.read()
    collided = text.replace("Patriots DST • NE ", "Chargers DST • LAC ")
    p = tmp_path / "collision.txt"
    p.write_text(collided)

    starters, _reserves = parse_lineup_rows(str(p))
    chargers_rows = [r for r in starters if r.name == "Chargers"]
    assert len(chargers_rows) == 2
    assert set(r.slot for r in chargers_rows) == {"TQB", "DST"}
    assert all(r.team == "LAC" for r in chargers_rows)


def test_parse_lineup_rows_collapses_only_an_exact_triple_match(tmp_path):
    # The SAME entity rendered twice (identical name, slot, AND team) is a
    # page-layout artifact, not two different roster entries - this is the
    # one case that should still collapse.
    p = tmp_path / "exact_dup.txt"
    p.write_text(
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "RESERVES\n"
    )
    starters, _reserves = parse_lineup_rows(str(p))
    assert starters == [RosterRow("Ja'Marr Chase", "WR", "CIN")]


# --- Task 3b: an optional leading "id=<digits>\t" prefix -------------------

def test_a_leading_id_prefix_lands_on_the_roster_rows_player_id(tmp_path):
    p = tmp_path / "with_id.txt"
    p.write_text(
        "id=9845591\t\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "RESERVES\n"
    )
    starters, _reserves = parse_lineup_rows(str(p))
    assert starters == [RosterRow("Ja'Marr Chase", "WR", "CIN", "9845591")]
    assert starters[0].player_id == "9845591"


def test_a_roster_row_with_no_id_prefix_falls_back_to_the_empty_string(tmp_path):
    """THE DOCUMENTED FALLBACK PATH. A row with no leading id prefix at all
    (page furniture, or a page saved before this existed - a real live
    Chargers TQB row DOES carry its own id, see the module docstring)
    must default `player_id` to "" so `identity.resolve_key` falls back to
    the (name, slot, team) composite unconditionally, exactly as it always
    has."""
    p = tmp_path / "no_id.txt"
    p.write_text("\tTQB\tChargers TQB • LAC\tARI\t\nRESERVES\n")
    starters, _reserves = parse_lineup_rows(str(p))
    assert starters == [RosterRow("Chargers", "TQB", "LAC")]
    assert starters[0].player_id == ""


def test_an_id_prefix_does_not_change_ROW_matching_for_any_other_parser(tmp_path):
    """`parse_roster`/`parse_positions`/`parse_lineup`/
    `find_name_position_collisions` all strip-and-discard the id prefix via
    `_iter_lines` - they must behave identically whether a row carries one
    or not, since none of them consume `player_id`."""
    p = tmp_path / "with_id.txt"
    p.write_text(
        "id=9845591\t\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "RESERVES\n"
    )
    assert parse_roster(str(p)) == ["Ja'Marr Chase"]
    assert parse_positions(str(p)) == {"Ja'Marr Chase": "WR"}
    starters, reserves = parse_lineup(str(p))
    assert starters == ["Ja'Marr Chase"]
    assert reserves == []
    assert find_name_position_collisions(str(p)) == {}


def test_two_id_prefixed_rows_that_share_an_id_are_still_two_distinct_rows(tmp_path):
    """The id prefix does not change `RosterRow` equality/uniqueness on its
    own here - `parse_lineup_rows` only collapses a row when name, slot, AND
    team all agree (see its own docstring); a shared id with a different
    slot is exactly the Chargers TQB/DST shape and must still yield two
    separate rows for `_cmd_alert` to resolve independently."""
    p = tmp_path / "shared_id.txt"
    # A hypothetical (not a real CBS shape) where a team's TQB and DST rows
    # were BOTH paired with the same id by a capture quirk - still two rows.
    p.write_text(
        "id=999\t\tTQB\tChargers TQB • LAC\tARI\t\n"
        "id=999\t\tDST\tChargers DST • LAC\tARI\t\n"
        "RESERVES\n"
    )
    starters, _reserves = parse_lineup_rows(str(p))
    assert len(starters) == 2
    assert set(r.slot for r in starters) == {"TQB", "DST"}
    assert all(r.player_id == "999" for r in starters)


def test_parse_lineup_rows_collapses_a_repeat_even_when_only_one_side_has_an_id(
        tmp_path):
    # Review round 2: the SAME entity (identical name, slot, team) rendered
    # twice, but only ONE occurrence paired with a `playerpage/<id>` link
    # (a real, if unobserved, capture-timing possibility - `_prefix_ids`
    # pairs by document-order text match, and a repeated `<tr>` need not
    # repeat identically in every detail). Dedup must key on (name, slot,
    # team) alone, per the function's own docstring - not on the full
    # 4-tuple including `player_id` - or this would silently survive as TWO
    # rows for one real roster slot.
    p = tmp_path / "one_sided_id.txt"
    p.write_text(
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "id=9845591\t\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "RESERVES\n"
    )
    starters, _reserves = parse_lineup_rows(str(p))
    assert starters == [RosterRow("Ja'Marr Chase", "WR", "CIN", "9845591")]

    # And the reverse order - id-bearing occurrence FIRST, id-less SECOND -
    # must not let the id-less repeat blank out the id already captured.
    p2 = tmp_path / "one_sided_id_reversed.txt"
    p2.write_text(
        "id=9845591\t\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "\tWR\tJa'Marr Chase WR • CIN \tTB\t\n"
        "RESERVES\n"
    )
    starters2, _reserves2 = parse_lineup_rows(str(p2))
    assert starters2 == [RosterRow("Ja'Marr Chase", "WR", "CIN", "9845591")]


# --------------------------------------------- bye-week rows (2026-10-20)
#
# A constructed page in the shape of the live team page of 2026-10-20: a
# player with a game spreads over three lines (row line, kickoff time, then
# the stat block, which is where the capture's id prefix lands), while a
# player ON BYE is a single line - opponent BYE, then his stat block - with
# the id prefix on it. Invented names, ids and numbers throughout.

BYE_WEEK_PAGE = "\n".join([
    "League",
    "My Team",
    "EDIT\tPOS\tPLAYERS\tOPP\tGAME TIME\tBYE\tO/U\tPOSRNK\tOVP\tROST\tSTART\tPRD. ",
    "",
    "\tTQB\tHawks TQB • SEA \t@MIA\t",
    "Sun 1:00pm EDT",
    "id=9100001\t\t8\t41.0\t---\t---\t50%\t25%\t1.11\t2.22\t3.33",
    "",
    "\tWR\tPat Example WR • SEA\tDEN\t",
    "Thurs 8:15pm EDT",
    "id=9100002\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
    "",
    "id=9100003\t\tWR\tLee Sample WR • LAC \tBYE\t\t7\t\t---\t\t50%\t25%\t0.00\t1.11\t0.00",
    "",
    "\tK\tKim Kicker K • NYG \t@HOU\t",
    "Sun 1:00pm EDT",
    "id=9100004\t\t8\t43.0\t40\t15\t50%\t25%\t1.11\t2.22\t3.33",
    "RESERVES",
    "",
    "id=9100005\t\tTQB\tBolts TQB • LAC\tBYE\t\t7\t\t---\t\t50%\t25%\t1.11\t2.22\t0.00",
    "",
    "\tRB\tSam Runner RB • DET\tGB\t",
    "Sun 1:00pm EDT",
    "id=9100006\t\t5\t47.5\t18\t8\t50%\t25%\t1.11\t2.22\t3.33",
    "ACTIVE: 4 RESERVE: 2",
    "",
])


def _bye_page(tmp_path):
    path = tmp_path / "team_page_bye_week.txt"
    path.write_text(BYE_WEEK_PAGE)
    return str(path)


def test_every_row_keeps_its_cbs_id_whether_it_has_a_game_or_a_bye(tmp_path):
    # Until 2026-10-21 the rows WITH a game parsed with "" here: their id
    # sits on the stats line, two lines below the row line, and only the
    # one-line bye rows carried theirs. Every row now has its own id.
    starters, reserves = parse_lineup_rows(_bye_page(tmp_path))
    assert starters == [
        RosterRow("Hawks", "TQB", "SEA", "9100001"),
        RosterRow("Pat Example", "WR", "SEA", "9100002"),
        RosterRow("Lee Sample", "WR", "LAC", "9100003"),
        RosterRow("Kim Kicker", "K", "NYG", "9100004"),
    ]
    assert reserves == [
        RosterRow("Bolts", "TQB", "LAC", "9100005"),
        RosterRow("Sam Runner", "RB", "DET", "9100006"),
    ]


# ------------------------- a playing-week row's id, off its stats line
#
# The live capture puts a row's id at the start of the row's LAST non-blank
# line (`capture._prefix_ids`), which for a row with a game is its stats line.
# `cbs_roster._iter_lines` reads it back from there - and must never hand one
# row's id to another. Invented names, ids and numbers throughout.

def _page(tmp_path, lines):
    path = tmp_path / "team_page.txt"
    path.write_text("\n".join(lines + [""]))
    return str(path)


def test_a_roster_row_with_a_game_keeps_its_cbs_id(tmp_path):
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "Sun 1:00pm EDT",
        "id=9200001\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", "9200001")]
    assert reserves == []


def test_a_row_whose_stats_line_lost_its_id_never_takes_the_next_bye_rows(tmp_path):
    # The next row is a bye row: one line, its OWN id on it. That id line
    # starts like a row, so it ends the search for the row above.
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "Sun 1:00pm EDT",
        "\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "",
        "id=9200002\t\tWR\tLee Sample WR • LAC \tBYE\t\t7\t\t---\t\t50%\t25%\t0.00\t1.11\t0.00",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", ""),
                        RosterRow("Lee Sample", "WR", "LAC", "9200002")]


def test_a_row_whose_stats_line_lost_its_id_never_takes_the_next_games_id(tmp_path):
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "Sun 1:00pm EDT",
        "\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "\tK\tKim Kicker K • NYG \t@HOU\t",
        "Sun 1:00pm EDT",
        "id=9200003\t\t8\t43.0\t40\t15\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", ""),
                        RosterRow("Kim Kicker", "K", "NYG", "9200003")]


def test_a_row_line_the_parser_cannot_read_still_keeps_its_id_to_itself(tmp_path):
    # `_ROW` allows only [A-Za-z0-9.'- ] in a name, so this next row is not
    # parsed at all (as before). It still starts like a row, so its stats
    # line's id is never given to the row above.
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "Sun 1:00pm EDT",
        "\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "\tRB\tJosé Ejemplo RB • DET\tGB\t",
        "Sun 1:00pm EDT",
        "id=9200004\t\t5\t47.5\t18\t8\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", "")]


def test_a_starters_id_never_comes_from_below_the_reserves_marker(tmp_path):
    path = _page(tmp_path, [
        "\tK\tKim Kicker K • NYG \t@HOU\t",
        "Sun 1:00pm EDT",
        "RESERVES",
        "id=9200005\t\t8\t43.0\t40\t15\t50%\t25%\t1.11\t2.22\t3.33",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Kim Kicker", "K", "NYG", "")]


def test_the_last_reserves_search_ends_at_the_footer(tmp_path):
    path = _page(tmp_path, [
        "RESERVES",
        "\tRB\tSam Runner RB • DET\tGB\t",
        "Sun 1:00pm EDT",
        "\t\t5\t47.5\t18\t8\t50%\t25%\t1.11\t2.22\t3.33",
        "ACTIVE: 0 RESERVE: 1",
        "id=9200006\tSomething Else",
    ])
    _starters, reserves = parse_lineup_rows(path)
    assert reserves == [RosterRow("Sam Runner", "RB", "DET", "")]


def test_a_game_time_on_two_lines_still_finds_the_stats_lines_id(tmp_path):
    # Never captured (no saved page has a game in progress), so this is the
    # tolerance, not a measured shape: a game-time cell that renders on two
    # lines puts the stats line three below the row line.
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "W 14-10",
        "Q3 5:21",
        "id=9200007\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", "9200007")]


def test_the_search_stops_after_its_lookahead(tmp_path):
    path = _page(tmp_path, [
        "\tWR\tPat Example WR • SEA \t@MIA\t",
        "a", "b", "c", "d",
        "id=9200008\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", "")]


def test_an_id_on_the_row_line_is_still_read_from_there(tmp_path):
    # The shape the first id-prefixing rule wrote (2026-08-30): id on the
    # row line, kickoff time and stats below it with none.
    path = _page(tmp_path, [
        "id=9200009\t\tWR\tPat Example WR • SEA \t@MIA\t",
        "Sun 1:00pm EDT",
        "\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
        "RESERVES",
    ])
    starters, _reserves = parse_lineup_rows(path)
    assert starters == [RosterRow("Pat Example", "WR", "SEA", "9200009")]


def test_the_fixture_gives_every_row_its_own_id_once():
    # The constructed team page is in the live shape since 2026-10-21: every
    # row has a game, so every id sits on a stats line.
    starters, reserves = parse_lineup_rows(FIXTURE)
    ids = [r.player_id for r in starters + reserves]
    assert len(ids) == 13 and all(ids)
    assert len(set(ids)) == len(ids)
    with open(FIXTURE) as fh:
        id_lines = [l for l in fh if l.startswith("id=")]
    assert not any(_ROW.match(_strip_id(l.rstrip("\n"))) for l in id_lines), (
        "the fixture's ids should sit on stats lines, as the live capture "
        "writes them")


def test_every_roster_parser_keeps_the_bye_rows(tmp_path):
    path = _bye_page(tmp_path)
    assert parse_roster(path) == ["Hawks", "Pat Example", "Lee Sample",
                                  "Kim Kicker", "Bolts", "Sam Runner"]
    assert parse_positions(path)["Lee Sample"] == "WR"
    assert parse_lineup(path) == (["Hawks", "Pat Example", "Lee Sample",
                                   "Kim Kicker"], ["Bolts", "Sam Runner"])


def test_the_row_pattern_still_refuses_page_furniture():
    for line in ("\t\t8\t41.0\t11\t22\t50%\t25%\t1.11\t2.22\t3.33",
                 "Sun 1:00pm EDT",
                 "EDIT\tPOS\tPLAYERS\tOPP\tGAME TIME\tBYE\tO/U",
                 "RESERVES",
                 "ACTIVE: 4 RESERVE: 2"):
        assert _ROW.match(line) is None, line


def test_a_row_ending_after_its_opponent_matches_exactly_as_before():
    # The shape every row had before byes started: nothing after the
    # opponent but an optional tab. Same groups as ever.
    for line in ("\tWR\tPat Example WR • SEA \t@MIA\t",
                 "\tTQB\tHawks TQB • SEA\tMIA"):
        m = _ROW.match(line)
        assert m is not None
        assert (m.group("slot"), m.group("team")) in (("WR", "SEA"), ("TQB", "SEA"))
