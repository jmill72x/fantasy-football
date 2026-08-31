"""`sffl alert` end to end, with the browser and the phone stubbed out.

WHY THIS FILE EXISTS. `_cmd_alert` is the one place every cross-module
contract in this pipeline meets - capture, roster parse, projections parse,
scoring, the injury feed, composition, delivery, exit code - and it had NO
tests at all: the whole suite passed with the function deleted. All three
Criticals from the final review lived in or were reachable through it.

WHAT IS STUBBED, AND ONLY WHAT IS STUBBED. `sffl.capture.capture` (it
launches a real browser and logs into CBS) and `sffl.notify`'s two functions
(one reads the login Keychain, the other POSTs to ntfy.sh). NOTHING ELSE.
Every parser, the scorer, the optimizer and the composer run for real,
against the committed fixtures copied into tmp_path - so these are genuine
integration tests of everything between the two boundaries, and no test here
can reach the network, open a browser, call StatsDeck, or send a push.

The fixtures are COPIED rather than read in place because `_cmd_alert` reads
file mtimes to compute the roster and injuries ages; a checked-out file's
mtime is an artifact of when git wrote it and would make those assertions
depend on the state of the working tree.

TASK 3 UPDATE. `_cmd_alert` used to capture exactly two pages (roster,
RB-WR-TE projections) in ONE `capture()` call keyed `{"roster":...,
"projections":...}`. It now captures the roster and all FOUR position-group
pages (RB-WR-TE, TQB, K, DST), each in its OWN `capture()` call - one
single-entry dict per call, never a combined one - so that a failure on any
one page cannot prevent the others from being attempted (see the
docstring in `_cmd_alert` and Task 3's report for why). `fake_capture` below
asserts exactly that shape (`len(urls) == 1`) so a regression back to one
combined call - which would silently defeat the per-page failure isolation
this file exists to pin - fails loudly here rather than only in production.
`alert_env.fail_group(group, exc)` lets a test fail exactly one page while
the rest still succeed; `alert_env.fail_capture(exc)` still fails EVERY
call, for the pre-existing "nothing could be verified at all" scenarios.

TASK 4 UPDATE. Four tasks after the "TQB/K/DST render UNFILLED" defect was
opened, this adds the regression guard the plan calls for: an end-to-end
test proving all EIGHT lineup slots fill from one alert run (not just a
count of eight - a count still passes if two flex slots double up while a
named position sits empty, so TQB/K/DST are each asserted BY NAME), plus a
scoring sanity check comparing our computed score against CBS's own FPTS
column on the same captured row for TQB and DST (both newly reachable and
banded, so a mis-mapped column would produce a plausible-but-wrong number,
not a crash). K is deliberately EXCLUDED from that sanity check and instead
has its divergence from CBS's FPTS pinned as expected: CBS pays a flat 1
point per made FG (verified 98/98 rows: FPTS == TOTAL_FG + XP_made) while
this league pays 2/3/4/5/8 by distance - see sources/cbs-weekly.yaml's K
group comment. Tolerances are not guesses: a prior review measured our
score minus CBS's FPTS across ALL 32 rows of a real 2026-08-30 capture at
-0.05 to +0.98 for TQB and 0.00 to +0.80 for DST; this file's fixtures are
a same-capture subset (see test_cbs_weekly_groups.py's module docstring),
so the same bounds must hold here.
"""

import json
import os
import shutil

import pytest

from sffl import cli
from sffl.capture import SessionExpired

ROSTER_FIXTURE = "tests/fixtures/cbs_team_page.txt"
PROJECTIONS_FIXTURE = "tests/fixtures/cbs_weekly_tab_rbwrte.txt"
TQB_FIXTURE = "tests/fixtures/cbs_weekly_tqb.txt"
K_FIXTURE = "tests/fixtures/cbs_weekly_k.txt"
DST_FIXTURE = "tests/fixtures/cbs_weekly_dst.txt"
INJURIES_FIXTURE = "tests/fixtures/statsdeck_injuries.json"


class _Sent(object):
    """Records what `notify.send` was asked to deliver, so a test can prove
    a push was or was not attempted without one ever leaving the machine."""

    def __init__(self):
        self.calls = []

    def __call__(self, topic, title, body, dry_run=False):
        self.calls.append((topic, title, body, dry_run))
        return False


