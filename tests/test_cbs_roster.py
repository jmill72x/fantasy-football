import pytest

from sffl.cbs_roster import _ROW, parse_lineup, parse_roster

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
