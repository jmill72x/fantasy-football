# In-Season Tooling — Design

**Date:** 2026-08-27
**Status:** approved in brainstorming, not yet planned

## Goal

Answer three in-season questions in this league's actual scoring — **who to start, who to
claim off waivers, and whether a trade helps** — and let Jeff execute waiver moves from his
phone. One command, no dashboard, no web service.

## Why this is worth building

Nothing off the shelf can score this league. SFFL uses **banded scoring with hard floors**;
every mainstream platform models per-unit rates plus fixed bonus thresholds.
`poc/compare_ds_scoring.py` already measures that gap against Draft Sharks' own sync and
finds the two structurally different. StatsDeck, the tool that prompted this, does not
support CBS at all and would inherit the same mismatch if it did.

`src/sffl/scoring.py::score_game(lg, stats, pos)` is validated against ~250 real CBS weekly
observations. It is the asset, it is already per-game, and it is the one thing that cannot
be bought.

## Scope

**In:** weekly projection ingest, live roster + free-agent scrape, a lineup optimizer, three
queries built on it, waiver-queue submission, and a one-line push when something changed.

**Out:** injury/news monitoring beyond what the scrape reveals; any web page or dashboard;
season-long standings or playoff modeling; anything that writes to CBS other than the
waiver queue and the starting lineup.

## Global constraints

Inherited from `CLAUDE.md` and non-negotiable:

- **Python 3.9.6 only.** No `match`, no PEP 604 (`int | None`).
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed,
  so ad-hoc scripts need `PYTHONPATH=src`.
- **`src/sffl/scoring.py` MUST NOT be modified.** It is validated ground truth.
- **The repo is public.** Anything holding licensed vendor projections or CBS stat lines is
  gitignored. Extend `.gitignore` before adding a new data path.
- **Never mix seasons.** A projection from one season and a price or actual from another is
  what produced this project's largest measurement error. The `tqb_starters_season` guard
  exists for exactly this; anything new that pairs data across a season boundary must fail
  loudly rather than proceed.
- **`by_index` source profiles declare `expect_columns`.** `_cell` returns `""` for an
  out-of-range index, so a vendor adding a column shifts every stat silently.

## The lineup — the fact everything else derives from

Eight starters from a thirteen-man roster:

| slot | eligible |
|---|---|
| TQB | TQB |
| RB | RB |
| WR/TE | WR, TE |
| FLEX x3 | RB, WR, TE |
| K | K |
| DST | DST |

This matches `leagues/sffl/2026.yaml`'s `starters: 8` and
`flex_slots: 5  # RB/WR/TE, floor of 1 RB and 1 WR/TE`. **Five of the eight starting slots
draw from one RB/WR/TE pool** with only one RB and one WR/TE forced — which is why the
auction model treats the two as near-interchangeable, and is the structural reason the
2026 positional bias (room paid +$133 into RB) did not surface in it.

The explicit slot list is NOT currently in the league YAML — only the aggregate. **Task 1
adds it**, because an optimizer needs slots, not counts.

## The calibration curves apply weekly, unchanged

Worth stating because it is not obvious and it saves building anything new.

`calibration/2025.yaml` maps **per-game mean -> expected points** for each banded stat. It
exists because `band(mean) != E[band(weekly)]` — averaging a season and banding the average
loses the distribution.

**A weekly projection is a per-game mean.** So `calibrate.expected_points(curve, projection)`
is exactly the right transform for a single week, and arguably a better fit than the season
use it was built for. The pattern to reuse is `pool.score_season_calibrated` — full score,
subtract the naive banded terms, add the calibrated ones — evaluated at `games=1`.

The same `STAT_POSITIONS` gating applies. **A zero is not a no-op for `def_pa`/`def_ya`**:
both band 0 at their MAXIMUM, so any loop over bands that is not position-gated pays every
receiver a shutout. That trap has been hit three times in this codebase. Do not hit it a
fourth.

## Data sources — all three unverified, all three verified first

