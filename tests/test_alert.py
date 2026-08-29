import pytest

from sffl.alert import STALE_ROSTER_DAYS, compose
from sffl.injuries import Report
from sffl.lineup import Candidate, LineupResult

CHASE_OFFICIAL = Report("Ja'Marr Chase", "CIN", "Questionable", "Limited",
                        "2026-09-05", "hyperextended knee", "official")
CHASE_INTEL = Report("Ja'Marr Chase", "CIN", "", "", "2026-09-06",
                     "expected to play per beat writer", "intel")
CHUBB_OUT = Report("Nick Chubb", "CLE", "Out", "DNP", "2026-09-05",
                   "foot", "official")

LINEUP = LineupResult(
    slots=[("RB", Candidate("Bijan Robinson", "RB", 18.0)),
           ("WR/TE", Candidate("Ja'Marr Chase", "WR", 16.5))],
    total=34.5)


def test_a_quiet_week_still_produces_a_message():
    # An absent push must mean a DEAD JOB, never a quiet week. If this
    # function could return "" the two would be indistinguishable.
    msg = compose("friday", 2, [], LINEUP, [])
    assert msg.strip()
    assert "no" in msg.lower()
    # Strengthened beyond the brief: "no" is a substring of many words, so
    # pin the actual behavior it is meant to guarantee - the message must
    # explicitly state there are no designations on the roster.
    assert msg.strip() != ""
    assert "no designations on your roster" in msg.lower()


def test_friday_leads_with_practice_participation():
    msg = compose("friday", 2, [CHASE_OFFICIAL], LINEUP, [])
    assert "Limited" in msg
    assert msg.lower().index("practice") < msg.lower().index("lineup")


def test_sunday_leads_with_official_status():
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [])
    assert "Out" in msg
    assert "Nick Chubb" in msg


def test_the_message_names_which_job_produced_it():
    assert "Friday" in compose("friday", 2, [], LINEUP, [])
    assert "Sunday" in compose("sunday", 2, [], LINEUP, [])


def test_every_intel_line_carries_its_reported_date():
    msg = compose("friday", 2, [CHASE_INTEL], LINEUP, [])
    assert "2026-09-06" in msg


def test_official_and_intel_are_both_shown_when_they_disagree():
    # The alert quotes; it does not adjudicate.
    msg = compose("friday", 2, [CHASE_OFFICIAL, CHASE_INTEL], LINEUP, [])
    assert "hyperextended knee" in msg
    assert "beat writer" in msg
    assert "2026-09-05" in msg and "2026-09-06" in msg


def test_a_stale_roster_says_so_loudly():
    msg = compose("friday", STALE_ROSTER_DAYS + 1, [], LINEUP, [])
    assert "STALE" in msg.upper()


def test_a_fresh_roster_still_states_its_age():
    # Visible staleness beats invisible staleness - the age prints every time.
    assert "2 day" in compose("friday", 2, [], LINEUP, [])


def test_a_capture_failure_replaces_the_roster_report_entirely():
    msg = compose("sunday", 2, [], LINEUP, [], capture_error="session expired")
    assert "session expired" in msg
    # Must NOT present a lineup it could not verify.
    assert "Bijan Robinson" not in msg


def test_sidelined_players_are_named_not_silently_dropped():
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert "Nick Chubb" in msg
    assert "excluded" in msg.lower()


def test_no_statsdeck_fantasy_points_can_leak_in():
    # StatsDeck is wired to a half-PPR Yahoo league. Its points are wrong
    # here by construction, so nothing in the payload should reach the text.
    msg = compose("friday", 2, [CHASE_OFFICIAL, CHUBB_OUT], LINEUP, [])
    assert "PPR" not in msg.upper()


def test_an_unknown_kind_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        compose("tuesday", 2, [], LINEUP, [])
