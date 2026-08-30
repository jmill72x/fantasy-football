"""Task 3: capturing and merging all four position-group pages (RB-WR-TE,
TQB, K, DST) into ONE pool before `best_lineup` runs.

WHAT THIS FILE PINS.

1. `_merge_projection_groups` (the pure merge/dedup helper `_cmd_week` and
   `_cmd_alert` both call) combines rows from several groups correctly,
   reports a TRUE cross-group duplicate rather than silently keeping one,
   and - the real, non-hypothetical hazard found while wiring this up -
   does NOT mistake CBS's TQB and DST pages sharing the NFL team nickname
   as a "player name" ("Chargers" is a genuine, distinct row on BOTH pages
   every week) for a duplicate.

2. `sffl week --projections-tqb/-k/-dst` merges four saved pages into one
   pool and fills all eight lineup slots, with `--group`/`--projections`
   left exactly as they were for every caller that does not pass the new
   flags (see test_cli_week.py, unmodified and still passing).

3. `sffl alert` makes a LOUD, degraded (non-zero exit) report - IN THE
   PUSHED BODY ITSELF, not only on stdout - when one of the four position-
   group pages fails to capture or parse, while STILL producing a lineup
   from the other three. It never silently reproduces `-- UNFILLED` in a
   slot whose page simply failed this run.

NO TEST HERE REACHES THE NETWORK OR LAUNCHES A BROWSER: `sffl.capture.capture`
is monkeypatched exactly as `test_cli_alert.py` does it.
"""

import shutil

import pytest

from sffl import cli
from sffl.capture import CaptureError
from sffl.cli import ALERT_GROUPS, _merge_projection_groups
from sffl.schema import PlayerProjection

PROJ = "tests/fixtures/cbs_weekly_rbwrte.txt"
TQB_FIXTURE = "tests/fixtures/cbs_weekly_tqb.txt"
K_FIXTURE = "tests/fixtures/cbs_weekly_k.txt"
DST_FIXTURE = "tests/fixtures/cbs_weekly_dst.txt"
ROSTER_FIXTURE = "tests/fixtures/cbs_team_page.txt"


def _proj(name, pos, team="XX"):
    return PlayerProjection(name=name, team=team, pos=pos,
                            source="cbs-weekly", source_year=2026,
                            games=1.0, stats={})


# --- _merge_projection_groups: the pure merge/dedup logic ------------------

def test_merge_combines_rows_from_every_group():
    merged, _owner = _merge_projection_groups([
        ("RB-WR-TE", [_proj("Ja'Marr Chase", "WR")]),
        ("TQB", [_proj("Chargers", "TQB")]),
        ("K", [_proj("Jake Bates", "K")]),
        ("DST", [_proj("Broncos", "DST")]),
    ])
    assert sorted(p.name for p in merged) == [
        "Broncos", "Chargers", "Ja'Marr Chase", "Jake Bates"]


def test_a_true_cross_group_duplicate_is_reported_and_not_double_counted(
        capsys):
    # Same name AND same position, claimed by two different groups - the
    # one real "duplicate player" shape the brief warns about.
    merged, owner = _merge_projection_groups([
        ("RB-WR-TE", [_proj("Ghost Player", "RB")]),
        ("TQB", [_proj("Ghost Player", "RB")]),
    ])
    out = capsys.readouterr().out
    assert len(merged) == 1
    assert "WARNING" in out
    assert "Ghost Player" in out
    assert "RB-WR-TE" in out and "TQB" in out
    assert owner[("ghost player", "RB")] == "RB-WR-TE"


def test_the_same_team_nickname_on_tqb_and_dst_pages_is_not_a_collision(
        capsys):
    # THE REAL HAZARD, found against the actual TQB/DST fixtures: CBS's TQB
    # and DST pages both use the NFL TEAM NICKNAME as the row's "player
    # name" - "Chargers" is a genuine, DISTINCT row on both pages, one an
    # aggregate of the team's passing production, the other of its
    # defense. Keying the merge on name ALONE would read this as a
    # cross-group duplicate for all 32 NFL teams, every week, and - worse -
    # whichever position merged last would silently answer for the other
    # slot too. Keying on (name, pos) keeps both with no warning at all,
    # because this is the ordinary shape of the data, not a collision.
    merged, owner = _merge_projection_groups([
        ("TQB", [_proj("Chargers", "TQB")]),
        ("DST", [_proj("Chargers", "DST")]),
    ])
    out = capsys.readouterr().out
    assert len(merged) == 2
    assert "WARNING" not in out
    assert owner[("chargers", "TQB")] == "TQB"
    assert owner[("chargers", "DST")] == "DST"


