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
