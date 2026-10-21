import json

import pytest

from sffl.injuries import Report, for_roster, load

FIXTURE = "tests/fixtures/statsdeck_injuries.json"


def test_every_row_loads_with_its_reported_date():
    reports = load(FIXTURE)
    assert len(reports) == 4
    # reported_date is load-bearing: the feed carries non-injury designations
    # (holdouts, rest days) and a status with no date cannot be judged.
    assert all(r.reported_date for r in reports)


def test_rows_are_filtered_to_the_roster_and_nobody_else():
    reports = load(FIXTURE)
    mine = for_roster(reports, ["Ja'Marr Chase"])
    assert {r.name for r in mine} == {"Ja'Marr Chase"}
    assert len(mine) == 2  # the two intel rows (sleeper_feed, web_digest)


def test_a_roster_name_with_different_punctuation_still_matches():
    # "JaMarr Chase" from one page must match "Ja'Marr Chase" from another.
    reports = load(FIXTURE)
    assert len(for_roster(reports, ["JaMarr Chase"])) == 2


def test_a_clean_roster_yields_no_rows_rather_than_an_error():
    reports = load(FIXTURE)
    assert for_roster(reports, ["Bijan Robinson"]) == []


def test_a_repeated_roster_name_does_not_duplicate_a_matching_report():
    # Task 3b minor (d): `roster_names` CAN now legitimately contain repeats
    # (`_cmd_alert` builds it from `RosterRow`s, which - since
    # `parse_lineup_rows` stopped collapsing by name alone - carries the
    # same display name twice for the Chargers TQB/DST shape). A matching
    # `Report` must still be emitted only ONCE per roster, not once per
    # occurrence of the name.
    reports = load(FIXTURE)
    once = for_roster(reports, ["Ja'Marr Chase"])
    twice = for_roster(reports, ["Ja'Marr Chase", "Ja'Marr Chase"])
    assert twice == once
    assert len(twice) == 2


def test_official_and_intel_are_kept_distinct():
    # The official report is the record; intel supplements and never
    # overrides. Collapsing them would let a beat writer outrank the report.
    # Nick Chubb has one row in each bucket in the fixture.
    mine = for_roster(load(FIXTURE), ["Nick Chubb"])
    assert len(mine) == 2
    assert {r.source for r in mine} == {"official", "intel"}


def test_source_is_the_bucket_not_the_feeds_own_outlet_label():
    # StatsDeck's per-row "source" field is an outlet name (sleeper_feed,
    # web_digest), never the string "official" - the bucket has to come from
    # which array the row was in, or every row would land in intel and the
    # official/intel distinction would collapse.
    mine = for_roster(load(FIXTURE), ["Nick Chubb"])
    official = [r for r in mine if r.source == "official"][0]
    intel = [r for r in mine if r.source == "intel"][0]
    assert official.outlet == ""  # official rows carry no outlet label
    assert intel.outlet == "beat_writer"

    chase = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    outlets = {r.outlet for r in chase}
    assert outlets == {"sleeper_feed", "web_digest"}


def test_notes_maps_to_detail_not_blank():
    # Regression: the feed's field is `notes` (plural). If load() only knew
    # `detail`/`note` (singular), detail would be blank on every real row.
    official = for_roster(load(FIXTURE), ["Nick Chubb"])[0]
    assert official.detail == "foot"


def test_a_null_notes_value_yields_an_empty_detail_not_a_crash():
    chase = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    sleeper_row = [r for r in chase if r.outlet == "sleeper_feed"][0]
    assert sleeper_row.detail == ""


def test_tier_is_carried_but_is_corroboration_not_severity():
    chase = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    web_digest_row = [r for r in chase if r.outlet == "web_digest"][0]
    assert web_digest_row.tier == "corroborated"


def test_practice_is_never_parsed_out_of_notes_prose():
    # The web_digest note for Chase describes missing Wednesday practice in
    # prose, but there is no `practice` key on that row - practice must stay
    # blank rather than being regexed out of free text.
    chase = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    web_digest_row = [r for r in chase if r.outlet == "web_digest"][0]
    assert web_digest_row.practice == ""


def test_practice_is_populated_when_the_row_actually_carries_it():
    official = for_roster(load(FIXTURE), ["Nick Chubb"])[0]
    assert official.practice == "DNP"


def test_a_row_carrying_status_since_and_previous_status_round_trips_them():
    # This pair is the only change signal the feed gives us for free - the
    # feed has no practice field and this module keeps no history of its
    # own. Sunday needs to be able to say "changed from X on <date>".
    chase = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    sleeper_row = [r for r in chase if r.outlet == "sleeper_feed"][0]
    assert sleeper_row.status_since == "2026-08-27"
    assert sleeper_row.previous_status == "Questionable"


def test_a_row_lacking_status_since_yields_empty_string_not_none():
    # A bare `None` would render as the literal string "None" in a push
    # notification - the kind of thing that reaches a phone and cannot be
    # taken back.
    official = for_roster(load(FIXTURE), ["Nick Chubb"])[0]
    assert official.status_since == ""
    assert official.previous_status == ""
    assert official.status_since is not None
    assert official.previous_status is not None