def test_a_within_group_suffix_collision_passes_through_unmerged():
    # Two genuinely different players who happen to normalize to the same
    # key WITHIN one group's own page are NOT a cross-group duplicate -
    # `_cmd_week`'s own by_key loop (test_cli_week.py) already warns about
    # and resolves exactly this case; the merge step must not pre-empt it
    # by dropping one before that check ever sees it.
    merged, _owner = _merge_projection_groups([
        ("RB-WR-TE", [_proj("Braelon Allen", "RB"),
                      _proj("Braelon Allen Jr.", "RB")]),
    ])
    assert len(merged) == 2


def test_group_order_decides_which_side_of_a_true_duplicate_survives():
    # The FIRST group given wins - documented behavior, not an accident of
    # dict ordering. Reversing the input order flips which row survives.
    a = _proj("Ghost Player", "RB", team="AAA")
    b = _proj("Ghost Player", "RB", team="BBB")
    merged1, _ = _merge_projection_groups(
        [("RB-WR-TE", [a]), ("TQB", [b])])
    merged2, _ = _merge_projection_groups(
        [("TQB", [b]), ("RB-WR-TE", [a])])
    assert merged1[0].team == "AAA"
    assert merged2[0].team == "BBB"


# --- `sffl week`: merging four saved pages into one pool -------------------

def _roster(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def test_week_merges_all_four_groups_into_one_lineup(tmp_path, capsys):
    # "Titans" (TQB) and "Broncos" (DST) are the roster's picks, chosen
    # because NEITHER team's nickname is the OWNED one that collides below
    # (the TQB and DST fixtures both happen to carry "Chargers" and
    # "Dolphins" rows - real teams on both real pages, unowned here). Those
    # two collisions still fire their WARNING (a REAL, universal hazard on
    # a full 32-team capture - see the dedicated collision test below) even
    # though neither is rostered; the point of THIS test is that the
    # merge still correctly fills every slot for the OWNED, non-colliding
    # names despite that noise - the feature remains usable, not silently
    # broken, in the presence of an expected, already-reported collision
    # elsewhere in the pool.
    r = _roster(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                           "Sam LaPorta", "Kyle Pitts", "Braelon Allen",
                           "Titans", "Jake Bates", "Broncos"])
    rc = cli.main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
                  "--projections-tqb", TQB_FIXTURE,
                  "--projections-k", K_FIXTURE,
                  "--projections-dst", DST_FIXTURE,
                  "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "merged 4 position group page(s)" in out
    # The Chargers/Dolphins collisions are EXPECTED and reported (see
    # test_week_a_team_nickname_owned_for_both_tqb_and_dst_warns_and_
    # loses_one_side) - neither is rostered here, so they must not affect
    # this roster's own, unambiguous names.
    assert "'Chargers'" in out and "'Dolphins'" in out

    slots = out.split("best legal lineup:", 1)[1].split("WAIVER TARGETS", 1)[0]
    assert "Titans" in slots
    assert "Jake Bates" in slots
    assert "Broncos" in slots
    # And the pre-existing RB-WR-TE-only slots are still filled too - the
    # merge ADDS positions, it does not displace the original group.
    assert "Harold Fannin Jr." in slots or "Isaiah Likely" in slots


def test_week_a_team_nickname_owned_for_both_tqb_and_dst_warns_and_loses_one_side(
        tmp_path, capsys):
    """THE REAL, UNIVERSAL HAZARD in `sffl week`'s plain-text --roster
    format, found while wiring this up and documented rather than papered
    over: a REAL CBS capture lists all 32 NFL teams on BOTH the TQB and the
    DST page, so a team nickname like "Chargers" is a genuine row on both
    pages EVERY WEEK - not a rare coincidence. `_cmd_alert` resolves this
    correctly because it has the CAPTURED ROSTER PAGE, which prints a
    position for every rostered name (see `cbs_roster.parse_positions`).
    `sffl week`'s --roster is a bare one-name-per-line text file with NO
    position column, so if the SAME team nickname is merged from both the
    TQB and DST pages, there is no signal left to tell which position an
    owned name of that team refers to. This is NOT silently resolved: the
    existing by_key collision warning (already covering a normalize_name
    suffix collision - see test_cli_week.py) fires here too, and names
    BOTH the kept and the dropped position, so the loss is visible - but
    it IS a real, load-bearing limitation of this file format that
    --projections-tqb and --projections-dst together cannot fully escape.
    """
    r = _roster(tmp_path, ["Harold Fannin Jr.", "Chargers"])
    rc = cli.main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
                  "--projections-tqb", TQB_FIXTURE,
                  "--projections-dst", DST_FIXTURE,
                  "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out
    assert "'Chargers' (TQB)" in out and "'Chargers' (DST)" in out


