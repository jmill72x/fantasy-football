import re

import pytest
from sffl.cbs_weekly import DEFAULT_PROFILE, _load_owner_codes
from sffl.cli import main

PROJ = "tests/fixtures/cbs_weekly_rbwrte.txt"

# _cmd_week has no --profile override, so it always classifies against the
# real profile's owner_codes. A fabricated manager token has to be one of
# those configured codes or the row simply fails to match at all (F4) rather
# than reaching classify_avail as "owned" - so tests that need an
# owned-by-another-team row use whatever code is actually configured instead
# of a hardcoded guess like "DAL".
OWNER_CODE = _load_owner_codes(DEFAULT_PROFILE)[0]

# "    3.20     WR/TE  Harold Fannin Jr. (TE)" -> (3.20, "WR/TE", "Harold
# Fannin Jr.", "TE"). Slot/bench and position are single tokens (no internal
# whitespace in this league's labels), so the name is whatever sits between
# them, matched non-greedily against the trailing " (POS)".
_ROW = re.compile(r"^\s*(\d+\.\d{2})\s+(\S+)\s+(.+?) \((\w+)\)\s*$")
_TOTAL = re.compile(r"best legal lineup: (\d+\.\d+) pts")


def roster_file(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def waiver_rows(out):
    """(points, slot_or_bench, name, pos) for each WAIVER TARGETS row, in
    printed order - the SLOT column is what distinguishes a claim that
    cracks the lineup from one that only benches."""
    section = out.split("WAIVER TARGETS", 1)[1]
    rows = []
    for line in section.splitlines():
        m = _ROW.match(line)
        if m:
            rows.append((float(m.group(1)), m.group(2), m.group(3), m.group(4)))
    return rows


def lineup_total(out):
    return float(_TOTAL.search(out).group(1))


def test_waivers_ranks_free_agents_by_what_they_add_to_the_lineup(tmp_path, capsys):
    """Own only receivers/tight ends - no RB at all. The RB slot then sits
    open, so the three free-agent backs rank purely by delta: Allen 1.70 >
    Marks 1.60 > Tracy 1.10. The fixture's file order for these three is
    Allen, Tracy, Marks - Marks and Tracy disagree between file order and
    delta order, so a ranking that forgot to sort would put Tracy above
    Marks and the ordering assertion below would fail."""
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Kyle Pitts", "Elic Ayomanor"])
    rc = main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0

    rows = waiver_rows(out)
    names = [name for _pts, _slot, name, _pos in rows]
    assert names.index("Woody Marks") < names.index("Tyrone Tracy Jr.")

    pts = [p for p, _slot, _name, _pos in rows]
    assert pts == sorted(pts, reverse=True), \
        "+PTS column must be non-increasing top to bottom: %r" % (pts,)


def test_waivers_names_the_slot_a_claim_would_fill(tmp_path, capsys):
    """A claim that cracks the lineup is a different recommendation from a
    bench stash, and the output must not present them identically. Owning
    the five weakest (LaPorta, Pitts, Ayomanor, Allen, Marks) leaves Fannin
    (4.80) and Likely (3.50) as free agents who crack the lineup, and Tracy
    (1.10 - worse than the owned Marks at 1.60) as one who benches, so both
    outcomes are genuinely exercised rather than merely printed as a column
    header."""
    r = roster_file(tmp_path, ["Sam LaPorta", "Kyle Pitts", "Elic Ayomanor",
                               "Braelon Allen", "Woody Marks"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out

    by_name = dict((name, slot) for _pts, slot, name, _pos in waiver_rows(out))
    assert by_name["Harold Fannin Jr."] == "WR/TE"
    assert by_name["Harold Fannin Jr."] != "bench"
    assert by_name["Tyrone Tracy Jr."] == "bench"


def test_a_roster_name_absent_from_the_projections_is_named_not_zeroed(tmp_path, capsys):
    """Scoring a missing player as 0 and folding him into the roster would
    still pass a test that only checks he is NAMED somewhere - so this also
    pins EXCLUSION: his name must not appear as if he occupies a lineup
    slot, and the total must be identical to the same roster with his line
    simply deleted from the file."""
    r = roster_file(tmp_path, ["Tyrone Tracy Jr.", "Nonexistent Player"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert "Nonexistent Player" in out
    assert "no projection" in out.lower()

    slots_section = out.split("best legal lineup:", 1)[1].split("WAIVER TARGETS", 1)[0]
    assert "Nonexistent Player" not in slots_section
    total_with_missing_named = lineup_total(out)

    r2 = roster_file(tmp_path, ["Tyrone Tracy Jr."])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r2, "--waivers"])
    out2 = capsys.readouterr().out
    assert total_with_missing_named == lineup_total(out2)


def test_an_empty_roster_file_raises_rather_than_claiming_everyone(tmp_path):
    r = roster_file(tmp_path, [])
    with pytest.raises(SystemExit, match="roster is empty"):
        main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
              "--week", "1", "--roster", r, "--waivers"])


def test_a_roster_that_resolves_to_zero_names_raises_rather_than_claiming_everyone(tmp_path):
    """I2: cli.py's guard at the top of _cmd_week only checks that the
    roster FILE is non-empty. A roster with names in it, none of which
    resolve to a projection, sails past that guard and reaches the same
    destination the spec explicitly raises for: an empty `roster` list,
    `best_lineup` optimising to 0.00, and every free agent ranked as a
    claim - at exit 0. Realistic trigger: get_page_text emitting a
    non-breaking space, so 'Woody\\xa0Marks' normalizes to 'woodymarks'
    (normalize_name's [^a-z0-9 ] strip deletes \\xa0 rather than treating it
    as a separator) and matches nothing on the saved page."""
    r = roster_file(tmp_path, ["Nonexistent Player One", "Nonexistent Player Two"])
    with pytest.raises(SystemExit, match="0 of 2"):
        main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
              "--week", "1", "--roster", r, "--waivers"])


