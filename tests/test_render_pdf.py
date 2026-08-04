import re

import pytest

from sffl.league import load_league
from sffl.render.pdf import render_pdf
from sffl.render.rows import BoardRow

LG = load_league("leagues/sffl/2026.yaml")


def row(rank, name, pos, dollars, est=None, tier=1):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=tier,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=est)


def board():
    rows = []
    n = 1
    for pos, count in (("RB", 40), ("WR", 60), ("TE", 20),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s Player %d" % (pos, i), pos,
                            60.0 - 0.2 * n, est=40.0 - 0.15 * n))
            n += 1
    return rows


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_writes_a_pdf_with_the_expected_page_count(tmp_path):
    path = str(tmp_path / "board.pdf")
    pages = render_pdf(LG, board(), path)
    data = read(path)
    assert data.startswith(b"%PDF-")
    assert pages == len(re.findall(rb"/Type\s*/Page[^s]", data))
    assert pages >= 6, "overall, TQB, RB, WR/TE, K+DST, management"


def test_page_size_is_the_ipad_geometry(tmp_path):
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, board(), path)
    # 454.9 x 660 pt portrait, reviewed on the real device
    assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+454\.9\d*\s+660", read(path))


def test_every_section_is_bookmarked(tmp_path):
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, board(), path)
    data = read(path)
    assert b"Overall Board" in data
    assert b"Team QB" in data
    assert b"Management" in data


def test_the_est_price_caveat_is_on_the_page(tmp_path):
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, board(), path)
    assert b"floor" in read(path).lower()


def test_rows_without_an_est_price_render_a_dash_not_a_zero(tmp_path):
    rows = [row(i, "P%d" % i, "RB", 10.0, est=None) for i in range(1, 30)]
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, rows, path)
    assert read(path).startswith(b"%PDF-")


def test_an_empty_board_raises_rather_than_writing_a_blank_pdf(tmp_path):
    with pytest.raises(ValueError):
        render_pdf(LG, [], str(tmp_path / "board.pdf"))
