"""Task 3: capturing and merging all four position-group pages (RB-WR-TE,
TQB, K, DST) into ONE pool before `best_lineup` runs.

WHAT THIS FILE PINS.

1. `_merge_projection_groups` (the pure merge/dedup helper `_cmd_week` and
   `_cmd_alert` both call) keys on `identity.player_key`'s (name, team,
   pos) - not (name, pos), and not name alone - so it combines rows from
   several groups correctly: it does NOT mistake CBS's TQB and DST pages
   sharing the NFL team nickname as a "player name" ("Chargers" is a
   genuine, distinct row on BOTH pages every week) for a duplicate, it
   does NOT merge two real different players sharing a name at the same
   position on different teams (a real NFL shape, not hypothetical), and
   it DOES report a TRUE duplicate - same name, position, AND team - rather
   than silently keeping one. `_cmd_alert`'s own by_key construction uses
   the same key and the same "detect and report, never silently drop"
   discipline for whatever survives merging (see the residual-duplicate
   tests below) - the key is a strong disambiguator, not a proven-unique
   identity (see `cbs_roster`'s module docstring).

2. `sffl week --projections-tqb/-k/-dst` merges four saved pages into one
   pool and fills all eight lineup slots, with `--group`/`--projections`
   left exactly as they were for every caller that does not pass the new
   flags (see test_cli_week.py, unmodified and still passing).

3. `sffl alert` makes a LOUD, degraded (non-zero exit) report - IN THE
   PUSHED BODY ITSELF, not only on stdout - when one of the four position-
   group pages fails to capture or parse, while STILL producing a lineup
   from the other three. It never silently reproduces `-- UNFILLED` in a
   slot whose page simply failed this run, nor does a same-named roster
   entry (the Chargers TQB/DST shape) - `cbs_roster.parse_lineup_rows`
   resolves both correctly and independently instead.

NO TEST HERE REACHES THE NETWORK OR LAUNCHES A BROWSER: `sffl.capture.capture`
is monkeypatched exactly as `test_cli_alert.py` does it.
"""

