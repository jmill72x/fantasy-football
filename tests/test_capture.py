import pytest

from sffl import capture


def test_a_long_login_page_over_char_floor_identified_by_title_raises_session_expired():
    # The dangerous case: a login page that is long enough to pass the
    # character floor. Without title/URL checks, it would be saved and parsed
    # downstream as 'Jeff rosters nobody' — the exact failure we guard against.
    text = "Log In\n\n" + ("x" * 1500)  # Over the 1000-char floor
    title = capture.SESSION_EXPIRED_TITLE
    url = "https://example.invalid/teams/1"
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, url, title)
    assert "log in again" in str(exc.value).lower()


def test_a_page_identified_by_login_url_path_alone_raises_session_expired():
    # A login redirect where the title is unhelpful. The URL path is a reliable
    # signal that CBS sends only on expired sessions.
    text = "Some generic page content"
    url = "https://www.cbssports.com/login?param=value"
    title = "Some Page"  # Doesn't match SESSION_EXPIRED_TITLE
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, url, title)
    assert "log in again" in str(exc.value).lower()


def test_a_real_looking_page_with_normal_title_and_url_passes():
    # A plausible roster or projections page with a normal title and URL.
    text = "y" * 5000
    url = "https://stripesfantasyfootballleague.football.cbssports.com/teams/1"
    title = "My Team - Fantasy Football"
    assert capture.check_page_text(text, url, title) is None


def test_an_empty_page_is_refused_rather_than_saved():
    with pytest.raises(capture.CaptureError) as exc:
        capture.check_page_text("   \n  \n", "https://example.invalid/teams/1")
    assert "empty" in str(exc.value).lower()


def test_a_suspiciously_short_page_is_refused():
    # A real CBS page is thousands of characters. A 200-character body means
    # an interstitial, a rate limit, or an error page - never a roster.
    with pytest.raises(capture.CaptureError):
        capture.check_page_text("x" * 200, "https://example.invalid/teams/1")


def test_a_plausible_page_passes():
    assert capture.check_page_text("y" * 5000, "https://example.invalid/x") is None


def test_session_expiry_is_a_capture_error_so_one_handler_catches_both():
    assert issubclass(capture.SessionExpired, capture.CaptureError)


# --- Task 3b: _prefix_ids, the pure logic behind capture()'s id prefix ----

def test_prefix_ids_inserts_id_before_the_rows_own_text():
    full = "nav\n\tWR\tJa'Marr Chase WR . CIN \tTB\t\nfooter"
    row_text = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    rows = [{"id": "2966320", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    assert out == "nav\nid=2966320\t" + row_text + "\nfooter"


def test_prefix_ids_leaves_a_page_with_no_ided_rows_byte_for_byte_unchanged():
    full = "nav\n\tTQB\tChargers TQB . LAC\tARI\t\nfooter"
    assert capture._prefix_ids(full, []) == full


def test_prefix_ids_handles_multiple_rows_in_document_order():
    row1 = "\tWR\tPuka Nacua WR . LAR \tSF\t"
    row2 = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    full = "nav\n" + row1 + "\n" + row2 + "\nfooter"
    rows = [{"id": "3121687", "text": row1}, {"id": "2966320", "text": row2}]
    out = capture._prefix_ids(full, rows)
    assert out == ("nav\nid=3121687\t" + row1 + "\nid=2966320\t" + row2
                  + "\nfooter")


def test_prefix_ids_skips_a_row_between_two_ided_ones_that_has_no_id():
    # A row with no playerpage link at all (page furniture) sitting
    # between two real players is emitted completely unchanged - only the
    # id-bearing rows either side get prefixed.
    row1 = "\tWR\tPuka Nacua WR . LAR \tSF\t"
    furniture = "\tTQB\tChargers TQB . LAC\tARI\t"
    row2 = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    full = "\n".join([row1, furniture, row2])
    rows = [{"id": "3121687", "text": row1}, {"id": "2966320", "text": row2}]
    out = capture._prefix_ids(full, rows)
    assert out == "\n".join(
        ["id=3121687\t" + row1, furniture, "id=2966320\t" + row2])


def test_prefix_ids_does_not_corrupt_the_page_when_a_rows_text_cannot_be_found():
    # A defensive case: `rows` names text that (for whatever reason) is not
    # actually present in `full_text`. The row is simply not prefixed -
    # the page is returned unmangled, not raised on or truncated.
    full = "nav\n\tWR\tJa'Marr Chase WR . CIN \tTB\t\nfooter"
    rows = [{"id": "9999999", "text": "\tWR\tSome Other Guy WR . XYZ \tAB\t"}]
    assert capture._prefix_ids(full, rows) == full


def test_prefix_ids_search_advances_past_a_matched_row_so_it_is_not_reused():
    # Two DISTINCT rows that happen to share identical rendered text (e.g. a
    # genuine data anomaly) must each get their OWN id, not both collapse
    # onto the first match.
    row_text = "\tDST\tSame Text DST . XX \tYY\t"
    full = row_text + "\n" + row_text
    rows = [{"id": "111"}, {"id": "222"}]
    rows[0]["text"] = row_text
    rows[1]["text"] = row_text
    out = capture._prefix_ids(full, rows)
    assert out == "id=111\t" + row_text + "\nid=222\t" + row_text


def test_prefix_ids_skips_past_a_leading_blank_line_within_the_rows_own_text():
    # REAL SHAPE, verified live 2026-08-30: a hidden action-buttons cell
    # renders as a lone space followed by a line break before the row's
    # actual tab-delimited content - the Chargers TQB row's own
    # `tr.innerText` is exactly this: " \n\tSgt Hu...\tChargers TQB • LAC "
    # "...\tARI\t...\t18.45". Inserting the prefix at the literal start
    # would orphan "id=1974\t " on its own throwaway line, never reaching
    # the actual content line a line-based parser reads - this is the bug
    # that made every id vanish on first regeneration; this test pins the
    # fix.
    content = "\tSgt Hu...\tChargers TQB • LAC \tARI\t---\t18.45"
    row_text = " \n" + content
    full = "nav\n\n" + row_text + "\n\nfooter"
    rows = [{"id": "1974", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    assert out == "nav\n\n \nid=1974\t" + content + "\n\nfooter"
    # And the content line, once split out, is exactly what a line-based
    # parser needs: the id prefix immediately followed by the row's own
    # leading tab, with nothing orphaned on the line above.
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=1974"))
    assert id_line == "id=1974\t" + content


def test_prefix_ids_handles_multiple_leading_blank_segments():
    content = "\tW (9/16)\tTitans TQB • TEN \tNYJ\t15.74"
    row_text = " \n\n" + content
    full = "nav\n" + row_text + "\nfooter"
    rows = [{"id": "1978", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=1978"))
    assert id_line == "id=1978\t" + content


def test_capture_page_text_calls_evaluate_once_and_prefixes_ids(monkeypatch):
    # `_capture_page_text` must do exactly ONE page.evaluate round trip
    # (see its own docstring on why a second, separate inner_text() call
    # would race a client-side re-render) and feed the result straight
    # through `_prefix_ids`.
    row_text = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    full = "nav\n" + row_text + "\nfooter"
    calls = []

    class _FakePage(object):
        def evaluate(self, js):
            calls.append(js)
            return {"full": full, "rows": [{"id": "2966320", "text": row_text}]}

    out = capture._capture_page_text(_FakePage())
    assert len(calls) == 1
    assert out == "nav\nid=2966320\t" + row_text + "\nfooter"