def test_a_row_missing_a_player_name_key_raises_rather_than_blanking(tmp_path):
    import json

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "report": [],
        "intel": [{"team": "CIN", "status": "Questionable"}],
    }))
    with pytest.raises(ValueError):
        load(str(bad))


def test_a_missing_file_raises_rather_than_returning_nothing(tmp_path):
    with pytest.raises(IOError):
        load(str(tmp_path / "nope.json"))


def test_an_official_row_spelling_status_as_report_status_still_carries_it(tmp_path):
    """The official-row mapping is PROVISIONAL - it has never been run
    against a real `report` row. nflverse's injury report names the column
    `report_status`/`game_status` in places, and if that is what arrives,
    every official row would come back with status="" and print as a player
    with no designation. Same defensive fallback `notes`/`detail` already
    has, for the same failure."""
    p = tmp_path / "inj.json"
    p.write_text(json.dumps({
        "report": [{"player": "Nick Chubb", "team": "CLE",
                    "report_status": "Out", "notes": "foot",
                    "reported_date": "2026-09-05"}],
        "intel": [],
    }))
    rows = load(str(p))
    assert len(rows) == 1
    assert rows[0].status == "Out"


def test_a_whitespace_only_status_is_treated_as_absent_not_as_a_status(tmp_path):
    p = tmp_path / "inj.json"
    p.write_text(json.dumps({
        "report": [{"player": "Nick Chubb", "team": "CLE", "status": "   ",
                    "game_status": "Doubtful", "reported_date": "2026-09-05"}],
        "intel": [],
    }))
    assert load(str(p))[0].status == "Doubtful"


def test_an_official_row_with_no_status_field_at_all_stays_empty(tmp_path):
    """Not raised here: one malformed row must not take down the whole
    unattended alert. The honesty guarantee lives one layer up, where
    `alert._status_text` renders an official row's blank status as an
    explicit unknown rather than as a clean bill of health."""
    p = tmp_path / "inj.json"
    p.write_text(json.dumps({
        "report": [{"player": "Nick Chubb", "team": "CLE",
                    "reported_date": "2026-09-05"}],
        "intel": [],
    }))
    assert load(str(p))[0].status == ""


# ------------------------------------------------------------- intel age
#
# A Week 4 Friday alert told Jeff McConkey was "trending toward suiting up in
# Week 2" and Bowers "could return in Week 3" - while Bowers sat in the
# optimal lineup. The intel feed is a ~4-week rolling window, and for a
# player nobody has written about lately the newest item IS the stale one.

import datetime as _dt


def _r(source, date, name="Ladd McConkey"):
    from sffl.injuries import Report
    return Report(name=name, team="LAC", status="Day-to-Day", practice="",
                  reported_date=date, detail="x", source=source)


def test_intel_older_than_a_league_week_is_dropped_and_counted():
    from sffl.injuries import fresh_intel
    today = _dt.date(2026, 10, 2)
    kept, dropped = fresh_intel([_r("intel", "2026-09-15"),
                                 _r("intel", "2026-10-01")], today)
    assert [r.reported_date for r in kept] == ["2026-10-01"]
    assert dropped == 1


def test_the_boundary_is_one_league_week_inclusive():
    from sffl.injuries import INTEL_MAX_AGE_DAYS, fresh_intel
    today = _dt.date(2026, 10, 2)
    edge = (today - _dt.timedelta(days=INTEL_MAX_AGE_DAYS)).isoformat()
    past = (today - _dt.timedelta(days=INTEL_MAX_AGE_DAYS + 1)).isoformat()
    kept, dropped = fresh_intel([_r("intel", edge), _r("intel", past)], today)
    assert [r.reported_date for r in kept] == [edge] and dropped == 1


def test_official_rows_are_never_aged_out():
    # The official report is the record, and usually carries no date anyway.
    from sffl.injuries import fresh_intel
    kept, dropped = fresh_intel([_r("official", "2026-08-01")],
                                _dt.date(2026, 10, 2))
    assert len(kept) == 1 and dropped == 0


def test_undated_or_garbled_intel_is_kept_not_silently_hidden():
    # Unknown age is not "old". Hiding it would be a claim we cannot make.
    from sffl.injuries import fresh_intel
    kept, dropped = fresh_intel([_r("intel", ""), _r("intel", "soon")],
                                _dt.date(2026, 10, 2))
    assert len(kept) == 2 and dropped == 0


# --------------------------------------- CBS ids, TQB units (2026-10-20)
#
# The direct feed's rows carry CBS ids (sffl.direct_injuries). Constructed
# players and ids throughout.

from sffl.cbs_roster import RosterRow
from sffl.injuries import rows_to_reports, source_notes


def _row(name, team, cbs_id="", position="WR", status="Questionable",
         outlet="espn"):
    return Report(name=name, team=team, status=status, practice="",
                  reported_date="2026-10-23", detail="", source="intel",
                  outlet=outlet, cbs_id=cbs_id, position=position)


