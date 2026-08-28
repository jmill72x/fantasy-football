import re

import pytest
from sffl.cli import main

PROJ = "tests/fixtures/cbs_weekly_rbwrte.txt"

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
