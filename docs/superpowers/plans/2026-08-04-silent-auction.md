# Silent Auction Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a real tradeoff table on the auction management page, so Jeff can decide his sealed bid at the table from five years of what this league has actually paid.

**Architecture:** `data/league/silent-auction-bids.csv` holds every bid from 2021-2025 — 60 rows, five complete years. That history maps a bid to the rank it historically bought, to how often that bid tied, and to what bump has won such ties. Joined against the current board it answers the only question that matters in round one: *if I bid $X, roughly where do I pick, who is likely there, and what am I left with for the other twelve spots?* The planner reports; it does not recommend.

**Tech Stack:** Python 3.9, pytest, reportlab, openpyxl. No new dependencies.

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations. Use `typing.Optional`/`List`/`Dict`/`Tuple`.
- **Use the project venv** at `.venv/`. Invoke as `./.venv/bin/pytest` and `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc commands need `PYTHONPATH=src`.
- **`data/extracts/` and `data/weekly/` are gitignored** — licensed vendor and CBS data, PUBLIC repo. Never commit from either, and never paste extract contents or real-run player names into a committed file. **`data/league/` IS tracked** — the bid history lives there and is league-owned, so tests may read it. `output/` is gitignored.
- **Wrong numbers must never be produced silently.** Prefer raising over guessing.
- **WR and TE are ONE position.**
- **`src/sffl/scoring.py` and `src/sffl/value.py` must NOT be modified.** This plan reads the board; it does not revalue.

## The mechanic, confirmed with Jeff on 2026-08-04

- Sealed bid, floor **$26**. Bids are ranked; **you pay your own bid**; you then pick a player in bid order, highest first.
- That same order governs nomination for the rest of the draft.
- Ties are broken by a sealed **bump**, and the bump is charged **only if it wins the tie** (`bump_charged_only_on_winning_tie` in the league YAML). Observed: 2024 rank 4 bid $39 bump $2 cap $39 — "no tie; bump not charged".
- **A bid below $26 is discarded and the team forfeits its silent pick.** Hard constraint. The planner must never present a sub-floor option.
- **A bump tie escalates to a live auction.** 2021 ranks 7-8 both bumped $4; 2023 saw a four-way tie at $39. The planner must not imply a bump guarantees anything.

## Two rulings from Jeff that shape the whole design

1. **Show the tradeoff; do not recommend.** No "best bid", no highlighting, no ranking of options. Render the table and let him decide live.
2. **Do not assume finishing first is worth anything beyond round one.** He does not know whether it is. State the order consequence factually and never price it.

## Observed history (do not re-derive)

Rank → bid, all five years. Total spend is stable at **$412-432** of the league's $1,320.

| rank | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| 1 | 44 | 45 | 39 | 41 | 43 |
| 2 | 41 | 42 | 39 | 41 | 40 |
| 3 | 40 | 39 | 39 | 40 | 40 |
| 4 | 40 | 38 | 39 | 39 | 39 |
| 5 | 38 | 38 | 38 | 35 | 38 |
| 6 | 37 | 35 | 35 | 34 | 37 |
| 7 | 35 | 33 | 33 | 33 | 33 |
| 8 | 35 | 30 | 31 | 31 | 33 |
| 9 | 32 | 30 | 30 | 31 | 30 |
| 10 | 30 | 27 | 30 | 30 | 27 |
| 11 | 26 | 26 | 26 | 26 | 26 |
| 12 | 26 | 26 | 26 | 26 | 26 |

**Ranks 11-12 tie at the floor every single year**, so a $26 bid has always needed a bump. Winning bumps at the floor have been $1-$2.

## File Structure

| File | Responsibility |
|---|---|
| `src/sffl/silent.py` | Load the bid history; map bid ↔ rank; tie and bump statistics |
| `src/sffl/plan.py` | Join history to the current board into `BidOutcome` rows |
| `src/sffl/render/pdf.py` (modify) | Replace the management page's static grid with the real table |
| `src/sffl/cli.py` (modify) | Add a `plan` subcommand printing the table |

---

### Task 1: The bid history

**Files:**
- Create: `src/sffl/silent.py`
- Create: `tests/fixtures/silent_bids_sample.csv`
- Test: `tests/test_silent.py`

**Interfaces:**
- Produces:
  - `SilentBid` dataclass: `year: int`, `rank: int`, `franchise: str`, `bid: int`, `bump: int`, `cap_cost: int`, `player: str`, `note: str`.
  - `load_bid_history(path=DEFAULT_BIDS) -> List[SilentBid]`
  - `ranks_for_bid(history, bid) -> Tuple[int, int, float]` — `(best_rank, worst_rank, median_rank)` observed for that exact bid across all years. Raises if the bid is below the floor.
  - `bids_for_rank(history, rank) -> Tuple[int, int, float]` — `(min, max, median)` bid that historically bought that rank.
  - `tie_rate_at(history, bid) -> float` — the fraction of years in which two or more franchises submitted this exact bid. *(Renamed `field_tie_rate_at` on 2026-08-05, when Jeff ruled that the page must also carry `join_tie_rate_at` — the fraction of years in which AT LEAST ONE franchise was already there, which is the bidder's own tie exposure and a much larger number: $30 is 40% by the first measure and 100% by the second. Two statistics named "tie rate" could not stay one word.)*
  - `winning_bumps_at(history, bid) -> List[int]` — bumps that were actually charged at that bid level, i.e. bumps that won a tie.

**Reading `cap_cost` correctly.** `cap_cost` differs from `bid` exactly when a bump was charged, which happens only on a winning tie. So `cap_cost - bid` is the bump that won, and a row where they are equal either had no tie or lost one. Do not infer a charged bump from the `bump` column alone — 2024 rank 4 recorded `bump 2` with `cap_cost 39 == bid 39` and the note "no tie; bump not charged".

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/silent_bids_sample.csv` — a small hand-written excerpt, two years, exercising the floor tie and a charged bump:

```csv
year,rank,franchise,bid,bump,cap_cost,player,note
2024,1,Alpha,41,1,42,Player One,won tie vs Beta on bump
2024,2,Beta,41,0,41,Player Two,lost tie on bump
2024,3,Gamma,39,2,39,Player Three,no tie; bump not charged
2024,4,Delta,26,2,28,Player Four,won tie vs Epsilon on bump
2024,5,Epsilon,26,1,26,Player Five,lost tie on bump
2025,1,Alpha,43,0,43,Player Six,
2025,2,Beta,39,0,39,Player Seven,
2025,3,Gamma,26,1,27,Player Eight,won tie vs Delta on bump
2025,4,Delta,26,0,26,Player Nine,lost tie on bump
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_silent.py`:

```python
import pytest

from sffl.silent import (SilentBid, bids_for_rank, load_bid_history,
                         ranks_for_bid, tie_rate_at, winning_bumps_at)

FIXTURE = "tests/fixtures/silent_bids_sample.csv"
REAL = "data/league/silent-auction-bids.csv"


def test_loads_every_row():
    h = load_bid_history(FIXTURE)
    assert len(h) == 9
    assert h[0].year == 2024
    assert h[0].bid == 41
    assert h[0].cap_cost == 42


def test_ranks_for_a_bid_span_the_observed_years():
    h = load_bid_history(FIXTURE)
    best, worst, median = ranks_for_bid(h, 26)
    assert best == 3          # 2025 rank 3
    assert worst == 5         # 2024 rank 5
    assert 3 <= median <= 5


def test_a_bid_below_the_floor_raises():
    h = load_bid_history(FIXTURE)
    with pytest.raises(ValueError) as e:
        ranks_for_bid(h, 20)
    assert "26" in str(e.value)


def test_a_bid_never_observed_reports_the_neighbouring_ranks():
    # $30 was never bid in the fixture; it sits between $26 and $39
    h = load_bid_history(FIXTURE)
    best, worst, median = ranks_for_bid(h, 30)
    assert best <= median <= worst


def test_bids_for_rank_reports_the_range_that_bought_it():
    h = load_bid_history(FIXTURE)
    lo, hi, median = bids_for_rank(h, 1)
    assert lo == 41
    assert hi == 43


def test_tie_rate_is_the_fraction_of_years_with_a_duplicate_bid():
    h = load_bid_history(FIXTURE)
    # $26 was bid twice in 2024 and twice in 2025 - tied in both years
    assert tie_rate_at(h, 26) == pytest.approx(1.0)
    # $43 appears once, in one year only
    assert tie_rate_at(h, 43) == pytest.approx(0.0)


def test_winning_bumps_come_from_cap_cost_not_the_bump_column():
    h = load_bid_history(FIXTURE)
    # Gamma 2024 recorded bump=2 but cap_cost == bid, so it was NOT charged
    assert 2 not in winning_bumps_at(h, 39)
    # Alpha 2024 paid 42 on a 41 bid -> a charged bump of 1
    assert winning_bumps_at(h, 41) == [1]


def test_the_real_history_loads_and_covers_five_years():
    h = load_bid_history(REAL)
    assert len(h) == 60
    assert sorted(set(b.year for b in h)) == [2021, 2022, 2023, 2024, 2025]
    assert all(b.bid >= 26 for b in h), "no observed bid is below the floor"


def test_every_real_year_has_twelve_bids():
    h = load_bid_history(REAL)
    counts = {}
    for b in h:
        counts[b.year] = counts.get(b.year, 0) + 1
    assert set(counts.values()) == {12}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_silent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.silent'`