def test_the_new_fields_default_to_empty_for_old_style_rows():
    r = Report("Pat Example", "SEA", "Out", "", "2026-10-23", "", "official")
    assert (r.cbs_id, r.position, r.as_of) == ("", "", "")


def test_a_direct_row_carries_its_cbs_id_position_as_of_and_outlet():
    (r,) = rows_to_reports([{
        "player": "Pat Example", "team": "SEA", "position": "WR",
        "status": "Out", "source": "nflverse", "cbs_id": 9000001,
        "as_of": "2026-10-23 08:41 EDT"}], "official")
    assert (r.cbs_id, r.position, r.as_of, r.outlet) == (
        "9000001", "WR", "2026-10-23 08:41 EDT", "nflverse")


def test_the_cbs_id_wins_over_a_differently_spelled_name():
    roster = [RosterRow("Pat Example Jr.", "WR", "SEA", "9000001")]
    rows = [_row("Patrick Example", "SEA", cbs_id="9000001")]
    assert for_roster(rows, ["Pat Example Jr."], roster_rows=roster) == rows


def test_a_row_whose_id_names_someone_else_is_never_matched_by_name():
    # Two real players can share a name; the id already says this is not him.
    roster = [RosterRow("Pat Example", "WR", "SEA", "9000001")]
    other = _row("Pat Example", "SEA", cbs_id="9000099")
    assert for_roster([other], ["Pat Example"], roster_rows=roster) == []


def test_a_row_with_no_cbs_id_falls_back_to_name_and_team():
    roster = [RosterRow("Pat Example", "WR", "JAC", "9000001")]
    same_team = _row("Pat Example", "JAX")      # normalized: JAX is JAC
    other_team = _row("Pat Example", "MIA")
    no_team = _row("Pat Example", "")
    got = for_roster([same_team, other_team, no_team], ["Pat Example"],
                     roster_rows=roster)
    assert got == [same_team, no_team]


def test_a_team_qb_unit_gets_its_quarterbacks_and_a_defense_gets_nothing():
    roster = [RosterRow("Hawks", "TQB", "SEA", "8001"),
              RosterRow("Hawks", "DST", "SEA", "8002")]
    qb = _row("Dee Thrower", "SEA", cbs_id="9000050", position="QB")
    wr = _row("Pat Example", "SEA", cbs_id="9000001", position="WR")
    other_qb = _row("Al Passer", "MIA", cbs_id="9000060", position="QB")
    assert for_roster([qb, wr, other_qb], ["Hawks", "Hawks"],
                      roster_rows=roster) == [qb]


def test_each_row_is_emitted_once_in_roster_order():
    roster = [RosterRow("Lee Sample", "RB", "MIA", "9000002"),
              RosterRow("Pat Example", "WR", "SEA", "9000001")]
    pat = _row("Pat Example", "SEA", cbs_id="9000001")
    lee = _row("Lee Sample", "MIA", cbs_id="9000002")
    got = for_roster([pat, lee, pat], ["Lee Sample", "Pat Example"],
                     roster_rows=roster)
    assert got == [lee, pat]


def test_without_roster_rows_matching_is_by_name_exactly_as_before():
    roster_names = ["Pat Example"]
    other = _row("Pat Example", "MIA", cbs_id="9000099")
    assert for_roster([other], roster_names) == [other]


def test_source_notes_name_each_failed_source(tmp_path):
    path = tmp_path / "x.direct.json"
    path.write_text(json.dumps({"report": [], "intel": [], "meta": {"sources": {
        "nflverse": {"ok": True},
        "espn": {"ok": False, "error": "HTTP 403"},
        "sleeper": {"ok": False}}}}))
    assert source_notes(str(path)) == [
        "!! espn unavailable this run: HTTP 403",
        "!! sleeper unavailable this run: unknown error"]


def test_source_notes_say_how_old_the_sleeper_statuses_are(tmp_path):
    path = tmp_path / "x.direct.json"

    def notes(age):
        path.write_text(json.dumps({"report": [], "intel": [], "meta": {"sources": {
            "sleeper": {"ok": True, "fetched_at": "2026-10-23T13:45:00",
                        "age_hours": age}}}}))
        return source_notes(str(path))

    assert notes(3.0) == ["Sleeper statuses as of 2026-10-23 13:45 (3 h old)"]
    assert notes(30.0) == ["!! Sleeper statuses as of 2026-10-23 13:45 (30 h old)"]


def test_a_statsdeck_file_has_no_source_notes():
    assert source_notes(FIXTURE) == []


def test_a_roster_row_whose_id_was_not_captured_matches_by_name_and_team():
    # The roster page puts a playing week's game time on its own line, so the
    # capture's id prefix lands on the row's last line and the name line has
    # none. Such a row still finds the direct feed's id-carrying rows.
    roster = [RosterRow("Pat Example", "WR", "SEA", "")]
    with_id = _row("Pat Example", "SEA", cbs_id="9000001")
    other_team = _row("Pat Example", "MIA", cbs_id="9000099")
    assert for_roster([with_id, other_team], ["Pat Example"],
                      roster_rows=roster) == [with_id]
