"""CBS's own designations, read from the pages' icon labels (sffl.cbs_icons).

Every label below is constructed: invented players, ids and opponents, in the
shapes the read-only probe of 2026-10-20 found on the live league pages.
"""

import json

import pytest

from sffl import cbs_icons
from sffl.cbs_roster import RosterRow
from sffl.schema import PlayerProjection


def _icon(label, cls="icon-red_cross"):
    return cbs_icons.parse_icon(cls, label)


# ------------------------------------------------------------- parse_icon

def test_a_questionable_label_parses_status_body_week_and_opponent():
    i = _icon("Injury Report: Knee: Questionable for Week 7 at Chicago")
    assert (i.kind, i.tag, i.status, i.body, i.week, i.opponent) == (
        "designation", "Q", "Questionable", "Knee", 7, "at Chicago")


def test_a_home_game_keeps_its_vs():
    i = _icon("Injury Report: Ankle: Out for Week 7 vs. Dallas")
    assert (i.tag, i.week, i.opponent) == ("O", 7, "vs. Dallas")


def test_injured_reserve_names_no_week_but_keeps_the_expected_return():
    i = _icon("Injury Report: Hamstring: Injured Reserve. Expected Return - Week 9",
              "icon-player-status-ir")
    assert (i.tag, i.status, i.week, i.expected_return) == (
        "IR", "Injured Reserve", None, 9)


def test_pup_maps_to_its_own_tag():
    i = _icon("Injury Report: Back: Physically Unable to Perform. "
              "Expected Return - Week 7", "icon-player-status-pup")
    assert (i.tag, i.week, i.expected_return) == ("PUP", None, 7)


@pytest.mark.parametrize("status,tag", [
    ("Doubtful for Week 7 at Denver", "D"),
    ("Retired", "O"),
    ("Did Not Report", "O"),
    ("NFI-R", "IR"),
])
def test_the_other_designation_phrases(status, tag):
    assert _icon("Injury Report: Knee: %s" % status).tag == tag


def test_a_suspension_is_susp_and_names_no_week():
    i = _icon("Suspension: Suspended for 4 games", "icon-suspended")
    assert (i.kind, i.tag, i.week) == ("designation", "SUSP", None)


def test_a_news_headline_and_a_trend_are_not_designations():
    news = _icon("Update: Hawks' Pat Example: Gets 12 touches",
                 "icon-news-note-recent")
    trend = _icon("Status: Cold Player", "icon-news-note-cold")
    assert (news.kind, news.tag) == ("news", "")
    assert (trend.kind, trend.tag, trend.status) == ("trend", "", "Cold Player")


def test_an_unknown_phrase_is_kept_but_never_tagged():
    # A guess could bench a healthy starter; no tag can't bench anyone.
    i = _icon("Injury Report: Knee: Game Time Decision for Week 7 at Miami")
    assert (i.kind, i.tag, i.status) == ("designation", "", "Game Time Decision")


def test_a_designation_icon_with_no_label_is_kept_and_untagged():
    i = cbs_icons.parse_icon("icon-red_cross", "")
    assert (i.kind, i.tag) == ("designation", "")


def test_a_colon_inside_the_body_part_does_not_eat_the_status():
    i = _icon("Injury Report: Knee: ACL: Out for Week 7 at Miami")
    assert (i.body, i.status, i.tag) == ("Knee: ACL", "Out", "O")


def test_tags_match_whole_phrases_only():
    assert cbs_icons.tag_for("Outside chance") == ""
    assert cbs_icons.tag_for(" out ") == "O"


# ------------------------------------------------------------- week rule

def test_a_label_counts_only_for_the_week_it_names():
    next_game = _icon("Injury Report: Concussion: Questionable for Week 8 at Miami")
    stale = _icon("Injury Report: Knee: Questionable for Week 5 at Miami")
    ir = _icon("Injury Report: Knee: Injured Reserve")
    assert not cbs_icons.applies(next_game, 7)
    assert not cbs_icons.applies(stale, 7)
    assert cbs_icons.applies(ir, 7)
    assert cbs_icons.applies(next_game, 8)


def test_designation_prefers_a_readable_label_over_an_unreadable_one():
    unreadable = cbs_icons.parse_icon("icon-red_cross", "")
    out = _icon("Injury Report: Knee: Out for Week 7 at Miami")
    assert cbs_icons.designation([unreadable, out], 7) is out
    assert cbs_icons.designation([unreadable], 7) is unreadable
    assert cbs_icons.designation([], 7) is None


# ------------------------------------------------------------- sidecar

def _rows():
    return [
        {"id": "9000001", "text": "a", "icons": [
            {"icon": "icon-red_cross",
             "label": "Injury Report: Knee: Out for Week 1 at Miami",
             "subtab": "Injury Report"}]},
        {"id": "9000002", "text": "b", "icons": []},
        {"id": "9000003", "text": "c", "icons": [
            {"icon": "icon-news-note-recent",
             "label": "Update: Hawks' Pat Example: Gets 12 touches",
             "subtab": "Update"}]},
    ]


def test_the_sidecar_keeps_only_rows_with_icons_and_counts_every_row():
    side = cbs_icons.build_sidecar(_rows(), "https://x/teams", "2026-10-20T19:00:00")
    assert side["rows_scanned"] == 3
    assert sorted(side["icons"]) == ["9000001", "9000003"]


def test_a_sidecar_round_trips(tmp_path):
    path = tmp_path / "rbwrte.icons.json"
    path.write_text(json.dumps(cbs_icons.build_sidecar(_rows(), "u", "t")))
    icons = cbs_icons.load_sidecar(str(path))
    assert icons["9000001"][0].tag == "O"
    assert icons["9000003"][0].kind == "news"


