#!/bin/bash
# The ONE StatsDeck call in this pipeline.
#
# Claude is a transport here, not an author: it writes raw JSON and composes
# nothing. Every word that reaches the phone is built by src/sffl/alert.py,
# which is pure and unit-tested. A model that both fetched and phrased the
# message could quietly reword a designation, and nothing downstream would
# catch it.
#
# StatsDeck's get_injuries returns a `data` object holding two arrays:
# `report` (the official nflverse injury report) and `intel` (dated
# news/intel). The official/intel distinction is WHICH ARRAY a row is in,
# not a field on the row - a row's own "source" field is an outlet name
# (e.g. "sleeper_feed"), never the word "official". So this script only
# lifts those two arrays out of the `data` wrapper; it must not rename,
# add, remove, or reshape any field within a row.
#
# Usage: ops/fetch_injuries.sh <output.json>
set -euo pipefail

OUT="${1:?usage: fetch_injuries.sh <output.json>}"

# REMOVE THE OLD FILE BEFORE FETCHING. `claude` can exit 0 without writing
# anything - a denied tool, a refusal, a model that answers in prose - and
# the `test -s` check at the bottom would then pass against LAST RUN'S FILE,
# reporting success while the alert renders a previous week's injury news as
# today's. The file must not survive a failed fetch: no file at all is a
# state `sffl alert` reports loudly in the message body, whereas a stale one
# is a confident wrong answer. `rm -f` so a first run (nothing to remove) is
# not an error under `set -e`.
rm -f "$OUT"

claude -p "Call the StatsDeck get_injuries tool with no player filter. Its \
result has a data object containing two arrays: report (the official \
injury report) and intel (dated news/intel). Write a JSON object of the \
form {\"report\": [...], \"intel\": [...]} to ${OUT}, copying every row of \
each array exactly as returned - do not rename, add, remove, or reshape \
any field within a row, and do not summarise, rank, interpret, corroborate, \
or drop any row from either array. If an array is empty, write it as an \
empty array. Do not include any fantasy points field. Output nothing to \
stdout except the word DONE." \
  --allowedTools "mcp__claude_ai_StatsDeck__get_injuries,Write" \
  >/dev/null

# Now a real check rather than one the previous run could satisfy: the file
# was removed above, so anything here was written by THIS invocation. Remove
# an empty or partial write too, for the same reason - a zero-byte file
# would be a file that exists and parses to nothing.
if [ ! -s "$OUT" ]; then
    rm -f "$OUT"
    echo "fetch_injuries: ${OUT} was not written" >&2
    exit 1
fi

# It must also be the JSON shape sffl.injuries.load expects. `claude` can
# answer in prose, or write a truncated file, and "the file exists" is
# exactly the assumption that let a bad fetch through before. A file that
# fails this is removed, not left behind: same reasoning as the rm above.
# The interpreter is resolved from THIS script's location, not the caller's
# working directory, so the check does not depend on where it was invoked.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
"$REPO/.venv/bin/python" - "$OUT" <<'PY' || { rm -f "$OUT"; exit 1; }
import json
import sys

path = sys.argv[1]
try:
    raw = json.load(open(path))
except ValueError as exc:
    sys.exit("fetch_injuries: %s is not valid JSON (%s)" % (path, exc))
if not isinstance(raw, dict) or "report" not in raw or "intel" not in raw:
    sys.exit('fetch_injuries: %s is not {"report": [...], "intel": [...]}'
             % path)
PY
