#!/bin/bash
# launchd entry point. One argument: tuesday | friday | sunday. After the
# alert it runs the weekly data collection (`sffl collect`, see the block at
# the end), except on a dry run.
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
# NOT `set -e`: the injury fetch (`sffl injuries-fetch`) is allowed to fail
# without taking the whole alert down - see the comment at the fetch below.
# A bare `set -e` would abort the script the instant that command returned
# non-zero, before the `|| echo ... continuing` fallback ever got a chance to
# run. `set -uo pipefail` still catches unset-variable typos and pipe
# failures elsewhere without that trap.
set -uo pipefail

KIND="${1:?usage: run_alert.sh tuesday|friday|sunday [--dry-run]}"

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

# A DATED LINE AT EACH END OF EVERY RUN (2026-11-11). launchd appends every
# run to logs/alert-<kind>.log (stdout) and .err (stderr) with no date of its
# own, and on 10-30 an August block was read as that day's. Both files now
# get "=== run_alert <kind> (live|dry run) started <date> ===" first and
# "... finished, exit <n> <date> ===" last: `grep -n '^=== run_alert'
# logs/alert-friday.log` lists every run, and today's block is below the
# last "started". The "finished" line comes from an EXIT trap (2026-11-12),
# so a `set -u` abort or an early exit still closes the block with its real
# exit code. A TERM, INT or HUP logs "finished, killed by SIG<name>" and then
# re-raises the signal, so the script still dies by it and launchd records the
# same status as before. Bash acts on a signal only once the command in the
# foreground returns, and nothing can log a SIGKILL.
if [ -n "$DRY_RUN_FLAG" ]; then RUN_MODE="dry run"; else RUN_MODE="live"; fi
run_stamp() {
    local line="=== run_alert $KIND ($RUN_MODE) $1 $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
    echo "$line"
    echo "$line" >&2
}
on_exit() {
    local rc=$?
    run_stamp "finished, exit $rc"
    exit "$rc"
}
on_signal() {
    trap - EXIT "$1"
    run_stamp "finished, killed by SIG$1"
    kill -s "$1" $$
}
trap on_exit EXIT
trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP
run_stamp started

# THE INJURY FEED. Since the StatsDeck switch the alert's injuries come from
# `sffl injuries-fetch` (nflverse, Sleeper and ESPN's public feed; see
# docs/plans/2026-10-20-replace-statsdeck.md), and CBS's own designations from
# the capture (`--cbs-designations`). THE ROLLBACK is the one line below: set
# it to "statsdeck" and the next run uses ops/fetch_injuries.sh again (a
# headless `claude -p` session with StatsDeck's get_injuries only). That
# script stays in the tree for a week after the switch, then goes with
# StatsDeck (plan section 10). SFFL_INJURY_FEED in the environment overrides
# it for a test or a rehearsal; launchd sets nothing.
INJURY_FEED="${SFFL_INJURY_FEED:-direct}"

# CBS's designations (Q/D/O/IR/PUP/SUSP from the pages' icons). Its own
# rollback, independent of the feed: set SFFL_CBS_DESIGNATIONS's default to 0.
# A plain scalar, used unquoted like DRY_RUN_FLAG above, for the same reason.
CBS_DESIGNATIONS_FLAG=""
if [ "${SFFL_CBS_DESIGNATIONS:-1}" = "1" ]; then
    CBS_DESIGNATIONS_FLAG="--cbs-designations"
fi

# The direct fetch gets a hard limit, enforced by killing it: each request has
# its own timeouts, but a stuck run must never hold the digest. The mini has
# no `timeout` binary, so perl's alarm does it (SIGALRM survives the exec and
# kills the Python process; exit 142). 300 s against a normal run of seconds.
FETCH_TIMEOUT_S="${SFFL_INJURY_FETCH_TIMEOUT_S:-300}"

# Only the rollback path needs the `claude` CLI. PATH under launchd is
# minimal (no ~/.local/bin), so resolve it explicitly. Verified on this
# machine with `command -v claude`.
export CLAUDE_BIN="${CLAUDE_BIN:-/Users/jeff/.local/bin/claude}"
export PATH="$(dirname "$CLAUDE_BIN"):$PATH"

# THE SEASON'S WEEK-1 DATE: NFL week 1 of the 2026 season begins Wed
# 2026-09-09. Season-bound - set it to the new season's Wednesday every year
# (docs/operations/preseason-runbook.md, step 13). `sffl alert --week1`
# checks it against today's season, and last season's date opens the digest
# with a STALE SEASON VALUES banner and makes the run exit non-zero.
WEEK1="2026-09-09"

