import openpyxl
import pytest

from sffl.league import load_league
from sffl.render.rows import BoardRow
from sffl.render.xlsx import render_xlsx

LG = load_league("leagues/sffl/2026.yaml")


def row(rank, name, pos, dollars, est=None):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=est)


def board():
    rows, n = [], 1
    for pos, count in (("RB", 40), ("WR", 60), ("TE", 20),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 60.0 - 0.2 * n,
                            est=40.0 - 0.15 * n))
            n += 1
    return rows


def test_writes_a_landscape_letter_sheet(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.page_setup.orientation == "landscape"
    assert ws.sheet_view.showGridLines is False


def test_header_row_carries_the_agreed_columns(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    headers = [ws.cell(2, c).value for c in range(1, 9)]
    assert headers == ["Rank", "Name", "Team/Bye", "Pos", "Tier",
                       "AVG", "MY$", "EST$"]


def test_team_and_bye_are_one_cell(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 3).value == "GB/11"


def test_font_is_calibri_8(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 2).font.name == "Calibri"
    assert ws.cell(3, 2).font.sz == 8


def test_missing_est_price_is_blank_not_zero(tmp_path):
    rows = [row(i, "P%d" % i, "RB", 10.0, est=None) for i in range(1, 20)]
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, rows, path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 8).value in (None, "")


def test_an_empty_board_raises(tmp_path):
    with pytest.raises(ValueError):
        render_xlsx(LG, [], str(tmp_path / "board.xlsx"))


def big_board():
    """Big enough to overflow ROW_BUDGET (532 TQB/RB/WR/TE rows against a
    248-row Overall capacity), so the truncation path actually runs."""
    rows, n = [], 1
    for pos, count in (("RB", 200), ("WR", 200), ("TE", 100),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.2 * n,
                            est=150.0 - 0.1 * n))
            n += 1
    return rows


def test_workbook_stays_within_the_two_page_row_budget(tmp_path):
    # The regression this guards against: a future change to margins, scale
    # or row height silently pushing the sheet past two printed pages again.
    # This recomputes the budget the same way render_xlsx does, rather than
    # hardcoding a row count, so it stays correct if that geometry changes.
    from sffl.render.xlsx import GROUP_GAP, ROW_BUDGET

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        used = 0
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, col0).value not in (None, ""):
                used = r
        assert used <= ROW_BUDGET, (
            "column %d used %d rows, exceeding the %d-row two-page budget"
            % (col0, used, ROW_BUDGET))


def test_render_xlsx_reports_what_it_truncated(tmp_path):
    rows = big_board()
    overall_total = sum(1 for r in rows if r.pos in ("TQB", "RB", "WR", "TE"))
    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, rows, path)

    assert stats["total"] == len(rows)
    assert stats["overall"]["shown"] + stats["overall"]["cut"] == overall_total
    assert stats["overall"]["cut"] > 0, "this board was built to overflow the budget"

    # Every position with real members must be reported, and shown > 0 -
    # a section present with zero rows is the exact bug a first version of
    # this module had (see test_every_position_appears_on_the_printed_sheet).
    for title in ("TEAM QB", "RUNNING BACKS", "RECEIVERS (WR + TE)", "KICKERS", "TEAM DEFENSE"):
        assert title in stats["sections"], "%s missing from the truncation report" % title
        assert stats["sections"][title]["shown"] > 0, "%s got zero rows" % title


def test_every_position_appears_on_the_printed_sheet(tmp_path):
    # The regression this guards against: a first version of this module
    # filled group 3 greedily in POSITION_BLOCKS order and spent the whole
    # row budget on Team QB plus part of Running Backs, leaving Receivers -
    # the largest position group in this league - Kickers and Team Defense
    # off the sheet entirely (not even a title). This must fail against
    # that code.
    from sffl.render.xlsx import POSITION_BLOCKS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    titles_present = set()
    for row_cells in ws.iter_rows():
        for cell in row_cells:
            if isinstance(cell.value, str):
                titles_present.add(cell.value)

    for title, _positions in POSITION_BLOCKS:
        assert title in titles_present, "%s is missing from the printed sheet" % title


def test_no_column_stops_short_of_the_budget_while_players_are_cut(tmp_path):
    # The regression this guards against: capping the Overall Board at half
    # of groups 1 and 2 freed 124 rows (close to half the printed sheet)
    # that a second version of this module left blank, while the same run
    # was cutting 105 Running Backs and 256 Receivers. A column may stop
    # short of the budget only once it has run out of players to show for
    # every section that uses it - never while there is still content that
    # would fit. big_board() has far more RB/Receivers than any budget can
    # hold, so every column here should reach ROW_BUDGET exactly.
    from sffl.render.xlsx import GROUP_GAP, ROW_BUDGET

    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    any_cut = stats["overall"]["cut"] > 0 or any(
        s["cut"] > 0 for s in stats["sections"].values())
    assert any_cut, "this board was built to overflow every budget - if " \
        "nothing was cut, the test proves nothing"

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        used = 0
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, col0).value not in (None, ""):
                used = r
        assert used == ROW_BUDGET, (
            "column %d stopped at row %d, short of the %d-row budget, "
            "while players are still being cut" % (col0, used, ROW_BUDGET))
