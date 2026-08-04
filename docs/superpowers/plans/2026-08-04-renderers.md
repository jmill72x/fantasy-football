# Renderers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the priced pool into the two artifacts Jeff actually uses at the auction — a marked-up PDF on the iPad and a printed Excel sheet.

**Architecture:** One shared layer turns a valued pool into render-ready rows (rank, name, team/bye, position, tier, per-game average, MY$, EST$), so the PDF and the Excel cannot disagree about what a player is worth. The PDF keeps the iPad-reviewed layout already proven in `poc/render_poc.py` — only its obsolete data loading and valuation are replaced. The Excel reproduces the shape of Jeff's 2022 workbook, whose format was measured from the file itself.

**Tech Stack:** Python 3.9, pytest, PyYAML, reportlab 5.0.0, openpyxl 3.1.5 — all pinned in `requirements.txt`.

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations. Use `typing.Optional`/`List`/`Dict`/`Tuple`.
- **Use the project venv** at `.venv/`. Invoke as `./.venv/bin/pytest` and `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc commands need `PYTHONPATH=src`.
- **`data/extracts/` and `data/weekly/` are gitignored** — licensed vendor and CBS data, and this repo is PUBLIC. Never commit a file from either, and **never paste extract contents or real-run player names into a committed file**. `data/league/` IS tracked. `output/` is gitignored — generated artifacts are never committed. Tests must not depend on gitignored data.
- **Wrong numbers must never be produced silently.** Prefer raising over guessing.
- **WR and TE are ONE position.** They share a pool, share a tier ladder, and share a page. Never split them.
- **`src/sffl/scoring.py` and `src/sffl/value.py` must NOT be modified.** This plan renders; it does not revalue.
- **A zero is not a no-op for `def_pa`/`def_ya`.** Not touched here, but do not introduce any loop over `lg.bands` without a position gate.

## Settled decisions — do not re-litigate

| | |
|---|---|
| **Two dollar columns** | `MY$` = worth against replacement (`_dollars`); `EST$` = what the room will pay (`_est_price`). Both render. |
| **EST$ is a floor at the top** | The market fit is concave, so the single most expensive player runs above the estimate. **This caveat must appear on the printed artifacts**, not just in the source. |
| **THEIR$ is dropped** | The vendor column assumed a ~$200 cap and priced Ja'Marr Chase at $62 against a $43 league record. Its width goes to the write-in box. |
| **Byes come from `leagues/nfl-byes-2026.yaml`** | Neither vendor carries them. Keyed by canonical team code. |
| **Tier and AVG PTS are derived** | `AVG PTS` = `_season_points / games`. `Tier` = natural breaks in `_dollars` within a position group. |
| **K and DST are $1** | Flat by league policy. They still render, ranked by points, priced at $1. |

## File Structure

| File | Responsibility |
|---|---|
| `src/sffl/render/__init__.py` | Package marker |
| `src/sffl/render/rows.py` | Valued pool → render-ready `BoardRow`s; tier derivation; bye join |
| `src/sffl/render/pdf.py` | The iPad board. Layout ported verbatim from `poc/render_poc.py` |
| `src/sffl/render/xlsx.py` | The printed workbook, shaped like the 2022 template |
| `src/sffl/cli.py` (modify) | `render` subcommand emitting either or both |

---

### Task 1: Render-ready rows, tiers, and byes

**Files:**
- Create: `src/sffl/render/__init__.py`, `src/sffl/render/rows.py`
- Test: `tests/test_render_rows.py`

**Interfaces:**
- Consumes: `PlayerProjection` with `stats["_season_points"]`, `["_dollars"]`, optionally `["_est_price"]`; `leagues/nfl-byes-2026.yaml`; `sffl.value._pool_of`.
- Produces:
  - `BoardRow` dataclass: `rank: int`, `name: str`, `team: str`, `bye: Optional[int]`, `pos: str`, `tier: int`, `avg_pts: float`, `my_dollars: float`, `est_price: Optional[float]`.
  - `load_byes(path) -> Dict[str, int]`
  - `assign_tiers(players, n_tiers=6) -> None` — writes `stats["_tier"]`, per position group.
  - `build_rows(lg, pool, byes) -> List[BoardRow]` — sorted by `_dollars` descending, ranked from 1.

**Tier derivation, precisely.** Within a position group, sort by `_dollars` descending. Compute the gap between each adjacent pair. Take the `n_tiers - 1` largest gaps as tier boundaries; players above the first boundary are tier 1, and so on. Ties in gap size break toward the higher-dollar boundary so the result is deterministic. A group with fewer members than `n_tiers` gets one tier per member, in order. Flat-priced pools (K, DST) have no dollar spread at all, so every member is tier 1 — that is correct and must not raise.

**Why natural breaks rather than fixed bands.** The useful question at the table is "if I miss this player, what does the next one cost?" — which is exactly where the gaps are.

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_rows.py`:

```python
import pytest

from sffl.league import load_league
from sffl.render.rows import BoardRow, assign_tiers, build_rows, load_byes
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
BYES = "leagues/nfl-byes-2026.yaml"


def player(name, pos, team, dollars, pts=100.0, games=17.0, est=None):
    stats = {"_season_points": float(pts), "_dollars": float(dollars)}
    if est is not None:
        stats["_est_price"] = float(est)
    return PlayerProjection(name=name, team=team, pos=pos, source="t",
                            source_year=2026, games=games, stats=stats,
                            raw_name=name)


def test_byes_load_for_all_32_teams():
    byes = load_byes(BYES)
    assert len(byes) == 32
    assert byes["NO"] == 8, "unquoted NO parses as boolean false in YAML 1.1"
    assert byes["KC"] == 5


def test_rows_are_ranked_by_dollars_descending():
    pool = [player("c", "WR", "KC", 5.0), player("a", "RB", "GB", 30.0),
            player("b", "WR", "NO", 12.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert [r.name for r in rows] == ["a", "b", "c"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_bye_is_joined_by_team_code():
    pool = [player("x", "RB", "NO", 10.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].bye == 8


def test_unknown_team_raises_rather_than_rendering_a_blank_bye():
    pool = [player("x", "RB", "ZZZ", 10.0)]
    with pytest.raises(ValueError) as e:
        build_rows(LG, pool, load_byes(BYES))
    assert "ZZZ" in str(e.value)


def test_avg_pts_is_season_points_over_games():
    pool = [player("x", "RB", "GB", 10.0, pts=170.0, games=17.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].avg_pts == pytest.approx(10.0)


def test_zero_games_does_not_divide_by_zero():
    pool = [player("x", "RB", "GB", 10.0, pts=0.0, games=0.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].avg_pts == pytest.approx(0.0)


def test_est_price_is_none_when_absent_rather_than_zero():
    pool = [player("x", "RB", "GB", 10.0)]
    rows = build_rows(LG, pool, load_byes(BYES))
    assert rows[0].est_price is None


def test_tiers_split_at_the_largest_gaps():
    # dollars 40, 39, 38 | 20, 19 | 5  -> three clear clusters
    vals = [40.0, 39.0, 38.0, 20.0, 19.0, 5.0]
    pool = [player("p%d" % i, "RB", "GB", v) for i, v in enumerate(vals)]
    assign_tiers(pool, n_tiers=3)
    tiers = [p.stats["_tier"] for p in
             sorted(pool, key=lambda p: -p.stats["_dollars"])]
    assert tiers == [1, 1, 1, 2, 2, 3]


def test_wr_and_te_share_one_tier_ladder():
    pool = [player("wr1", "WR", "GB", 40.0), player("te1", "TE", "KC", 39.0),
            player("wr2", "WR", "NO", 5.0)]
    assign_tiers(pool, n_tiers=2)
    by = dict((p.name, p.stats["_tier"]) for p in pool)
    assert by["wr1"] == by["te1"] == 1
    assert by["wr2"] == 2


def test_a_flat_priced_pool_is_all_one_tier():
    pool = [player("k%d" % i, "K", "GB", 1.0) for i in range(12)]
    assign_tiers(pool, n_tiers=6)
    assert set(p.stats["_tier"] for p in pool) == {1}


def test_a_group_smaller_than_the_tier_count_gets_one_tier_each():
    pool = [player("a", "TQB", "GB", 30.0), player("b", "TQB", "KC", 10.0)]
    assign_tiers(pool, n_tiers=6)
    tiers = sorted(p.stats["_tier"] for p in pool)
    assert tiers == [1, 2]


def test_missing_dollars_raises():
    p = player("x", "RB", "GB", 10.0)
    del p.stats["_dollars"]
    with pytest.raises(ValueError) as e:
        build_rows(LG, [p], load_byes(BYES))
    assert "_dollars" in str(e.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_render_rows.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.render'`

