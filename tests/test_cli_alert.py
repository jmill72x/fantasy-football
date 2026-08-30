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
    assert "DATA PROBLEM" in section
    assert "Evan McPherson (K)" in section
    assert "Patriots (DST)" in section
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
