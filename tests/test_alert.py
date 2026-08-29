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

# A row the feed itself marks as having moved status - the only genuine
# differentiator Sunday has, now that the real feed turns out to carry no
# practice field at all (see sffl.injuries).
CHASE_STATUS_CHANGED = Report(
    name="Ja'Marr Chase", team="CIN", status="Questionable", practice="",
    reported_date="2026-09-07", detail="knee responding well",
    source="official", outlet="", tier="",
    status_since="2026-09-06", previous_status="Doubtful")

LINEUP = LineupResult(
    slots=[("RB", Candidate("Bijan Robinson", "RB", 18.0)),
           ("WR/TE", Candidate("Ja'Marr Chase", "WR", 16.5))],
    total=34.5)


def _block(msg, heading):
    """The text under one heading only, so an assertion cannot be satisfied
    by the same name appearing in a different block of the message."""
    start = msg.index(heading)
    end = msg.find("\n\n", start)
    return msg[start:end if end != -1 else len(msg)]


class _ReportPlusPoints(object):
    """Duck-types a `Report` plus a `points` attribute a future StatsDeck
    payload could add. Used only to give teeth to the points-leak test - see
    its comment below.
    """

    def __init__(self, report, points):
        self.__dict__.update(report._asdict())
        self.points = points


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
    # Pinned on the literal Friday heading and the ABSENCE of Sunday's, not
    # just on "Limited" appearing somewhere - a per-row "practice: Limited"
    # substring survives even if the `kind` branch that picks the heading is
    # deleted, which is exactly how this test failed to guard anything
    # before. See the mutation check recorded in task-6-report.md.
    msg = compose("friday", 2, [CHASE_OFFICIAL], LINEUP, [])
    assert "Limited" in msg
    assert "PRACTICE / STATUS on your roster:" in msg
    assert "WHAT CHANGED" not in msg
    assert msg.lower().index("practice / status") < msg.lower().index("best lineup")


def test_sunday_leads_with_official_status():
    # Pinned on Sunday's literal "WHAT CHANGED" lead heading, its absence of
    # Friday's heading, and that the change block precedes the status block -
    # not just on "Out"/"Nick Chubb" appearing anywhere, which survives even
    # if Sunday is rendered exactly like Friday.
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [])
    assert "Out" in msg
    assert "Nick Chubb" in msg
    assert "WHAT CHANGED" in msg
    assert "PRACTICE / STATUS" not in msg
    assert msg.lower().index("what changed") < msg.lower().index("official status")


def test_sunday_change_block_names_previous_status_and_change_date():
    # The feed's own `previous_status` / `status_since` are the genuine
    # change signal Sunday leads with - the player, what it moved from, what
    # it is now, and the date it moved.
    msg = compose("sunday", 2, [CHASE_STATUS_CHANGED], LINEUP, [])
    assert "Doubtful" in msg
    assert "Questionable" in msg
    assert "2026-09-06" in msg  # status_since - the date it moved

    # AND the row is still in the official block below. This test fed
    # exactly the input that broke it - an OFFICIAL row that also CHANGED -
    # and asserted nothing about that block, so the change block emptying
    # the record passed unchallenged: "OFFICIAL STATUS on your roster: no
    # designations on your roster." printed while the row said Out.
    assert "no designations on your roster" not in msg
    official = _block(msg, "OFFICIAL STATUS on your roster:")
    assert "Ja'Marr Chase" in official
    assert "Questionable" in official


def test_a_row_that_is_both_official_and_changed_still_appears_in_the_record():
    # The worst case the previous behavior produced: a starter ruled OUT on
    # Sunday morning is BOTH official AND changed, so he was the one row
    # removed from the official block - which then declared the roster
    # clean, ninety minutes before kickoff.
    chubb_ruled_out = Report(
        name="Nick Chubb", team="CLE", status="Out", practice="",
        reported_date="2026-09-07", detail="foot", source="official",
        outlet="", tier="", status_since="2026-09-07",
        previous_status="Questionable")
    msg = compose("sunday", 2, [chubb_ruled_out], LINEUP, [])
    assert "no designations on your roster" not in msg
    official = _block(msg, "OFFICIAL STATUS on your roster:")
    assert "Nick Chubb" in official
    assert "Out" in official
    # Still LED with as a change - the Sunday differentiator is intact.
    assert msg.index("WHAT CHANGED") < msg.index("OFFICIAL STATUS")
    assert "Questionable -> Out" in msg


