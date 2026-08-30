# Full Position Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the weekly alert and `sffl week` scoring all eight starting slots instead of five, by wiring the TQB, K and DST projection pages that CBS already serves.

**Architecture:** Three new groups in `sources/cbs-weekly.yaml`, one minimal parser extension so a stat name repeated in a `stats:` list sums its columns, and a multi-group capture that merges four pages into one pool before the lineup optimiser runs. Nothing about pricing changes.

**Tech Stack:** Python 3.9.6, pure stdlib, PyYAML, pytest, Playwright (capture only).

**Spec:** `docs/superpowers/specs/2026-08-30-full-position-coverage.md`

## Global Constraints

- **Python 3.9.6 only.** No `match`, no PEP 604 annotations. No numpy/scipy.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc scripts need `PYTHONPATH=src`.
- **This repo is PUBLIC.** `data/weekly/`, `data/extracts/`, `data/captures/` and `data/browser-profile/` are gitignored. Never commit their contents. Committed fixtures must have the fantasy team names placeholdered; real NFL player names stay.
- **Do NOT modify `src/sffl/scoring.py`** — validated against ~250 real observations.
- **Do NOT modify `src/sffl/market.py`, `src/sffl/calibrate.py`, `calibration/2025.yaml` or `market/2026.yaml`.** This work does not touch pricing: TQB is priced through the season path, K and DST are flat-priced.
- **Do NOT relax `expect_tokens` for any group.** It is the column-shift guard.
- Full suite is **654 passing**. Report the count after each task.

## The measured column maps — captured live 2026-08-30, not guessed

URL shape, identical to the working RB-WR-TE group:
`/stats/stats-main/all:<SCOPE>/<WEEK>:p/standard/projections`

### TQB — 17 tokens after the team code

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START | EXPERT
      | ATT COMP YDS TD INT      (passing)
      | ATT YDS AVG TD           (rushing)
      | LOST | FPTS
```
Real row: `Chargers TQB • LAC | ARI | --- | 7 | 84 | 45 | N/R | 33.7 23.8 265.1 2.3 0.7 | 5.4 35 6.5 0.2 | 0.1 | 18.45`

### DST — 16 tokens (NO EXPERT column; that is the whole difference)

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START
      | SACK FUM INT DWN TD STY
      | AVG TOTAL   (yards against)
      | AVG TOTAL   (points against)
      | FPTS
```
Real row: `Chargers DST • LAC | ARI | 26 | 7 | 65 | 47 | 4.5 0.7 0.8 0.6 0.2 0.0 | 284.00 284 | 19.40 19.4 | 9.70`

### K — 21 tokens

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START | EXPERT
      | FG ATT (total) | FG ATT (1-19) | FG ATT (20-29)
      | FG ATT (30-39) | FG ATT (40-49) | FG ATT (50+)
      | XP ATT | FPTS
```
Real row: `Jake Bates K • DET | NO | 21 | 6 | 84 | 75 | 12 | 2.1 2.6 | 0.0 0.0 | 0.5 0.5 | 0.7 0.7 | 0.7 0.8 | 0.3 0.7 | 3.5 3.6 | 5.60`

**DECIDED BY THE REPO OWNER:** CBS's single `50+` column is scored as **`fg_50_59`**, never
`fg_60_plus`. This under-states a 60+ yard kick rather than over-valuing every 50-yarder.
Record it in the profile AND pin it with a test.

---

## Task 1: Summed columns in the parser

**Files:** Modify `src/sffl/cbs_weekly.py`; modify `tests/test_cbs_weekly.py`

**Why:** the league scores `fg_under_30`, but CBS splits it across `1-19` and `20-29`. The
`stats:` map is strictly positional — one token, one name — so it cannot express that today.

**The extension:** a stat name appearing MORE THAN ONCE in a group's `stats:` list means those
columns are SUMMED into that key. Minimal, general, and reads naturally in YAML.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_repeated_stat_name_sums_its_columns(tmp_path):
    # fg_under_30 is CBS's 1-19 plus its 20-29 column.
    prof = tmp_path / "p.yaml"
    prof.write_text(
        "owner_codes: [ZZ]\n"
        "groups:\n"
        "  T:\n"
        "    stats: [a, a, b]\n"
        "    expect_tokens: 4\n")
    page = tmp_path / "page.txt"
    page.write_text("FA\tNick Chubb RB • CLE\tOPP\t1.5\t2.5\t9.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert row.stats["a"] == 4.0      # 1.5 + 2.5
    assert row.stats["b"] == 9.0


def test_a_single_occurrence_name_is_unaffected(tmp_path):
    prof = tmp_path / "p.yaml"
    prof.write_text("owner_codes: [ZZ]\ngroups:\n  T:\n    stats: [a, b]\n    expect_tokens: 3\n")
    page = tmp_path / "page.txt"
    page.write_text("FA\tNick Chubb RB • CLE\tOPP\t1.5\t9.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert row.stats["a"] == 1.5 and row.stats["b"] == 9.0


def test_repeated_underscore_columns_are_still_all_discarded(tmp_path):
    # `_` marks a column the engine does not use; repeating it must not
    # create a summed stat literally named "_".
    prof = tmp_path / "p.yaml"
    prof.write_text("owner_codes: [ZZ]\ngroups:\n  T:\n    stats: [_, _, a]\n    expect_tokens: 4\n")
    page = tmp_path / "page.txt"
    page.write_text("FA\tNick Chubb RB • CLE\tOPP\t1.0\t2.0\t3.0\n")
    from sffl.cbs_weekly import parse
    row = parse(str(page), group="T", week=1, profile_path=str(prof))[0]
    assert "_" not in row.stats
    assert row.stats["a"] == 3.0
```