| source | gives | status |
|---|---|---|
| Draft Sharks Projections export | weekly per-stat lines | **UNVERIFIED** — weekly not published until ~week 1. The Who to Start page states DS uses "weekly stat projections". The 47-column season export parses today. |
| CBS public projections | per-stat incl. **`FL` (fumbles lost)** | Reachable and scrapeable as text today at `/fantasy/football/stats/{POS}/2026/season/projections/nonppr/`. Weekly not yet live. |
| CBS league site | live roster, free agents, waiver queue | **UNVERIFIED** — league URL not yet known to the pipeline. |

**Everything in this design rests on those three. Task 1 is a spike that proves each is
reachable and parseable, and the plan must not build modeling on top of an unproven
source.** If the CBS league scrape does not expose free agents, waivers is not buildable and
the scope drops to start/sit.

CBS's `FL` column unblocks the recorded lost-fumble gap: the league penalises a lost fumble
(~-1), `leagues/sffl/2026.yaml` has no term, and Draft Sharks does not publish the stat at
all.

## Architecture

Four new modules, one new command. Everything else is reused.

| file | responsibility |
|---|---|
| `src/sffl/weekly_proj.py` | Load weekly per-stat projections for a given week from a source profile. Returns `PlayerProjection` objects, same schema the auction path uses. |
| `src/sffl/roster.py` | Scrape live roster, free agents, and the waiver queue from the CBS league site. Read-only. |
| `src/sffl/lineup.py` | The optimizer and the marginal-value primitive. No I/O. |
| `src/sffl/waiver.py` | Submit `(add, drop)` pairs to the CBS queue and verify the result. The only module that writes anything. |
| `src/sffl/cli.py` | New `week` command. |

`lineup.py` holds no I/O on purpose: it is the piece with real logic and it must be testable
against hand-built rosters with no network and no fixtures.

## The optimizer

```
best_lineup(lg, players) -> (slots, total_points)
```

Small enough to solve exactly, and it must be solved exactly rather than greedily:

1. TQB, K, DST each take the highest-scoring eligible player. Independent of everything else.
2. The five flex-eligible slots take the best legal set from RB/WR/TE subject to **>=1 RB and
   >=1 WR/TE**.

Step 2 is the only interesting part. Take the top 5 by projected points; if a floor is
violated, the fix is a single swap — the best player of the missing position replaces the
worst player of the over-represented one. **The plan must include a test that brute-forces
every legal combination on a small roster and asserts the fast path agrees**, because a
greedy repair that is subtly wrong produces a plausible lineup and silently costs points.

Marginal value is then one line, and it is what all three queries use:

```
delta(player) = best_lineup(roster + [player]).total - best_lineup(roster).total
```

**This is deliberately marginal against Jeff's roster, not against a league replacement
level.** A generic tool ranks the best available player. This ranks the player who most
improves *his worst starting slot* — which, with four backs at or below replacement and one
RB slot forced every week, is a different answer.

## The three queries

All three are `sffl week`:

- **`--start-sit`** — optimize over owned players; report only where the optimum differs from
  the lineup currently set on CBS. Silence means the lineup is already right.
- **`--waivers`** — compute `delta` for every free agent; rank `(add, drop)` pairs. The drop
  is chosen as the player whose removal costs least, not simply the lowest-projected.
- **`--trade "GIVE1,GIVE2 for GET1,GET2"`** — `delta` for a hypothetical swap. Names resolve
  through `sffl.identity` like every other name in this project.

Default with no flag: run all three and report only what changed since the last run.

**"Since the last run" needs state**, and the spec must say where it lives:
`data/weekly-state/<season>-week<N>.json`, holding the previous run's optimal lineup, the
ranked waiver pairs, and a timestamp. **Gitignored** — it contains roster composition and
vendor-derived projections, and `.gitignore` must be extended before the path is first
written. A missing state file means "first run this week": report everything, push nothing,
since a first run has no change to report and should not fire an alert.

## Execution — the waiver queue