def test_sunday_with_no_changes_says_so_explicitly():
    # CHUBB_OUT carries no previous_status, so nothing changed. Sunday must
    # state that plainly rather than printing an empty "WHAT CHANGED"
    # heading with nothing under it.
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [])
    assert "no status changes" in msg.lower()


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
    #
    # `Report` itself has no points field today, which made the original
    # form of this test tautological - it could not fail under any real
    # leak. Given teeth here: simulate the future field a StatsDeck payload
    # change could add (a row with everything a real Report has, PLUS a
    # `points` attribute) and assert the renderer never touches it. This
    # actually exercises the property that matters - the renderer reads only
    # the fields it names explicitly (r.status, r.practice, r.detail, ...)
    # rather than dumping a row's fields generically - so a future `points`
    # field cannot reach the phone even before anyone thinks to test for it.
    fishy = _ReportPlusPoints(CHASE_OFFICIAL, 987.65)
    msg = compose("friday", 2, [fishy, CHUBB_OUT], LINEUP, [])
    assert "987.65" not in msg
    assert "PPR" not in msg.upper()


def test_an_unknown_kind_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        compose("tuesday", 2, [], LINEUP, [])


# --- current_starters / START-SIT diff -------------------------------------

# The exact string `compose` produced before `current_starters` existed, for
# this exact call, pinned verbatim (not re-derived) so a change to the
# default behavior would have to edit this literal, not slip past silently.
_PRE_CURRENT_STARTERS_PINNED_OUTPUT = (
    "Sunday inactives\nWhat changed since Friday. Kickoff is close.\n\n"
    "Roster captured 2 days ago.\n\n"
    "WHAT CHANGED since the last report:\n"
    "  no status changes since the previous report.\n\n"
    "OFFICIAL STATUS on your roster:\n"
    "  - Nick Chubb (CLE) Out / practice: DNP / foot [official 2026-09-05]\n\n"
    "INTEL (supplements the official report, never overrides it):\n"
    "  nothing new.\n\n"
    "EXCLUDED from the lineup - will not play:\n"
    "  - Nick Chubb (O)\n\n"
    "BEST LINEUP (34.50 pts, this league's scoring):\n"
    "  RB     Bijan Robinson\n"
    "  WR/TE  Ja'Marr Chase"
)


def test_current_starters_none_renders_exactly_as_before():
    # `current_starters` defaults to None, and None must mean "the caller
    # does not know" - not "known and empty" - so it must render NOTHING
    # extra: the message is byte-for-byte identical to what this module
    # produced before the parameter existed. Pinned against a literal
    # captured from the pre-change implementation, not re-derived from the
    # current code, so a regression here cannot silently pass.
    args = ("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert compose(*args) == _PRE_CURRENT_STARTERS_PINNED_OUTPUT
    assert compose(*args, current_starters=None) == _PRE_CURRENT_STARTERS_PINNED_OUTPUT
    assert "START / SIT" not in compose(*args)


def test_a_real_difference_renders_both_the_start_and_the_sit_name():
    # Bijan is started both places (no mention needed); Chase is optimal but
    # not currently started (a START); Chubb is currently started but not in
    # the optimal two (a SIT).
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=["Nick Chubb", "Bijan Robinson"])
    assert "START / SIT vs your current CBS lineup:" in msg
    assert "Ja'Marr Chase" in msg
    assert "Nick Chubb" in msg
    assert "already optimal" not in msg.lower()


def test_an_already_optimal_lineup_says_so_and_prints_no_empty_block():
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=["Bijan Robinson", "Ja'Marr Chase"])
    assert "lineup is already optimal" in msg.lower()
    # No dangling two-column header with nothing under it.
    assert "START           SIT" not in msg


def test_current_starters_empty_list_is_known_and_empty_not_unknown():
    # [] means "known: nothing is started" - a real state that CAN recommend
    # starting every optimal player, unlike None.
    msg = compose("friday", 2, [], LINEUP, [], current_starters=[])
    assert "START / SIT vs your current CBS lineup:" in msg
    assert "already optimal" not in msg.lower()
    assert "Bijan Robinson" in msg
    assert "Ja'Marr Chase" in msg


def _start_sit_block(msg):
    """The text of the START/SIT section only, for assertions that must not
    be satisfied by the same name appearing in some other block (e.g. the
    EXCLUDED list)."""
    start = msg.index("START / SIT vs your current CBS lineup:")
    end = msg.index("\n\n", start)
    return msg[start:end]


def test_a_sidelined_player_is_never_recommended_as_a_start():
    # Nick Chubb is (unrealistically, for this test) present in the optimal
    # lineup's own slots AND sidelined. The diff must not recommend starting
    # him regardless of how he got into lineup_result - the guard does not
    # get to assume upstream filtering already handled it.
    lineup_with_sidelined_pick = LineupResult(
        slots=[("RB", Candidate("Nick Chubb", "RB", 5.0)),
               ("WR/TE", Candidate("Ja'Marr Chase", "WR", 16.5))],
        total=21.5)
    msg = compose("friday", 2, [], lineup_with_sidelined_pick,
                  [("Nick Chubb", "O")], current_starters=[])
    block = _start_sit_block(msg)
    assert "Nick Chubb" not in block
    assert "Ja'Marr Chase" in block
    # He is still named - just in EXCLUDED, not as a start recommendation.
    assert "Nick Chubb" in msg


