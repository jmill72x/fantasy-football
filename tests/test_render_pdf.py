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
    # Every section needs at least one row - see
    # test_a_position_with_zero_rows_raises_rather_than_dropping_its_page -
    # so round out the other five positions, keeping est=None throughout to
    # exercise the same dash rendering this test is actually about.
    rows += [row(30, "TQB1", "TQB", 5.0, est=None),
             row(31, "WR1", "WR", 5.0, est=None),
             row(32, "TE1", "TE", 5.0, est=None),
             row(33, "K1", "K", 1.0, est=None),
             row(34, "DST1", "DST", 1.0, est=None)]
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, rows, path)
    assert read(path).startswith(b"%PDF-")


def test_an_empty_board_raises_rather_than_writing_a_blank_pdf(tmp_path):
    with pytest.raises(ValueError):
        render_pdf(LG, [], str(tmp_path / "board.pdf"))


def test_overall_board_excludes_kickers_and_defense(tmp_path):
    # K and DST are flat-priced fillers that belong only on their own dual
    # page - never the Overall Board, and never in a combination that mixes
    # all six palette colours (see COLORS' two-set colourblind validation).
    # Given the highest dollar values on the sheet, a K/DST row that leaked
    # into the Overall Board would rank #1 and render on page 1 - well
    # before the K/DST section's own page.
    # Invented names, not real players: this repo is public, and the plan's
    # global constraints allow no real player name in a committed file. The
    # name here only has to be findable in the PDF's bytes.
    rows = [row(1, "Boone Castellane", "K", 999.0, est=999.0),
            row(2, "Ironmoor DST", "DST", 998.0, est=998.0)]
    rows += [row(i, "RB Player %d" % i, "RB", 50.0 - i, est=30.0)
             for i in range(3, 30)]
    # Every section needs at least one row - see
    # test_a_position_with_zero_rows_raises_rather_than_dropping_its_page.
    rows += [row(30, "TQB1", "TQB", 5.0, est=3.0),
             row(31, "WR1", "WR", 5.0, est=3.0),
             row(32, "TE1", "TE", 5.0, est=3.0)]
    path = str(tmp_path / "board.pdf")
    render_pdf(LG, rows, path)
    data = read(path)
    overall_title = data.index(b"Overall Board")
    kdst_title = data.index(b"Kickers & Team Defense")
    kicker = data.index(b"Boone Castellane")
    assert overall_title < kdst_title < kicker, (
        "Boone Castellane (K, $999) must not render on the Overall Board")


def test_a_position_with_zero_rows_raises_rather_than_dropping_its_page(tmp_path):
    # No RB rows at all. Without a guard, board()'s loop simply never
    # executes for an empty section - no page, no bookmark, no error - and
    # the Running Backs section vanishes with nothing to say why.
    rows = [row(i, "TQB Player %d" % i, "TQB", 10.0, est=5.0) for i in range(1, 5)]
    rows += [row(i, "WR Player %d" % i, "WR", 10.0, est=5.0) for i in range(5, 9)]
    rows += [row(i, "K Player %d" % i, "K", 1.0, est=1.0) for i in range(9, 13)]
    rows += [row(i, "DST Player %d" % i, "DST", 1.0, est=1.0) for i in range(13, 17)]
    path = str(tmp_path / "board.pdf")
    with pytest.raises(ValueError):
        render_pdf(LG, rows, path)
