"""The iPad auction board PDF.

Ports the `Sheet` class from `poc/render_poc.py` — the layout Jeff reviewed
on an iPad Pro 11" with an Apple Pencil on 2026-08-02, with its constants
(page size, margins, gutter, row height, header height, colours, the 33pt
PAID write-in box) settled and unchanged. This module discards the poc's
own data loading and valuation (`load_ds`, `load_fp_kdst`, `value_pool`,
`num`, `TEAM_ABBR`) — all obsolete, predating flat-priced K/DST, the TQB
and DST price joins, the calibration curves and the lineup floors — and
renders real `BoardRow` records produced by the value pipeline instead.

The one layout change from the poc: THEIR$ (an uncalibrated vendor number)
is dropped, and its width goes to EST$ (this league's own market fit). See
`sffl.render.rows.BoardRow` and `sffl.market` for what the two columns mean.
"""

from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas

from sffl.plan import pick_range, tie_cells
from sffl.render.rows import overall_board

PAGE_W, PAGE_H = 454.9, 660.0        # iPad Pro 11" M4 portrait, 264ppi
MARGIN, GUTTER, ROW_H, HEADER_H = 12.0, 9.0, 16.0, 42.0
COL_W = (PAGE_W - 2 * MARGIN - GUTTER) / 2

# The silent-auction table's own row pitch, tighter than ROW_H because it
# carries twenty candidate bids (the $26 floor to the $45 record high) in the
# space the seven-row placeholder used. ROW_H itself is untouched - it is the
# iPad-reviewed pitch for a board row you write on, and this table has no
# write-in box. The LEAGUE SPEND block below already sets its own 14pt pitch
# for the same reason.
#
# 13.5 IS LOAD-BEARING, NOT TASTE. The right column has to end with all twelve
# LEAGUE SPEND rows above the footer, and at 15.0 the first real render pushed
# T12 off the bottom of the page and through the footer caveat. Anything that
# lengthens this table - more candidate bids, another note line - has to be
# paid for out of this number, and checked by looking at the page.
PLAN_ROW_H = 13.5

# Everything on a page must clear the footer caveat, whose baseline is y=5.
FOOTER_TOP = 12.0

# Column offsets inside the silent-auction table, from the right column's left
# edge. LEFT and DISCR are right-aligned at theirs; the rest are left-aligned.
# Everything from PLAN_X_PICK to COL_W belongs to the pick range.
(PLAN_X_BID, PLAN_X_RANK, PLAN_X_TIE, PLAN_X_BUMP, PLAN_X_LIVE,
 PLAN_X_LEFT, PLAN_X_DISCR, PLAN_X_PICK) = (0, 17, 36, 57, 77, 106, 128, 132)

# Validated with dataviz/scripts/validate_palette.js, light mode, --pairs all.
#
# Validated as two sets, because the six colors never co-occur: the overall board
# carries TQB/RB/WR/TE, while K and DST appear only together on their own page.
#   TQB/RB/WR/TE  -> all pass, worst pair 18.9 dE protan / 20.8 normal
#   K/DST         -> all pass, worst pair 10.2 dE deutan / 21.8 normal
#
# TQB is gold rather than green: red<->green is dE 5.7 under deuteranopia, and
# purple was worse still against blue at dE 1.1 under protanopia.
# WR/TE keep a light-dark gradient of one hue - same position, related colors -
# with enough lightness separation to clear the normal-vision floor at 20.8.
COLORS = {
    "TQB": HexColor("#D9A441"),   # gold
    "RB": HexColor("#C0392B"),    # red - most-scanned distinction
    "WR": HexColor("#1B6CA8"),    # blue, dark end of the receiver gradient
    "TE": HexColor("#5BAEE8"),    # blue, light end - same pool as WR
    "K": HexColor("#00968F"),     # teal
    "DST": HexColor("#8E5FBF"),   # purple
}
ZEBRA, RULE, BOXLINE, MUTED = (
    HexColor("#F5F5F5"), HexColor("#CCCCCC"), HexColor("#9A9A9A"), HexColor("#777777")
)