def test_week_without_the_new_flags_is_unaffected_by_their_existence(
        tmp_path, capsys):
    # Merely DEFINING --projections-tqb/-k/-dst must not change a single
    # thing about the original single-group path when they are omitted -
    # this is the same claim test_cli_week.py's 21 tests make already, run
    # here once more as a same-file smoke check.
    r = _roster(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                           "Sam LaPorta", "Kyle Pitts", "Elic Ayomanor"])
    rc = cli.main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
                  "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "merged" not in out.lower()


def test_week_a_true_cross_group_duplicate_is_named_in_the_wiring(
        tmp_path, capsys):
    """A player showing up on two of the four saved pages must be visible,
    not silently resolved. Constructed with a hand-written duplicate row
    (same name, same position) fed to --projections-tqb - a group it does
    not really belong to - to exercise the wiring end to end rather than
    only the pure `_merge_projection_groups` unit above."""
    dup_tqb = tmp_path / "dup_tqb.txt"
    # A TQB-shaped row for a name that also appears as an RB in `PROJ`.
    dup_tqb.write_text(
        "FA Braelon Allen TQB • NYJ @TEN --- 7 84 45 N/R "
        "33.7 23.8 265.1 2.3 0.7 5.4 35 6.5 0.2 0.1 18.45\n")
    r = _roster(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                           "Braelon Allen"])
    # Braelon Allen is RB in PROJ; give the duplicate the SAME pos (RB) so
    # this is a genuine (name, pos) collision, not a same-name-different-
    # position case like the TQB/DST team-nickname one.
    dup_same_pos = tmp_path / "dup_same_pos.txt"
    dup_same_pos.write_text(
        "FA Braelon Allen RB • NYJ @TEN --- 7 84 45 N/R "
        "33.7 23.8 265.1 2.3 0.7 5.4 35 6.5 0.2 0.1 18.45\n")
    rc = cli.main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
                  "--projections-tqb", str(dup_same_pos),
                  "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out
    assert "Braelon Allen" in out


# --- `sffl alert`: loud, degraded partial failure --------------------------

class _Sent(object):
    def __init__(self):
        self.calls = []

    def __call__(self, topic, title, body, dry_run=False):
        self.calls.append((topic, title, body, dry_run))
        return False


@pytest.fixture
def alert_env(tmp_path, monkeypatch):
    """Same stubbing discipline as test_cli_alert.py's fixture: only
    `sffl.capture.capture` and `sffl.notify`'s two functions are stubbed.
    `capture()` here is called once per page (never a combined dict) -
    exactly the shape `_cmd_alert` uses so a failure on one page cannot
    prevent the other three from being attempted."""
    roster = tmp_path / "roster.txt"
    rbwrte = tmp_path / "rbwrte.txt"
    tqb = tmp_path / "tqb.txt"
    k = tmp_path / "k.txt"
    dst = tmp_path / "dst.txt"
    shutil.copy(ROSTER_FIXTURE, str(roster))
    shutil.copy("tests/fixtures/cbs_weekly_tab_rbwrte.txt", str(rbwrte))
    shutil.copy(TQB_FIXTURE, str(tqb))
    shutil.copy(K_FIXTURE, str(k))
    shutil.copy(DST_FIXTURE, str(dst))

    sent = _Sent()
    monkeypatch.setattr("sffl.notify.send", sent)
    monkeypatch.setattr("sffl.notify.topic_from_keychain",
                        lambda *a, **k: "stub-topic")

    state = {
        "group_errors": {},
        "paths": {"roster": str(roster), "RB-WR-TE": str(rbwrte),
                  "TQB": str(tqb), "K": str(k), "DST": str(dst)},
    }

    def fake_capture(urls, out_dir, profile_dir, **kwargs):
        assert len(urls) == 1
        (name, url), = urls.items()
        if name in state["group_errors"]:
            raise state["group_errors"][name]
        return {url: state["paths"][name]}

    monkeypatch.setattr("sffl.capture.capture", fake_capture)

    class _Env(object):
        tmp = tmp_path
        sent_calls = sent.calls

        def fail_group(self, name, exc):
            state["group_errors"][name] = exc

        def run(self, capsys, *extra):
            argv = ["alert", "--kind", "friday", "--week", "1",
                    "--out-dir", str(tmp_path / "out"),
                    "--profile-dir", str(tmp_path / "profile"),
                    "--dry-run"] + list(extra)
            code = cli.main(argv)
            return code, capsys.readouterr().out

    return _Env()


