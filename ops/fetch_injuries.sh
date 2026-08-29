#!/bin/bash
# The ONE StatsDeck call in this pipeline.
#
# Claude is a transport here, not an author: it writes raw JSON and composes
# nothing. Every word that reaches the phone is built by src/sffl/alert.py,
# which is pure and unit-tested. A model that both fetched and phrased the
# message could quietly reword a designation, and nothing downstream would
# catch it.
#
# Usage: ops/fetch_injuries.sh <output.json>
set -euo pipefail

OUT="${1:?usage: fetch_injuries.sh <output.json>}"

claude -p "Call the StatsDeck get_injuries tool with no player filter. Write \
its result to ${OUT} as a single JSON object of the form {\"injuries\": [...]}, \
one array entry per reported player, each with the keys: player, team, status, \
practice, reported_date, detail, source. Set source to \"official\" for rows \
from the official injury report and \"intel\" for rows from the news/intel \
feed. Do not summarise, rank, interpret, or drop any row. Do not include any \
fantasy points field. Output nothing to stdout except the word DONE." \
  --allowedTools "mcp__claude_ai_StatsDeck__get_injuries,Write" \
  >/dev/null

test -s "$OUT" || { echo "fetch_injuries: ${OUT} was not written" >&2; exit 1; }
