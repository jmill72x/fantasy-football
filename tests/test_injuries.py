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