def fallback_bids(bid_floor):
    """The bid ladder drawn when no bid history was supplied.

    ARITHMETIC ONLY. Without a history there is no rank, no tie rate and no
    illustration to draw, so this ladder shows nothing but what each bid
    leaves in the budget - and the block says so on the page.

    It starts AT THE FLOOR. The block this replaced was hardcoded to
    `[20, 25, 30, 35, 40, 50, 60]`, and $20 and $25 are both below the $26
    floor: either would have been discarded and forfeited the silent pick
    outright. A degraded path is still a path onto the printed page, so it
    does not get to keep offering bids that lose the pick.
    """
    # type: (int) -> list
    return [bid_floor + 5 * i for i in range(7)]


def _fit(c, text, font, size, width):
    """`text` shortened until it fits `width`: given names first, then chars.

    Names before characters because "St. Clair - Winters" is still two
    identifiable players where "Bo St. Clair - Cal Wint" is one player and a
    mistake waiting to happen.

    THE SEPARATOR SURVIVES THE SHORTENING. Joining the shortened names on a
    bare space, as the first real render did, prints "Winters Marchetti" -
    two players read as one, at exactly the bids where the rank span is widest
    and the range matters most.

    It drops the GIVEN NAME rather than keeping the last word, which is not
    the same thing on a real board: a name like "Bo St. Clair" shortens to
    "St. Clair" and not to "Clair", and one like "Cal Winters Jr." shortens to
    "Winters Jr." and not to "Jr." - and on this board there really are two
    players a bare last word would merge.
    """
    if c.stringWidth(text, font, size) <= width:
        return text
    short = " - ".join(part.split(None, 1)[-1] if part.split() else part
                       for part in text.split(" - "))
    if c.stringWidth(short, font, size) <= width:
        return short
    while short and c.stringWidth(short + "…", font, size) > width:
        short = short[:-1]
    return short + "…" if short else ""