def test_a_zero_row_parse_raises_rather_than_exiting_0(tmp_path):
    """F5: the spec's failure table requires a raise for an empty roster,
    which IS implemented (see the test above) - a zero-row PROJECTIONS parse
    is the same class of mistake. A login page or a truncated save yields no
    player rows at all; before this fix that printed '0 rows parsed ... best
    legal lineup: 0.00' and returned success, when it is almost certainly
    the wrong page or a failed save, not a real empty result."""
    login_page = tmp_path / "login_page.txt"
    login_page.write_text("Please sign in to continue.\n")
    r = roster_file(tmp_path, ["Tyrone Tracy Jr."])
    with pytest.raises(SystemExit, match="0 rows parsed"):
        main(["week", "--projections", str(login_page), "--group", "RB-WR-TE",
              "--week", "1", "--roster", r, "--waivers"])


OPTIMAL_FIVE = ["Harold Fannin Jr.", "Isaiah Likely", "Sam LaPorta",
                "Kyle Pitts", "Braelon Allen"]
SIX = OPTIMAL_FIVE + ["Tyrone Tracy Jr."]


def test_start_sit_is_silent_when_the_current_lineup_is_already_optimal(tmp_path, capsys):
    r = roster_file(tmp_path, SIX)
    cur = tmp_path / "current.txt"
    cur.write_text("\n".join(OPTIMAL_FIVE) + "\n")
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    assert "already optimal" in out.lower()


def test_start_sit_names_both_sides_of_a_swap(tmp_path, capsys):
    """Six players, five flex slots: Tracy (1.10) is the odd one out, so a
    lineup that starts him instead of Allen (1.70) is one swap from optimal."""
    r = roster_file(tmp_path, SIX)
    cur = tmp_path / "current.txt"
    swapped = [n for n in OPTIMAL_FIVE if n != "Braelon Allen"]
    cur.write_text("\n".join(swapped + ["Tyrone Tracy Jr."]) + "\n")
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    assert "START" in out and "SIT" in out
    assert "Braelon Allen" in out
    assert "Tyrone Tracy Jr." in out
    # Verify sidedness: Braelon Allen (better) should be in START, Tracy (worse) in SIT
    tail = out[out.index("START"):]
    assert tail.index("Braelon Allen") < tail.index("Tyrone Tracy Jr.")


