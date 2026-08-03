# fantasy-football

Builds custom auction cheatsheets — a dense Excel sheet for two-sided printing, and a
scrolling PDF sized for markup on an iPad with an Apple Pencil — for a fantasy football
league whose rules no commercial tool can represent.

## Why this exists

The league drafts by **offline auction**. Results are entered into CBS afterward, so no
draft app can sync live and every ranking product has to be reduced to a static artifact
before draft day. On top of that, three league rules put it outside what any vendor
models:

- **Team QB.** You draft an NFL franchise's entire quarterback room as one unit. There
  are 32 draftable Team QBs, not ~40 quarterbacks.
- **WR and TE are the same position**, competing for five flexible lineup slots.
- **Scoring is banded, not per-unit.** Receiving yards pay 1 point at 50–74 and 7 at
  200+, with **nothing below 50**. Receptions score nothing below 5. A large share of
  real weekly stat lines score zero.

That last one matters most. Every projection service models scoring as points-per-yard
with threshold bonuses, which cannot express a band table. Feed this league generic
rankings and they are wrong at every position.

So the pipeline takes a vendor's **raw statistical projections** — yards, receptions,
completions, touchdowns — and applies the league's actual scoring itself.

## Status

| | |
|---|---|
| Scoring engine + ingest | ✅ working, 64 tests |
| Value engine (VORP → dollars) | planned |
| Excel + PDF renderers | planned |
| Silent auction planner | planned |

## The scoring engine is validated, not assumed

Transcribing a scoring table from a settings page and hoping is how you get a
confidently wrong draft board. Instead, **44 of 45 scoring bands are verified against
roughly 250 real weekly stat lines**, each compared to the points the platform itself
awarded.

That process found things the settings page never states:

- There is **no fumble-lost penalty**, no penalty for a missed extra point, and none for
  a missed 50+ yard field goal.
- Touchdowns are **not symmetric across positions** — a goal-line rushing touchdown
  scores 3 where a short receiving touchdown scores 5.
- The platform's own historical data contains at least one **arithmetic error**, caught
  because a game fit no legal combination of scoring rules and then refuted by two
  independent games.
- The league's rules **changed between 2024 and 2025**, so prior seasons cannot validate
  current values. The league profile is versioned per season for exactly this reason.

The one unproven band is 250+ rushing yards. No game in the sample reached it — the
season high was 244.

## Design

The repository is meant to outlive any one subscription, so which service is used is a
configuration choice rather than an architectural one.

- **`leagues/<league>/<year>.yaml`** holds every scoring band and roster rule as data.
- **`sources/*.yaml`** describes a vendor's export — column mapping, file globs,
  capability flags. Adding a second vendor with a completely different file shape (name
  keyed instead of positional, 18 stacked analyst sets, defensive players to filter) cost
  **one YAML file and zero lines of Python**.
- **Identity resolution** is normalization, then a hand-maintained alias file, then fuzzy
  matching with a review queue. Unmatched players are reported loudly — a silently
  dropped player is a disaster discovered mid-draft.
- **Team QB units are constructed** by aggregating a franchise's quarterbacks, so no
  vendor needs to support the slot.

## Running it

Python 3.9+, no services required.

```bash
python3 -m venv .venv
./.venv/bin/pip install pytest PyYAML rapidfuzz
./.venv/bin/pytest

PYTHONPATH=src ./.venv/bin/python -m sffl.cli ingest \
  --source sources/draftsharks.yaml \
  --file "data/extracts/<vendor>/<year>/<export>.csv" --year 2026
```

Prints a scored, league-correct player pool: individual quarterbacks removed, Team QB
units added, everything valued under the league's own scoring.

## Layout

| Path | |
|---|---|
| `src/sffl/` | league profile, scoring, schema, identity, ingest, TQB, pool, CLI |
| `leagues/` | scoring bands and roster rules, versioned per season |
| `sources/` | one profile per vendor |
| `identity/aliases.yaml` | player-name fixes; grows every year |
| `poc/` | validation scripts, each carrying the real data it checks against |
| `docs/superpowers/specs/` | design spec — rules, findings, open questions |
| `docs/superpowers/plans/` | implementation plans |
| `NEXT.md` | current state and what to do next |

## A note on data

**Projection exports are not in this repository.** They are paid, licensed content and
`data/extracts/` is gitignored. Weekly stat lines pulled from the league platform are
likewise excluded. The league's own auction history — bids and prices — is included,
since it belongs to the league.

Bring your own exports and write a ~20-line source profile. That is the point of the
design.

## License

Personal project, shared in case the approach is useful. No warranty, and definitely no
guarantee it wins you your league.