- [ ] **Step 3: Implement**

Create `src/sffl/render/__init__.py` (empty).

Create `src/sffl/render/rows.py`:

```python
"""Turn a valued pool into render-ready rows.

Both artifacts render from this one list, so the PDF and the Excel can never
disagree about what a player is worth or which tier he sits in.

Tiers are natural breaks in dollar value within a position group, not fixed
bands. The question that matters at the table is "if I miss this player, what
does the next one cost" - which is exactly where the gaps are.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

from sffl.value import _pool_of

DEFAULT_BYES = "leagues/nfl-byes-2026.yaml"
N_TIERS = 6


@dataclass
class BoardRow(object):
    rank: int
    name: str
    team: str
    bye: Optional[int]
    pos: str
    tier: int
    avg_pts: float
    my_dollars: float
    est_price: Optional[float]


def load_byes(path=DEFAULT_BYES):
    """Canonical team code -> bye week."""
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    out = {}  # type: Dict[str, int]
    for team, week in (raw.get("byes") or {}).items():
        out[str(team).strip().upper()] = int(week)
    return out


def assign_tiers(players, n_tiers=N_TIERS):
    """Write stats['_tier'], per position group, splitting at the largest gaps."""
    groups = defaultdict(list)
    for p in players:
        groups[_pool_of(p.pos)].append(p)

    for _, members in groups.items():
        members.sort(key=lambda p: -p.stats["_dollars"])
        if len(members) <= n_tiers:
            for i, p in enumerate(members):
                p.stats["_tier"] = i + 1
            continue

        gaps = []
        for i in range(1, len(members)):
            drop = members[i - 1].stats["_dollars"] - members[i].stats["_dollars"]
            # -i breaks ties toward the higher-dollar boundary, so the result
            # does not depend on sort stability
            gaps.append((drop, -i))
        gaps.sort(reverse=True)
        cuts = sorted(-i for _, i in gaps[: n_tiers - 1])

        tier = 1
        cut_set = set(cuts)
        for i, p in enumerate(members):
            if i in cut_set:
                tier += 1
            p.stats["_tier"] = tier


def build_rows(lg, pool, byes):
    """Ranked, render-ready rows. Sorted by MY$ descending."""
    missing = [p.name for p in pool if "_dollars" not in p.stats]
    if missing:
        raise ValueError(
            "%d player(s) have no '_dollars'; run the value pipeline first "
            "(e.g. %s)" % (len(missing), ", ".join(sorted(missing)[:3])))

    unknown = sorted(set(p.team for p in pool if p.team not in byes))
    if unknown:
        raise ValueError(
            "no bye week for team code(s) %s; add them to the bye file rather "
            "than rendering a blank bye" % ", ".join(unknown))

    assign_tiers(pool)
    ordered = sorted(pool, key=lambda p: -p.stats["_dollars"])

    rows = []  # type: List[BoardRow]
    for i, p in enumerate(ordered, 1):
        rows.append(BoardRow(
            rank=i,
            name=p.name,
            team=p.team,
            bye=byes[p.team],
            pos=p.pos,
            tier=int(p.stats["_tier"]),
            avg_pts=(p.stats["_season_points"] / p.games) if p.games else 0.0,
            my_dollars=p.stats["_dollars"],
            est_price=p.stats.get("_est_price"),
        ))
    return rows
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_render_rows.py -v`
Expected: 12 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass. 165 before this task.

- [ ] **Step 6: Commit**

```bash
git add src/sffl/render tests/test_render_rows.py
git commit -m "feat: render-ready rows with derived tiers and bye weeks"
```

---

### Task 2: The iPad PDF

**Files:**
- Create: `src/sffl/render/pdf.py`
- Test: `tests/test_render_pdf.py`

