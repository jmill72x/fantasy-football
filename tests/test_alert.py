import pytest

from sffl.alert import (POSITION_NOT_CAPTURED, PROJECTION_MISSING,
                        PROJECTION_PAGE_FAILED, ROSTER_NAME_AMBIGUOUS,
                        STALE_INJURIES_MINUTES, STALE_ROSTER_DAYS,
                        compose)
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


def test_an_all_projections_failure_gets_its_own_message_not_the_roster_ones():
    # Fix round 1, IMPORTANT 3: `_cmd_alert` used to reuse `capture_error`'s
    # roster-failure prose ("No roster could be read... Fix: cbs_login.py")
    # for this case too - untrue when the roster capture WORKED FINE and
    # only the four projection pages failed, and it points the reader at
    # the wrong fix (a login problem, when login was never the issue).
    msg = compose("sunday", 2, [], LINEUP, [],
                  projections_capture_error="all 4 position-group "
                  "projection pages failed to capture or parse: ...")
    assert "all 4 position-group" in msg
    assert "Bijan Robinson" not in msg
    # The roster-failure-specific claims - including its fix instruction -
    # must NOT appear here. "cbs_login.py" alone is too strict a check (this
    # message correctly explains that re-running it will NOT help, which
    # legitimately mentions the filename); the exact capture_error fix line
    # is the thing that must be absent.
    assert "No roster could be read" not in msg
    assert "Fix: ./.venv/bin/python ops/cbs_login.py" not in msg
    assert "will not help here" in msg
    # And it must say the roster itself was fine - the opposite claim from
    # the capture_error branch.
    assert "roster" in msg.lower() and "read successfully" in msg.lower()


def test_capture_error_wins_over_projections_capture_error_if_both_given():
    # Should never happen in practice (capture_error means the roster
    # capture never even reached the projections loop), but the ordering
    # is deliberate defensive behavior, not undefined.
    msg = compose("sunday", 2, [], LINEUP, [],
                  capture_error="session expired",
                  projections_capture_error="all 4 pages failed")
    assert "session expired" in msg
    assert "all 4 pages failed" not in msg


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
    "  RB     Bijan Robinson        18.00\n"
    "  WR/TE  Ja'Marr Chase         16.50"
)
# AMENDED 2026-08-30, deliberately, for the roster_board change. Every
# lineup row now carries its own projected points, so this literal moved by
# exactly one column on two lines and NOTHING else - verified against the
# failure diff before editing, not re-derived by pasting the new output.
# The tests below still pin what they were written to pin: that each
# OPTIONAL parameter, left at its default, adds no section. `roster_board`
# defaulting to None is asserted the same way, in
# test_roster_board_defaults_to_no_bench_section.


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
                  current_starters=[("Nick Chubb", "RB", ""),
                                    ("Bijan Robinson", "RB", "")])
    assert "START / SIT vs your current CBS lineup:" in msg
    assert "Ja'Marr Chase" in msg
    assert "Nick Chubb" in msg
    assert "already optimal" not in msg.lower()


def test_an_already_optimal_lineup_says_so_and_prints_no_empty_block():
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", "")])
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
                  current_starters=[("JaMarr Chase", "WR", ""),
                                    ("Bijan Robinson", "RB", "")])
    assert "lineup is already optimal" in msg.lower()


def test_current_starters_team_must_already_be_normalized_by_the_caller():
    """Task 3b minor (a): `_start_sit_diff` (via `compose`) compares
    `current_starters`' team against `lineup_result` picks' team with NO
    normalization of its own - it trusts the caller to have already done
    that (`sffl.cli._cmd_alert` now normalizes `RosterRow.team` before
    building `current_starters`; see its comment). This test pins the
    MECHANISM that fix depends on: an un-normalized team code ("JAX", CBS's
    own raw roster-page spelling) does NOT match the canonical code
    ("JAC") a `PlayerProjection`-derived `Candidate` always carries, so
    the SAME real player renders as BOTH a START and a SIT - exactly the
    double-listing bug the fix prevents by normalizing before this point.
    """
    thomas_lineup = LineupResult(
        slots=[("WR/TE", Candidate("Brian Thomas Jr.", "WR", 10.0, "JAC"))],
        total=10.0)

    # Un-normalized team code reaching this function directly: the bug,
    # reproduced at the unit level.
    msg_raw = compose("friday", 2, [], thomas_lineup, [],
                      current_starters=[("Brian Thomas Jr.", "WR", "JAX")])
    assert "Brian Thomas Jr." in _start_sit_block(msg_raw)
    assert "already optimal" not in msg_raw.lower()

    # The SAME player, ALREADY normalized (what `_cmd_alert` now passes):
    # correctly recognized as already optimal, no phantom start/sit.
    msg_normalized = compose(
        "friday", 2, [], thomas_lineup, [],
        current_starters=[("Brian Thomas Jr.", "WR", "JAC")])
    assert "already optimal" in msg_normalized.lower()


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