- [ ] **Step 2: Run to verify they fail** — `./.venv/bin/pytest tests/test_cbs_weekly.py -q`

- [ ] **Step 3: Implement.** In `parse`, replace the direct assignment in the field loop with an
accumulate-if-present. Keep the `_` skip BEFORE the accumulation so a repeated `_` cannot
create a stat. Update the module docstring and `sources/cbs-weekly.yaml`'s header comment to
document the rule — a format extension nobody can discover from the data is a trap.

- [ ] **Step 4: Run the tests, then the full suite.** The existing RB-WR-TE fixture has no
repeated names, so its parse must be byte-identical. Confirm.

- [ ] **Step 5: Commit.**

---

## Task 2: The three group configs and their fixtures

**Files:** Modify `sources/cbs-weekly.yaml`; create `tests/fixtures/cbs_weekly_{tqb,k,dst}.txt`; create `tests/test_cbs_weekly_groups.py`

**Interfaces produced:** groups `TQB`, `K`, `DST` in the profile.

- [ ] **Step 1: Capture the three real pages**

```bash
PYTHONPATH=src ./.venv/bin/python -c "
from sffl.capture import capture
B='https://stripesfantasyfootballleague.football.cbssports.com/stats/stats-main/all:%s/1:p/standard/projections'
print(capture({'tqb':B%'TQB','k':B%'K','dst':B%'DST'},'data/captures','data/browser-profile'))
"
```

**Build each fixture from the real capture.** Keep real NFL player and team names — they are
public and make the fixture honest. **Replace every fantasy team name** (the leading owner
column: `Sgt Hu...`, `Lean M...`, `Sawyer...` etc.) with neutral placeholders; this repo is
public. Keep enough rows to cover a free agent, a waiver row, an owned row, and — for K — a
kicker with a non-zero `50+` value.

- [ ] **Step 2: Write the failing tests**

One test per group asserting: the row count parses, a named player's key stats land in the
right keys with the right values (read them off the real capture — do NOT copy from this
plan), and `expect_tokens` refuses a row with one token added or removed.

For K specifically, also assert:
- `fg_under_30` equals the `1-19` column plus the `20-29` column;
- a non-zero `50+` value lands in **`fg_50_59`** and `fg_60_plus` is absent or zero.
  This is the owner's decision and must be pinned, not merely commented.

- [ ] **Step 3: Add the groups to `sources/cbs-weekly.yaml`**

```yaml
  TQB:
    stats: [pass_att, pass_cmp, pass_yds, pass_td, pass_int,
            rush_att, rush_yds, _, rush_td, fum_lost, _]
    expect_tokens: 17

  DST:
    # No EXPERT column on this page - that is why it is 16, not 17.
    # DWN is unidentified; see Step 4 before mapping it.
    stats: [sacks, def_fum_rec, def_int, _, def_td, def_safety,
            _, def_ya, _, def_pa, _]
    expect_tokens: 16

  K:
    # CBS's distance bands do not match the league's. fg_under_30 is CBS's
    # 1-19 PLUS its 20-29 column - a repeated name sums (see cbs_weekly.parse).
    # CBS gives ONE 50+ column and the league scores 50-59 and 60+ separately;
    # they are not separable. DECIDED: 50+ scores as fg_50_59, which
    # UNDER-states a 60+ yard kick rather than over-valuing every 50-yarder.
    stats: [_, _, fg_under_30, _, fg_under_30, _, fg_30_39, _,
            fg_40_49, _, fg_50_59, _, xp_made, _, _]
    expect_tokens: 21
```

**Every one of these maps is a hypothesis until the test proves it against the real capture.**
Verify each against the fixture and correct the map, not the test, where they disagree. Report
any correction.

- [ ] **Step 4: Identify or discard `DWN`**