WEEK=$(./.venv/bin/python -c "
import datetime, sys
# Weeks run Wednesday to Tuesday from WEEK1. Clamp to a minimum
# of 1 so a run before the season starts (a pre-season dry-run, or a job
# firing while testing this script) never computes zero or negative, and
# to a maximum of 18 - the last week of the NFL regular season - so a bug
# in this arithmetic late in the year (or a run long after the season
# ends) can't ask CBS for a week that doesn't exist.
start = datetime.date.fromisoformat(sys.argv[1])
week = (datetime.date.today() - start).days // 7 + 1
print(min(18, max(1, week)))
" "$WEEK1")

# The injury fetch is allowed to fail without taking the alert with it: a
# digest carrying the lineup but no news is far better than no digest at
# all. A missing --injuries file is NOT rendered as a quiet week -
# `sffl.cli._cmd_alert` notices the file doesn't exist, states that
# explicitly in the pushed message body ("... the injury fetch step ...
# did not produce a file"), and marks the run DEGRADED, so `sffl alert`
# still composes and pushes the digest but exits non-zero. `set -e` is
# deliberately NOT set above so this `||` fallback actually runs instead of
# the script aborting first - the script must survive a failed fetch long
# enough to hand the missing file off to `sffl alert`, which is what
# actually reports it (both in the pushed body and in the exit code).
# When this run started, in epoch seconds. `sffl collect` (below) keeps only
# the captures written at or after it, so a page left over from an earlier
# run - one that failed to refresh this time - is never filed under this week.
RUN_START=$(date +%s)

INJ="data/captures/injuries-${KIND}.json"
# Removed before fetching, whichever feed runs: a failed fetch must never leave
# an earlier run's file to be read as today's news. It also clears the last
# StatsDeck-shaped file at the switch, which `injuries-fetch` would refuse to
# replace (it only replaces its own earlier output).
rm -f "$INJ" "$INJ.tmp"
if [ "$INJURY_FEED" = "statsdeck" ]; then
    ops/fetch_injuries.sh "$INJ" || echo "WARN: injury fetch failed; continuing" >&2
else
    # A dry run fetches as `--kind manual`: it never reads or writes the
    # scheduled change state, caches on its own, and leaves ESPN out (its
    # one call per 12 hours is the scheduled runs').
    if [ -n "$DRY_RUN_FLAG" ]; then
        FETCH_KIND="manual"
    else
        FETCH_KIND="$KIND"
    fi
    /usr/bin/perl -e 'alarm shift @ARGV; exec @ARGV or die "exec: $!\n"' \
        "$FETCH_TIMEOUT_S" \
        env PYTHONPATH=src ./.venv/bin/python -m sffl.cli injuries-fetch \
        --kind "$FETCH_KIND" \
        --out "$INJ" \
        --allow-live-path
    FETCH_RC=$?
    if [ "$FETCH_RC" -ne 0 ]; then
        rm -f "$INJ" "$INJ.tmp"
        if [ "$FETCH_RC" -eq 142 ]; then
            echo "WARN: injury fetch killed after ${FETCH_TIMEOUT_S}s; continuing" >&2
        else
            echo "WARN: injury fetch failed (exit $FETCH_RC); continuing" >&2
        fi
    fi
fi

# --team-url and --projections-url are NOT passed here: `sffl alert`
# defaults --team-url to bare /teams (CBS resolves it to whoever is
# logged in) and builds --projections-url from --week itself. Passing
# either here would duplicate URL construction that already lives in
# src/sffl/cli.py, with the two copies free to drift apart.
PYTHONPATH=src ./.venv/bin/python -m sffl.cli alert \
  --kind "$KIND" \
  --week "$WEEK" \
  --week1 "$WEEK1" \
  --curves calibration/2025.yaml \
  --injuries "$INJ" \
  $CBS_DESIGNATIONS_FLAG \
  $DRY_RUN_FLAG
  # ^ deliberately unquoted (both flags): DRY_RUN_FLAG is either "" (contributes zero
  # words - the empty-string default case) or the single word "--dry-run"
  # (no embedded whitespace/glob chars to mis-split), so this is safe. Do
  # not "fix" this by quoting it - quoting would pass a single empty-string
  # argument to argparse on the no-flag path instead of omitting the flag.
ALERT_RC=$?

# WEEKLY DATA COLLECTION - after the digest has gone out, so it can never stop
# or delay it, and never on a dry run (a rehearsal's captures are not a
# week's record). `sffl collect` copies this run's pages, plus CBS's actual
# results for the week just played, into dated, never-overwritten folders in
# the local archive, on the Pi and in the private data repo, then commits and
# pushes that repo (Jeff's standing OK, 2026-10-19: that repo and these
# commits only). Results: Tuesday takes the week just played (first final
# numbers), Friday takes it again after CBS's stat corrections, Sunday none.
# A failure is printed, pushed as a short note (--notify) and makes this
# script exit non-zero, so launchd's status shows it; the alert's own
# failure, if any, wins the exit code.
COLLECT_RC=0
if [ -z "$DRY_RUN_FLAG" ]; then
    case "$KIND" in
        tuesday) RESULTS_WEEK="$WEEK" ;;
        friday)  RESULTS_WEEK=$((WEEK - 1)) ;;
        *)       RESULTS_WEEK=0 ;;
    esac
    PYTHONPATH=src ./.venv/bin/python -m sffl.cli collect \
      --kind "$KIND" \
      --week "$WEEK" \
      --since "$RUN_START" \
      --results-week "$RESULTS_WEEK" \
      --notify
    COLLECT_RC=$?
    if [ "$COLLECT_RC" -ne 0 ]; then
        echo "ERROR: weekly data collection failed (exit $COLLECT_RC); the alert itself already ran" >&2
    fi
else
    echo "dry run: weekly data collection skipped"
fi

# The alert's own failure wins the exit code; collection's counts only when
# the alert succeeded.
RC="$ALERT_RC"
if [ "$RC" -eq 0 ]; then
    RC="$COLLECT_RC"
fi
# The EXIT trap (top) logs the "finished" line.
exit "$RC"
