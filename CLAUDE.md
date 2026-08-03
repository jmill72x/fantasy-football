# fantasy-football

Auction cheatsheet pipeline for the STRIPES Fantasy Football League on CBS.

**Read `NEXT.md` first.** It carries the current state, what to work on next, and the
facts you must not re-derive.

## Non-negotiables

- **This repo is public.** `data/extracts/` (licensed vendor projections) and
  `data/weekly/` (CBS stat lines) are gitignored. Never commit a file from either, and
  extend `.gitignore` before adding any new data path.
- **The scoring engine in `src/sffl/scoring.py` is validated against ~250 real CBS
  weekly observations.** Do not modify it without new ground-truth evidence.
- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not
  pip-installed, so ad-hoc scripts need `PYTHONPATH=src`.
- **Never validate current scoring against pre-2025 data.** The league's rules changed
  between 2024 and 2025.

## Layout

| Path | What |
|---|---|
| `leagues/sffl/2026.yaml` | Every scoring band and roster rule, versioned per season |
| `sources/*.yaml` | One profile per vendor — adding a vendor should cost no Python |
| `identity/aliases.yaml` | Player-name fixes; grows every year |
| `src/sffl/` | league, scoring, schema, identity, ingest, tqb, pool, cli |
| `poc/` | Validation scripts, each carrying the real CBS data it checks against |
| `docs/superpowers/specs/` | Design spec — league rules, findings, open questions |
| `docs/superpowers/plans/` | Implementation plans |