Capture a second week's DST page and compare. If `DWN` cannot be identified with confidence,
leave it mapped to `_` and say so in the profile comment. **Do not guess it into a scoring
key** — a wrong mapping silently adds points to every defense.

- [ ] **Step 5: Decide `fg_missed`**

The league scores `fg_missed`, which is derived (`total ATT − total FG`) and cannot be
expressed positionally. Either compute it in `parse` from the two total columns, or leave it
unscored and record that. Measure which matters — how many points per week it is worth on the
real capture — and choose on that number, stating it.

- [ ] **Step 6: Run tests, then the full suite. Commit.**

---

## Task 3: Capture and merge all four groups

**Files:** Modify `src/sffl/cli.py`; create `tests/test_cli_multigroup.py`

- [ ] **Step 1: Write the failing test** — a `week`/`alert` run given four saved pages produces
one pool containing all four position groups, with no duplicate players and no cross-group
key collisions.

- [ ] **Step 2: Implement.** `_cmd_alert` and `_cmd_week` currently capture and parse ONE page
with `--group`. They must capture four URLs and parse each with its own group, merging the
results into a single pool before `best_lineup` runs.

Keep the URL construction in ONE place (`cli.py` already owns `PROJECTIONS_URL_TEMPLATE`) —
parameterise it by scope rather than adding four literals.

**A partial failure must be loud.** If one of the four pages fails to capture or parse, the run
must say which and mark itself degraded — never silently produce a lineup missing a slot,
which is indistinguishable from today's behaviour and is what this whole task exists to fix.

- [ ] **Step 3: Run tests and the full suite. Commit.**

---

## Task 4: End-to-end — all eight slots

**Files:** Create/modify `tests/test_cli_alert.py`

- [ ] **Step 1: Write the failing test** — a roster containing a TQB, a K and a DST, with all
four projection pages present, fills **all eight** lineup slots. Assert no slot is `UNFILLED`.
This is the deliverable; nothing else proves it.

- [ ] **Step 2: Run a REAL alert** with `--dry-run` against the live site and confirm all eight
slots fill with your actual roster. Paste the rendered lineup into the report.

- [ ] **Step 3: Confirm the scoring is sane.** TQB and DST are banded and now reachable —
compare each slot's points against the CBS `FPTS` column on the same capture and report the
differences. They will not match exactly (that is the entire point of calibration), but a
wildly different number means a column is mis-mapped, and this is the check that catches it.

- [ ] **Step 4: Commit.**

---

## Task 5: The def-curve gate — PRE-REGISTERED, written before measuring

**Files:** Create `docs/superpowers/specs/<date>-def-curve-weekly-gate.md`; create `poc/measure_dst_ranking.py`

This work makes `def_pa`/`def_ya` reachable for the first time. They have 3 and 4 anchors from
4 defenses. Whether to rebuild them from the 26 available defenses is now a live question that
no pre-registration has covered.

- [ ] **Step 1: Write and COMMIT the pre-registration before measuring anything.**

The metric is **not** mean error. The alert starts exactly ONE defense, and
`poc/measure_weekly_calibration.py` states the standard: *"What matters for a start/sit or
waiver decision is whether it changes the ORDER of two players."*

So the gate is **rank accuracy**: across 2025 weeks, rank the defenses by predicted weekly
points and compare to actual. Pre-register the statistic (top-1 hit rate, or a rank
correlation — pick one and say why), the threshold, and the leave-one-out or fold structure,
BEFORE running it. State what would make you abandon it.

Candidates: the shipped interpolation from 4 defenses, versus `build_curves_isotonic` and
`build_curves_pooled` from all 26. The first experiment found pooled beat baseline on `def_ya`
under both predictors and split on `def_pa` — that is a hypothesis, not a result, because it
was never gated.

- [ ] **Step 2: Measure, apply the gate exactly, and adopt only what clears it.**

If nothing clears, record that and leave the curves alone. That is a legitimate outcome and
this project has twice been saved by one.

---

## Self-Review

**1. Spec coverage.** Summed columns (T1); three group maps and fixtures with the `50+` decision
pinned (T2); multi-group capture and merge with loud partial failure (T3); the eight-slot
deliverable verified live (T4); the def-curve question gated rather than assumed (T5).

**2. Placeholders.** The three `stats:` maps in Task 2 Step 3 are explicitly labelled
hypotheses to be verified against the real capture, with instructions to correct the map rather
than the test. `DWN` and `fg_missed` are open questions with a stated procedure and an explicit
ban on guessing.

**3. Type consistency.** All groups produce `PlayerProjection` through the same `parse`; the
merge in Task 3 consumes exactly that.

**4. Known risk.** Task 2 depends on a working authenticated capture. If the CBS session has
expired, `capture()` raises `SessionExpired` naming the fix (`ops/cbs_login.py`) — re-run it
and continue.