class Sheet:
    def __init__(self, path):
        # Uncompressed content streams: this is a small, text-only document,
        # and it lets the caveat text in the footer (and section titles) be
        # found by a plain byte search of the file - useful for tests and
        # for anyone grepping the PDF, at no visible cost on the page.
        self.c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H), pageCompression=0)
        self.c.setTitle("SFFL 2026 Auction Cheatsheet")
        self.bm = []
        self.pages = 0

    def rows_per_col(self):
        return int((PAGE_H - MARGIN - HEADER_H - MARGIN) // ROW_H)

    def page_header(self, title, subtitle, key=None):
        c = self.c
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(MARGIN, PAGE_H - MARGIN - 12, title)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, PAGE_H - MARGIN - 21, subtitle)
        if key:
            x, y = MARGIN, PAGE_H - MARGIN - 33
            for label in key:
                c.setFillColor(COLORS[label])
                c.rect(x, y, 5, 7, stroke=0, fill=1)
                c.setFillColor(black)
                c.setFont("Helvetica-Bold", 6)
                c.drawString(x + 7, y + 1.5, label)
                x += 7 + c.stringWidth(label, "Helvetica-Bold", 6) + 9
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN, PAGE_H - MARGIN - HEADER_H + 6,
               PAGE_W - MARGIN, PAGE_H - MARGIN - HEADER_H + 6)

    def col_header(self, x, y):
        c = self.c
        c.setFont("Helvetica-Bold", 5.5)
        c.setFillColor(MUTED)
        c.drawString(x + 6, y, "#")
        c.drawString(x + 23, y, "PLAYER")
        c.drawString(x + 100, y, "TM/BYE")
        c.drawRightString(x + 146, y, "MY$")
        c.drawRightString(x + 172, y, "EST$")
        c.drawString(x + 178, y, "PAID")

    def row(self, x, y, rank, r, zebra):
        c = self.c
        if zebra:
            c.setFillColor(ZEBRA)
            c.rect(x, y, COL_W, ROW_H, stroke=0, fill=1)
        c.setFillColor(COLORS.get(r.pos, MUTED))
        c.rect(x, y, 5, ROW_H, stroke=0, fill=1)

        ty = y + 5
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawRightString(x + 20, ty, str(rank))

        c.setFillColor(black)
        c.setFont("Helvetica", 7.5)
        name = r.name
        while c.stringWidth(name, "Helvetica", 7.5) > 74 and len(name) > 4:
            name = name[:-1]
        c.drawString(x + 23, ty, name)

        c.setFont("Helvetica", 6.5)
        c.setFillColor(MUTED)
        c.drawString(x + 100, ty, "%s/%s" % (r.team, r.bye if r.bye else "-"))

        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(x + 146, ty, "$%.0f" % r.my_dollars)

        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.5)
        est = ("$%.0f" % r.est_price) if r.est_price is not None else "—"
        c.drawRightString(x + 172, ty, est)

        c.setFillColor(white)
        c.setStrokeColor(BOXLINE)
        c.setLineWidth(0.5)
        c.rect(x + 176, y + 1.5, 33, ROW_H - 3, stroke=1, fill=1)

    def board(self, title, subtitle, players, key, bookmark):
        if not players:
            raise ValueError(
                "render_pdf: no rows for section %r; a page/bookmark would "
                "silently vanish rather than render" % title)
        per_col = self.rows_per_col()
        per_page = per_col * 2
        first = True
        for start in range(0, len(players), per_page):
            chunk = players[start:start + per_page]
            self.page_header(title if first else "%s (cont.)" % title,
                             subtitle, key if first else None)
            if first:
                self.c.bookmarkPage(bookmark)
                self.bm.append(bookmark)
                first = False
            for ci in range(2):
                x = MARGIN + ci * (COL_W + GUTTER)
                y_top = PAGE_H - MARGIN - HEADER_H
                self.col_header(x, y_top + 2)
                for i, p in enumerate(chunk[ci * per_col:(ci + 1) * per_col]):
                    self.row(x, y_top - (i + 1) * ROW_H,
                             start + ci * per_col + i + 1, p, i % 2 == 1)
            self.footer()
            self.c.showPage()
            self.pages += 1

    def dual_board(self, title, subtitle, left, lname, right, rname, key, bookmark):
        """Two independent lists side by side on one page, one per column."""
        c = self.c
        # Per-column labels occupy the same band the page key uses on every other
        # board, so this page's header sits at identical heights to the rest.
        self.page_header(title, subtitle, None)
        c.bookmarkPage(bookmark)
        self.bm.append(bookmark)
        per_col = self.rows_per_col()
        key_y = PAGE_H - MARGIN - 33
        for ci, (lst, label) in enumerate([(left, lname), (right, rname)]):
            x = MARGIN + ci * (COL_W + GUTTER)
            y_top = PAGE_H - MARGIN - HEADER_H
            c.setFillColor(COLORS[lst[0].pos] if lst else MUTED)
            c.rect(x, key_y, 5, 7, stroke=0, fill=1)
            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + 8, key_y + 1.5, label)
            self.col_header(x, y_top + 2)
            for i, p in enumerate(lst[:per_col]):
                self.row(x, y_top - (i + 1) * ROW_H, i + 1, p, i % 2 == 1)
        self.footer()
        c.showPage()
        self.pages += 1

    def footer(self):
        c = self.c
        c.setFont("Helvetica", 5.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, 5,
                     "EST$ is what the room is likely to pay, fitted from real league "
                     "prices; it compresses at the top, so treat it as a floor, not a "
                     "point estimate, for your number-one target. MY$ is worth against "
                     "replacement.")

    def silent_auction_block(self, x, y, teams, budget, roster_size,
                             bid_floor, outcomes):
        """The round-one tradeoff table. Returns the y it finished at.

        SHOWS THE TRADEOFF, DOES NOT RECOMMEND. Bids run in bid order, never
        sorted by attractiveness; nothing is highlighted, starred, coloured or
        otherwise marked as the answer. The bidder decides at the table. In
        particular, RANK IS STATED AND NEVER PRICED - bid order also governs
        nomination for the rest of the draft, but whether that is worth
        anything is unmeasured, so this page must not imply it is.

        `outcomes` is None when no bid history was supplied, in which case the
        block degrades to `fallback_bids` and says on the page that it is
        arithmetic with no evidence behind it.
        """
        c = self.c
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, "SILENT AUCTION (RD 1)")
        y -= 10

        c.setFont("Helvetica", 5.8)
        c.setFillColor(MUTED)
        notes = [
            "Sealed bid, floor $%d. A BID UNDER $%d IS DISCARDED AND YOU"
            % (bid_floor, bid_floor),
            "FORFEIT YOUR SILENT PICK. All %d pay their own bid and pick in"
            % teams,
            "bid order, which also sets nomination control all draft.",
        ]
        if outcomes is None:
            notes.append("No bid history loaded: budget arithmetic only - no rank,")
            notes.append("no tie evidence, no pick illustration.")
        else:
            notes.append("PICK is an ILLUSTRATION, not a prediction: our own board read")
            notes.append("at each end of the rank span. The room will not draft in")
            notes.append("that order. RANK is stated as a fact and priced at nothing.")
        for line in notes:
            c.drawString(x, y, line)
            y -= 7
        y -= 2

        if outcomes is None:
            return self._fallback_grid(x, y, budget, roster_size, bid_floor)

        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(MUTED)
        for label, dx in (("BID", PLAN_X_BID), ("RANK", PLAN_X_RANK),
                          ("TIE", PLAN_X_TIE), ("BUMP", PLAN_X_BUMP),
                          ("LIVE", PLAN_X_LIVE), ("PICK RANGE", PLAN_X_PICK)):
            c.drawString(x + dx, y, label)
        c.drawRightString(x + PLAN_X_LEFT, y, "LEFT")
        c.drawRightString(x + PLAN_X_DISCR, y, "DISCR")
        y -= 3

        for i, o in enumerate(outcomes):
            ry = y - (i + 1) * PLAN_ROW_H
            if i % 2 == 1:
                c.setFillColor(ZEBRA)
                c.rect(x, ry, COL_W, PLAN_ROW_H, stroke=0, fill=1)
            ty = ry + 4.5

            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + PLAN_X_BID, ty, "$%d" % o.bid)

            c.setFont("Helvetica", 6)
            span = ("%d" % o.best_rank if o.best_rank == o.worst_rank
                    else "%d-%d" % (o.best_rank, o.worst_rank))
            c.drawString(x + PLAN_X_RANK, ty, span)
            c.drawRightString(x + PLAN_X_LEFT, ty, "$%d" % o.budget_left)
            c.drawRightString(x + PLAN_X_DISCR, ty, "$%d" % o.discretionary)

            tie, bump, live = tie_cells(o)
            c.setFont("Helvetica", 5.5)
            # Absence of evidence is muted; a measurement is not. "no data"
            # and "0%" must never be mistaken for each other at arm's length
            # on an iPad, so they differ in wording AND in weight.
            c.setFillColor(MUTED if not o.observations else black)
            c.drawString(x + PLAN_X_TIE, ty, tie)
            c.drawString(x + PLAN_X_BUMP, ty, bump)
            c.drawString(x + PLAN_X_LIVE, ty, live)

            c.setFillColor(MUTED)
            c.drawString(x + PLAN_X_PICK, ty,
                         _fit(c, pick_range(o), "Helvetica", 5.5,
                              COL_W - PLAN_X_PICK))

        y -= len(outcomes) * PLAN_ROW_H + 7
        c.setFont("Helvetica", 5.2)
        c.setFillColor(MUTED)
        for line in (
            "TIE = share of years 2+ teams bid this. \"no data\" = never bid,",
            "so nothing is known there - it is not a measured 0%. BUMP = bumps",
            "actually charged to win a tie. LIVE = a year the tie escalated to a",
            "live auction, where money was paid above the bid: an empty BUMP",
            "beside a LIVE year is not a free tie.",
        ):
            c.drawString(x, y, line)
            y -= 6.5
        return y

    def _fallback_grid(self, x, y, budget, roster_size, bid_floor):
        """Budget arithmetic for a bid ladder, with no evidence behind it.

        The per-slot figure divides by the ROSTER SPOTS still to fill, not by
        the number of teams. The two are both 12 in this league, which is why
        the placeholder's `left / teams` looked right; they are not the same
        quantity and a league with a different roster size would print a
        number that means nothing.
        """
        c = self.c
        spots_left = roster_size - 1
        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(MUTED)
        for label, dx in (("BID", 0), ("LEFT", 32),
                          ("%d SLOTS" % spots_left, 68), ("DISCR.", 122)):
            c.drawString(x + dx, y, label)
        y -= 3
        bids = fallback_bids(bid_floor)
        for i, bid in enumerate(bids):
            ry = y - (i + 1) * ROW_H
            if i % 2 == 1:
                c.setFillColor(ZEBRA)
                c.rect(x, ry, COL_W, ROW_H, stroke=0, fill=1)
            left = budget - bid
            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(x + 2, ry + 5, "$%d" % bid)
            c.setFont("Helvetica", 7.5)
            c.drawString(x + 32, ry + 5, "$%d" % left)
            c.drawString(x + 68, ry + 5, "$%.2f/ea" % (float(left) / spots_left))
            c.drawString(x + 122, ry + 5, "$%d" % (left - spots_left))
        return y - len(bids) * ROW_H

    def management_page(self, teams, budget, roster_size, bid_floor, outcomes=None):
        c = self.c
        self.page_header("Auction Management",
                         "$%d budget · %d spots · %d teams · silent auction rd 1"
                         % (budget, roster_size, teams))
        c.bookmarkPage("6. Auction Management")
        self.bm.append("6. Auction Management")
        y = PAGE_H - MARGIN - HEADER_H - 4

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(black)
        c.drawString(MARGIN, y, "MY ROSTER")
        y -= 12
        c.setFont("Helvetica", 5.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, y, "SLOT")
        c.drawString(MARGIN + 34, y, "PLAYER")
        c.drawRightString(MARGIN + 207, y, "$")
        y -= 3
        slots = ["TQB", "RB", "W/T"] + ["FLEX"] * 3 + ["K", "DST"] + ["BN"] * 5
        for i, s in enumerate(slots):
            ry = y - (i + 1) * ROW_H
            if i % 2 == 1:
                c.setFillColor(ZEBRA)
                c.rect(MARGIN, ry, 211, ROW_H, stroke=0, fill=1)
            starter = i < 8
            c.setFillColor(black if starter else MUTED)
            c.setFont("Helvetica-Bold" if starter else "Helvetica", 6.5)
            c.drawString(MARGIN + 2, ry + 5, s)
            c.setFillColor(white)
            c.setStrokeColor(BOXLINE)
            c.setLineWidth(0.5)
            c.rect(MARGIN + 30, ry + 1.5, 138, ROW_H - 3, stroke=1, fill=1)
            c.rect(MARGIN + 172, ry + 1.5, 37, ROW_H - 3, stroke=1, fill=1)

        by = y - (len(slots) + 1) * ROW_H - 6
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(MARGIN, by, "SPENT")
        c.setStrokeColor(BOXLINE)
        c.rect(MARGIN + 34, by - 4, 48, 14, stroke=1, fill=0)
        c.drawString(MARGIN + 90, by, "LEFT")
        c.rect(MARGIN + 120, by - 4, 48, 14, stroke=1, fill=0)

        x2 = MARGIN + COL_W + GUTTER
        y2 = self.silent_auction_block(
            x2, PAGE_H - MARGIN - HEADER_H - 4,
            teams, budget, roster_size, bid_floor, outcomes) - 12
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x2, y2, "MY BID")
        c.setStrokeColor(BOXLINE)
        c.rect(x2 + 40, y2 - 4, 44, 14, stroke=1, fill=0)
        c.drawString(x2 + 92, y2, "BUMP")
        c.rect(x2 + 126, y2 - 4, 44, 14, stroke=1, fill=0)

        y3 = y2 - 24
        # The right column is a stack, and the silent-auction table at the top
        # of it now grows with the number of candidate bids. On the first real
        # render the table was 30pt too tall and pushed T12 clean off the
        # bottom of the page and through the footer caveat - visible only by
        # opening the file. Nothing in a byte-search test can see that, so
        # check it here and refuse rather than print a page that has silently
        # lost a franchise's spend box.
        last_spend_row = y3 - 4 - teams * 14 + 1
        if last_spend_row < FOOTER_TOP:
            raise ValueError(
                "management_page: the silent-auction table is too tall - the "
                "last of the %d LEAGUE SPEND rows would land at y=%.1f, under "
                "the footer at y=%.1f. Shorten the table or PLAN_ROW_H (%.1f)."
                % (teams, last_spend_row, FOOTER_TOP, PLAN_ROW_H))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x2, y3, "LEAGUE SPEND")
        y3 -= 4
        for i in range(teams):
            ry = y3 - (i + 1) * 14
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 6)
            c.drawString(x2, ry + 4, "T%02d" % (i + 1))
            c.setFillColor(white)
            c.setStrokeColor(BOXLINE)
            c.rect(x2 + 20, ry + 1, 62, 12, stroke=1, fill=1)
            c.rect(x2 + 86, ry + 1, 36, 12, stroke=1, fill=1)

        self.footer()
        self.c.showPage()
        self.pages += 1

    def save(self):
        for b in self.bm:
            self.c.addOutlineEntry(b, b, level=0)
        self.c.showOutline()
        self.c.save()


