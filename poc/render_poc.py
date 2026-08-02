"""Proof-of-concept PDF renderer for the SFFL auction cheatsheet.

Demonstrates layout and the VORP->dollars value method. Reads real extracts:
  - 2024 Draft Sharks CBS-synced export -> TQB + RB/WR/TE, league-aware projections
  - 2025 FantasyPros cheatsheet export  -> K and DST (absent from the DS export)

MY$ is computed with the real method (see value_pool below). THEIR$ is blank for
DS-sourced rows because that export's auction column is broken: file 1 is "$-11"
on every row, file 2 puts 525 of 646 players at $1 with five QBs at $99.
"""

import csv
import os
import re
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white, black

ICLOUD = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Fantasy Football/"
)
DOWNLOADS = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Downloads/"
)
OUT = os.path.join(os.path.dirname(__file__), "..", "output", "sffl-cheatsheet-poc.pdf")

PAGE_W, PAGE_H = 454.9, 660.0        # iPad Pro 11" M4 portrait, 264ppi
MARGIN, GUTTER, ROW_H, HEADER_H = 12.0, 9.0, 16.0, 42.0
COL_W = (PAGE_W - 2 * MARGIN - GUTTER) / 2

# league constants
TEAMS, BUDGET, ROSTER = 12, 110, 13
FLEX_SLOTS = 5            # RB/WR/TE per team
TOTAL_MONEY = TEAMS * BUDGET
TOTAL_SPOTS = TEAMS * ROSTER

COLORS = {
    "TQB": HexColor("#6D4AA6"),
    "RB": HexColor("#2E8B57"),
    "WR": HexColor("#1F6FB2"),
    "TE": HexColor("#6FA8D6"),
    "K": HexColor("#D98A2B"),
    "DST": HexColor("#7A6A5A"),
}
ZEBRA, RULE, BOXLINE, MUTED = (
    HexColor("#F5F5F5"), HexColor("#CCCCCC"), HexColor("#9A9A9A"), HexColor("#777777")
)


def num(x):
    try:
        return float(str(x).replace("$", "").strip())
    except ValueError:
        return 0.0


def load_ds():
    """TQB + RB/WR/TE with league-aware Consensus projections."""
    out = []
    with open(DOWNLOADS + "STRIPES FANTASY FOOTBALL LEAGUE.csv") as f:
        for r in csv.reader(f):
            if len(r) > 13 and r[4] in ("TQB", "RB", "WR", "TE"):
                out.append({
                    "name": r[3], "pos": r[4], "team": r[5], "bye": r[6],
                    "adp": r[7], "proj": num(r[9]), "their": None,
                })
    return out


def load_fp_kdst():
    """K and DST from the 2025 FantasyPros cheatsheet, which carries real $ values."""
    rows = list(csv.reader(open(ICLOUD + "cheatsheet (3).csv")))
    out = []
    for r in rows[2:]:
        if not r or not r[0].strip():
            continue
        m = re.match(r"^(.*?)\s*\((\w+)\s*-\s*(\w+)\)$", r[0].strip())
        if not m or m.group(2) not in ("K", "DST"):
            continue
        out.append({
            "name": m.group(1).strip(), "pos": m.group(2), "team": m.group(3),
            "bye": r[1].strip(), "adp": "", "proj": 0.0, "their": r[2].strip(),
        })
    return out