- [ ] **Step 4: Implement**

Create `src/sffl/silent.py`. Key points:

- `BID_FLOOR = 26`, but read it from the league YAML where a league object is available; the module constant is the fallback for history analysis, which has no league context.
- `ranks_for_bid` for a bid never observed: find the nearest observed bid below and above, and return the span between their observed ranks. Never extrapolate past the observed range — clamp, and say so in the docstring.
- `winning_bumps_at` returns `cap_cost - bid` for rows where that difference is positive, at the given bid level.
- Raise `ValueError` naming the floor for any bid below it.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_silent.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add src/sffl/silent.py tests/test_silent.py tests/fixtures/silent_bids_sample.csv
git commit -m "feat: load and summarise five years of silent auction bids"
```

---

### Task 2: The tradeoff table

**Files:**
- Create: `src/sffl/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `sffl.silent` (Task 1); `sffl.render.rows.BoardRow`; `lg.budget`, `lg.roster_size`, `lg.silent_auction["bid_floor"]`.
- Produces:
  - `BidOutcome` dataclass: `bid: int`, `best_rank: int`, `worst_rank: int`, `median_rank: float`, `likely_player: Optional[str]`, `likely_my_dollars: Optional[float]`, `likely_est_price: Optional[float]`, `budget_left: int`, `per_remaining_spot: float`, `discretionary: int`, `tie_rate: float`, `winning_bumps: List[int]`. *(As built: `per_remaining_spot` was dropped after the `$/ea` column was cut from the page — nothing computed it for any reader. `tie_rate` became the pair `join_tie_rate` / `field_tie_rate`, both `Optional[float]`, both None exactly when `observations == 0`.)*
  - `plan_bids(lg, rows, history, candidates=None) -> List[BidOutcome]`

**The arithmetic.** Winning at bid `X` leaves `lg.budget - X` for `lg.roster_size - 1` further spots. Each costs at least $1, so `discretionary = (lg.budget - X) - (lg.roster_size - 1)`. With the real config: bid $26 leaves $84 and $72 discretionary; bid $44 leaves $66 and $54 discretionary.

**Which player you would get.** At median rank `N`, the `N`-th best board row by `my_dollars` is the illustration — **assuming the room drafts in our board's order**, which it will not exactly. Label it as an illustration everywhere it surfaces. Only `pos in ("TQB", "RB", "WR", "TE")` are candidates; nobody spends a silent pick on a kicker.

**Default candidates.** The observed range, floor to the highest bid ever recorded, in $1 steps. Do not invent bids above the observed maximum. *(Corrected after task 1: `ranks_for_bid` does NOT clamp — it places the bid against every year, so a bid above everything ever submitted correctly reports rank 1, as `test_a_bid_above_everything_ever_observed_is_rank_one` pins. The cap stands for a different reason, recorded in `default_candidates`: rank 1 is the only thing $50 could ever be told, and a ladder of bids that all say the same thing invites spending $5 to buy nothing.)*

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan.py`:

```python
import pytest