@pytest.fixture
def alert_env(tmp_path, monkeypatch):
    """A stubbed run: real fixtures on disk, no browser, no push.

    Returns an object whose `.run(*extra_args)` invokes `sffl alert` exactly
    as launchd would and hands back (exit_code, printed_body).
    """
    roster = tmp_path / "roster.txt"
    rbwrte = tmp_path / "rbwrte.txt"
    tqb = tmp_path / "tqb.txt"
    k = tmp_path / "k.txt"
    dst = tmp_path / "dst.txt"
    shutil.copy(ROSTER_FIXTURE, str(roster))
    shutil.copy(PROJECTIONS_FIXTURE, str(rbwrte))
    shutil.copy(TQB_FIXTURE, str(tqb))
    shutil.copy(K_FIXTURE, str(k))
    shutil.copy(DST_FIXTURE, str(dst))

    sent = _Sent()
    monkeypatch.setattr("sffl.notify.send", sent)
    monkeypatch.setattr("sffl.notify.topic_from_keychain",
                        lambda *a, **k: "stub-topic")

    # "roster" and each of the four `sffl.cli.ALERT_GROUPS` names are the
    # only keys `_cmd_alert` ever calls `capture()` with - one at a time.
    state = {
        "capture_error": None,     # raised for EVERY capture() call
        "group_errors": {},        # name -> exception, for ONE page only
        "paths": {"roster": str(roster), "RB-WR-TE": str(rbwrte),
                  "TQB": str(tqb), "K": str(k), "DST": str(dst)},
    }

    def fake_capture(urls, out_dir, profile_dir, **kwargs):
        assert len(urls) == 1, (
            "_cmd_alert must capture exactly one page per capture() call "
            "(got %r) so a failure on one page cannot abort the others - "
            "see this file's module docstring" % (urls,))
        (name, url), = urls.items()
        if state["capture_error"] is not None:
            raise state["capture_error"]
        if name in state["group_errors"]:
            raise state["group_errors"][name]
        return {url: state["paths"][name]}

    monkeypatch.setattr("sffl.capture.capture", fake_capture)

    class _Env(object):
        tmp = tmp_path
        sent_calls = sent.calls

        def fail_capture(self, exc):
            """Every capture() call fails - nothing at all is verified."""
            state["capture_error"] = exc

        def fail_group(self, name, exc):
            """Only the ONE named page ("roster", "RB-WR-TE", "TQB", "K",
            or "DST") fails; every other page still succeeds."""
            state["group_errors"][name] = exc

        def set_projections(self, path, group="RB-WR-TE"):
            state["paths"][group] = str(path)

        def set_roster(self, path):
            state["paths"]["roster"] = str(path)

        def run(self, capsys, *extra):
            argv = ["alert", "--kind", "friday", "--week", "1",
                    "--out-dir", str(tmp_path / "out"),
                    "--profile-dir", str(tmp_path / "profile"),
                    "--dry-run"] + list(extra)
            code = cli.main(argv)
            return code, capsys.readouterr().out

    return _Env()


def _injuries_file(tmp_path, name="injuries-friday.json"):
    path = tmp_path / name
    shutil.copy(INJURIES_FIXTURE, str(path))
    return path


# --- capture failure -------------------------------------------------------

def test_a_capture_failure_reports_it_exits_non_zero_and_shows_no_lineup(
        alert_env, capsys):
    # An expired CBS session returns a well-formed login page that parses to
    # an EMPTY roster - a valid-looking input meaning "Jeff owns nobody". A
    # lineup built from that is confidently, entirely wrong.
    alert_env.fail_capture(SessionExpired("CBS served its login page"))
    code, out = alert_env.run(capsys)
    assert code == 1
    assert "CAPTURE FAILED" in out
    assert "CBS served its login page" in out
    assert "BEST LINEUP" not in out
    assert "START / SIT" not in out


def test_a_capture_failure_still_produces_a_body_to_deliver(alert_env, capsys):
    # An absent push must mean a DEAD JOB, never a failed capture - the
    # digest always has a body, and delivery is still attempted.
    alert_env.fail_capture(SessionExpired("session expired"))
    alert_env.run(capsys)
    assert len(alert_env.sent_calls) == 1
    assert "CAPTURE FAILED" in alert_env.sent_calls[0][2]


# --- C2: the injuries file ------------------------------------------------

