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

test -s "$OUT" || { echo "fetch_injuries: ${OUT} was not written" >&2; exit 1; }