def render_pdf(lg, rows, path, subtitle="", outcomes=None):
    """Render the auction board to `path`. Returns the page count.

    Six sections: overall board (TQB ranked inline with flex by $ value,
    two-up), Team QB (all 32 franchises), Running Backs, Receivers (WR+TE
    merged), Kickers and Team Defense side by side, then Auction Management.

    `outcomes` is `sffl.plan.plan_bids` output, and drives the management
    page's silent-auction table. It stays OPTIONAL on purpose: the board is
    the artifact that must exist on auction day, so a missing or unreadable
    bid history degrades that one block to budget arithmetic rather than
    failing the whole render three weeks out.

    Raises ValueError on an empty `rows` rather than writing a blank PDF —
    a silently-empty board three weeks before the auction is exactly the
    failure mode the project's "raise clearly" rule exists to prevent.
    """
    if not rows:
        raise ValueError("render_pdf: rows is empty; nothing to render")

    # One shared filter with the workbook's Overall Board - see
    # sffl.render.rows.overall_board, which also records why K and DST are
    # excluded (flat-priced $1 fillers with their own page, and a six-colour
    # page the colourblind validation deliberately never covered).
    overall = overall_board(rows)
    tqb = sorted([r for r in rows if r.pos == "TQB"], key=lambda r: -r.my_dollars)
    rb = sorted([r for r in rows if r.pos == "RB"], key=lambda r: -r.my_dollars)
    wrte = sorted([r for r in rows if r.pos in ("WR", "TE")], key=lambda r: -r.my_dollars)
    k = sorted([r for r in rows if r.pos == "K"], key=lambda r: -r.my_dollars)
    dst = sorted([r for r in rows if r.pos == "DST"], key=lambda r: -r.my_dollars)

    s = Sheet(path)
    s.board("Overall Board", subtitle or "TQB ranked inline with flex by $ value. WR/TE one pool.",
            overall, ["TQB", "RB", "WR", "TE"], "1. Overall Board")
    s.board("Team QB", "All 32 franchises", tqb, ["TQB"], "2. Team QB")
    s.board("Running Backs", "", rb, ["RB"], "3. Running Backs")
    s.board("Receivers (WR + TE)", "One merged position in this league",
            wrte, ["WR", "TE"], "4. Receivers")
    s.dual_board("Kickers & Team Defense", "",
                 k, "KICKERS", dst, "TEAM DEFENSE", ["K", "DST"], "5. K / DST")
    s.management_page(lg.teams, lg.budget, lg.roster_size,
                      lg.silent_auction["bid_floor"], outcomes)
    s.save()

    return s.pages