def test_punctuation_differing_name_is_not_reported_as_a_change():
    # The roster page and the projections page disagree about punctuation.
    # "JaMarr Chase" (no apostrophe) here must be recognized as the same
    # player as "Ja'Marr Chase" in LINEUP's optimal slot, via normalize_name -
    # a literal comparison would invent a phantom START and a phantom SIT.
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=["JaMarr Chase", "Bijan Robinson"])
    assert "lineup is already optimal" in msg.lower()


# --- I2: a blank status is never rendered as data --------------------------

# An official row whose status came back empty. The official-row field
# mapping in sffl.injuries is PROVISIONAL - if the real feed spells the
# field `report_status`, every official row arrives exactly like this.
BLANK_OFFICIAL = Report(
    name="Nick Chubb", team="CLE", status="", practice="",
    reported_date="2026-09-05", detail="", source="official")

BLANK_OFFICIAL_CHANGED = Report(
    name="Nick Chubb", team="CLE", status="", practice="",
    reported_date="2026-09-07", detail="", source="official", outlet="",
    tier="", status_since="2026-09-06", previous_status="Questionable")


def test_an_official_row_with_no_status_says_unknown_not_no_detail():
    # "no detail" reads as "nothing wrong with this player". The whole row
    # arriving empty is a DATA problem and must look like one.
    msg = compose("friday", 2, [BLANK_OFFICIAL], LINEUP, [])
    assert "STATUS UNKNOWN" in msg
    assert "no detail" not in msg


def test_a_blank_status_never_renders_as_an_empty_arrow_target():
    # `"%s -> %s" % (prev, "")` produced "Questionable -> , since ..." - a
    # line that reads as a change to nothing in particular.
    msg = compose("sunday", 2, [BLANK_OFFICIAL_CHANGED], LINEUP, [])
    assert "-> ," not in msg
    assert "STATUS UNKNOWN" in msg


def test_an_intel_row_with_no_status_is_not_flagged_as_unknown():
    # Intel rows routinely carry only prose - the real captured feed has
    # one. Only the official record is held to having a status.
    msg = compose("friday", 2, [CHASE_INTEL], LINEUP, [])
    assert "STATUS UNKNOWN" not in msg
    assert "expected to play per beat writer" in msg


# --- I4: row-level provenance actually reaches the phone -------------------

CHASE_WEB_DIGEST = Report(
    name="Ja'Marr Chase", team="CIN", status="Day-to-Day", practice="",
    reported_date="2026-08-26", detail="did not practice Wednesday",
    source="intel", outlet="web_digest", tier="corroborated")

CHUBB_UNCONFIRMED = Report(
    name="Nick Chubb", team="CLE", status="", practice="",
    reported_date="2026-09-06", detail="game-time decision per beat writer",
    source="intel", outlet="beat_writer", tier="unconfirmed")


def test_an_intel_line_names_the_outlet_it_came_from():
    # Without this every intel line read "[intel <date>]", which only
    # repeats the block heading it already sits under - and two intel rows
    # disagreeing about the same player were indistinguishable.
    msg = compose("friday", 2, [CHASE_WEB_DIGEST, CHUBB_UNCONFIRMED],
                  LINEUP, [])
    assert "web_digest" in msg
    assert "beat_writer" in msg


def test_tier_is_rendered_as_corroboration_never_as_a_designation():
    # `tier` is CORROBORATION STRENGTH, not injury severity. A bare
    # "unconfirmed" next to a status would read as a second opinion on the
    # player; it must always carry the word that says what it measures.
    msg = compose("friday", 2, [CHASE_WEB_DIGEST, CHUBB_UNCONFIRMED],
                  LINEUP, [])
    assert "corroboration: corroborated" in msg
    assert "corroboration: unconfirmed" in msg
    for line in msg.splitlines():
        for value in ("corroborated", "unconfirmed"):
            if value in line:
                assert "corroboration: %s" % value in line


def test_an_official_row_carries_no_outlet_and_prints_none():
    # Official rows never carry an outlet label (see sffl.injuries), so the
    # tag stays the bare "[official <date>]" it always was.
    msg = compose("friday", 2, [CHUBB_OUT], LINEUP, [])
    assert "[official 2026-09-05]" in msg
    assert "via" not in msg