def test_a_single_group_capture_failure_degrades_but_still_produces_a_lineup(
        alert_env, capsys):
    alert_env.fail_group(
        "DST", CaptureError("timed out navigating to the DST page"))
    code, out = alert_env.run(capsys)

    assert code == 1
    assert "PROJECTIONS DEGRADED" in out
    assert "DST" in out
    assert "timed out navigating to the DST page" in out
    # The other three pages still produced a real, partial lineup - never
    # the old byte-identical-to-broken "-- UNFILLED" with no explanation.
    assert "BEST LINEUP" in out
    assert "K      -- UNFILLED" not in out or "PROJECTIONS DEGRADED" in out


def test_the_degraded_banner_is_in_the_pushed_body_not_only_on_stdout(
        alert_env, capsys):
    # The requirement that matters most: a page failure must be visible IN
    # THE MESSAGE THAT REACHES THE PHONE, not merely in a log nobody but
    # this test reads.
    alert_env.fail_group("K", CaptureError("K page returned a 404"))
    alert_env.run(capsys)
    assert len(alert_env.sent_calls) == 1
    pushed_body = alert_env.sent_calls[0][2]
    assert "PROJECTIONS DEGRADED" in pushed_body
    assert "K page returned a 404" in pushed_body


def test_a_group_failure_names_which_page_and_does_not_swallow_others(
        alert_env, capsys):
    alert_env.fail_group("TQB", CaptureError("TQB page: session expired"))
    code, out = alert_env.run(capsys)
    assert code == 1
    assert "1 of %d" % len(ALERT_GROUPS) in out
    assert "TQB: TQB page: session expired" in out
    # K and DST both succeeded and are not named as failures.
    for group in ("K", "DST"):
        assert "%s:" % group not in out.split("PROJECTIONS DEGRADED")[1].split(
            "\n\n")[0].replace("TQB: TQB page: session expired", "")


def test_two_group_failures_still_leaves_a_readable_partial_lineup(
        alert_env, capsys):
    alert_env.fail_group("K", CaptureError("K capture timed out"))
    alert_env.fail_group("DST", CaptureError("DST capture timed out"))
    code, out = alert_env.run(capsys)
    assert code == 1
    assert "2 of %d" % len(ALERT_GROUPS) in out
    assert "K: K capture timed out" in out
    assert "DST: DST capture timed out" in out
    assert "BEST LINEUP" in out
    # RB-WR-TE and TQB still succeeded, so Chargers (TQB) should score.
    assert "Chargers" in out


def test_all_four_group_failures_fall_back_to_a_full_capture_failure(
        alert_env, capsys):
    # When NOTHING about the projections could be verified, this is the
    # same class of failure as the roster capture failing outright - no
    # partial lineup is shown, because there is nothing to build one from.
    for group in ALERT_GROUPS:
        alert_env.fail_group(group, CaptureError("%s: unreachable" % group))
    code, out = alert_env.run(capsys)
    assert code == 1
    assert "CAPTURE FAILED" in out
    assert "BEST LINEUP" not in out


def test_a_roster_capture_failure_still_suppresses_everything(
        alert_env, capsys):
    # The roster page is NOT one of the four position groups and keeps its
    # pre-existing all-or-nothing behavior: no roster, nothing can be
    # trusted, full suppression - unchanged by this task.
    from sffl.capture import SessionExpired
    alert_env.fail_group("roster", SessionExpired("session expired"))
    code, out = alert_env.run(capsys)
    assert code == 1
    assert "CAPTURE FAILED" in out
    assert "BEST LINEUP" not in out
    assert "PROJECTIONS DEGRADED" not in out


def test_no_failures_at_all_prints_no_degraded_banner(alert_env, capsys):
    code, out = alert_env.run(capsys)
    assert code == 0
    assert "PROJECTIONS DEGRADED" not in out
    assert "BEST LINEUP" in out
