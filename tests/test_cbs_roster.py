import pytest

from sffl.cbs_roster import (_ROW, RosterRow, find_name_position_collisions,
                             parse_lineup, parse_lineup_rows,
                             parse_positions, parse_roster)

FIXTURE = "tests/fixtures/cbs_team_page.txt"


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
            m = _ROW.match(line.rstrip("\n"))
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
    assert starters[0] == RosterRow("Chargers", "TQB", "LAC")
    assert reserves[-1] == RosterRow("Courtland Sutton", "WR", "DEN")


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
