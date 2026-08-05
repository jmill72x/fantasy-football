import argparse
import os
import re

import openpyxl

from sffl.cli import _value_pool, main
from sffl.identity import NFL_TEAMS
from sffl.league import load_league
from sffl.render.xlsx import GROUP_GAP

DS = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_value_sample.csv"


def test_render_writes_both_artifacts(tmp_path):
    pdf = str(tmp_path / "board.pdf")
    xlsx = str(tmp_path / "board.xlsx")
    rc = main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--pdf", pdf, "--xlsx", xlsx])
    assert rc == 0
    assert os.path.getsize(pdf) > 0
    assert os.path.getsize(xlsx) > 0


def test_render_requires_at_least_one_output(capsys):
    rc = main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--pdf" in out and "--xlsx" in out


# A dedicated fixture: draftsharks_value_sample.csv plus one extra WR row on
# team "UNS" (an unsigned free agent placeholder, not a real NFL franchise).
# The real Draft Sharks extract has 23 such rows (UNS x22, RK x1) - they have
# no bye week and build_rows correctly raises rather than rendering a blank,
# so cmd_render must filter them out itself and say how many it dropped,
# rather than silently shrinking the board or crashing.
UNROSTERED_FIXTURE = "tests/fixtures/draftsharks_render_unrostered_sample.csv"


def test_render_drops_unrostered_players_and_reports_the_count(tmp_path, capsys):
    pdf = str(tmp_path / "board.pdf")
    rc = main(["render", "--source", DS, "--file", UNROSTERED_FIXTURE, "--year", "2026",
               "--pdf", pdf])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dropped 1" in out
    assert "UNS" in out


def test_dropping_unrostered_players_reprices_nobody_on_the_rendered_board(tmp_path):
    # cmd_render drops non-NFL team codes AFTER _value_pool has priced the
    # whole pool, so removing them cannot move anyone's _dollars -
    # replacement levels and the market curve are already fixed by then.
    # The ordering is deliberate, not incidental: filtering first would
    # shrink the pool the replacement level is computed from and quietly
    # reprice the entire board. This class of "obviously true" invariant
    # has broken three times in the renderers' history, so pin it.
    #
    # The comparison must cross a real boundary or it proves nothing. An
    # earlier version of this test read the dollars off the same Player
    # objects it then filtered a list of - and since filtering a Python
    # list does not mutate its elements, every assertion compared a value
    # to itself. It passed against a cmd_render deliberately mutated to
    # reprice after filtering. So: snapshot the independently-valued
    # dollars, drive the REAL `render` command end to end, and read the
    # MY$ back out of the workbook it wrote.
    args = argparse.Namespace(
        source=DS, file=UNROSTERED_FIXTURE, year=2026, set=None,
        curves=None, prices=None, policy="starter", tqb_starters=None)
    pool, _curve, _prices = _value_pool(load_league("leagues/sffl/2026.yaml"), args)

    # The workbook rounds MY$ to whole dollars, so compare on that basis.
    priced = dict((p.name, round(p.stats["_dollars"], 0)) for p in pool)
    unrostered = [p.name for p in pool if p.team not in NFL_TEAMS]
    assert unrostered, (
        "the fixture must contain at least one unrostered player, or this "
        "test filters nothing and proves nothing")

    xlsx = str(tmp_path / "board.xlsx")
    rc = main(["render", "--source", DS, "--file", UNROSTERED_FIXTURE,
               "--year", "2026", "--xlsx", xlsx])
    assert rc == 0

    ws = openpyxl.load_workbook(xlsx).active
    on_board = {}
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for r in range(1, ws.max_row + 1):
            name = ws.cell(r, col0 + 1).value
            if name in priced:
                on_board[name] = ws.cell(r, col0 + 6).value   # the MY$ column

    assert on_board, "no player from the valued pool reached the board"
    for name in unrostered:
        assert name not in on_board, (
            "%s has a non-NFL team code and must not render" % name)
    for name, my_dollars in sorted(on_board.items()):
        assert my_dollars == priced[name], (
            "%s was repriced by dropping unrostered players: the board says "
            "$%s, the valuation said $%s" % (name, my_dollars, priced[name]))


def test_plan_prints_the_tradeoff_table_and_keeps_the_three_tie_states(capsys):
    rc = main(["plan", "--source", DS, "--file", FIXTURE, "--year", "2026"])
    out = capsys.readouterr().out
    assert rc == 0
    # The floor and its penalty, in words.
    assert "under $26" in out and "forfeits" in out
    # The illustration, labelled.
    assert "ILLUSTRATION" in out
    # All three tie states, distinct. "no data" is $28/$29/$36 - never
    # submitted - and must never be printed as the measured 0% that $27 is.
    assert "no data" in out and "0%" in out and "100%" in out
    # An escalated tie is money paid above the bid, not a free tie.
    assert "LIVE" in out
    # Bids run in bid order, from the floor. Nothing is ranked, starred or
    # recommended: this table shows the tradeoff, it does not answer it.
    bids = [int(m.group(1)) for m in
            (re.match(r"  \$(\d+) +\d", line) for line in out.splitlines())
            if m]
    assert len(bids) == 20, "the floor $26 to the record high $45"
    assert bids == sorted(bids) and min(bids) == 26


def test_plan_prints_both_tie_numbers_under_headings_that_tell_them_apart(capsys):
    # Jeff's ruling on 2026-08-05: show both. The terminal and the PDF must
    # not be able to disagree about what either number means, so both carry
    # the same two headings and the same legend wording.
    main(["plan", "--source", DS, "--file", FIXTURE, "--year", "2026"])
    out = capsys.readouterr().out
    assert "TIE1+" in out and "TIE2+" in out
    assert "ALREADY at this exact bid" in out
    assert "2+ teams tied EACH OTHER" in out
    # $30 is the case that made the ruling: occupied every year, tied twice.
    row = [l for l in out.splitlines() if l.startswith("  $30 ")][0]
    assert "100%" in row and "40%" in row
    # ...and $28, never bid, refuses to answer either question.
    row = [l for l in out.splitlines() if l.startswith("  $28 ")][0]
    assert row.count("no data") == 2
    # LEFT and DISCR say on the page that they are before any bump.
    assert "LEFT*" in out and "DISCR*" in out and "PRE-BUMP" in out


def test_plan_reports_a_malformed_bid_history_instead_of_a_traceback(tmp_path, capsys):
    # `load_bid_history` raises ValueError - not OSError - for a file that
    # exists and is wrong: a missing column, an unparseable number, a cap_cost
    # under its own bid, a duplicated rank. It raises with a message naming the
    # file and the line, and that message is the useful thing. Catching only
    # OSError sent it out as a traceback instead of the intended clean exit.
    bad = tmp_path / "bad.csv"
    bad.write_text("year,rank,franchise,bid,bump,cap_cost,player,note\n"
                   "2025,1,Alpha,40,0,39,Player One,\n")
    rc = main(["plan", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--bids", str(bad)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "cannot read the bid history" in err
    assert "cap_cost" in err, "the loader's own diagnosis must survive"


def test_render_degrades_loudly_when_the_bid_history_cannot_be_read(tmp_path, capsys):
    # The board is the artifact that must exist on auction day, so a bad
    # --bids path costs one block of one page - never the whole render, and
    # never silently.
    pdf = str(tmp_path / "board.pdf")
    rc = main(["render", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--pdf", pdf, "--bids", str(tmp_path / "nope.csv")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WARNING" in out and "budget arithmetic only" in out
    assert os.path.getsize(pdf) > 0
