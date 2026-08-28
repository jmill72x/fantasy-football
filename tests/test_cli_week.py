import pytest
from sffl.cli import main

PROJ = "tests/fixtures/cbs_weekly_rbwrte.txt"


def roster_file(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def test_waivers_ranks_free_agents_by_what_they_add_to_the_lineup(tmp_path, capsys):
    r = roster_file(tmp_path, ["Tyrone Tracy Jr."])
    rc = main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    # Fannin projects highest of the free agents and must lead the ranking.
    assert "Harold Fannin Jr." in out
    assert out.index("Harold Fannin Jr.") < out.index("Braelon Allen")


def test_waivers_names_the_slot_a_claim_would_fill(tmp_path, capsys):
    """A claim that cracks the lineup is a different recommendation from a
    bench stash, and the output must not present them identically. With six
    owned players against five flex slots, a weak free agent benches."""
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Sam LaPorta", "Kyle Pitts", "Braelon Allen",
                               "Elic Ayomanor"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert "SLOT" in out
    assert "bench" in out.lower()


def test_a_roster_name_absent_from_the_projections_is_named_not_zeroed(tmp_path, capsys):
    """Scoring a missing player as 0 silently benches him."""
    r = roster_file(tmp_path, ["Tyrone Tracy Jr.", "Nonexistent Player"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert "Nonexistent Player" in out
    assert "no projection" in out.lower()


def test_an_empty_roster_file_raises_rather_than_claiming_everyone(tmp_path):
    r = roster_file(tmp_path, [])
    with pytest.raises(SystemExit, match="roster is empty"):
        main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
              "--week", "1", "--roster", r, "--waivers"])
