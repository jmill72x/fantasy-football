#!/bin/bash
# launchd entry point. One argument: friday | sunday.
# Optional second argument (or DRY_RUN=1 in the environment): rehearse the
# exact scheduled command with `--dry-run`, so a human can verify a run
# without editing this file. `ops/run_alert.sh friday --dry-run` and
# `DRY_RUN=1 ops/run_alert.sh friday` are equivalent.
#
# Runs from the repo root regardless of how launchd invokes it, because
# every default path in `sffl alert` is repo-relative (data/captures,
# data/browser-profile, the league YAML). `cd` happens before anything else
# reads a relative path, and WorkingDirectory in the plist is belt-and-braces
# for the same reason.
#
# NOT `set -e`: the injury fetch (ops/fetch_injuries.sh) is allowed to fail
# without taking the whole alert down - see the comment at the fetch below.
# A bare `set -e` would abort the script the instant that command returned
# non-zero, before the `|| echo ... continuing` fallback ever got a chance to
# run. `set -uo pipefail` still catches unset-variable typos and pipe
# failures elsewhere without that trap.
set -uo pipefail

KIND="${1:?usage: run_alert.sh friday|sunday [--dry-run]}"

# A plain scalar, not an array: `/bin/bash` on macOS is 3.2.57 (Apple ships
# no newer bash for licensing reasons - GPLv3 - and the shebang below pins
# this script to it regardless of what's on $PATH). In bash <4.4, expanding
# an EMPTY array as "${ARR[@]}" under `set -u` raises "unbound variable" -
# only a non-empty array is safe. `--dry-run` has no whitespace to split on,
# so a scalar sidesteps the whole hazard instead of requiring the
# "${ARR[@]+"${ARR[@]}"}" bash-3.2-safe expansion idiom. Do not change this
# back to an array without that guard - the failure only shows up on the
# no-flag path (the one with nothing to expand), which is exactly the path
# launchd uses every scheduled run, and dry-run rehearsal never exercises it.
DRY_RUN_FLAG=""
if [ "${2:-}" = "--dry-run" ] || [ "${DRY_RUN:-0}" = "1" ]; then
    DRY_RUN_FLAG="--dry-run"
fi

cd "$(dirname "$0")/.."
mkdir -p logs data/captures

# PATH under launchd is minimal (no ~/.local/bin, no interactive-shell
# additions), and ops/fetch_injuries.sh below shells out to the `claude` CLI.
# Resolve it explicitly rather than depending on however this script happens
# to be invoked. Verified on this machine with `command -v claude`.
CLAUDE_BIN="${CLAUDE_BIN:-/Users/jeff/.local/bin/claude}"
export PATH="$(dirname "$CLAUDE_BIN"):$PATH"

WEEK=$(./.venv/bin/python -c "
import datetime
# NFL week 1 of the 2026 season begins Wed 2026-09-09. Clamp to a minimum
# of 1 so a run before the season starts (a pre-season dry-run, or a job
# firing while testing this script) never computes zero or negative, and
# to a maximum of 18 - the last week of the NFL regular season - so a bug
# in this arithmetic late in the year (or a run long after the season
# ends) can't ask CBS for a week that doesn't exist.
start = datetime.date(2026, 9, 9)
week = (datetime.date.today() - start).days // 7 + 1
print(min(18, max(1, week)))
")

# The injury fetch is allowed to fail without taking the alert with it: a
# digest carrying the lineup but no news is far better than no digest at
# all. A missing --injuries file is NOT rendered as a quiet week -
# `sffl.cli._cmd_alert` notices the file doesn't exist, states that
# explicitly in the pushed message body ("... the StatsDeck fetch step ...
# did not produce a file"), and marks the run DEGRADED, so `sffl alert`
# still composes and pushes the digest but exits non-zero. `set -e` is
# deliberately NOT set above so this `||` fallback actually runs instead of
# the script aborting first - the script must survive a failed fetch long
# enough to hand the missing file off to `sffl alert`, which is what
# actually reports it (both in the pushed body and in the exit code).
INJ="data/captures/injuries-${KIND}.json"
ops/fetch_injuries.sh "$INJ" || echo "WARN: injury fetch failed; continuing" >&2

# --team-url and --projections-url are NOT passed here: `sffl alert`
# defaults --team-url to bare /teams (CBS resolves it to whoever is
# logged in) and builds --projections-url from --week itself. Passing
# either here would duplicate URL construction that already lives in
# src/sffl/cli.py, with the two copies free to drift apart.
PYTHONPATH=src ./.venv/bin/python -m sffl.cli alert \
  --kind "$KIND" \
  --week "$WEEK" \
  --curves calibration/2025.yaml \
  --injuries "$INJ" \
  $DRY_RUN_FLAG
  # ^ deliberately unquoted: DRY_RUN_FLAG is either "" (contributes zero
  # words - the empty-string default case) or the single word "--dry-run"
  # (no embedded whitespace/glob chars to mis-split), so this is safe. Do
  # not "fix" this by quoting it - quoting would pass a single empty-string
  # argument to argparse on the no-flag path instead of omitting the flag.
