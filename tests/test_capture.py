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
    rows = [{"id": "9845591", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    assert out == "nav\nid=9845591\t" + row_text + "\nfooter"


def test_prefix_ids_leaves_a_page_with_no_ided_rows_byte_for_byte_unchanged():
    full = "nav\n\tTQB\tChargers TQB . LAC\tARI\t\nfooter"
    assert capture._prefix_ids(full, []) == full


def test_prefix_ids_handles_multiple_rows_in_document_order():
    row1 = "\tWR\tPuka Nacua WR . LAR \tSF\t"
    row2 = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    full = "nav\n" + row1 + "\n" + row2 + "\nfooter"
    rows = [{"id": "9477011", "text": row1}, {"id": "9845591", "text": row2}]
    out = capture._prefix_ids(full, rows)
    assert out == ("nav\nid=9477011\t" + row1 + "\nid=9845591\t" + row2
                  + "\nfooter")


def test_prefix_ids_skips_a_row_between_two_ided_ones_that_has_no_id():
    # A row with no playerpage link at all (page furniture) sitting
    # between two real players is emitted completely unchanged - only the
    # id-bearing rows either side get prefixed.
    row1 = "\tWR\tPuka Nacua WR . LAR \tSF\t"
    furniture = "\tTQB\tChargers TQB . LAC\tARI\t"
    row2 = "\tWR\tJa'Marr Chase WR . CIN \tTB\t"
    full = "\n".join([row1, furniture, row2])
    rows = [{"id": "9477011", "text": row1}, {"id": "9845591", "text": row2}]
    out = capture._prefix_ids(full, rows)
    assert out == "\n".join(
        ["id=9477011\t" + row1, furniture, "id=9845591\t" + row2])


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
    # would orphan "id=8987\t " on its own throwaway line, never reaching
    # the actual content line a line-based parser reads - this is the bug
    # that made every id vanish on first regeneration; this test pins the
    # fix.
    content = "\tSgt Hu...\tChargers TQB • LAC \tARI\t---\t18.45"
    row_text = " \n" + content
    full = "nav\n\n" + row_text + "\n\nfooter"
    rows = [{"id": "8987", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    assert out == "nav\n\n \nid=8987\t" + content + "\n\nfooter"
    # And the content line, once split out, is exactly what a line-based
    # parser needs: the id prefix immediately followed by the row's own
    # leading tab, with nothing orphaned on the line above.
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=8987"))
    assert id_line == "id=8987\t" + content


def test_prefix_ids_handles_multiple_leading_blank_segments():
    content = "\tW (9/16)\tTitans TQB • TEN \tNYJ\t15.74"
    row_text = " \n\n" + content
    full = "nav\n" + row_text + "\nfooter"
    rows = [{"id": "8762", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=8762"))
    assert id_line == "id=8762\t" + content


def test_prefix_ids_skips_past_a_leading_NON_BLANK_cell_too():
    # Task 3b review round 1 Important 2, reproduced: a leading segment
    # that is a real, non-blank label ("Add" - an action-button cell's
    # text) followed by a newline BEFORE the row's actual content. The
    # earlier "skip only blank segments" version stopped at this segment
    # and inserted right before it - re-orphaning the id exactly like the
    # original blank-segment bug, only SILENTLY (no exception anywhere).
    content = "\tSgt Hu...\tChargers TQB • LAC \tARI\t---\t18.45"
    row_text = "Add\n" + content
    full = "nav\n\n" + row_text + "\n\nfooter"
    rows = [{"id": "8987", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=8987"))
    assert id_line == "id=8987\t" + content
    # "Add" itself is untouched, on its own line, with no id attached.
    assert "Add" in out
    assert "id=8987\tAdd" not in out


def test_prefix_ids_is_content_agnostic_about_the_leading_segment():
    # The fix is general, not a second special case bolted onto the first:
    # ANY leading segment - blank, a word, punctuation, digits - must be
    # skipped past uniformly, because the function has no way to know (and
    # must not need to guess) what CBS puts in a hidden cell.
    for leading in (" ", "Add", "***", "12", "Trade"):
        content = "\tRow\tContent • XX \tYY\t1.23"
        row_text = leading + "\n" + content
        full = "nav\n" + row_text + "\nfooter"
        rows = [{"id": "42", "text": row_text}]
        out = capture._prefix_ids(full, rows)
        id_line = next(l for l in out.splitlines() if l.startswith("id=42"))
        assert id_line == "id=42\t" + content, "failed for leading=%r" % leading


def test_prefix_ids_skips_a_row_whose_own_text_is_entirely_blank():
    # Task 3b review round 1 Important 2, second half: a row with NO real
    # content anywhere in its own text must not be prefixed at all -
    # anchoring on its last newline would land somewhere inside its own
    # blank span, which can coincide with (or precede) where the NEXT
    # row's real text begins, migrating THIS row's id onto that row's line
    # ("id=A\tid=B\t...") - loud in cbs_weekly (still contains " • ", so
    # it is caught as an unmatched line) but a SILENT DROP in cbs_roster
    # (`_ROW` has no such watchdog - a non-matching line just vanishes).
    blank_row = " \n \n "
    next_row = "\tWR\tJa'Marr Chase WR • CIN \tTB\t"
    # A real newline-separated page - `full`'s own structure separates
    # every row onto its own line(s) regardless of what any one row's
    # `tr.innerText` contains; this test's `blank_row` is deliberately
    # entirely blank content WITHIN that structure, not a missing
    # separator between rows (a different, unrelated concern).
    full = "nav\n" + blank_row + "\n" + next_row + "\nfooter"
    rows = [{"id": "AAA", "text": blank_row},
           {"id": "9845591", "text": next_row}]
    out = capture._prefix_ids(full, rows)
    # The blank row contributed NOTHING - no "id=AAA" anywhere in the
    # output, and it never merges onto the next row's line.
    assert "id=AAA" not in out
    assert "id=AAAid=9845591" not in out
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=9845591"))
    assert id_line == "id=9845591\t" + next_row


def test_prefix_ids_skips_past_a_trailing_empty_cell():
    # Task 3b review round 2: the mirror image of the leading-blank bug.
    # A row's REAL content followed by a trailing empty cell renders as
    # `tr.innerText` ending in "\n" with nothing after it - e.g. the
    # Chargers DST row: "\tChargers\t18.4\n". Anchoring on the literal
    # LAST "\n" (the old `rfind` logic) lands the prefix AFTER this row's
    # own text entirely - i.e. at the START of the very next row's text -
    # attaching this row's id to the NEXT row's content. Silent: the id
    # is still present and still unique, so neither `ID COVERAGE LOST`
    # nor a duplicate-id warning fires - a wrong-player join with no
    # signal anywhere.
    chargers = "\tChargers\t18.4\n"
    patriots = "\tPatriots\t10.2\n"
    full = "nav\n" + chargers + patriots + "footer"
    rows = [{"id": "8987", "text": chargers}, {"id": "1981", "text": patriots}]
    out = capture._prefix_ids(full, rows)
    # The old buggy behavior (regression pin): "id=8987" must NOT end up
    # immediately before the Patriots row's content.
    assert "id=8987\t\tPatriots" not in out
    lines = out.splitlines()
    chargers_line = next(l for l in lines if l.startswith("id=8987"))
    assert chargers_line == "id=8987\t\tChargers\t18.4"
    patriots_line = next(l for l in lines if l.startswith("id=1981"))
    assert patriots_line == "id=1981\t\tPatriots\t10.2"


def test_prefix_ids_skips_past_a_trailing_whitespace_only_cell():
    # Task 3b review round 2, second shape: a trailing cell that is
    # whitespace-only rather than empty - `tr.innerText` ending in
    # "\n " (a real line, non-empty, but blank once stripped). Anchoring
    # on the literal last "\n" orphans the id onto that trailing blank
    # line - a TOTAL id loss for this row. `cbs_weekly`'s unmatched-line
    # watchdog would catch this (the merged text still contains " • "),
    # but `cbs_roster` has no such guard - silent on the roster page.
    row_text = "\tChargers\t18.4\n "
    full = "nav\n" + row_text + "\nfooter"
    rows = [{"id": "8987", "text": row_text}]
    out = capture._prefix_ids(full, rows)
    assert "id=8987" in out
    lines = out.splitlines()
    id_line = next(l for l in lines if l.startswith("id=8987"))
    assert id_line == "id=8987\t\tChargers\t18.4"


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
            return {"full": full, "rows": [{"id": "9845591", "text": row_text}]}

    out = capture._capture_page_text(_FakePage())
    assert len(calls) == 1
    assert out == "nav\nid=9845591\t" + row_text + "\nfooter"


# ------------------------------------------------------- navigation timeout
#
# The first real scheduled Friday run (2026-09-04) lost five of eight lineup
# slots to a 30s navigation timeout. `?print_rows=9999` - the parameter that
# stops CBS hiding rostered players outside its default top 100 - makes the
# RB/WR/TE page 1710 rows, which measures ~33s to domcontentloaded.

def test_the_nav_timeout_clears_the_measured_page_load():
    # 33s measured. A timeout at or near that is a coin flip, not a margin.
    from sffl.capture import _NAV_TIMEOUT_MS
    assert _NAV_TIMEOUT_MS >= 60000, (
        "the heaviest captured page measured ~33s; a timeout under 60s has "
        "no margin and cost a real run five lineup slots")


def test_navigation_is_retried_but_not_unboundedly():
    # One retry: the measured failure is slowness, not breakage. A loop
    # across eight pages is how a background job becomes a hung one.
    from sffl.capture import _NAV_RETRIES
    assert _NAV_RETRIES == 1


def test_goto_retries_once_then_raises_the_timeout():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from sffl.capture import _goto_with_retry

    class _AlwaysSlow(object):
        def __init__(self):
            self.calls = 0

        def goto(self, url, timeout=None, wait_until=None):
            self.calls += 1
            raise PlaywrightTimeoutError("nope")

    page = _AlwaysSlow()
    with pytest.raises(PlaywrightTimeoutError):
        _goto_with_retry(page, "http://x", 1000)
    assert page.calls == 2, "expected one attempt plus one retry"


def test_a_slow_first_attempt_that_then_succeeds_is_not_an_error():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from sffl.capture import _goto_with_retry

    class _SlowOnce(object):
        def __init__(self):
            self.calls = 0

        def goto(self, url, timeout=None, wait_until=None):
            self.calls += 1
            if self.calls == 1:
                raise PlaywrightTimeoutError("slow")

    page = _SlowOnce()
    _goto_with_retry(page, "http://x", 1000)
    assert page.calls == 2


# ------------------------------------------------------- icon sidecar (2026-10-20)
#
# CBS draws a player's injury designation as an icon whose label lives in the
# link's aria-label, never in the row's text (see sffl.cbs_icons). With icons
# asked for, the same single evaluate call also returns each row's icon links.

def test_the_live_text_path_still_calls_evaluate_with_the_script_alone():
    # The alert runs without icons until the switch: one argument, exactly as
    # before, so the page gets the same call it always did.
    calls = []

    class _FakePage(object):
        def evaluate(self, *args):
            calls.append(args)
            return {"full": "nav\nfooter", "rows": []}

    capture._capture_page_text(_FakePage())
    assert calls == [(capture._ID_EXTRACT_JS,)]


def test_capture_with_icons_is_still_one_evaluate_and_returns_the_rows():
    row_text = "\tWR\tPat Example WR . SEA \tMIA\t"
    full = "nav\n" + row_text + "\nfooter"
    icons = [{"icon": "icon-red_cross",
              "label": "Injury Report: Knee: Out for Week 7 at Miami",
              "subtab": "Injury Report"}]
    calls = []

    class _FakePage(object):
        def evaluate(self, *args):
            calls.append(args)
            return {"full": full,
                    "rows": [{"id": "9000001", "text": row_text, "icons": icons}]}

    text, rows = capture._capture_page_with_icons(_FakePage())
    assert calls == [(capture._ID_EXTRACT_JS, True)]
    assert text == "nav\nid=9000001\t" + row_text + "\nfooter"
    assert rows[0]["icons"] == icons


def test_the_script_reads_icons_only_when_asked():
    js = capture._ID_EXTRACT_JS
    assert "(withIcons) =>" in js
    assert "if (withIcons)" in js
    assert ".playerIconsWrapper a.playerLink" in js
    assert "aria-label" in js


def test_the_sidecar_is_written_whole(tmp_path):
    import json

    path = str(tmp_path / "roster.icons.json")
    rows = [{"id": "9000001", "text": "x", "icons": [
        {"icon": "icon-red_cross", "label": "Injury Report: Knee: Out",
         "subtab": "Injury Report"}]}]
    capture._write_icons_sidecar(path, rows, "https://x/teams")
    data = json.load(open(path))
    assert data["url"] == "https://x/teams"
    assert data["rows_scanned"] == 1
    assert list(data["icons"]) == ["9000001"]
    assert not (tmp_path / "roster.icons.json.tmp").exists()


def test_the_script_skips_icons_for_a_row_it_cannot_attribute():
    # A row holding another row, or linking two players, gets icons: null, so
    # none of its icons can be credited to the wrong player.
    js = capture._ID_EXTRACT_JS
    assert "tr.querySelector('tr')" in js and "ids.size > 1" in js
    assert "row.icons = null" in js