def test_a_missing_injuries_file_is_reported_not_rendered_as_a_quiet_week(
        alert_env, capsys):
    # THE C2 DEFECT: StatsDeck down or `claude -p` failing leaves no file,
    # `reports` stays [], and the digest printed "no designations on your
    # roster." and "nothing new." - byte-identical to a genuinely quiet
    # week - at exit 0, with the only warning on stderr, which never
    # reaches the phone.
    missing = alert_env.tmp / "injuries-friday.json"
    assert not os.path.exists(str(missing))
    code, out = alert_env.run(capsys, "--injuries", str(missing))
    assert code == 1
    assert "INJURY DATA UNAVAILABLE" in out
    assert "no designations on your roster" not in out
    assert "nothing new." not in out
    assert "NOT FETCHED" in out
    # The rest of the digest still went out - a lineup with no news beats
    # no digest at all.
    assert "BEST LINEUP" in out
    assert len(alert_env.sent_calls) == 1


def test_a_present_injuries_file_renders_its_rows_and_exits_zero(
        alert_env, capsys):
    path = _injuries_file(alert_env.tmp)
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 0
    assert "INJURY DATA UNAVAILABLE" not in out
    # Ja'Marr Chase is on the fixture roster AND in the fixture feed.
    assert "Ja'Marr Chase" in out
    assert "Injury data fetched" in out


def test_an_unreadable_injuries_file_fails_loudly_without_killing_the_alert(
        alert_env, capsys):
    # A file that exists but is not JSON is the same class of failure as no
    # file at all, and must not surface as a traceback that takes the whole
    # digest down.
    path = alert_env.tmp / "injuries-friday.json"
    path.write_text("I could not complete that request.\n")
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 1
    assert "INJURY DATA UNAVAILABLE" in out
    assert "could not be parsed" in out
    assert "BEST LINEUP" in out


def test_a_wrong_shape_payload_degrades_the_run_instead_of_ending_it(
        alert_env, capsys):
    """Well-formed JSON, wrong shape: a list of STRINGS under "report".

    `injuries.load` reaches `row.get(...)` on a string and raises
    AttributeError, which is neither ValueError nor OSError, so it used to
    escape every handler in the process: no digest composed, nothing pushed,
    a traceback in a log nobody reads - on a Sunday morning, silence ninety
    minutes before kickoff. That is precisely the outcome the injury-fetch
    degradation exists to prevent, so a malformed payload must degrade the
    same way a missing one does. ops/fetch_injuries.sh's shape check blocks
    the top-level case; it cannot vet each row inside the arrays.
    """
    path = alert_env.tmp / "injuries-friday.json"
    path.write_text(json.dumps({"report": ["some prose"], "intel": []}))
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 1
    # The alert still composed, and still carries the half that works.
    assert "BEST LINEUP" in out
    assert "Ja'Marr Chase" in out
    # The problem is stated, and named as a PAYLOAD problem - a different
    # cause with a different fix from "the fetch produced no file".
    assert "INJURY DATA UNAVAILABLE" in out
    assert "could not be parsed" in out
    assert "AttributeError" in out
    assert "no designations on your roster" not in out
    # And it was actually delivered.
    assert len(alert_env.sent_calls) == 1


def test_a_dict_where_a_list_belongs_also_degrades(alert_env, capsys):
    # The other half of the same shape hazard: `{"report": {...}}` iterates
    # a dict's KEYS, handing `_row_to_report` a string again.
    path = alert_env.tmp / "injuries-friday.json"
    path.write_text(json.dumps({"report": {"player": "Nick Chubb"},
                                "intel": []}))
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 1
    assert "BEST LINEUP" in out
    assert "could not be parsed" in out


def test_stale_injury_data_is_flagged_and_counts_as_a_degraded_run(
        alert_env, capsys):
    # Real rows, but from an earlier run - the failure mode fetch_injuries.sh
    # used to leave behind by never truncating its output file.
    from sffl.alert import STALE_INJURIES_MINUTES
    path = _injuries_file(alert_env.tmp)
    old = os.path.getmtime(str(path)) - (STALE_INJURIES_MINUTES + 10) * 60
    os.utime(str(path), (old, old))
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 1
    assert "STALE INJURY DATA" in out
    # The rows are still shown; they are real, just old.
    assert "Ja'Marr Chase" in out