def test_start_sit_without_a_current_lineup_prints_the_optimum_and_says_so(tmp_path, capsys):
    r = roster_file(tmp_path, SIX)
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--start-sit"])
    out = capsys.readouterr().out
    assert "no current lineup" in out.lower()


def test_start_sit_normalizes_current_lineup_names(tmp_path, capsys):
    """Player names in --current should be normalized to match projections.
    Harold Fannin Jr. spelled as 'Harold Fannin' in --current should match
    the canonical 'Harold Fannin Jr.' in projections, not trigger START/SIT."""
    r = roster_file(tmp_path, SIX)
    cur = tmp_path / "current.txt"
    # Write names with "Harold Fannin" (no Jr.) to test normalization
    normalized_optimal = ["Harold Fannin", "Isaiah Likely", "Sam LaPorta",
                          "Kyle Pitts", "Braelon Allen"]
    cur.write_text("\n".join(normalized_optimal) + "\n")
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    # Despite the different spelling, the normalized names should match,
    # so output should show "already optimal"
    assert "already optimal" in out.lower()


def test_start_sit_excludes_a_current_name_with_no_projection_from_sit(tmp_path, capsys):
    """--current is documented as the eight-player lineup currently set on
    CBS - TQB, K and DST included. sources/cbs-weekly.yaml defines only the
    RB-WR-TE group, so those names have no projection and never land in
    by_key. Before the fix they still fell into SIT every real run: 'bench
    your kicker', unconditionally. They must be named as not evaluated
    instead, and must not appear as a SIT recommendation."""
    r = roster_file(tmp_path, SIX)
    cur = tmp_path / "current.txt"
    cur.write_text("\n".join(OPTIMAL_FIVE + ["Some Kicker"]) + "\n")
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    assert "not evaluated" in out.lower()
    assert "Some Kicker" in out
    # OPTIMAL_FIVE is genuinely optimal among the evaluated players, so once
    # "Some Kicker" is correctly excluded there is nothing left to report.
    assert "already optimal" in out.lower()