**Interfaces:**
- Consumes: `BoardRow` (Task 1); `lg.teams`, `lg.budget`, `lg.roster_size`, `lg.silent_auction`.
- Produces: `render_pdf(lg, rows, path, subtitle="") -> int` — writes the file and returns the page count.

**Port, do not redesign.** `poc/render_poc.py` holds the layout Jeff reviewed on the real iPad on 2026-08-02, and the spec records its constants as settled. Copy the `Sheet` class — `page_header`, `col_header`, `row`, `board`, `dual_board`, `footer`, `management_page`, `save` — and its `COLORS`, `ZEBRA`, `RULE`, `BOXLINE`, `MUTED` palette **verbatim**. Do not adjust page size, row height, margins, gutter, colours, or the write-in box width. Discard the poc's `load_ds`, `load_fp_kdst`, `value_pool`, `num`, `TEAM_ABBR` and `main` — every one is obsolete, predating flat-priced K/DST, the TQB and DST price joins, the calibration curves and the lineup floors.

**The column change.** The poc's row is `# | PLAYER | TM/BYE | THEIR$ | MY$ | PAID`. THEIR$ is dropped. The freed width goes to `EST$`, keeping `PAID` at its settled 33pt — that width was measured against an Apple Pencil and 10pt was tried and rejected.

**Page structure** stays exactly as shipped: overall board (deepest, two-up), Team QB (all 32), Running Backs, Receivers (WR+TE merged), Kickers and Team Defense side by side, then Auction Management.

**The EST$ caveat must be on the page.** Put it in the footer, which the poc already draws on every page: EST$ is what the room is likely to pay, and the top of the board is a floor rather than a point estimate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_pdf.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_render_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.render.pdf'`

- [ ] **Step 3: Implement**

Create `src/sffl/render/pdf.py` by porting the `Sheet` class from `poc/render_poc.py` verbatim, with these changes and no others:

1. Take `BoardRow` objects rather than dicts — `p["name"]` becomes `r.name`, and so on.
2. `col_header` drops `THEIR$` and adds `EST$`. Keep `#` at `x+6`, `PLAYER` at `x+23`, `TM/BYE` at `x+100`; put `MY$` right-aligned at `x+146` and `EST$` right-aligned at `x+172`; `PAID` stays at `x+178` with its 33pt box.
3. `row` renders `r.my_dollars` as `$%.0f` in bold at `x+146`, and `r.est_price` as `$%.0f` in muted at `x+172`, or an em dash when it is `None`.
4. `TM/BYE` renders `"%s/%s" % (r.team, r.bye if r.bye else "-")`.
5. `footer` carries the EST$ caveat instead of the poc's proof-of-concept text.
6. `render_pdf(lg, rows, path, subtitle="")` builds the six sections from `rows`, filtering by `pos`, and returns the page count. Raise `ValueError` on an empty `rows`.
7. `management_page` keeps its layout but reads `lg.teams`, `lg.budget`, `lg.roster_size` and `lg.silent_auction["bid_floor"]` rather than module constants.

Track the page count as you call `showPage()` and return it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_render_pdf.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/render/pdf.py tests/test_render_pdf.py
git commit -m "feat: render the iPad auction board to PDF"
```

---

### Task 3: The printed Excel, and the `render` command

**Files:**
- Create: `src/sffl/render/xlsx.py`
- Modify: `src/sffl/cli.py`
- Test: `tests/test_render_xlsx.py`, `tests/test_cli_render.py`

**Interfaces:**
- Consumes: `BoardRow` (Task 1).
- Produces:
  - `render_xlsx(lg, rows, path) -> None`
  - CLI: `python -m sffl.cli render --source SRC --file PATH --year YEAR [--set NAME] [--curves PATH] [--policy ...] [--prices PATH] [--byes PATH] [--pdf PATH] [--xlsx PATH]`

**The workbook's measured format**, taken from Jeff's 2022 template (`data/extracts/_templates/stripes-2022-rankings-template.xlsx`, gitignored):

| | |
|---|---|
| One sheet, landscape **letter**, 97% scale, gridlines off | |
| Three column groups separated by narrow spacers at width 0.9 | |
| Calibri 8pt throughout, bold headers | |
| Widths: rank 2.8, name 11.6, Team/Bye 5.1, pos 3.8, tier 3.8, numeric 3.5 | |
| **Must print on two letter sheets, back to back** | |

The 2022 columns were `Rank, Name, Team/Bye, Pos, Tier, AVG PTS`. For 2026 the group becomes `Rank, Name, Team/Bye, Pos, Tier, AVG, MY$, EST$` — Jeff asked for tier and average points to be derived and kept, and the two dollar columns are the point of the board.

**The two-page constraint is a hard requirement and must be verified, not assumed.** Eight columns per group is wider than the 2022 six. Step 5 measures the real page count. If it exceeds two pages, reduce in this order and record what you dropped: (1) narrow the numeric columns to 3.2, (2) drop `AVG` from the position blocks but keep it on the overall board, (3) lower the scale to 90%. Do not silently ship three pages.

**Sheet layout.** Group 1 columns `A-F` plus the extra two, group 2 after a spacer, group 3 after another. The overall board spans groups 1 and 2; position blocks stack below and fill group 3, exactly as the 2022 file does.

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_xlsx.py`:

```python
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
```

Create `tests/test_cli_render.py`:

```python
import os

from sffl.cli import main

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_render_xlsx.py tests/test_cli_render.py -v`
Expected: FAIL — `sffl.render.xlsx` does not exist and `render` is not a subcommand.

- [ ] **Step 3: Implement the workbook**

Create `src/sffl/render/xlsx.py`. Build one sheet, write the three column groups, apply the measured widths and Calibri 8pt, set `page_setup.orientation = "landscape"`, `paperSize = ws.PAPERSIZE_LETTER`, `scale = 97`, `sheet_view.showGridLines = False`, and margins matching the template (left 0.75, others 0.0). Write `""` — not `0` — for a missing `est_price`. Raise `ValueError` on empty rows.

- [ ] **Step 4: Implement the `render` command**

Add `cmd_render` to `src/sffl/cli.py`. It reuses the existing pool-building, curve-fitting and valuation path from `cmd_value` — extract the shared part into a helper rather than duplicating it — then calls `build_rows`, then `render_pdf` and/or `render_xlsx`. Require at least one of `--pdf`/`--xlsx`, printing a message naming both and returning 1 otherwise. Print the path and page count of each artifact written.

- [ ] **Step 5: Verify the print constraint and run against real data**

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli render \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml \
  --pdf output/sffl-2026.pdf --xlsx output/sffl-2026.xlsx
```

Then measure the workbook's real page count by converting it:

```bash
soffice --headless --convert-to pdf --outdir output output/sffl-2026.xlsx
```

and counting pages in the result. **Report the actual count.** If it is more than two, apply the reduction order above and report what you changed. `output/` is gitignored; never commit an artifact.

- [ ] **Step 6: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/sffl/render/xlsx.py src/sffl/cli.py tests/test_render_xlsx.py tests/test_cli_render.py
git commit -m "feat: render the printed workbook and add the render command"
```

---

## Self-Review

**Spec coverage.** Dense two-sided Excel preserved from current practice → Task 3, format measured from Jeff's own file. Portrait two-up continuous-scroll PDF at the settled constants → Task 2, ported rather than redesigned. Colour as an edge bar, validated palette, six PDF bookmarks, three sections → Task 2, carried over verbatim. Tier and AVG PTS derived rather than sourced → Task 1. Byes → Task 1.

**Deliberately out of scope.** The silent auction planner is plan 4; the management page keeps the poc's static bid grid until then. Consensus across vendors is still unwired, so `_spread_*` stays absent and both renderers show it blank.

**Known limitation carried forward.** EST$ compresses the extreme tail, so the top of the board is a floor. The caveat is rendered on the PDF footer; the Excel has no footer in the 2022 shape, so it is not carried there — call that out during review if it matters to Jeff.

**Type consistency.** `BoardRow` is the only structure the renderers see. `est_price` is `Optional[float]` and renders as an em dash (PDF) or an empty cell (Excel) when absent — never `0`. Position strings are the pool's own (`RB`, `WR`, `TE`, `TQB`, `K`, `DST`); `_pool_of` is used only for tier grouping, where WR and TE must share a ladder.
