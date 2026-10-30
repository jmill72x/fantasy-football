#!/bin/bash
# The ONE StatsDeck call in this pipeline.
#
# Claude is a transport here, not an author, and since 2026-10-30 not even a
# copier: the headless session gets exactly one tool, StatsDeck's
# get_injuries, and no shell, no file reads and no writes. It makes the call
# and stops. This script then lifts the result out of the session's
# stream-json output itself (src/sffl/injury_stream.py, stdlib only, unit
# tested). Every word that reaches the phone is still built by
# src/sffl/alert.py.
#
# Why the redesign (Jeff's option (a), 10-30): get_injuries returns 85 to
# 140 KB, which Claude Code saves to a tool-results file instead of handing
# back to the model. The old script asked the model to copy it with Write,
# and from 10-20 the session quietly used Bash under auto mode to read that
# file, in a public repo, while reading third-party news text. Locking the
# flags down without changing the design wrote no file at all.
#
# The flags, and what each one is for (tests/test_fetch_injuries.py checks
# them, and injury_stream refuses a session whose init event shows any
# built-in tool or a permissive mode):
#   --tools ""                 no built-in tools at all: no Bash, Read, Write
#   --allowedTools <get_injuries only>
#                              the one tool that runs without a prompt
#   --permission-mode manual   never auto: anything else is denied (headless,
#                              nobody can approve)
#   --setting-sources user     ignore this repo's project/local settings
#   --output-format stream-json --verbose
#                              the events this script parses
# No --strict-mcp-config: StatsDeck is a claude.ai connector, which that
# flag would drop.
#
# StatsDeck's get_injuries returns a `data` object holding two arrays:
# `report` (the official nflverse injury report) and `intel` (dated
# news/intel). The official/intel distinction is WHICH ARRAY a row is in,
# not a field on the row - a row's own "source" field is an outlet name
# (e.g. "sleeper_feed"), never the word "official". So only those two arrays
# are lifted out of the `data` wrapper; no field within a row is renamed,
# added, removed or reshaped.
#
# Usage: ops/fetch_injuries.sh <output.json>
set -euo pipefail

OUT="${1:?usage: fetch_injuries.sh <output.json>}"

# REMOVE THE OLD FILE BEFORE FETCHING. A failed fetch must not leave last
# run's file behind for `sffl alert` to render as today's news: no file at
# all is a state `sffl alert` reports loudly in the message body, whereas a
# stale one is a confident wrong answer. `rm -f` so a first run (nothing to
# remove) is not an error under `set -e`.
rm -f "$OUT"

# Resolved from THIS script's location, not the caller's working directory.
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# The raw stream holds the whole result; it lives only for this run.
STREAM="$(mktemp -t sffl-injuries)"
trap 'rm -f "$STREAM"' EXIT

# CLAUDE_BIN, when set, is the exact binary to run - not just a directory to
# put on PATH. On 2026-10-19 a rehearsal passed CLAUDE_BIN=<stub named
# claude-stub>; run_alert.sh only put the stub's folder on PATH, a bare
# `claude` here still found the real one, and a real `claude -p` session ran.
# Unset (the scheduled runs), this is the same `claude` run_alert.sh resolved.
"${CLAUDE_BIN:-claude}" -p "Call the StatsDeck get_injuries tool once, with \
no arguments. Do not call any other tool. Then reply with the single word \
DONE." \
  --tools "" \
  --allowedTools "mcp__claude_ai_StatsDeck__get_injuries" \
  --permission-mode manual \
  --setting-sources user \
  --output-format stream-json \
  --verbose \
  >"$STREAM"

# The parser writes OUT only from a get_injuries result it found, with both
# arrays present, via a temp file and a rename, so a partial file is never
# left at OUT. On any failure, make sure nothing is there.
if ! PYTHONPATH="$REPO/src" "$REPO/.venv/bin/python" -m sffl.injury_stream \
        "$STREAM" "$OUT"; then
    rm -f "$OUT" "$OUT.tmp"
    exit 1
fi

if [ ! -s "$OUT" ]; then
    rm -f "$OUT"
    echo "fetch_injuries: ${OUT} was not written" >&2
    exit 1
fi