def test_a_name_collision_after_normalization_warns_instead_of_silently_dropping(tmp_path, capsys):
    """normalize_name strips generational suffixes, so a page carrying both
    'Collision Test' and 'Collision Test Jr.' collide on the same by_key
    entry. last-write-wins previously erased one with no signal at all;
    this must warn, naming both raw spellings, and must not raise - a real
    page can legitimately hold two similarly-named players."""
    proj = tmp_path / "collide.txt"
    proj.write_text(
        "W (9/16) Collision Test RB • NYJ @TEN 17 13 25 1 55 "
        "9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70\n"
        "W (9/16) Collision Test Jr. RB • NYJ @TEN 17 13 25 1 55 "
        "5.0 20.0 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70\n"
    )
    r = roster_file(tmp_path, ["Collision Test"])
    rc = main(["week", "--projections", str(proj), "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out
    assert "Collision Test" in out
    assert "Collision Test Jr." in out


def test_a_waiver_row_owned_by_another_team_is_excluded_and_reported(tmp_path, capsys):
    """F3: `avail` on the ALL PLAYERS view can name another manager's team,
    not just FA/waiver. A row like that must never be offered as a waiver
    target, and the exclusion must be visible in the output, not silent."""
    lines = open(PROJ).read().splitlines()
    lines.append(
        "%s Ghost Player RB • SF @LAR 22 11 86 63 8 "
        "9.5 99.9 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 9.99" % OWNER_CODE)
    proj = tmp_path / "with_owned.txt"
    proj.write_text("\n".join(lines) + "\n")

    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Kyle Pitts", "Elic Ayomanor"])
    rc = main(["week", "--projections", str(proj), "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0

    names = [name for _pts, _slot, name, _pos in waiver_rows(out)]
    assert "Ghost Player" not in names
    assert "1 excluded" in out


def test_waiver_ranking_ties_break_by_name_not_page_order(tmp_path, capsys):
    """Owning Fannin/Likely/LaPorta/Allen/Marks/Tracy leaves Ayomanor and
    Pitts as free agents. Both project 2.50 naive (a real tie in the
    fixture) and, against this roster, both add exactly 0.90 to the optimal
    lineup by displacing Marks - a genuine tie in `delta`, not just in raw
    score. `sorted` is stable over insertion order, so without an explicit
    tiebreak the ranking between them depends on which one the saved page
    happened to list first - reversing the file must not change the
    printed order."""
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Braelon Allen",
                               "Woody Marks", "Tyrone Tracy Jr."])

    reversed_path = tmp_path / "reversed.txt"
    lines = open(PROJ).read().splitlines()
    reversed_path.write_text("\n".join(reversed(lines)) + "\n")

    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out_forward = capsys.readouterr().out
    main(["week", "--projections", str(reversed_path), "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out_reversed = capsys.readouterr().out

    names_forward = [name for _pts, _slot, name, _pos in waiver_rows(out_forward)]
    names_reversed = [name for _pts, _slot, name, _pos in waiver_rows(out_reversed)]
    assert names_forward == names_reversed, (
        "waiver order changed when the saved page's line order was reversed: "
        "%r vs %r" % (names_forward, names_reversed))
    # And specifically: with a real tie in delta, the name tiebreak sorts
    # Ayomanor ahead of Pitts, in both directions.
    assert names_forward.index("Elic Ayomanor") < names_forward.index("Kyle Pitts")


def test_zero_delta_ties_break_by_points_not_name(tmp_path, capsys):
    """F8: among players who add nothing this week, the better player is the
    better stash. Owning Fannin/Likely/LaPorta/Pitts/Ayomanor/Allen fills
    every flex slot with players who all outscore both remaining free
    agents, so Marks (1.60) and Tracy (1.10) both add exactly 0.00 to the
    lineup - but Marks is the better player and must rank above Tracy, not
    below him by alphabetical accident ('Tyrone Tracy Jr.' < 'Woody
    Marks')."""
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Kyle Pitts", "Elic Ayomanor",
                               "Braelon Allen"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out

    rows = waiver_rows(out)
    assert [pts for pts, _slot, _name, _pos in rows] == [0.0, 0.0]
    names = [name for _pts, _slot, name, _pos in rows]
    assert names == ["Woody Marks", "Tyrone Tracy Jr."]


def test_a_zero_delta_claim_is_never_labelled_with_a_real_slot(tmp_path, capsys):
    """F8: a free agent tied exactly with the worst starter can still be the
    one `best_lineup` happens to choose (ties break by name), which used to
    print a real slot label like FLEX3 for a claim that changes nothing -
    reading as though it cracks the lineup when the total is unchanged. Five
    owned players (10/9/8/7/6 pts, via a clean rec_td-only line) fill every
    flex slot; a free agent tied at 6 pts with the worst of them, and
    alphabetically first, displaces it with delta 0.00 - and must show as
    bench, never as the slot the tie happened to resolve into."""
    proj = tmp_path / "ties.txt"
    proj.write_text(
        "FA Player One RB • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 2.0 0.0 0.0\n"
        "FA Player Two WR • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.8 0.0 0.0\n"
        "FA Player Three WR • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.6 0.0 0.0\n"
        "FA Player Four WR • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.4 0.0 0.0\n"
        "FA Player Zulu WR • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.2 0.0 0.0\n"
        "FA Player Alpha WR • DAL @LAR 22 11 86 63 8 "
        "0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 1.2 0.0 0.0\n"
    )
    r = roster_file(tmp_path, ["Player One", "Player Two", "Player Three",
                               "Player Four", "Player Zulu"])
    main(["week", "--projections", str(proj), "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out

    rows = waiver_rows(out)
    assert len(rows) == 1
    pts, slot, name, _pos = rows[0]
    assert name == "Player Alpha"
    assert pts == 0.0
    assert slot == "bench"


def test_calibrated_waivers_rank_the_higher_yardage_back_first(tmp_path, capsys):
    """C1 end-to-end regression. Two free-agent RBs differing ONLY in
    projected rushing yards (25.7 vs 21.0) must never have the LOWER one
    outrank the higher one. Before the monotone-envelope fix,
    calibrate.expected_points' raw, unsmoothed anchors scored 21.0 yds at
    0.525 and 25.7 yds at only 0.119 - so `sffl week --waivers --curves`
    recommended claiming the strictly worse back. Names are chosen so the
    intended winner also wins the name tiebreak, since a flat stretch of the
    enveloped curve can legitimately tie the two exactly - the fix is that
    the worse one can no longer win outright, not that every tie must break
    a particular way by coincidence."""
    lines = open(PROJ).read().splitlines()
    lines.append("FA Higher Yards Back RB • SF @LAR 22 11 86 63 8 "
                 "5.0 25.7 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0")
    lines.append("FA Lower Yards Back RB • SF @LAR 22 11 86 63 8 "
                 "5.0 21.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0")
    proj = tmp_path / "with_backs.txt"
    proj.write_text("\n".join(lines) + "\n")

    # No RB at all on the roster - the RB slot sits open, so both
    # free-agent backs rank by what they add directly (same trick as
    # test_waivers_ranks_free_agents_by_what_they_add_to_the_lineup).
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Kyle Pitts", "Elic Ayomanor"])
    rc = main(["week", "--projections", str(proj), "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--curves",
               "calibration/2025.yaml", "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0

    rows = waiver_rows(out)
    by_points = dict((name, pts) for pts, _slot, name, _pos in rows)
    assert "Higher Yards Back" in by_points and "Lower Yards Back" in by_points
    assert by_points["Higher Yards Back"] >= by_points["Lower Yards Back"], (
        "25.7 projected rushing yards must score at least as much as 21.0: %r"
        % (by_points,))

    names = [name for _pts, _slot, name, _pos in rows]
    assert names.index("Higher Yards Back") < names.index("Lower Yards Back"), (
        "the higher-yardage back must rank first, not the lower one: %r"
        % (names,))


def test_curves_flag_changes_a_named_number_in_the_output(tmp_path, capsys):
    """I5: --curves had no test at all before this - mutating _cmd_week to
    hardcode curves = None (silently disabling calibration) passed all 398
    tests with no signal. Run the identical command with and without
    --curves and check two specific, named things actually change: the
    best-legal-lineup total, and which player fills FLEX3. (Both owned
    rostered players are scored through score_week, so calibration reaches
    them even with zero free agents in play.)"""
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Elic Ayomanor", "Braelon Allen",
                               "Tyrone Tracy Jr.", "Sam LaPorta",
                               "Kyle Pitts", "Woody Marks"])

    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--waivers"])
    out_naive = capsys.readouterr().out

    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--curves", "calibration/2025.yaml", "--waivers"])
    out_curved = capsys.readouterr().out

    def flex3(out):
        for line in out.splitlines():
            if line.strip().startswith("FLEX3"):
                return line.split(None, 1)[1].strip()
        raise AssertionError("no FLEX3 line in output:\n%s" % out)

    assert lineup_total(out_naive) != lineup_total(out_curved), (
        "--curves must change the best-legal-lineup total: naive %.2f, "
        "curved %.2f" % (lineup_total(out_naive), lineup_total(out_curved)))
    assert flex3(out_naive) != flex3(out_curved), (
        "--curves must change who fills FLEX3: naive picked %r, curved "
        "picked %r" % (flex3(out_naive), flex3(out_curved)))