from sffl.league import load_league
from sffl.plan import BidOutcome, plan_bids
from sffl.render.rows import BoardRow
from sffl.silent import load_bid_history

LG = load_league("leagues/sffl/2026.yaml")
REAL = "data/league/silent-auction-bids.csv"


def row(rank, name, pos, dollars, est):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=float(est))


def board():
    return [row(i, "Player %d" % i, "RB" if i % 2 else "WR",
                60.0 - 1.5 * i, 40.0 - 1.0 * i) for i in range(1, 40)]


def test_every_outcome_is_at_or_above_the_floor():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    assert out
    assert all(o.bid >= LG.silent_auction["bid_floor"] for o in out)


def test_budget_arithmetic_matches_the_league_config():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    o = [x for x in out if x.bid == 26][0]
    assert o.budget_left == LG.budget - 26
    assert o.discretionary == (LG.budget - 26) - (LG.roster_size - 1)


def test_a_higher_bid_never_buys_a_worse_rank():
    out = sorted(plan_bids(LG, board(), load_bid_history(REAL)),
                 key=lambda o: o.bid)
    medians = [o.median_rank for o in out]
    assert medians == sorted(medians, reverse=True), \
        "median rank must improve (fall) as the bid rises"


def test_the_floor_bid_reports_a_tie_every_year():
    out = plan_bids(LG, board(), load_bid_history(REAL))
    o = [x for x in out if x.bid == 26][0]
    assert o.tie_rate == pytest.approx(1.0)
    assert o.winning_bumps, "a floor bid has always needed a bump"


def test_only_skill_positions_are_offered_as_the_likely_pick():
    rows = board() + [row(99, "Some Kicker", "K", 1.0, 1.0),
                      row(98, "Some Defense", "DST", 1.0, 1.0)]
    out = plan_bids(LG, rows, load_bid_history(REAL))
    assert all(o.likely_player not in ("Some Kicker", "Some Defense")
               for o in out)


def test_an_empty_board_raises():
    with pytest.raises(ValueError):
        plan_bids(LG, [], load_bid_history(REAL))


def test_a_board_shallower_than_the_rank_reports_no_player_rather_than_guessing():
    out = plan_bids(LG, [row(1, "Only Guy", "RB", 50.0, 30.0)],
                    load_bid_history(REAL))
    deep = [o for o in out if o.median_rank > 1]
    assert deep, "expected some bid whose median rank is past the board"
    assert all(o.likely_player is None for o in deep)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_plan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.plan'`

- [ ] **Step 3: Implement**

Create `src/sffl/plan.py`. Raise `ValueError` on an empty board. Where the board is shallower than a rank, set `likely_player`/`likely_my_dollars`/`likely_est_price` to `None` rather than clamping to the last row — a fabricated pick is worse than an honest blank.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_plan.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/plan.py tests/test_plan.py
git commit -m "feat: join the bid history to the board into a tradeoff table"
```

---

### Task 3: Put it on the page

**Files:**
- Modify: `src/sffl/render/pdf.py`
- Modify: `src/sffl/cli.py`
- Test: `tests/test_plan_render.py`

**Interfaces:**
- Consumes: `plan_bids` (Task 2).
- Produces: the management page's silent-auction block driven by real data; a `plan` CLI subcommand printing the same table.

**What replaces what.** `management_page` currently draws a hardcoded grid over bids `[20, 25, 30, 35, 40, 50, 60]` — two of which are below the floor and would forfeit the pick, and two of which exceed any bid ever recorded. Replace that grid with `plan_bids` output. Keep the surrounding layout, the roster-slot block and the league-spend grid exactly as they are.

**Required on the page:**
- The floor and its penalty, in words: a bid under $26 is discarded and forfeits the pick.
- That the "likely pick" column is an **illustration** assuming the room drafts in board order.
- The tie rate and historical winning bump for the floor bid — it has tied every year for five years.

**Do not** highlight a recommended bid, sort by attractiveness, or add a "best value" marker. Jeff asked for the tradeoff, not the answer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan_render.py`:

```python
import re

from sffl.league import load_league
from sffl.plan import plan_bids
from sffl.render.pdf import render_pdf
from sffl.render.rows import BoardRow
from sffl.silent import load_bid_history

LG = load_league("leagues/sffl/2026.yaml")


def row(rank, name, pos, dollars, est):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=float(est))


def board():
    rows, n = [], 1
    for pos, count in (("RB", 40), ("WR", 60), ("TE", 20),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 60.0 - 0.1 * n,
                            40.0 - 0.07 * n))
            n += 1
    return rows


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_the_management_page_states_the_floor_and_its_penalty(tmp_path):
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path,
               outcomes=plan_bids(LG, board(),
                                  load_bid_history("data/league/silent-auction-bids.csv")))
    data = read(path).lower()
    assert b"$26" in data or b"26" in data
    assert b"forfeit" in data or b"discard" in data


def test_the_likely_pick_is_labelled_an_illustration(tmp_path):
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path,
               outcomes=plan_bids(LG, board(),
                                  load_bid_history("data/league/silent-auction-bids.csv")))
    assert b"illustration" in read(path).lower()


def test_no_bid_below_the_floor_appears_on_the_page(tmp_path):
    path = str(tmp_path / "b.pdf")
    outcomes = plan_bids(LG, board(),
                         load_bid_history("data/league/silent-auction-bids.csv"))
    assert all(o.bid >= 26 for o in outcomes)
    render_pdf(LG, board(), path, outcomes=outcomes)
    assert read(path).startswith(b"%PDF-")


def test_the_pdf_still_renders_without_outcomes(tmp_path):
    # rendering with no bid history must degrade, not crash
    path = str(tmp_path / "b.pdf")
    pages = render_pdf(LG, board(), path)
    assert pages > 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_plan_render.py -v`
Expected: FAIL — `render_pdf` takes no `outcomes` argument.

- [ ] **Step 3: Implement**

Give `render_pdf` an optional `outcomes=None` parameter, threaded to `management_page`. When it is `None`, keep the current static block so the PDF still renders without bid history. When present, draw the real table.

Add `cmd_plan` to `src/sffl/cli.py` printing the same table to stdout, and wire `--outcomes` into `cmd_render` so the rendered PDF carries it.

> **Note added 2026-08-30 (docs audit):** this shipped as **`--bids`**, not `--outcomes` —
> on both `sffl plan` and `sffl render`, defaulting to
> `data/league/silent-auction-bids.csv`. No `--outcomes` flag exists on any subcommand.
> (Every step in this plan is left unchecked, as in the other merged plans here; the work
> itself is merged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_plan_render.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the whole suite and render for real**

Run: `./.venv/bin/pytest -q`, then the production render command from `NEXT.md` with `--pdf`. Confirm the page count and report the printed table verbatim in your report — it goes in the report only, never a committed file.

- [ ] **Step 6: Commit**

```bash
git add src/sffl/render/pdf.py src/sffl/cli.py tests/test_plan_render.py
git commit -m "feat: put the real silent auction tradeoff table on the management page"
```

---

## Self-Review

**Spec coverage.** A silent auction planner on the management page → Task 3. Grounded in what the league actually paid rather than a model → Tasks 1-2, five years of real bids. The floor and its forfeiture penalty → stated on the page and enforced in `ranks_for_bid`. The tradeoff shown rather than a recommendation → no ranking, no highlighting, explicit in Task 3.

**Deliberately out of scope.** Nomination-order value is not modelled — Jeff does not know whether finishing first is worth anything beyond round one, so the planner states the rank and prices nothing. Bump strategy beyond reporting historical winning bumps is out: a bump tie escalates to a live auction, so no bump guarantees an outcome.

**Known limitation carried forward.** The "likely pick" column assumes the room drafts in our board's order. It will not. The column is labelled an illustration everywhere it appears, and a board shallower than the rank reports no player rather than fabricating one.

**Type consistency.** `BoardRow` is the board contract, unchanged from the renderers plan. `BidOutcome` is new and local to `plan.py`. Bids and ranks are `int`; `median_rank` is `float` and the two tie rates are `Optional[float]` (see the correction at Task 2's interfaces); `likely_*` are `Optional`. `bid_floor` is read from `lg.silent_auction` wherever a league is in scope.
