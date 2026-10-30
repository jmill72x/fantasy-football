"""Lift StatsDeck's get_injuries arrays out of a `claude -p` stream-json run.

`ops/fetch_injuries.sh` gives the headless model ONE tool, StatsDeck's
get_injuries, and nothing else: no shell, no file reads, no writes. The model
only makes the call. This module, run by the script, does the copying the
model used to do: it reads the run's `--output-format stream-json` events,
finds the get_injuries result and writes `{"report": [...], "intel": [...]}`.

Why (2026-10-30): get_injuries returns 85 to 140 KB, too big to go back to
the model inline, so Claude Code saves it to a `tool-results/` file and hands
the model a `<persisted-output>` pointer. With no shell the model can't open
that file, and every scheduled fetch from 10-20 to 10-30 had used Bash under
auto mode to do it. Here the script reads the result instead, so the model
needs no shell and writes nothing.

Where the result text is found, in order:

1. the `tool_use_result` field the stream puts on the user event that carries
   the tool_result (sometimes the full text even when the model only saw a
   pointer; sometimes just the pointer again);
2. the file the tool_result points to (`_PERSISTED` has both pointer shapes),
   read only when it sits in a `tool-results/` folder under `results_root`;
3. the tool_result's own content, when it came back inline.

Either way the text is StatsDeck's `{"data": {"report": [...], "intel": [...],
...}}`. Only those two arrays are lifted. No row is renamed, added to,
removed or reshaped: the official/intel split is which array a row is in.

The init event is checked before anything is read: a session that had any
built-in tool (Bash, Read, Write...) or ran in a permissive mode is refused,
so a flag dropped from the script fails the fetch instead of quietly
widening it.

Stdlib only, so the script can run it with nothing but the venv's python.

Usage: python -m sffl.injury_stream <stream.jsonl> <output.json>
           [--results-root DIR]
"""
import json
import os
import re
import sys

TOOL = "mcp__claude_ai_StatsDeck__get_injuries"

# `--permission-mode manual` is reported as "default" in the init event
# (seen 2026-10-30). "manual" is accepted too in case a later CLI reports the
# name it was given. Anything else (auto, acceptEdits, bypassPermissions,
# plan, dontAsk) is refused.
SAFE_PERMISSION_MODES = frozenset(["default", "manual"])

DEFAULT_RESULTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")

# The two ways Claude Code 2.1.310 hands back a result too big to return
# inline (both seen 2026-10-30). Only the pointer's own header is searched,
# never the preview below it, which quotes third-party news text.
#   Over the MCP token limit (the default; what a scheduled run gets):
#     Error: result (84,762 characters across 2,803 lines) exceeds maximum
#     allowed tokens. Output has been saved to <...>/tool-results/<name>.txt.
#     The file is the result's plain text.
#   Under that limit but too big to keep (seen with MAX_MCP_OUTPUT_TOKENS
#   raised):
#     <persisted-output>
#     Output too large (94.1KB). Full output saved to: <...>/tool-results/<id>.json
#     The file is a JSON list of content blocks; the stream also carries the
#     full text in `tool_use_result`.
_PERSISTED = re.compile(
    r"\A\s*(?:<persisted-output>\s*\n[^\n]*?saved to: "
    r"|Error: result \([^)\n]*\) exceeds maximum allowed tokens\. "
    r"Output has been saved to )"
    r"(/\S+?\.(?:json|txt))(?=\.?(?:\s|\Z))")


class StreamError(Exception):
    """The run did not produce a usable get_injuries result."""


def _events(lines):
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise StreamError("stream line %d is not JSON" % number)
        if isinstance(event, dict):
            yield event


def check_init(event):
    """Refuse a session that could do more than call get_injuries."""
    mode = event.get("permissionMode")
    if mode not in SAFE_PERMISSION_MODES:
        raise StreamError("session ran in permission mode %r, not manual" % (mode,))
    tools = event.get("tools")
    if not isinstance(tools, list):
        raise StreamError("init event lists no tools")
    builtins = sorted(t for t in tools if not str(t).startswith("mcp__"))
    if builtins:
        raise StreamError("session had built-in tools: %s" % ", ".join(builtins))
    if TOOL not in tools:
        raise StreamError("session did not have %s" % TOOL)


def _content_blocks(message):
    content = (message or {}).get("content")
    return content if isinstance(content, list) else []


def _first_text(blocks):
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text")
    return None


def _persisted_text(content, results_root):
    match = _PERSISTED.match(content)
    if not match:
        return None
    path = os.path.realpath(match.group(1))
    root = os.path.realpath(results_root)
    if (not path.startswith(root + os.sep)
            or os.path.basename(os.path.dirname(path)) != "tool-results"):
        raise StreamError("persisted result is outside %s" % results_root)
    with open(path) as handle:
        text = handle.read()
    try:
        saved = json.loads(text)
    except ValueError:
        return text
    if isinstance(saved, list):
        return _first_text(saved)
    return text


def _candidate_texts(event, block, results_root):
    """The result text, from each place it can be, most direct first."""
    use_result = event.get("tool_use_result")
    if isinstance(use_result, list):
        yield _first_text(use_result)
    elif isinstance(use_result, str):
        yield use_result
    content = block.get("content")
    if isinstance(content, str):
        persisted = _persisted_text(content, results_root)
        yield persisted if persisted is not None else content
    elif isinstance(content, list):
        yield _first_text(content)


def _arrays(text):
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    report, intel = data.get("report"), data.get("intel")
    if not isinstance(report, list) or not isinstance(intel, list):
        return None
    return {"report": report, "intel": intel}


def extract(lines, results_root=DEFAULT_RESULTS_ROOT):
    """Return {"report": [...], "intel": [...]} from a stream-json run."""
    saw_init = False
    call_ids = set()
    problems = []
    for event in _events(lines):
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            check_init(event)
            saw_init = True
        elif kind == "assistant":
            for block in _content_blocks(event.get("message")):
                if block.get("type") == "tool_use" and block.get("name") == TOOL:
                    call_ids.add(block.get("id"))
        elif kind == "user":
            for block in _content_blocks(event.get("message")):
                if (block.get("type") != "tool_result"
                        or block.get("tool_use_id") not in call_ids):
                    continue
                if not saw_init:
                    raise StreamError("tool result before the init event")
                if block.get("is_error"):
                    problems.append("get_injuries returned an error")
                    continue
                for text in _candidate_texts(event, block, results_root):
                    found = _arrays(text)
                    if found is not None:
                        return found
                problems.append("get_injuries result has no data.report/data.intel")
    if not saw_init:
        raise StreamError("stream has no init event")
    if not call_ids:
        raise StreamError("the model never called %s" % TOOL)
    raise StreamError("; ".join(problems) or "no result for the get_injuries call")


def write_atomically(found, out_path):
    tmp = out_path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(found, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, out_path)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    results_root = DEFAULT_RESULTS_ROOT
    if "--results-root" in args:
        at = args.index("--results-root")
        results_root = args[at + 1]
        del args[at:at + 2]
    if len(args) != 2:
        print("usage: python -m sffl.injury_stream <stream.jsonl> <output.json>"
              " [--results-root DIR]", file=sys.stderr)
        return 2
    stream_path, out_path = args
    try:
        with open(stream_path) as handle:
            found = extract(handle, results_root)
    except (StreamError, OSError, ValueError) as exc:
        print("fetch_injuries: %s" % exc, file=sys.stderr)
        return 1
    write_atomically(found, out_path)
    print("fetch_injuries: %d report rows, %d intel rows"
          % (len(found["report"]), len(found["intel"])), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
