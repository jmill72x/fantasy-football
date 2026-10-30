"""ops/fetch_injuries.sh: the headless session gets get_injuries and nothing else.

Since 2026-10-30 (Jeff's option (a)) the `claude -p` session the injury fetch
starts has no shell, no file tools and no auto mode; the script parses the
result itself. These tests run the real script with CLAUDE_BIN pointed at a
stub that records its arguments and prints a synthetic stream
(tests/fixtures/injury_stream.jsonl), so no real session ever starts.
"""
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "ops" / "fetch_injuries.sh"
FIXTURE = REPO / "tests" / "fixtures" / "injury_stream.jsonl"
TOOL = "mcp__claude_ai_StatsDeck__get_injuries"

STUB = """#!/bin/bash
printf '%s\\0' "$@" > "{args}"
{body}
"""


def _run(tmp_path, body):
    args_file = tmp_path / "args.bin"
    stub = tmp_path / "claude-stub"
    stub.write_text(STUB.format(args=args_file, body=body))
    stub.chmod(0o755)
    out = tmp_path / "injuries.json"
    env = dict(os.environ, CLAUDE_BIN=str(stub))
    proc = subprocess.run(["/bin/bash", str(SCRIPT), str(out)], cwd=str(tmp_path),
                          env=env, capture_output=True, text=True, timeout=60)
    args = None
    if args_file.exists():
        args = args_file.read_bytes().split(b"\0")[:-1]
        args = [a.decode() for a in args]
    return proc, out, args


def _flag(args, name):
    """The value after `name`; the flag must appear exactly once."""
    assert args.count(name) == 1, "%s appears %d times" % (name, args.count(name))
    return args[args.index(name) + 1]


def test_session_gets_only_get_injuries_no_shell_no_writes_manual_mode(tmp_path):
    proc, out, args = _run(tmp_path, 'cat "%s"' % FIXTURE)
    assert proc.returncode == 0, proc.stderr
    assert args[0] == "-p"

    # No built-in tools at all: an empty --tools list, not a list of names.
    assert _flag(args, "--tools") == ""
    # Exactly one tool runs without a prompt, and it is get_injuries.
    assert _flag(args, "--allowedTools") == TOOL
    # Manual permission mode, never auto; only the user's own settings.
    assert _flag(args, "--permission-mode") == "manual"
    assert _flag(args, "--setting-sources") == "user"
    assert _flag(args, "--output-format") == "stream-json"
    assert "--verbose" in args

    flags_only = [a for a in args[2:] if a.startswith("--")]
    for banned in ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                   "--add-dir", "--strict-mcp-config", "--disallowedTools",
                   "--mcp-config", "--settings"):
        assert banned not in flags_only, banned
    # Nothing in the arguments hands the session a shell or a file tool.
    for word in ("Bash", "Write", "Edit", "Read", "NotebookEdit", "auto", "bypassPermissions"):
        assert all(word not in a for a in args[2:]), word


def test_script_writes_the_two_arrays_from_the_stream(tmp_path):
    proc, out, _ = _run(tmp_path, 'cat "%s"' % FIXTURE)
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text())
    assert set(written) == {"report", "intel"}
    assert [r["player"] for r in written["report"]] == ["Testy McFixture", "Placeholder Jones"]
    assert len(written["intel"]) == 1
    assert "2 report rows, 1 intel rows" in proc.stderr


def test_failed_session_leaves_no_file_not_even_last_runs(tmp_path):
    stale = tmp_path / "injuries.json"
    stale.write_text('{"report": [], "intel": []}')
    proc, out, _ = _run(tmp_path, "exit 1")
    assert proc.returncode != 0
    assert not out.exists()


def test_session_that_answers_without_calling_the_tool_leaves_no_file(tmp_path):
    body = "echo '%s'" % json.dumps({
        "type": "system", "subtype": "init", "permissionMode": "default", "tools": [TOOL]})
    proc, out, _ = _run(tmp_path, body)
    assert proc.returncode != 0
    assert not out.exists()
    assert not Path(str(out) + ".tmp").exists()
    assert "never called" in proc.stderr


def test_session_with_a_shell_is_refused_even_if_it_fetched(tmp_path):
    lines = FIXTURE.read_text().splitlines()
    init = json.loads(lines[0])
    init["tools"] = ["Bash"] + init["tools"]
    widened = tmp_path / "widened.jsonl"
    widened.write_text("\n".join([json.dumps(init)] + lines[1:]) + "\n")
    proc, out, _ = _run(tmp_path, 'cat "%s"' % widened)
    assert proc.returncode != 0
    assert not out.exists()
    assert "Bash" in proc.stderr
