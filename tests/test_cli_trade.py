"""`sffl trade` end to end.

The command is READ-ONLY by construction: it has no path to CBS's trade
form, and `test_no_test_or_code_path_sends_a_trade` pins that.
"""
import pytest

from sffl.cli import main

ROS = "tests/fixtures/cbs_ros_rbwrte.txt"


def roster_file(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def run(tmp_path, capsys, owned, extra=None):
    argv = ["trade", "--projections", ROS, "--roster",
            roster_file(tmp_path, owned), "--week", "1"]
    rc = main(argv + (extra or []))
    return rc, capsys.readouterr().out


def test_the_owner_column_is_matched_not_the_player_names(tmp_path, capsys):
    # Ownership comes off the page's own owner column. A name-only join
    # matched "Chargers" to BOTH the TQB and DST rows on real data and
    # reported a 13-man roster as 16 entries.
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"])
    assert rc == 0
    assert "you are 'OWNER_A'" in out
    assert "2 of your 2 roster names matched" in out


def test_only_other_teams_players_are_trade_targets(tmp_path, capsys):
    # Free agents are a waiver question, not a trade. Ranking a costless add
    # beside players costing real assets is the wrong comparison.
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"])
    targets = out.split("TOP ACQUISITION TARGETS", 1)[1]
    assert "Beta Back" in targets and "Gamma Wide" in targets
    assert "Free Back" not in targets
    assert "Alpha Back" not in targets


def test_targets_name_the_owner_so_an_offer_can_be_addressed(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"])
    targets = out.split("TOP ACQUISITION TARGETS", 1)[1]
    assert "OWNER_B" in targets or "OWNER_C" in targets


def test_an_unmatchable_roster_refuses_rather_than_valuing_nothing(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, ["Nobody At All"])
    assert rc == 1
    assert "could not identify which owner column is yours" in out


def test_a_proposal_reports_both_sides(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"],
                  ["--give", "Alpha Back", "--get", "Beta Wide"])
    assert rc == 0
    assert "your ROS lineup change:" in out
    assert "their ROS lineup change:" in out
    assert "DRAFT PROPOSAL" in out


def test_a_player_not_in_the_pool_is_refused_not_priced_as_zero(tmp_path, capsys):
    # Pricing a trade around a player the pool does not contain would value
    # him at nothing and silently understate what is being given away.
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"],
                  ["--give", "Ghost Player", "--get", "Beta Wide"])
    assert rc == 1
    assert "NOT FOUND" in out


def test_giving_a_player_you_do_not_own_is_refused(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, ["Alpha Back", "Alpha Wide"],
                  ["--give", "Beta Back", "--get", "Beta Wide"])
    assert rc == 1
    assert "NOT FOUND" in out


def test_no_code_path_sends_a_trade():
    # The tool drafts; a human sends. Pinned so a change that starts posting
    # to CBS has to delete this test deliberately rather than slip in.
    import inspect
    from sffl import trade as trade_mod
    from sffl import cli as cli_mod
    src = inspect.getsource(trade_mod) + inspect.getsource(cli_mod._cmd_trade)
    for forbidden in ("capture(", "requests", "urlopen", "post(", "click("):
        assert forbidden not in src, (
            "sffl trade must not contact CBS; found %r" % forbidden)