# --- C1: a player who was never evaluated is never a SIT -------------------

def test_an_unevaluated_starter_is_never_rendered_as_a_sit():
    # The real shape of this bug: CBS sets eight starters, the projections
    # group covers RB/WR/TE only, so the TQB, the kicker and the defense
    # could NEVER be in the optimal lineup and landed in SIT every single
    # week - merit-based bench advice, in the block placed first.
    msg = compose(
        "friday", 2, [], LINEUP, [],
        current_starters=[("Bijan Robinson", "RB", ""),
                          ("Ja'Marr Chase", "WR", ""),
                          ("Chargers", "TQB", ""),
                          ("Evan McPherson", "K", ""),
                          ("Patriots", "DST", "")],
        unevaluated_starters=[("Chargers", "TQB", POSITION_NOT_CAPTURED),
                              ("Evan McPherson", "K", POSITION_NOT_CAPTURED),
                              ("Patriots", "DST", POSITION_NOT_CAPTURED)])
    block = _block(msg, "START / SIT vs your current CBS lineup:")
    for name in ("Chargers", "Evan McPherson", "Patriots"):
        assert name not in block
        # Named, not silently dropped: vanishing reads as "no longer on your
        # roster" rather than "not evaluated" - _cmd_week's own reasoning.
        assert name in msg


def test_the_unevaluated_section_does_not_read_as_advice():
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Evan McPherson", "K", "")],
                  unevaluated_starters=[("Evan McPherson", "K",
                                         POSITION_NOT_CAPTURED)])
    section = _block(msg, "NOT EVALUATED for start/sit")
    assert "NOT recommendations to bench anyone" in section
    assert "Evan McPherson (K)" in section


def test_a_scope_limit_and_a_data_problem_are_told_apart():
    # Conflating them costs a real signal: one is a known limit of what this
    # job captures, the other means a player who SHOULD have had a
    # projection did not.
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Evan McPherson", "K", ""),
                                    ("Jameson Williams", "WR", "")],
                  unevaluated_starters=[
                      ("Evan McPherson", "K", POSITION_NOT_CAPTURED),
                      ("Jameson Williams", "WR", PROJECTION_MISSING)])
    section = _block(msg, "NOT EVALUATED for start/sit")
    assert "DATA PROBLEM" in section
    scope_at = section.index("Evan McPherson")
    data_at = section.index("Jameson Williams")
    limit_at = section.index("not in the projections page this job captures")
    problem_at = section.index("DATA PROBLEM")
    # Each name sits under its own explanation, not lumped under one.
    assert limit_at < scope_at < problem_at < data_at


def test_a_transient_page_failure_is_not_worded_as_a_permanent_limit():
    # Fix round 1, IMPORTANT 2: with the K page failed THIS RUN,
    # Evan McPherson used to be filed under POSITION_NOT_CAPTURED, whose
    # wording ("their position is not in the projections page this job
    # captures... it is a limit of the tool") is FALSE when the position is
    # ordinarily captured and only this run's fetch of it failed. The two
    # reasons must render with different, non-overlapping wording, and the
    # transient one must say it is NOT permanent.
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Evan McPherson", "K", "")],
                  unevaluated_starters=[("Evan McPherson", "K",
                                         PROJECTION_PAGE_FAILED)])
    section = _block(msg, "NOT EVALUATED for start/sit")
    assert "Evan McPherson (K)" in section
    assert "NOT a permanent limit" in section
    assert "is not in the projections page this job captures" not in section
    assert "DATA PROBLEM" not in section