def test_no_injuries_argument_still_refuses_to_claim_a_clean_roster(
        alert_env, capsys):
    # Not a failed step - nobody asked for injury data - so it does NOT
    # make the run degraded. It still must not print "no designations".
    code, out = alert_env.run(capsys)
    assert code == 0
    assert "no --injuries file was given" in out
    assert "no designations on your roster" not in out


# --- C1: un-evaluated starters --------------------------------------------

def test_a_now_captured_tqb_starter_is_scored_not_left_unevaluated(
        alert_env, capsys):
    # UPDATED FOR TASK 3 - this used to be part of the C1 regression test
    # (`test_the_tqb_kicker_and_defense_are_named_not_listed_as_sits`):
    # before this task only RB-WR-TE was ever captured, so Chargers (the
    # fixture roster's current TQB starter) had no projection anywhere and
    # was reported as a SCOPE LIMIT (POSITION_NOT_CAPTURED), landing in
    # NOT EVALUATED rather than being scored. Now that `_cmd_alert` also
    # captures and merges the TQB page, and the real TQB fixture DOES carry
    # a "Chargers TQB" row, he is scored for real: he must fill the
    # optimal lineup's TQB slot and must no longer appear anywhere in NOT
    # EVALUATED - the exact gap this task exists to close.
    code, out = alert_env.run(capsys)
    assert code == 0
    assert "Chargers (TQB)" not in out
    slots_section = out[out.index("BEST LINEUP"):]
    assert "TQB    Chargers" in slots_section


def test_a_covered_positions_player_with_no_row_is_a_data_problem_not_a_scope_limit(
        alert_env, capsys):
    # Evan McPherson (K) and the Patriots (DST) are on the fixture roster's
    # current lineup, but neither name appears on the K/DST fixtures used
    # here. Their POSITIONS are captured (the K and DST pages both
    # succeeded this run - see `covered_positions` in `_cmd_alert`), so
    # their absence is a DATA PROBLEM (PROJECTION_MISSING), never a scope
    # limit (POSITION_NOT_CAPTURED) - and, either way, they must never
    # silently read as a SIT recommendation.
    code, out = alert_env.run(capsys)
    assert code == 0
    start = out.index("START / SIT vs your current CBS lineup:")
    sit_block = out[start:out.index("\n\n", start)]
    for name in ("Evan McPherson", "Patriots"):
        assert name not in sit_block
        assert name in out  # named, never silently dropped

    section = out[out.index("NOT EVALUATED for start/sit"):]
    # TIE EACH NAME TO ITS OWN HEADING, not just "somewhere in the
    # section" - a reviewer noted the substring-only version would still
    # pass if these two were mislabelled under a DIFFERENT heading while
    # "DATA PROBLEM" happened to appear for an unrelated reason. Slice the
    # section AT the DATA PROBLEM heading and confirm both names sit AFTER
    # it (there is no other heading in this section for this fixture, so
    # "after the heading, before the section ends" is the precise claim).
    data_problem_at = section.index("DATA PROBLEM")
    data_problem_block = section[data_problem_at:]
    assert "Evan McPherson (K)" in data_problem_block
    assert "Patriots (DST)" in data_problem_block
    # And neither name appears BEFORE that heading, under some other one.
    assert "Evan McPherson" not in section[:data_problem_at]
    assert "Patriots" not in section[:data_problem_at]
    assert "NOT recommendations to bench anyone" in out


def test_a_covered_position_with_no_projection_reads_as_a_data_problem(
        alert_env, capsys):
    # Distinct from the scope limit above: Jameson Williams is a WR, the
    # projections page DOES carry WRs, so his absence from it is a data
    # problem worth chasing - not a limit of the tool, and not bench advice.
    trimmed = alert_env.tmp / "projections_no_williams.txt"
    with open(PROJECTIONS_FIXTURE) as fh:
        kept = [l for l in fh if "Jameson Williams" not in l]
    trimmed.write_text("".join(kept))
    alert_env.set_projections(trimmed)

    code, out = alert_env.run(capsys)
    assert code == 0
    section = out[out.index("NOT EVALUATED for start/sit"):]
    assert "Jameson Williams (WR)" in section
    assert "DATA PROBLEM" in section
    # And he is NOT in the SIT column.
    start = out.index("START / SIT vs your current CBS lineup:")
    assert "Jameson Williams" not in out[start:out.index("\n\n", start)]