def value_pool(players):
    """VORP -> auction dollars.

    Replacement level is set by actual starting demand:
      TQB   12 starters -> 13th best TQB
      flex  12 x 5 = 60 -> 61st best of the merged RB/WR/TE pool, floor of 12 RB
    Every one of the 156 roster spots costs at least $1, so $156 is committed and
    the remaining surplus is distributed in proportion to VORP.
    """
    tqb = sorted([p for p in players if p["pos"] == "TQB"],
                 key=lambda p: -p["proj"])
    flex = sorted([p for p in players if p["pos"] in ("RB", "WR", "TE")],
                  key=lambda p: -p["proj"])

    repl_tqb = tqb[TEAMS]["proj"] if len(tqb) > TEAMS else 0.0

    # enforce the >=1 RB per team floor when locating flex replacement
    starters, rbs = [], 0
    for p in flex:
        if len(starters) >= TEAMS * FLEX_SLOTS:
            break
        starters.append(p)
        rbs += p["pos"] == "RB"
    if rbs < TEAMS:
        need = TEAMS - rbs
        extra = [p for p in flex if p["pos"] == "RB" and p not in starters][:need]
        starters = starters[: len(starters) - need] + extra
    repl_flex = flex[len(starters)]["proj"] if len(flex) > len(starters) else 0.0

    for p in players:
        base = repl_tqb if p["pos"] == "TQB" else repl_flex
        p["vorp"] = max(0.0, p["proj"] - base) if p["proj"] else 0.0

    surplus = TOTAL_MONEY - TOTAL_SPOTS          # $1,320 - $156 = $1,164
    tot = sum(p["vorp"] for p in players)
    rate = surplus / tot if tot else 0.0
    for p in players:
        p["mine"] = 1 + p["vorp"] * rate if p["vorp"] > 0 else 1
    return repl_tqb, repl_flex, rate