CBS processes waivers on a schedule, so a submission is a **queued pair, not a live drop**.
That is the difference that makes execution acceptable: nothing is irreversible at the moment
of submission, and the queue can be reviewed and edited before it processes.

Rules:

1. **Print the COMPLETE resulting queue**, not just what was added. A queue Jeff has not seen
   in full is one he cannot approve.
2. **Verify after submitting** by re-reading the queue from CBS. A click that did not land
   must be an error, never silence.
3. **Never drop a player who is in the current optimal starting lineup** without saying so
   explicitly in the output.

Lineup changes are written the same way, with the same read-back verification.

## Delivery

- **ntfy** sends one line when something changed: *"inactives are out — 2 lineup changes
  worth making."* It is the only piece that must fire unprompted, and it must work when
  nothing else is alive. The existing `linkedin-post-agent` pattern is the reference:
  topic in Keychain, never in the repo; thin body; the detail lives behind the link.
  fantasy-football gets its OWN topic — no coupling between the repos.
- **Dispatch** is the conversation and the execution. Jeff messages it from his phone, it
  spawns a Code session on the mini with the repo and his logged-in browser, and pushes back
  when done or when it needs approval. **Nothing to build for this.**

Scheduling is launchd, matching `linkedin-post-agent/launchd/`. Sessions did not survive the
Desktop app auto-updating on 2026-08-26; launchd jobs and the standalone review server did.
That is measured on this machine, not assumed.

Three runs: **Tuesday** (waivers, before CBS processes), **Saturday** (start/sit),
**Sunday morning** (late scratches). Each run always leaves a trace even when it pushes
nothing, so silence is checkable rather than ambiguous.

## Failure modes that must be handled

| failure | required behaviour |
|---|---|
| Scrape returns an empty roster | Raise. An empty roster optimizes to an empty lineup and would recommend claiming everyone. |
| Weekly projections missing for a rostered player | Name the player and exclude him from optimization. Never score him as 0 — that silently benches him. |
| Projection source column layout shifted | Raise via `expect_columns`. |
| A scheduled run dies | The next run reports the gap. A missed Sunday must not look like a quiet Sunday. |
| CBS write did not take effect | Raise after read-back. Never report success on an unverified write. |

## Testing

- `lineup.py` is pure and gets the most tests: floors enforced, brute-force agreement,
  ties broken deterministically, empty and short rosters, a roster with no eligible RB.
- Scrapers get fixture-based tests against saved HTML/CSV, plus one live smoke test marked
  so it can be skipped offline.
- `waiver.py` is tested against a fake queue; **no test may submit to the real league.**
- Golden-file tests pin the weekly output so a scoring change shows up as a visible diff.
- Follow the existing convention: behaviour pins against **frozen fixtures**, live data gets
  only structural tests that survive growth. See `tests/fixtures/silent_bids_2021_2025.csv`
  and the note above it.

## Sequencing

1. **Spike — prove the three sources.** No modeling. Output is an answer, not code we keep.
2. Explicit lineup slots in the league YAML.
3. `lineup.py` and the optimizer, fully tested, no I/O.
4. `weekly_proj.py`.
5. `roster.py`.
6. `sffl week --start-sit` end to end.
7. `--waivers`.
8. `waiver.py` submission with read-back verification.
9. ntfy + launchd.
10. `--trade`.

Steps 3-6 are buildable against fixtures before the season starts. Steps 1, 5, 7 and 8
cannot be finished until the CBS league site and weekly projections are live.

## Open questions

1. **CBS league URL** — not yet known to the pipeline. Blocks the spike.
2. **Do CBS league weekly projections carry stat lines or only points?** If only points, CBS
   is a cross-check and Draft Sharks is the source of record.
3. **Does the DS Projections export switch to weekly in-season?** If not, weekly stat lines
   must come from the Who to Start tool, which is a per-player UI rather than a bulk export —
   a materially harder scrape.
4. **Should the lost-fumble term be added now that CBS publishes `FL`?** It is a scoring
   change and belongs on its own branch with its own evidence, not folded into this.