def test_a_raw_roster_team_code_does_not_double_list_a_starter(
        alert_env, capsys):
    """Task 3b minor (a). The roster fixture's Chargers TQB row carries
    team "LAC" already, so this substitutes the OLD San Diego code CBS's
    own `identity.TEAM_ALIASES` still maps ("SD" -> "LAC") to prove the
    fix holds even when the roster page's raw code is not the canonical
    one `cbs_weekly.parse` always normalizes projections to. Before the
    fix (`current_starters` built from the RAW `RosterRow.team`), "SD" !=
    "LAC" would make `_start_sit_diff` treat the Chargers TQB as BOTH a
    START (the optimal LAC pick) and a SIT (the un-normalized SD one) -
    the same real, single-slot starter recommended against himself.
    """
    with open(ROSTER_FIXTURE) as fh:
        text = fh.read()
    assert "Chargers TQB • LAC" in text
    roster = alert_env.tmp / "roster_sd_code.txt"
    roster.write_text(text.replace("Chargers TQB • LAC", "Chargers TQB • SD"))
    alert_env.set_roster(roster)

    code, out = alert_env.run(capsys)
    assert code == 0
    slots_section = out[out.index("BEST LINEUP"):]
    assert "TQB    Chargers" in slots_section
    # The core assertion: never in BOTH columns of the diff. Unconditional -
    # `sit_sit_block.split("SIT", 1)` always returns two pieces (the second
    # is "" when "SIT" is absent, which trivially satisfies the assertion
    # rather than skipping it), so this no longer needs to be guarded behind
    # "did both column headers even appear".
    start = out.index("START / SIT vs your current CBS lineup:")
    sit_sit_block = out[start:out.index("\n\n", start)]
    start_col, sit_col = sit_sit_block.split("SIT", 1)
    assert "Chargers" not in start_col or "Chargers" not in sit_col
    # And no phantom recommendation to bench/start the same real player.
    assert sit_sit_block.count("Chargers") <= 1


# --- delivery and exit codes ----------------------------------------------

def test_the_body_is_printed_before_delivery_is_attempted(alert_env, capsys):
    # A run that produced a correct alert but could not push it must leave
    # the alert readable in the log.
    path = _injuries_file(alert_env.tmp)
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 0
    assert out.index("BEST LINEUP") < out.index("[dry run - nothing sent]")