def test_a_permanent_scope_limit_and_a_transient_page_failure_are_told_apart():
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Evan McPherson", "K", ""),
                                    ("Patriots", "DST", "")],
                  unevaluated_starters=[
                      ("Evan McPherson", "K", PROJECTION_PAGE_FAILED),
                      ("Patriots", "DST", POSITION_NOT_CAPTURED)])
    section = _block(msg, "NOT EVALUATED for start/sit")
    assert "NOT a permanent limit" in section
    assert "is not in the projections page" in section
    # Each name sits under ITS OWN heading, not the other's - split the
    # section at whichever heading comes first (compose renders them in a
    # fixed order that is an implementation detail this test should not
    # assume) and confirm each name appears on only one side.
    transient_idx = section.index("NOT a permanent limit")
    permanent_idx = section.index("is not in the projections page")
    if transient_idx < permanent_idx:
        transient_block, permanent_block = (section[:permanent_idx],
                                            section[permanent_idx:])
    else:
        permanent_block, transient_block = (section[:transient_idx],
                                            section[transient_idx:])
    assert "Evan McPherson" in transient_block
    assert "Evan McPherson" not in permanent_block
    assert "Patriots" in permanent_block
    assert "Patriots" not in transient_block


def test_a_roster_name_ambiguous_between_two_positions_is_reported_and_scored_as_neither():
    # Fix round 1's CRITICAL fix (SUPERSEDED, same day, by a more complete
    # one - see ROSTER_NAME_AMBIGUOUS's comment above): a reviewer
    # reproduced a real NFL team (e.g. "Chargers") rostered for BOTH TQB
    # and DST silently losing its DST slot to `-- UNFILLED` with no
    # mention anywhere. Round 1's fix routed BOTH ambiguous entries here
    # under ROSTER_NAME_AMBIGUOUS; `_cmd_alert` no longer produces this
    # reason (`cbs_roster.parse_lineup_rows` resolves both entries
    # correctly instead of merely flagging them), but `compose` must still
    # render it correctly if it is ever passed - this pins that contract.
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Chargers", "TQB", "")],
                  unevaluated_starters=[
                      ("Chargers", "TQB", ROSTER_NAME_AMBIGUOUS),
                      ("Chargers", "DST", ROSTER_NAME_AMBIGUOUS)])
    section = _block(msg, "NOT EVALUATED for start/sit")
    assert "Chargers (TQB)" in section
    assert "Chargers (DST)" in section
    assert "more than once" in section
    assert "NEITHER was scored" in section
    # And it must not leak into the diff as a SIT recommendation, the exact
    # prohibited outcome.
    diff_block = _block(msg, "START / SIT vs your current CBS lineup:")
    assert "Chargers" not in diff_block


def test_already_optimal_is_not_claimed_when_someone_was_not_evaluated():
    # "lineup is already optimal" claims a comparison that did not happen
    # for part of the lineup.
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", ""),
                                    ("Patriots", "DST", "")],
                  unevaluated_starters=[("Patriots", "DST",
                                         POSITION_NOT_CAPTURED)])
    assert "already optimal" not in msg.lower()
    assert "could be evaluated" in msg


def test_no_unevaluated_starters_renders_no_section_and_keeps_the_old_wording():
    msg = compose("friday", 2, [], LINEUP, [],
                  current_starters=[("Bijan Robinson", "RB", ""),
                                    ("Ja'Marr Chase", "WR", "")],
                  unevaluated_starters=[])
    assert "NOT EVALUATED" not in msg
    assert "lineup is already optimal" in msg.lower()


