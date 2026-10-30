"""sffl.injury_stream: lifting get_injuries out of a stream-json run.

All data here is synthetic (tests/fixtures/injury_stream.jsonl and rows built
below): no real StatsDeck result is committed.
"""
import json
from pathlib import Path

import pytest

from sffl import injury_stream as ist

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "injury_stream.jsonl"


def _events():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def _lines(events):
    return [json.dumps(e) for e in events]


def _payload(events):
    return json.loads(events[2]["tool_use_result"][0]["text"])


def test_inline_result_rows_are_copied_exactly():
    events = _events()
    found = ist.extract(_lines(events))
    data = _payload(events)["data"]
    assert found == {"report": data["report"], "intel": data["intel"]}
    # Not reshaped: same keys, same order, None kept as None.
    assert list(found["report"][0]) == list(data["report"][0])
    assert found["report"][0]["secondary"] is None


def _persist(events, tmp_path, where="proj/session/tool-results"):
    """Turn the fixture into the shape a too-large result takes."""
    folder = tmp_path / where
    folder.mkdir(parents=True)
    saved = folder / "toolu_SYNTHETIC0001.json"
    text = events[2]["tool_use_result"][0]["text"]
    saved.write_text(json.dumps([{"type": "text", "text": text}]))
    events[2]["message"]["content"][0]["content"] = (
        "<persisted-output>\nOutput too large (94.1KB). Full output saved to: %s\n\n"
        "Preview (first 2KB):\n{\"success\": true, ...\n...\n</persisted-output>" % saved)
    del events[2]["tool_use_result"]
    return events


def test_persisted_result_is_read_from_the_tool_results_file(tmp_path):
    events = _persist(_events(), tmp_path)
    found = ist.extract(_lines(events), results_root=str(tmp_path))
    assert found == {k: _payload(_events())["data"][k] for k in ("report", "intel")}


def _over_mcp_limit(events, tmp_path, where="proj/session/tool-results"):
    """The default shape (2.1.310): over the MCP token limit, saved as plain
    text, and `tool_use_result` holds only the pointer again."""
    folder = tmp_path / where
    folder.mkdir(parents=True)
    saved = folder / "mcp-claude_ai_StatsDeck-get_injuries-1.txt"
    saved.write_text(events[2]["tool_use_result"][0]["text"])
    pointer = (
        "Error: result (3,000 characters across 60 lines) exceeds maximum allowed "
        "tokens. Output has been saved to %s.\nFormat: Plain text\n- For targeted "
        "searches (find a line, locate a string): use grep on the file directly.\n"
        % saved)
    events[2]["message"]["content"][0]["content"] = pointer
    events[2]["tool_use_result"] = pointer
    return events


def test_result_over_the_mcp_limit_is_read_from_the_saved_text_file(tmp_path):
    events = _over_mcp_limit(_events(), tmp_path)
    found = ist.extract(_lines(events), results_root=str(tmp_path))
    assert found == {k: _payload(_events())["data"][k] for k in ("report", "intel")}


def test_saved_text_file_outside_the_results_root_is_refused(tmp_path):
    events = _over_mcp_limit(_events(), tmp_path / "elsewhere")
    with pytest.raises(ist.StreamError, match="outside"):
        ist.extract(_lines(events), results_root=str(tmp_path / "root"))


def test_a_path_quoted_in_the_preview_is_never_followed(tmp_path):
    events = _persist(_events(), tmp_path)
    content = events[2]["message"]["content"][0]["content"]
    # Same file, but named only inside the preview text, not the header.
    events[2]["message"]["content"][0]["content"] = (
        "Some inline text\nsaved to: " + content.split("saved to: ")[1])
    with pytest.raises(ist.StreamError, match="no data.report/data.intel"):
        ist.extract(_lines(events), results_root=str(tmp_path))


def test_persisted_path_outside_the_results_root_is_refused(tmp_path):
    events = _persist(_events(), tmp_path / "elsewhere")
    with pytest.raises(ist.StreamError, match="outside"):
        ist.extract(_lines(events), results_root=str(tmp_path / "root"))


def test_persisted_path_not_in_a_tool_results_folder_is_refused(tmp_path):
    events = _persist(_events(), tmp_path, where="proj/session/other")
    with pytest.raises(ist.StreamError, match="outside"):
        ist.extract(_lines(events), results_root=str(tmp_path))


@pytest.mark.parametrize("tool", ["Bash", "Read", "Write", "Edit"])
def test_session_with_any_builtin_tool_is_refused(tool):
    events = _events()
    events[0]["tools"].append(tool)
    with pytest.raises(ist.StreamError, match=tool):
        ist.extract(_lines(events))


@pytest.mark.parametrize("mode", ["auto", "acceptEdits", "bypassPermissions", "plan", None])
def test_session_in_a_permissive_mode_is_refused(mode):
    events = _events()
    events[0]["permissionMode"] = mode
    with pytest.raises(ist.StreamError, match="permission mode"):
        ist.extract(_lines(events))


def test_manual_mode_reports_as_default_and_is_accepted():
    events = _events()
    assert events[0]["permissionMode"] == "default"
    events[0]["permissionMode"] = "manual"
    assert ist.extract(_lines(events))["intel"]


def test_no_init_event_is_refused():
    with pytest.raises(ist.StreamError, match="init"):
        ist.extract(_lines(_events()[1:]))


def test_no_tool_call_is_an_error():
    events = [e for i, e in enumerate(_events()) if i not in (1, 2)]
    with pytest.raises(ist.StreamError, match="never called"):
        ist.extract(_lines(events))


def test_tool_error_is_an_error():
    events = _events()
    events[2]["message"]["content"][0]["is_error"] = True
    with pytest.raises(ist.StreamError, match="returned an error"):
        ist.extract(_lines(events))


def test_result_missing_an_array_is_an_error():
    events = _events()
    payload = _payload(events)
    del payload["data"]["intel"]
    text = json.dumps(payload)
    events[2]["tool_use_result"][0]["text"] = text
    events[2]["message"]["content"][0]["content"] = text
    with pytest.raises(ist.StreamError, match="no data.report/data.intel"):
        ist.extract(_lines(events))


def test_result_for_another_tool_is_ignored():
    events = _events()
    events[1]["message"]["content"][0]["name"] = "mcp__claude_ai_StatsDeck__get_my_roster"
    with pytest.raises(ist.StreamError, match="never called"):
        ist.extract(_lines(events))


def test_empty_arrays_are_kept_as_empty_arrays():
    events = _events()
    payload = _payload(events)
    payload["data"]["report"] = []
    events[2]["tool_use_result"][0]["text"] = json.dumps(payload)
    assert ist.extract(_lines(events))["report"] == []


def test_non_json_line_is_an_error():
    with pytest.raises(ist.StreamError, match="not JSON"):
        ist.extract(["not json"])


def test_main_writes_the_file_and_counts(tmp_path, capsys):
    out = tmp_path / "out.json"
    assert ist.main([str(FIXTURE), str(out)]) == 0
    assert set(json.loads(out.read_text())) == {"report", "intel"}
    assert not (tmp_path / "out.json.tmp").exists()
    assert "2 report rows, 1 intel rows" in capsys.readouterr().err


def test_main_fails_without_writing(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"type": "system", "subtype": "init",
                               "permissionMode": "auto", "tools": []}) + "\n")
    out = tmp_path / "out.json"
    assert ist.main([str(bad), str(out)]) == 1
    assert not out.exists()