class Sheet:
    def __init__(self, path):
        self.c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
        self.c.setTitle("SFFL 2026 Auction Cheatsheet (layout proof of concept)")
        self.bm = []

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
        c.drawRightString(x + 146, y, "THEIR$")
        c.drawRightString(x + 172, y, "MY$")
        c.drawString(x + 178, y, "PAID")

    def row(self, x, y, rank, p, zebra):
        c = self.c
        if zebra:
            c.setFillColor(ZEBRA)
            c.rect(x, y, COL_W, ROW_H, stroke=0, fill=1)
        c.setFillColor(COLORS.get(p["pos"], MUTED))
        c.rect(x, y, 5, ROW_H, stroke=0, fill=1)

        ty = y + 5
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawRightString(x + 20, ty, str(rank))

        c.setFillColor(black)
        c.setFont("Helvetica", 7.5)
        name = p["name"]
        while c.stringWidth(name, "Helvetica", 7.5) > 74 and len(name) > 4:
            name = name[:-1]
        c.drawString(x + 23, ty, name)

        c.setFont("Helvetica", 6.5)
        c.setFillColor(MUTED)
        c.drawString(x + 100, ty, f"{p['team'] or ''}/{p['bye'] or '-'}")

        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(x + 146, ty, p["their"] or "—")
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(x + 172, ty, f"${p['mine']:.0f}")

        c.setFillColor(white)
        c.setStrokeColor(BOXLINE)
        c.setLineWidth(0.5)
        c.rect(x + 176, y + 1.5, 33, ROW_H - 3, stroke=1, fill=1)

    def board(self, title, subtitle, players, key, bookmark):
        per_col = self.rows_per_col()
        per_page = per_col * 2
        first = True
        for start in range(0, len(players), per_page):
            chunk = players[start:start + per_page]
            self.page_header(title if first else f"{title} (cont.)",
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

    def footer(self):
        c = self.c
        c.setFont("Helvetica", 5.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, 5,
                     "LAYOUT POC — MY$ = VORP/$1,164 surplus on 2024 Draft Sharks "
                     "league-aware projections. THEIR$ blank: DS auction column broken.")

    def management_page(self):
        c = self.c
        self.page_header("Auction Management",
                         "$110 budget · 13 spots · 12 teams · silent auction rd 1")
        c.bookmarkPage("mgmt")
        self.bm.append("mgmt")
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
        y = PAGE_H - MARGIN - HEADER_H - 4
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x2, y, "SILENT AUCTION (RD 1)")
        y -= 11
        c.setFont("Helvetica", 5.8)
        c.setFillColor(MUTED)
        c.drawString(x2, y, "Sealed bid, min ~$20. All 12 pay own bid.")
        y -= 8
        c.drawString(x2, y, "Order sets nomination control all draft.")
        y -= 12
        c.setFont("Helvetica-Bold", 5.5)
        for lbl, dx in [("BID", 0), ("LEFT", 32), ("12 SLOTS", 68), ("DISCR.", 122)]:
            c.drawString(x2 + dx, y, lbl)
        y -= 3
        for i, bid in enumerate([20, 25, 30, 35, 40, 50, 60]):
            ry = y - (i + 1) * ROW_H
            if i % 2 == 1:
                c.setFillColor(ZEBRA)
                c.rect(x2, ry, COL_W, ROW_H, stroke=0, fill=1)
            left = BUDGET - bid
            disc = left - (ROSTER - 1)
            c.setFillColor(black)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(x2 + 2, ry + 5, f"${bid}")
            c.setFont("Helvetica", 7.5)
            c.drawString(x2 + 32, ry + 5, f"${left}")
            c.drawString(x2 + 68, ry + 5, f"${left/12:.2f}/ea")
            c.setFillColor(HexColor("#B03030") if disc < 60 else black)
            c.drawString(x2 + 122, ry + 5, f"${disc}")

        y2 = y - 8 * ROW_H - 10
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x2, y2, "MY BID")
        c.setStrokeColor(BOXLINE)
        c.rect(x2 + 40, y2 - 4, 44, 14, stroke=1, fill=0)
        c.drawString(x2 + 92, y2, "BUMP")
        c.rect(x2 + 126, y2 - 4, 44, 14, stroke=1, fill=0)

        y3 = y2 - 24
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x2, y3, "LEAGUE SPEND")
        y3 -= 4
        for i in range(12):
            ry = y3 - (i + 1) * 14
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 6)
            c.drawString(x2, ry + 4, f"T{i+1:02d}")
            c.setFillColor(white)
            c.setStrokeColor(BOXLINE)
            c.rect(x2 + 20, ry + 1, 62, 12, stroke=1, fill=1)
            c.rect(x2 + 86, ry + 1, 36, 12, stroke=1, fill=1)

        self.footer()
        self.c.showPage()

    def save(self):
        for b in self.bm:
            self.c.addOutlineEntry(b, b, level=0)
        self.c.showOutline()
        self.c.save()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ds = load_ds()
    kdst = load_fp_kdst()
    repl_tqb, repl_flex, rate = value_pool(ds)
    for p in kdst:
        p["vorp"], p["mine"] = 0.0, 1

    # TQB now sits inside the overall board, ranked by dollar value alongside flex
    overall = sorted(ds, key=lambda p: -p["mine"])[:296]
    tqb = sorted([p for p in ds if p["pos"] == "TQB"], key=lambda p: -p["mine"])
    rb = sorted([p for p in ds if p["pos"] == "RB"], key=lambda p: -p["mine"])[:74]
    wrte = sorted([p for p in ds if p["pos"] in ("WR", "TE")],
                  key=lambda p: -p["mine"])[:148]
    k = [p for p in kdst if p["pos"] == "K"][:37]
    dst = [p for p in kdst if p["pos"] == "DST"][:37]

    s = Sheet(OUT)
    s.board("Overall Board", "TQB ranked inline with flex by $ value. WR/TE one pool.",
            overall, ["TQB", "RB", "WR", "TE"], "1. Overall Board")
    s.board("Team QB", "All 32 franchises", tqb, ["TQB"], "2. Team QB")
    s.board("Running Backs", "", rb, ["RB"], "3. Running Backs")
    s.board("Receivers (WR + TE)", "One merged position in this league",
            wrte, ["WR", "TE"], "4. Receivers")
    s.board("Kickers", "2025 FantasyPros — absent from the DS export", k, ["K"],
            "5. Kickers")
    s.board("Team Defense", "2025 FantasyPros — absent from the DS export", dst,
            ["DST"], "6. Team Defense")
    s.management_page()
    s.save()

    print(f"wrote {OUT}")
    print(f"replacement: TQB {repl_tqb:.1f}  flex {repl_flex:.1f}  "
          f"rate ${rate:.3f}/vorp pt")
    print("\ntop 12 overall by MY$:")
    for i, p in enumerate(overall[:12], 1):
        print(f"  {i:2d}. ${p['mine']:5.1f}  {p['pos']:4s} {p['name']}")
    print("\nTQB vs flex crossover:")
    for i, p in enumerate(overall[:40], 1):
        if p["pos"] == "TQB":
            print(f"  overall #{i:2d}  ${p['mine']:5.1f}  {p['name']}")


if __name__ == "__main__":
    main()