def test_the_parameter_defaults_so_existing_callers_are_unaffected():
    args = ("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert compose(*args) == _PRE_CURRENT_STARTERS_PINNED_OUTPUT
    assert (compose(*args, unevaluated_starters=None)
            == _PRE_CURRENT_STARTERS_PINNED_OUTPUT)


def test_an_unknown_unevaluated_reason_raises_rather_than_guessing():
    # The reason decides whether the reader is told "known limit of the
    # tool" or "your data is broken". Guessing tells them the wrong one.
    with pytest.raises(ValueError):
        compose("friday", 2, [], LINEUP, [], current_starters=[],
                unevaluated_starters=[("Evan McPherson", "K", "who-knows")])


# --- C2: a failed injury fetch is not a clean bill of health ---------------

def test_a_failed_fetch_never_renders_as_no_designations():
    # The whole defect: with StatsDeck down there is no file, `reports` is
    # [], and the digest printed "no designations on your roster." and
    # "nothing new." - byte-identical to a genuinely quiet week.
    msg = compose("friday", 2, [], LINEUP, [],
                  injury_error="injuries.json does not exist")
    assert "no designations on your roster" not in msg
    assert "nothing new." not in msg
    assert "INJURY DATA UNAVAILABLE" in msg
    assert "injuries.json does not exist" in msg
    assert "NOT FETCHED" in msg


def test_a_failed_fetch_on_sunday_does_not_claim_nothing_changed():
    msg = compose("sunday", 2, [], LINEUP, [],
                  injury_error="claude -p returned no file")
    assert "no status changes since the previous report" not in msg
    assert "NOT FETCHED" in msg


def test_a_quiet_week_and_a_failed_fetch_do_not_render_the_same():
    quiet = compose("friday", 2, [], LINEUP, [], injuries_age_minutes=0)
    broken = compose("friday", 2, [], LINEUP, [], injury_error="down")
    assert quiet != broken
    assert "no designations on your roster" in quiet
    assert "no designations on your roster" not in broken


def test_the_warning_precedes_the_blocks_it_explains():
    msg = compose("sunday", 2, [], LINEUP, [], injury_error="down")
    assert msg.index("INJURY DATA UNAVAILABLE") < msg.index("WHAT CHANGED")


def test_a_failed_fetch_does_not_claim_the_feed_carried_no_practice_data():
    # That line is a statement about what a feed we actually read contained.
    msg = compose("friday", 2, [], LINEUP, [], injury_error="down")
    assert "feed carried no practice data" not in msg


def test_fresh_injury_data_states_its_age():
    msg = compose("friday", 2, [CHUBB_OUT], LINEUP, [], injuries_age_minutes=3)
    assert "Injury data fetched 3 minutes ago." in msg
    assert "STALE INJURY DATA" not in msg


def test_injury_data_not_from_this_run_says_so_loudly():
    # The roster file is written milliseconds before it is read and can
    # never be stale; the injuries file is the input that genuinely can be.
    msg = compose("friday", 2, [CHUBB_OUT], LINEUP, [],
                  injuries_age_minutes=STALE_INJURIES_MINUTES + 1)
    assert "STALE INJURY DATA" in msg
    assert "EARLIER run" in msg
    # The rows are still shown - they are real, just old.
    assert "Nick Chubb" in msg


def test_the_injury_parameters_default_so_existing_callers_are_unaffected():
    args = ("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert compose(*args) == _PRE_CURRENT_STARTERS_PINNED_OUTPUT


# --------------------------------------------------------------- roster board
#
# The defect these cover, in one sentence: the optimizer always CONSIDERED
# all thirteen rostered players, but the digest only ever NAMED the eight it
# started, so every bench projection - the numbers that justify the pick -
# was computed and then thrown away before the message was built.

BOARD_LINEUP = LineupResult(
    slots=[("RB", Candidate("Bijan Robinson", "RB", 18.0, "ATL")),
           ("WR/TE", Candidate("Ja'Marr Chase", "WR", 16.5, "CIN"))],
    total=34.5)


def _board(*rows):
    """BoardRow list; each row is (name, pos, team, points, status, why)."""
    from sffl.alert import BoardRow
    return [BoardRow(*r) for r in rows]


def test_roster_board_defaults_to_no_bench_section():
    # Same contract every other optional parameter here has: None means "the
    # caller does not know the roster", which must render NOTHING rather
    # than asserting an empty bench. This is what lets the pinned literal
    # above stay meaningful.
    msg = compose("sunday", 2, [], BOARD_LINEUP, [])
    assert "BENCH" not in msg
    assert compose("sunday", 2, [], BOARD_LINEUP, [], roster_board=None) == msg


def test_bench_names_every_rostered_player_the_lineup_did_not_start():
    board = _board(
        ("Bijan Robinson", "RB", "ATL", 18.0, "", None),
        ("Ja'Marr Chase", "WR", "CIN", 16.5, "", None),
        ("Rico Dowdle", "RB", "CAR", 9.25, "", None),
        ("Tucker Kraft", "TE", "GB", 7.5, "", None),
    )
    msg = compose("sunday", 2, [], BOARD_LINEUP, [], roster_board=board)
    bench = _block(msg, "BENCH")
    # The two started players are NOT repeated in the bench block...
    assert "Bijan Robinson" not in bench
    assert "Ja'Marr Chase" not in bench
    # ...and both reserves appear, with their points.
    assert "Rico Dowdle" in bench and "9.25" in bench
    assert "Tucker Kraft" in bench and "7.50" in bench
    assert "(2)" in bench


def test_bench_sorts_by_points_descending_so_the_top_row_is_the_question():
    board = _board(
        ("Bijan Robinson", "RB", "ATL", 18.0, "", None),
        ("Ja'Marr Chase", "WR", "CIN", 16.5, "", None),
        ("Low Guy", "WR", "NYJ", 2.0, "", None),
        ("High Guy", "WR", "SEA", 14.0, "", None),
        ("Mid Guy", "TE", "DAL", 8.0, "", None),
    )
    bench = _block(compose("sunday", 2, [], BOARD_LINEUP, [],
                           roster_board=board), "BENCH")
    assert bench.index("High Guy") < bench.index("Mid Guy") < bench.index("Low Guy")


def test_an_unscored_bench_player_is_named_with_a_reason_never_as_zero():
    # 0.00 is a real projection meaning "expect nothing". None means "we do
    # not know". Rendering the second as the first is how an absent data
    # file turns into confident advice to bench a healthy player.
    board = _board(
        ("Bijan Robinson", "RB", "ATL", 18.0, "", None),
        ("Ja'Marr Chase", "WR", "CIN", 16.5, "", None),
        ("Genuine Zero", "WR", "NYJ", 0.0, "", None),
        ("Unknown Guy", "K", "LAC", None, "", PROJECTION_PAGE_FAILED),
    )
    bench = _block(compose("sunday", 2, [], BOARD_LINEUP, [],
                           roster_board=board), "BENCH")
    assert "Genuine Zero" in bench and "0.00" in bench
    assert "Unknown Guy" in bench
    unknown_line = [l for l in bench.split("\n") if "Unknown Guy" in l][0]
    assert "0.00" not in unknown_line
    assert "--" in unknown_line
    assert "failed" in unknown_line
    # An unscored player sorts AFTER every scored one - he is not a 0.
    assert bench.index("Genuine Zero") < bench.index("Unknown Guy")


def test_bench_keys_on_name_pos_team_so_one_team_at_tqb_and_dst_survives():
    # The reproduced hazard this whole module keys on triples for: an NFL
    # team rostered at BOTH TQB and DST shares a display name. Started at
    # TQB, the DST must still show on the bench - a name-only key would
    # suppress a real, separately-rostered asset.
    lineup = LineupResult(
        slots=[("TQB", Candidate("Chargers", "TQB", 18.45, "LAC"))],
        total=18.45)
    board = _board(
        ("Chargers", "TQB", "LAC", 18.45, "", None),
        ("Chargers", "DST", "LAC", 6.10, "", None),
    )
    bench = _block(compose("sunday", 2, [], lineup, [], roster_board=board),
                   "BENCH")
    assert "6.10" in bench
    assert "DST" in bench
    assert "(1)" in bench


def test_bench_notes_an_injury_status_next_to_the_points():
    board = _board(
        ("Bijan Robinson", "RB", "ATL", 18.0, "", None),
        ("Ja'Marr Chase", "WR", "CIN", 16.5, "", None),
        ("Nick Chubb", "RB", "CLE", 4.0, "O", None),
    )
    bench = _block(compose("sunday", 2, [], BOARD_LINEUP, [],
                           roster_board=board), "BENCH")
    chubb = [l for l in bench.split("\n") if "Nick Chubb" in l][0]
    assert "(O)" in chubb


def test_an_all_starting_roster_says_so_rather_than_printing_an_empty_block():
    board = _board(
        ("Bijan Robinson", "RB", "ATL", 18.0, "", None),
        ("Ja'Marr Chase", "WR", "CIN", 16.5, "", None),
    )
    bench = _block(compose("sunday", 2, [], BOARD_LINEUP, [],
                           roster_board=board), "BENCH")
    assert "none" in bench
    assert "(0)" in bench


def test_every_lineup_row_carries_its_own_points():
    # The other half of "projections for all thirteen": the eight that ARE
    # started need their numbers too, or the bench block is the only place
    # a number appears and there is nothing to compare it against.
    msg = compose("sunday", 2, [], BOARD_LINEUP, [])
    lineup_block = _block(msg, "BEST LINEUP")
    assert "18.00" in lineup_block
    assert "16.50" in lineup_block


def test_an_unfilled_slot_still_renders_without_a_points_column():
    lineup = LineupResult(slots=[("RB", Candidate("Bijan Robinson", "RB", 18.0)),
                                 ("K", None)], total=18.0)
    block = _block(compose("sunday", 2, [], lineup, []), "BEST LINEUP")
    assert "-- UNFILLED" in block


# ------------------------------------------------- week / freshness warnings
#
# `--week` was accepted by cbs_weekly.parse and dropped on the floor: a saved
# week-3 page handed to a week-4 run exited 0 with a confident lineup. These
# cover the rendering half of the fix; cbs_weekly's own tests cover detection.

def test_a_week_mismatch_is_stated_before_the_lineup_not_after_it():
    msg = compose("sunday", 2, [], BOARD_LINEUP, [],
                  week_mismatch=(30, 32, [("ARI", {"DST": "@LAC", "TQB": "SEA"})]))
    assert "WRONG WEEK" in msg
    assert "30 of the 32" in msg
    assert "ARI" in msg
    # Ahead of the lineup: a reader who stops at the first screen must see it.
    assert msg.index("WRONG WEEK") < msg.index("BEST LINEUP")


def test_no_week_mismatch_renders_no_warning_at_all():
    # None means "the check did not fire", and must not print a reassurance
    # the caller never earned.
    msg = compose("sunday", 2, [], BOARD_LINEUP, [])
    assert "WRONG WEEK" not in msg


def test_stale_projections_name_the_stamp_and_the_limit():
    import datetime
    from sffl.alert import STALE_PROJECTIONS_HOURS
    when = datetime.datetime(2026, 9, 9, 14, 30)
    msg = compose("sunday", 2, [], BOARD_LINEUP, [],
                  stale_projections=(51.0, when))
    assert "STALE PROJECTIONS" in msg
    assert "51 hours" in msg
    assert str(STALE_PROJECTIONS_HOURS) in msg
    assert msg.index("STALE PROJECTIONS") < msg.index("BEST LINEUP")


def test_a_fresh_page_reports_its_age_rather_than_staying_silent():
    # Silence cannot be told from "never checked". A fresh run says so.
    msg = compose("sunday", 2, [], BOARD_LINEUP, [], projections_age_hours=3.0)
    assert "updated 3 hours ago" in msg
    assert "STALE PROJECTIONS" not in msg


def test_a_stale_page_reports_staleness_instead_of_the_bare_age_line():
    import datetime
    msg = compose("sunday", 2, [], BOARD_LINEUP, [],
                  stale_projections=(99.0, datetime.datetime(2026, 9, 5, 9, 0)),
                  projections_age_hours=99.0)
    assert "STALE PROJECTIONS" in msg
    assert "updated 99 hours ago" not in msg


def test_both_warnings_default_off_so_existing_callers_are_unaffected():
    args = ("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert compose(*args) == _PRE_CURRENT_STARTERS_PINNED_OUTPUT
    assert (compose(*args, week_mismatch=None, stale_projections=None,
                    projections_age_hours=None)
            == _PRE_CURRENT_STARTERS_PINNED_OUTPUT)