import re
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
    merged, _owner, dupes = _merge_projection_groups([
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
    merged, owner, dupes = _merge_projection_groups([
        ("RB-WR-TE", [_proj("Ghost Player", "RB")]),
        ("TQB", [_proj("Ghost Player", "RB")]),
    ])
    out = capsys.readouterr().out
    assert len(merged) == 1
    assert "WARNING" in out
    assert "Ghost Player" in out
    assert "RB-WR-TE" in out and "TQB" in out
    assert owner[_proj("Ghost Player", "RB").key()] == "RB-WR-TE"
    # The SAME fact returned as DATA, not just printed - a caller such as
    # `_cmd_alert` needs this to reach the pushed body and the exit code,
    # not merely stdout (a reviewer found the stdout-only print was the
    # ONLY degradation in `sffl alert` that never reached either).
    assert dupes == [("Ghost Player", "RB", "XX", "RB-WR-TE", "TQB")]


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
    merged, owner, dupes = _merge_projection_groups([
        ("TQB", [_proj("Chargers", "TQB")]),
        ("DST", [_proj("Chargers", "DST")]),
    ])
    out = capsys.readouterr().out
    assert len(merged) == 2
    assert "WARNING" not in out
    assert dupes == []
    assert owner[_proj("Chargers", "TQB").key()] == "TQB"
    assert owner[_proj("Chargers", "DST").key()] == "DST"


def test_a_within_group_suffix_collision_passes_through_unmerged():
    # Two genuinely different players who happen to normalize to the same
    # key WITHIN one group's own page are NOT a cross-group duplicate -
    # `_cmd_week`'s own by_key loop (test_cli_week.py) already warns about
    # and resolves exactly this case; the merge step must not pre-empt it
    # by dropping one before that check ever sees it.
    merged, _owner, dupes = _merge_projection_groups([
        ("RB-WR-TE", [_proj("Braelon Allen", "RB"),
                      _proj("Braelon Allen Jr.", "RB")]),
    ])
    assert len(merged) == 2


def test_group_order_decides_which_side_of_a_true_duplicate_survives():
    # The FIRST group given wins - documented behavior, not an accident of
    # dict ordering. Reversing the input order flips which row survives.
    # SAME team on both, unlike the test below - that is what makes this a
    # genuine (name, pos, team) duplicate rather than two different real
    # players.
    a = _proj("Ghost Player", "RB", team="AAA")
    b = _proj("Ghost Player", "RB", team="AAA")
    merged1, _, dupes1 = _merge_projection_groups(
        [("RB-WR-TE", [a]), ("TQB", [b])])
    merged2, _, dupes2 = _merge_projection_groups(
        [("TQB", [b]), ("RB-WR-TE", [a])])
    assert len(merged1) == 1 and merged1[0] is a
    assert len(merged2) == 1 and merged2[0] is b
    assert dupes1 and dupes2


def test_two_different_players_sharing_name_and_position_both_survive_the_merge():
    # THE OWNER'S CORE POINT: (name, pos) is NOT enough. The NFL has had
    # two simultaneously active players named Mike Williams, both WRs, on
    # different teams - a name+pos-only key would misread this as one
    # cross-group-style duplicate and silently drop one, handing his
    # projection to the other. `team` is what tells them apart, and they
    # are not even in different GROUPS here - both are plain RB-WR-TE rows,
    # which is the realistic shape (two different WRs on one page).
    lac_williams = _proj("Mike Williams", "WR", team="LAC")
    nyj_williams = _proj("Mike Williams", "WR", team="NYJ")
    merged, owner, dupes = _merge_projection_groups([
        ("RB-WR-TE", [lac_williams, nyj_williams]),
    ])
    assert len(merged) == 2
    assert dupes == []
    assert owner[lac_williams.key()] == "RB-WR-TE"
    assert owner[nyj_williams.key()] == "RB-WR-TE"
    assert set(p.team for p in merged) == {"LAC", "NYJ"}


# --- `sffl week`: merging four saved pages into one pool -------------------

def _roster(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def test_week_merges_all_four_groups_into_one_lineup(tmp_path, capsys):
    # "Titans" (TQB) and "Broncos" (DST) are the roster's picks. The TQB
    # and DST fixtures also both happen to carry "Chargers" and "Dolphins"
    # rows - real teams on both real pages - but NEITHER is rostered here.
    # Fix round 1's minor: the by_key collision warning is restricted to
    # names actually IN `owned` (see the code comment above `by_key` in
    # `_cmd_week`), precisely so an unrelated, unowned pool-wide collision
    # like this one does NOT print at all - only a collision that could
    # actually produce a wrong start/sit or waiver read is worth
    # interrupting the output for. This test pins the quiet case; the
    # dedicated collision test below pins the loud one.
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
    # The unowned Chargers/Dolphins collision is real but irrelevant to
    # this roster, so it must NOT be printed at all.
    assert "WARNING" not in out

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
    assert "'Chargers' (TQB, LAC)" in out and "'Chargers' (DST, LAC)" in out


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

        def set_path(self, name, path):
            """Override the saved page served for "roster", "RB-WR-TE",
            "TQB", "K", or "DST"."""
            state["paths"][name] = str(path)

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


# --- fix round 1: the same NFL team rostered for BOTH TQB and DST ---------

def test_the_same_team_rostered_for_tqb_and_dst_never_silently_loses_a_slot(
        alert_env, capsys, tmp_path):
    """THE PROHIBITED OUTCOME, reproduced, then FULLY fixed (not merely
    made loud). `parse_lineup`/`parse_positions` (src/sffl/cbs_roster.py)
    dedup by raw NAME ALONE and ran before any position-aware key ever
    applied - so a roster carrying "Chargers" for BOTH the TQB slot and the
    DST slot (CBS lists all 32 teams on both pages, so nothing stops a
    manager from doing this) used to have the SECOND row's slot silently
    discarded the moment its name collided with the first's: `parse_lineup`
    returned "Chargers" ONCE, `parse_positions` mapped it to TQB only, and
    the DST row was never even a candidate. Output before the fix: `DST
    -- UNFILLED`, exit 0, no mention anywhere - byte-identical to the old
    broken behavior the whole task exists to end.

    THE OWNER'S AMENDMENT superseded round 1's "detect the ambiguity and
    refuse to score either side" fix with a more complete one:
    `cbs_roster.parse_lineup_rows` never collapses by name alone in the
    first place - it keeps each row's own (name, slot, team), so "Chargers"
    TQB and "Chargers" DST are two distinct, independently-resolved
    entries from the start. Each is looked up against the merged
    projections pool via `identity.player_key`'s (name, team, pos), the
    SAME identity `_merge_projection_groups` uses. Result: BOTH slots fill
    CORRECTLY, with no ambiguity to report and no degradation - a strictly
    better outcome than round 1's "loudly refuse to score either."
    """
    collided = tmp_path / "roster_collision.txt"
    with open(ROSTER_FIXTURE) as fh:
        text = fh.read()
    # The fixture's real DST starter is "Patriots" on team "NE"; renaming
    # BOTH the name and the team to "Chargers"/"LAC" reproduces a manager
    # genuinely rostering the same real team for both TQB and DST (a
    # rename that only changed the display name, leaving team "NE", would
    # NOT be a genuine collision under the fuller (name, pos, team) key -
    # the two rows would already differ by team).
    collided.write_text(_rename_patriots_dst_to_chargers(text))
    alert_env.set_path("roster", collided)

    code, out = alert_env.run(capsys)

    # THE CORE ASSERTION: never exit 0 with a silently-unfilled slot and no
    # explanation - satisfied here because there is no unfilled slot at
    # all. Both TQB and DST resolve correctly and independently.
    assert code == 0
    slots_section = out[out.index("BEST LINEUP"):]
    assert "TQB    Chargers" in slots_section
    assert "DST    Chargers" in slots_section
    assert "UNFILLED" not in slots_section.split("K ")[0]
    # And, since both are correctly resolved, NEITHER is reported as
    # unevaluated or ambiguous anywhere.
    assert "Chargers" not in out.split("BEST LINEUP")[0]


def test_a_roster_collision_does_not_affect_an_unambiguous_teammate(
        alert_env, capsys, tmp_path):
    # Sanity check on the fix's precision: a DIFFERENT starter with no
    # collision at all (Evan McPherson, K) is unaffected by the Chargers
    # resolution elsewhere on the same roster - it still reads as a
    # data-problem (his name simply is not on the K fixture), exactly as
    # it would with no collision present anywhere on the page.
    collided = tmp_path / "roster_collision.txt"
    with open(ROSTER_FIXTURE) as fh:
        text = fh.read()
    collided.write_text(_rename_patriots_dst_to_chargers(text))
    alert_env.set_path("roster", collided)

    code, out = alert_env.run(capsys)
    assert code == 0
    start = out.index("NOT EVALUATED for start/sit")
    section = out[start:out.index("\n\n", start)]
    mcpherson_line = next(l for l in section.splitlines()
                          if "Evan McPherson" in l)
    assert "(K)" in mcpherson_line
    assert "DATA PROBLEM" in section
    # And "Chargers" is nowhere in this section - both its slots resolved
    # cleanly, so it has nothing to be reported for.
    assert "Chargers" not in section


# --- fix round 2 (owner's amendment): (name, pos, team), not (name, pos) --

def test_two_different_players_sharing_name_and_position_are_disambiguated_end_to_end(
        alert_env, capsys, tmp_path):
    """THE OWNER'S CORE EXAMPLE, end to end. The RB-WR-TE page carries TWO
    "Mike Williams WR" rows on different real teams (LAC and NYJ) - exactly
    the real NFL shape the owner named. The roster's own "Mike Williams" is
    the LAC one (the roster page carries his team too, via `RosterRow`).
    A (name, pos)-only key would not be able to tell these two rows apart
    at the `by_key` lookup used to build the scored candidate: it would
    resolve to WHICHEVER one happened to be inserted last, potentially
    handing the NYJ Williams's (fabricated, much higher) projection to the
    LAC roster pick. `identity.player_key`'s (name, team, pos) key fixes
    this: the roster's LAC pick must score at the LAC row's real value.
    """
    with open("tests/fixtures/cbs_weekly_tab_rbwrte.txt") as fh:
        proj_text = fh.read()
    # Rename the real "Ladd McConkey WR • LAC" row to "Mike Williams" (same
    # stat line - 6.01 pts) and append a SECOND "Mike Williams WR" row on a
    # different real team (NYJ) with a wildly different, unmistakable
    # projection - if the two are ever confused, the total will show it.
    proj_text = proj_text.replace("Ladd McConkey WR • LAC ",
                                  "Mike Williams WR • LAC ")
    proj_text += ("\tFA\tMike Williams WR • NYJ\tBUF\t22\t11\t86\t63\t8\t"
                 "0.0\t0.0\t0.0\t0.0\t99.9\t99.9\t999.9\t99.9\t0.9\t0.0\t99.99\n")
    proj = tmp_path / "rbwrte_two_williams.txt"
    proj.write_text(proj_text)
    alert_env.set_path("RB-WR-TE", proj)

    with open(ROSTER_FIXTURE) as fh:
        roster_text = fh.read()
    # The roster's own pick is the LAC Williams - same substitution
    # approach as the Chargers TQB/DST tests above.
    roster_text = roster_text.replace("Ladd McConkey WR • LAC ",
                                      "Mike Williams WR • LAC ")
    roster = tmp_path / "roster_two_williams.txt"
    roster.write_text(roster_text)
    alert_env.set_path("roster", roster)

    code, out = alert_env.run(capsys)
    assert code == 0
    # No residual-duplicate or cross-group-duplicate warning - the two
    # rows are correctly told apart by team, not treated as a collision.
    assert "WARNING" not in out
    assert "residual projection duplicate" not in out
    slots_section = out[out.index("BEST LINEUP"):]
    assert "Mike Williams" in slots_section
    # The absurd NYJ projection (999.9 total) must NEVER reach the lineup
    # total - if it did, this would be nowhere close to double digits.
    total_line = next(l for l in out.splitlines() if "BEST LINEUP" in l)
    total = float(total_line.split("(")[1].split(" pts")[0])
    assert total < 100, (
        "the fabricated NYJ Mike Williams projection (999.9) leaked into "
        "the scored total (%s) - the LAC roster pick was matched to the "
        "wrong row" % total)


def test_a_residual_projection_duplicate_is_loud_and_degrades_the_run(
        alert_env, capsys, tmp_path):
    """Even (name, pos, team) is not PROVABLY unique - the owner's second
    point. Two rows identical on all three fields (same real entity's row
    appearing twice within one group's own page, a data anomaly rather
    than the ordinary TQB/DST or two-teams-one-name shapes) must never be
    silently resolved by keeping the first and dropping the second: it
    must be reported and the run marked degraded."""
    with open("tests/fixtures/cbs_weekly_tab_rbwrte.txt") as fh:
        proj_text = fh.read()
    # Duplicate the Ladd McConkey row verbatim - same name, same pos, same
    # team - within the SAME group's own page (not a cross-group case,
    # which `_merge_projection_groups` already reports; this exercises
    # `_cmd_alert`'s OWN by_key residual-duplicate detection instead).
    mcconkey_line = next(l for l in proj_text.splitlines()
                         if "Ladd McConkey" in l)
    proj_text = proj_text.rstrip("\n") + "\n" + mcconkey_line + "\n"
    proj = tmp_path / "rbwrte_duplicate_row.txt"
    proj.write_text(proj_text)
    alert_env.set_path("RB-WR-TE", proj)

    code, out = alert_env.run(capsys)
    assert code == 1
    assert "residual projection duplicate" in out
    assert "Ladd McConkey" in out
    # And the digest still produced a real, usable lineup - a residual
    # duplicate degrades the run, it does not blank it out.
    assert "BEST LINEUP" in out
    # Minor review fix (c): the pushed body must carry this too, not only
    # stdout - see test_the_degraded_banner_is_in_the_pushed_body... above
    # for the same requirement on a group-capture failure.
    assert len(alert_env.sent_calls) == 1
    pushed_body = alert_env.sent_calls[0][2]
    assert "residual projection duplicate" in pushed_body
    assert "Ladd McConkey" in pushed_body


# --- Task 3b: CBS player ids as the real CBS ↔ CBS join key ----------------

def _rename_patriots_dst_to_chargers(text):
    """Rename the fixture's real "Patriots DST • NE " starter row to
    "Chargers DST • LAC ", reproducing a manager who rostered the SAME
    real NFL team for both the TQB and DST slots.

    The row's id is rewritten too - from Patriots' own real id (1931) to
    the REAL Chargers DST id (1924), which is what `tests/fixtures/
    cbs_weekly_dst.txt` (Task 3b regenerated both fixtures from the SAME
    live capture, 2026-08-30) actually carries for that row. Carrying
    Patriots' id forward unchanged would attach the WRONG entity's id to a
    row that now DISPLAYS a different team - `identity.resolve_key` trusts
    an id over the (renamed) composite fields, so it would look up
    Patriots' real projection by id 1931 and never find "Chargers DST" at
    all (UNFILLED, not resolved) - a mismatch a real capture could never
    produce, since both pages' ids for the SAME entity are pulled from the
    SAME `playerpage/<id>` link mechanism and always agree. Using the real
    id 1924 keeps this reproduction internally consistent AND upgrades what
    it proves: the Chargers TQB+DST case (Task 3's original bug) now
    resolves via the id join, one step stronger than the composite
    fallback it required before this task."""
    return text.replace(
        "id=1931\t\tDST\tPatriots DST • NE \t",
        "id=1924\t\tDST\tChargers DST • LAC \t")


_LEADING_ID = re.compile(r"^id=\d+\t")


def _strip_any_id_prefix(line):
    """Remove a leading "id=<digits>\\t" prefix, if `line` already has one.

    Several fixtures now carry real ids from a live capture (Task 3b) - a
    test that wants to attach its OWN synthetic id to a fixture row must
    strip whatever real one is already there first, or the two concatenate
    into a malformed double prefix that fails to parse at all.
    """
    return _LEADING_ID.sub("", line)


def _replace_line_containing(text, needle, new_line):
    lines = text.splitlines()
    found = False
    for i, line in enumerate(lines):
        if needle in line:
            lines[i] = new_line
            found = True
            break
    assert found, "no line contains %r" % needle
    return "\n".join(lines) + "\n"


def test_a_roster_row_matches_a_projection_by_id_even_when_names_disagree(
        alert_env, capsys, tmp_path):
    """THE ID PATH, proven to matter rather than merely present: CBS
    sometimes spells the same player's name differently across its own
    pages (this project already normalizes punctuation for exactly that
    reason) - here the projections page spells the roster's Ja'Marr Chase
    as "Jamarr C.", a mismatch `identity.normalize_name` does NOT paper
    over. The (name, team, pos) composite key would therefore fail to
    match these two rows at all; the shared CBS id must still resolve them
    to the SAME real player and score him at his real, unmistakable line
    (8.01 pts, not zero and not "no projection")."""
    with open("tests/fixtures/cbs_weekly_tab_rbwrte.txt") as fh:
        proj_text = fh.read()
    proj_text = _replace_line_containing(
        proj_text, "Ja'Marr Chase",
        "id=2966320\t\tTeam I...\tJamarr C. WR • CIN \tTB\t17\t6\t97\t96\t1\t"
        "0.2\t1.1\t5.5\t0.0\t10.6\t7.3\t90.8\t12.4\t0.6\t0.0\t8.01")
    proj = tmp_path / "rbwrte_id_name_mismatch.txt"
    proj.write_text(proj_text)
    alert_env.set_path("RB-WR-TE", proj)

    with open(ROSTER_FIXTURE) as fh:
        roster_text = fh.read()
    roster_text = _replace_line_containing(
        roster_text, "Ja'Marr Chase",
        "id=2966320\t\tWR\tJa'Marr Chase WR • CIN \tTB\t")
    roster = tmp_path / "roster_id_name_mismatch.txt"
    roster.write_text(roster_text)
    alert_env.set_path("roster", roster)

    code, out = alert_env.run(capsys)
    assert code == 0
    slots_section = out[out.index("BEST LINEUP"):]
    # Scored under the PROJECTIONS page's own spelling - the id resolved
    # the roster pick to this row, not a name-based match (which would have
    # failed and left him unevaluated/data-problem instead).
    assert "Jamarr C." in slots_section
    assert "PROJECTIONS DEGRADED" not in out
    # The real assertion the id path buys: he is not reported as
    # unevaluated/a data problem. (The cosmetic START/SIT name diff below
    # BEST LINEUP is a separate, purely-display comparison that is still
    # name-based - see alert._start_sit_diff - and is out of this task's
    # scope; it is not what this test is about.)
    if "NOT EVALUATED for start/sit" in out:
        unevaluated_section = out[out.index("NOT EVALUATED for start/sit"):]
        assert "Chase" not in unevaluated_section.split("\n\n")[0]


def test_two_same_name_team_position_rows_are_disambiguated_by_different_ids(
        alert_env, capsys, tmp_path):
    """THE RESIDUAL COLLISION THE COMPOSITE KEY COULD NEVER RESOLVE: two
    rows identical on name, team, AND position (the one case
    `_merge_projection_groups`'s own docstring names as unresolvable by
    that key alone) - here told apart because they carry DIFFERENT CBS
    ids. No warning, no degradation: this is the id path succeeding where
    the composite fallback structurally cannot."""
    with open("tests/fixtures/cbs_weekly_tab_rbwrte.txt") as fh:
        proj_text = fh.read()
    mcconkey_line = next(l for l in proj_text.splitlines()
                         if "Ladd McConkey" in l)
    # The fixture's own McConkey row already carries a REAL id (Task 3b
    # regenerated it from a live capture) - strip it first so this test's
    # own synthetic ids are the only ones on either constructed row.
    mcconkey_content = _strip_any_id_prefix(mcconkey_line)
    id_a = "id=1111111\t" + mcconkey_content
    id_b = "id=2222222\t" + mcconkey_content
    proj_text = proj_text.replace(mcconkey_line, id_a) + id_b + "\n"
    proj = tmp_path / "rbwrte_two_ids_same_everything.txt"
    proj.write_text(proj_text)
    alert_env.set_path("RB-WR-TE", proj)

    with open(ROSTER_FIXTURE) as fh:
        roster_text = fh.read()
    roster_text = _replace_line_containing(
        roster_text, "Ladd McConkey",
        "id=1111111\t\tWR\tLadd McConkey WR • LAC \tARI\t")
    roster = tmp_path / "roster_two_ids.txt"
    roster.write_text(roster_text)
    alert_env.set_path("roster", roster)

    code, out = alert_env.run(capsys)
    assert code == 0
    assert "WARNING" not in out
    assert "residual projection duplicate" not in out
    assert "BEST LINEUP" in out


def test_two_rows_sharing_the_same_id_are_still_a_loud_residual_collision(
        alert_env, capsys, tmp_path):
    """THE ID COLLISION ITSELF IS NOT SILENTLY TRUSTED. Two rows claiming
    the SAME CBS id (a genuine data anomaly CBS itself would presumably
    never produce, but this project never assumes a heuristic - or an id -
    holds without checking) must still be reported exactly like a
    composite-key residual duplicate: named, degraded, in the pushed body,
    non-zero exit."""
    with open("tests/fixtures/cbs_weekly_tab_rbwrte.txt") as fh:
        proj_text = fh.read()
    mcconkey_line = next(l for l in proj_text.splitlines()
                         if "Ladd McConkey" in l)
    id_line = "id=5555555\t" + _strip_any_id_prefix(mcconkey_line)
    proj_text = proj_text.replace(mcconkey_line, id_line) + id_line + "\n"
    proj = tmp_path / "rbwrte_duplicate_id.txt"
    proj.write_text(proj_text)
    alert_env.set_path("RB-WR-TE", proj)

    code, out = alert_env.run(capsys)
    assert code == 1
    assert "residual projection duplicate" in out
    assert "Ladd McConkey" in out
    assert "BEST LINEUP" in out
    assert len(alert_env.sent_calls) == 1
    assert "residual projection duplicate" in alert_env.sent_calls[0][2]