def test_a_sidecar_of_the_wrong_shape_raises(tmp_path):
    path = tmp_path / "bad.icons.json"
    path.write_text(json.dumps({"icons": []}))
    with pytest.raises(ValueError):
        cbs_icons.load_sidecar(str(path))


def test_the_sidecar_sits_beside_its_page():
    assert cbs_icons.sidecar_path("/x/out/RB-WR-TE.txt") == "/x/out/RB-WR-TE.icons.json"


# ------------------------------------------------------------- apply

def _proj(name, player_id, status=""):
    return PlayerProjection(name=name, team="SEA", pos="WR", source="cbs",
                            source_year=2026, games=1.0, player_id=player_id,
                            status=status)


def test_apply_sets_the_tag_by_cbs_id_and_reports_what_it_skipped():
    out = _proj("Pat Example", "9000001")
    bye = _proj("Lee Sample", "9000002")
    odd = _proj("Kim Placeholder", "9000003")
    clean = _proj("Sam Nobody", "9000004")
    icons = {
        "9000001": [_icon("Injury Report: Knee: Out for Week 7 at Miami")],
        "9000002": [_icon("Injury Report: Knee: Questionable for Week 8 at Miami")],
        "9000003": [_icon("Injury Report: Knee: Game Time Decision for Week 7 at Miami")],
    }
    done = cbs_icons.apply_designations([out, bye, odd, clean], icons, 7)
    assert (out.status, bye.status, odd.status, clean.status) == ("O", "", "", "")
    assert done.applied == [("Pat Example", "O")]
    assert [n for n, _ in done.other_week] == ["Lee Sample"]
    assert [n for n, _ in done.unreadable] == ["Kim Placeholder"]


def test_apply_never_overrides_a_status_the_page_text_carried():
    p = _proj("Pat Example", "9000001", status="Q")
    cbs_icons.apply_designations(
        [p], {"9000001": [_icon("Injury Report: Knee: Out for Week 7 at Miami")]}, 7)
    assert p.status == "Q"


def test_a_row_with_no_cbs_id_is_never_matched():
    p = _proj("Pat Example", "")
    cbs_icons.apply_designations(
        [p], {"": [_icon("Injury Report: Knee: Out for Week 7 at Miami")]}, 7)
    assert p.status == ""


# ------------------------------------------------------------- roster rows

def test_roster_rows_carry_this_and_later_weeks_but_not_games_already_played():
    roster = [RosterRow("Pat Example", "WR", "SEA", "9000001"),
              RosterRow("Lee Sample", "RB", "MIA", "9000002"),
              RosterRow("Kim Placeholder", "TE", "DEN", "9000003")]
    icons = {
        "9000001": [_icon("Injury Report: Concussion: Questionable for Week 8 at Miami"),
                    _icon("Update: Hawks' Pat Example: Gets 12 touches",
                          "icon-news-note-recent")],
        "9000002": [_icon("Injury Report: Knee: Questionable for Week 5 at Denver")],
        "9000003": [_icon("Injury Report: Hamstring: Injured Reserve. "
                          "Expected Return - Week 9", "icon-player-status-ir")],
    }
    rows = cbs_icons.roster_rows(roster, icons, 7, "2026-10-20")
    assert [(r["player"], r["status"]) for r in rows] == [
        ("Pat Example", "Questionable"), ("Kim Placeholder", "Injured Reserve")]
    assert rows[0]["notes"] == "Concussion; for week 8 at Miami"
    assert rows[1]["notes"] == "Hamstring; expected back week 9"
    assert all(r["source"] == "cbs" and r["cbs_id"] for r in rows)


# --------------------------------------- Ultron's 10-20 findings, Jeff's call

def test_the_most_severe_label_that_applies_wins():
    q = _icon("Injury Report: Knee: Questionable for Week 7 at Miami")
    d = _icon("Injury Report: Knee: Doubtful for Week 7 at Miami")
    out = _icon("Injury Report: Knee: Out for Week 7 at Miami")
    ir = _icon("Injury Report: Knee: Injured Reserve", "icon-player-status-ir")
    susp = _icon("Suspension: Suspended for 2 games", "icon-suspended")
    assert cbs_icons.designation([q, d], 7) is d
    assert cbs_icons.designation([q, out, d], 7) is out
    assert cbs_icons.designation([out, ir], 7) is ir
    assert cbs_icons.designation([ir, susp, q], 7) is susp


def test_a_no_week_label_keeps_benching_past_the_expected_return():
    # Jeff, 2026-10-20: "keep benching". IR with an expected return of week 7
    # still benches in week 9, until CBS takes the label down, and the
    # expected return is still shown.
    ir = _icon("Injury Report: Hamstring: Injured Reserve. Expected Return - Week 7",
               "icon-player-status-ir")
    p = _proj("Pat Example", "9000001")
    done = cbs_icons.apply_designations([p], {"9000001": [ir]}, 9)
    assert p.status == "IR" and done.applied == [("Pat Example", "IR")]
    rows = cbs_icons.roster_rows([RosterRow("Pat Example", "WR", "SEA", "9000001")],
                                 {"9000001": [ir]}, 9, "2026-11-04")
    assert rows[0]["notes"] == "Hamstring; expected back week 7"


def test_a_row_the_script_skipped_is_counted_and_never_attributed(tmp_path):
    rows = _rows() + [{"id": "9000009", "text": "nested", "icons": None}]
    side = cbs_icons.build_sidecar(rows, "u", "t")
    assert side["rows_skipped"] == 1 and "9000009" not in side["icons"]
    path = tmp_path / "x.icons.json"
    path.write_text(json.dumps(side))
    summary = cbs_icons.read_sidecar(str(path))
    assert (summary.rows_scanned, summary.rows_skipped, summary.designations) == (4, 1, 1)