def test_a_delivery_failure_exits_non_zero_without_a_traceback(
        alert_env, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no Keychain entry for account 'x'")

    monkeypatch.setattr("sffl.notify.topic_from_keychain", boom)
    path = _injuries_file(alert_env.tmp)
    code, out = alert_env.run(capsys, "--injuries", str(path))
    assert code == 1
    assert "[DELIVERY FAILED]" in out
    assert "BEST LINEUP" in out


def test_nothing_in_this_module_can_reach_the_network(alert_env, capsys):
    # Belt and braces on the stubbing contract this file promises: --dry-run
    # is passed on every run, so even the stub is told not to send.
    path = _injuries_file(alert_env.tmp)
    alert_env.run(capsys, "--injuries", str(path))
    assert alert_env.sent_calls
    for _topic, _title, _body, dry_run in alert_env.sent_calls:
        assert dry_run is True


def test_the_injuries_fixture_is_the_shape_fetch_injuries_writes():
    # The whole C2 chain assumes ops/fetch_injuries.sh produces exactly
    # this: the two arrays StatsDeck returns, lifted out of `data`.
    with open(INJURIES_FIXTURE) as fh:
        raw = json.load(fh)
    assert isinstance(raw["report"], list)
    assert isinstance(raw["intel"], list)


# --- TASK 4: the all-eight-slots regression guard --------------------------

# The fixture roster's own current K and DST starters (see
# tests/fixtures/cbs_team_page.txt) - real CBS player ids, lifted from the
# same 2026-08-30 capture this whole branch is built on. Neither name is on
# the committed K_FIXTURE/DST_FIXTURE (those two fixtures were captured with
# only 3 rows each - see test_cbs_weekly_groups.py), which is WHY every
# other test in this file (e.g.
# test_a_covered_positions_player_with_no_row_is_a_data_problem_not_a_scope_
# limit) sees them as a DATA PROBLEM rather than a filled slot. This test
# needs them actually filled, so it adds one real-shaped row for each,
# cloned from an existing fixture row (same tab count, so `expect_tokens`
# still accepts it) with only the id/name/team substituted - never a
# hand-invented row shape.
_EVAN_MCPHERSON_K_ROW = (
    "id=2962681\t\tTeam C...\tEvan McPherson K • CIN \tTB\t21\t6\t84\t75\t12"
    "\t2.1\t2.6\t0.0\t0.0\t0.5\t0.5\t0.7\t0.7\t0.7\t0.8\t0.3\t0.7\t3.5\t3.6"
    "\t5.60\n")
_PATRIOTS_DST_ROW = (
    "id=1931\t\tTeam A...\tPatriots DST • NE\t@SEA\t12\t10\t100\t92\t4.4"
    "\t0.3\t0.8\t0.7\t0.1\t0.0\t248.00\t248\t19.60\t19.6\t9.70\n")


def _fixture_plus_row(tmp_path, name, base_fixture, extra_row):
    path = tmp_path / name
    with open(base_fixture) as fh:
        text = fh.read()
    path.write_text(text + extra_row)
    return str(path)


def test_all_eight_slots_fill_with_a_tqb_a_k_and_a_dst_on_the_roster(
        alert_env, capsys):
    """THE deliverable this task exists to pin: with all four projection
    pages present and a roster carrying a TQB, a K and a DST, every one of
    the league's eight lineup slots (leagues/sffl/2026.yaml: TQB, RB,
    WR/TE, FLEX1-3, K, DST) fills - none renders `-- UNFILLED`.

    A bare count of eight would be a WEAKER guard than this: it would still
    pass if, say, K and DST both stayed empty while two RBs doubled up
    across FLEX1 and FLEX2. So TQB, K and DST are each asserted BY NAME,
    not just counted - the exact three positions this whole branch exists
    to make reachable (see docs/superpowers/specs/
    2026-08-30-full-position-coverage.md).

    The fixture roster (tests/fixtures/cbs_team_page.txt) already starts a
    TQB (Chargers), a K (Evan McPherson) and a DST (Patriots) - see
    test_a_now_captured_tqb_starter_is_scored_not_left_unevaluated and
    test_a_covered_positions_player_with_no_row_is_a_data_problem_not_a_
    scope_limit above. The committed K/DST fixtures don't carry those two
    names (they're 3-row samples), which is exactly why THAT test sees them
    as unfilled data problems - so this test adds one real-shaped row for
    each (see _EVAN_MCPHERSON_K_ROW/_PATRIOTS_DST_ROW above) to prove the
    FULL pipeline, not just the three already-covered positions, actually
    fills all eight when the data is there.
    """
    k_path = _fixture_plus_row(alert_env.tmp, "k_plus.txt", K_FIXTURE,
                               _EVAN_MCPHERSON_K_ROW)
    dst_path = _fixture_plus_row(alert_env.tmp, "dst_plus.txt", DST_FIXTURE,
                                 _PATRIOTS_DST_ROW)
    alert_env.set_projections(k_path, group="K")
    alert_env.set_projections(dst_path, group="DST")

    code, out = alert_env.run(capsys)
    assert code == 0

    slots_section = out[out.index("BEST LINEUP"):out.index("[dry run")]
    # No slot anywhere renders as unfilled - the failure mode being guarded
    # against is exactly one quietly reverting to this, at exit 0.
    assert "UNFILLED" not in slots_section
    # And the three previously-broken positions are named, not merely
    # counted - see the docstring above for why a count of eight is weaker.
    assert "TQB    Chargers" in slots_section
    assert "K      Evan McPherson" in slots_section
    assert "DST    Patriots" in slots_section
    # All eight slot labels from the league file are present in the
    # section at all (belt and braces on the "eight slots" claim itself).
    for slot in ("TQB", "RB", "WR/TE", "FLEX1", "FLEX2", "FLEX3", "K",
                "DST"):
        assert ("\n  %-6s " % slot) in slots_section
    # Bonus: Evan McPherson and the Patriots are no longer DATA PROBLEMs
    # now that their positions have real rows for them.
    assert "NOT EVALUATED for start/sit" not in out or (
        "Evan McPherson" not in out[out.index("NOT EVALUATED"):]
        and "Patriots" not in out[out.index("NOT EVALUATED"):])


# --- TASK 4: scoring sanity, TQB/DST against CBS's own FPTS ----------------

def _rows_with_cbs_fpts(path, group):
    """Parse `path` and pair each row with CBS's own trailing FPTS column
    from that SAME raw line. These fixtures are pure one-row-per-team text
    (no header, no blank lines - see test_cbs_weekly_groups.py), so
    parse-order and file-order line up 1:1; asserting the lengths match
    before zipping catches it if that ever stops being true."""
    from sffl.cbs_weekly import parse as parse_weekly
    rows = parse_weekly(path, group=group, week=1)
    with open(path) as fh:
        lines = [line for line in fh if line.strip()]
    assert len(rows) == len(lines)
    return [(row, float(line.rstrip("\n").split("\t")[-1]))
            for row, line in zip(rows, lines)]


def test_tqb_score_agrees_with_cbs_fpts_within_the_measured_tolerance():
    """TQB is banded and newly reachable - a mis-mapped column would give a
    PLAUSIBLE but wrong number, not a crash, so this checks the actual
    magnitude against CBS's own FPTS column on the same captured row.

    Tolerance -0.05 to +0.98 is measured, not guessed: a prior review
    checked our score minus CBS's FPTS across ALL 32 TQB rows of the real
    2026-08-30 capture and found exactly that range (see
    test_cbs_weekly_groups.py's Chargers reconciliation, 18.40 vs 18.45,
    for one row of the same measurement). This fixture's 4 rows are a
    subset of that same capture, so the same bounds must hold.
    """
    from sffl.league import load_league
    from sffl.pool import score_week
    lg = load_league("leagues/sffl/2026.yaml")
    pairs = _rows_with_cbs_fpts(TQB_FIXTURE, "TQB")
    assert len(pairs) == 4
    for row, cbs_fpts in pairs:
        ours = score_week(lg, row, None)
        diff = ours - cbs_fpts
        assert -0.05 <= diff <= 0.98, (
            "%s: ours=%.2f cbs=%.2f diff=%.2f outside the measured "
            "[-0.05, +0.98] TQB tolerance" % (row.name, ours, cbs_fpts, diff))


def test_dst_score_agrees_with_cbs_fpts_within_the_measured_tolerance():
    """Same check as TQB's, for DST - also banded, also newly reachable.

    Tolerance 0.00 to +0.80 is measured the same way: a prior review
    checked our score minus CBS's FPTS across ALL 32 DST rows of the real
    2026-08-30 capture and found exactly that range.
    """
    from sffl.league import load_league
    from sffl.pool import score_week
    lg = load_league("leagues/sffl/2026.yaml")
    pairs = _rows_with_cbs_fpts(DST_FIXTURE, "DST")
    assert len(pairs) == 3
    for row, cbs_fpts in pairs:
        ours = score_week(lg, row, None)
        diff = ours - cbs_fpts
        assert 0.00 <= diff <= 0.80, (
            "%s: ours=%.2f cbs=%.2f diff=%.2f outside the measured "
            "[0.00, +0.80] DST tolerance" % (row.name, ours, cbs_fpts, diff))


def test_k_score_deliberately_diverges_from_cbs_fpts_by_roughly_2x():
    """NOT a bug, and must never be "fixed" to match CBS: CBS's FPTS column
    for kickers pays a flat 1 point per made field goal, verified on 98/98
    rows of the real 2026-08-30 capture to equal exactly TOTAL_FG +
    XP_made. This league instead pays 2/3/4/5/8 points by distance (see
    sources/cbs-weekly.yaml's K group comment and poc/validate_k_weekly.py,
    exact on 17/17 real scored weeks), so our score legitimately runs
    roughly double CBS's FPTS. K is deliberately excluded from the
    agrees-with-CBS checks above; this test asserts the divergence itself,
    so nobody mistakes it for the same class of bug those checks catch.
    """
    from sffl.league import load_league
    from sffl.pool import score_week
    lg = load_league("leagues/sffl/2026.yaml")
    pairs = _rows_with_cbs_fpts(K_FIXTURE, "K")
    assert len(pairs) == 3
    for row, cbs_fpts in pairs:
        ours = score_week(lg, row, None)
        ratio = ours / cbs_fpts
        assert 1.5 <= ratio <= 2.5, (
            "%s: ours=%.2f cbs=%.2f ratio=%.2f is no longer ~2x - if this "
            "moved toward 1x, someone may have 'fixed' the kicker table to "
            "match CBS's flat convention, which would be wrong"
            % (row.name, ours, cbs_fpts, ratio))

